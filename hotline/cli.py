"""Command-line interface wiring config, sources, detection, dedupe, notify.

Exposes three subcommands:

``once``
    Poll the selected sources a single time, detect giveaway callouts, dedupe
    them via the SQLite store, and notify. With ``--dry-run`` and no reachable
    config it falls back to the bundled ``fixtures/`` so it prints detections
    offline with zero setup.

``watch``
    Same as ``once`` but loops forever, sleeping ``--interval`` seconds between
    polls.

``test-alert``
    Send (or dry-run) a single sample Telegram alert to verify delivery.

``main(argv)`` returns an exit code: ``0`` on success, non-zero on bad usage.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from hotline import __version__
from hotline.config import Config, Station, load_config
from hotline.detect import Detection, detect
from hotline.notify import notify, notify_rich
from hotline.pipeline import handle_audio_trigger
from hotline.sources import Item
from hotline.sources.audio import iter_windows, transcribe_stream
from hotline.sources.sitemap import poll_sitemap
from hotline.sources.social import poll_social
from hotline.sources.web import parse_html, poll_web
from hotline.store import Store, item_hash
from hotline.summarize import summarize

#: All selectable source names, in default polling order.
ALL_SOURCES = ("web", "sitemap", "social", "audio")

#: Default SQLite dedupe database path (gitignored).
DEFAULT_DB_PATH = "hotline.db"

#: Sentinel marking the ``--db`` flag as left at its default (not passed).
_DB_UNSET = object()

#: Repo fixtures directory used for the offline ``once --dry-run`` fallback.
_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="hotline",
        description=(
            "Watch Singapore radio stations (987FM and friends) for giveaways "
            "and alert via Telegram. Use --station SLUG to restrict."
        ),
    )
    parser.add_argument("--version", action="version", version=f"hotline {__version__}")
    _add_verbose_flag(parser)

    # Shared parent so ``-v`` also works AFTER the subcommand
    # (``hotline once -v`` as well as ``hotline -v once``).
    verbose_parent = argparse.ArgumentParser(add_help=False)
    _add_verbose_flag(verbose_parent)

    subparsers = parser.add_subparsers(dest="command", required=True)

    once = subparsers.add_parser(
        "once", help="Poll all sources once and notify.", parents=[verbose_parent]
    )
    _add_common_flags(once)
    once.set_defaults(func=cmd_once)

    watch = subparsers.add_parser(
        "watch", help="Poll repeatedly on an interval.", parents=[verbose_parent]
    )
    _add_common_flags(watch)
    watch.add_argument(
        "--interval",
        type=int,
        default=45,
        help="Seconds between polls (default: 45).",
    )
    watch.set_defaults(func=cmd_watch)

    test_alert = subparsers.add_parser(
        "test-alert",
        help="Send (or dry-run) a sample Telegram alert.",
        parents=[verbose_parent],
    )
    test_alert.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the alert instead of sending it.",
    )
    test_alert.add_argument("--config", help="Path to a TOML config file.")
    test_alert.set_defaults(func=cmd_test_alert)

    return parser


def _add_verbose_flag(parser: argparse.ArgumentParser) -> None:
    """Add the repeatable ``-v/--verbose`` flag to ``parser``.

    Added both to the top-level parser and to a shared parent for the
    subcommands so ``-v`` is accepted before or after the subcommand.
    """
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help=(
            "Increase log verbosity to stderr: -v for INFO (ffmpeg capture, "
            "music/speech gate decisions, transcript), -vv for DEBUG."
        ),
    )


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    """Add the ``--dry-run``, ``--source``, and ``--config`` flags."""
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print detections/alerts instead of sending them.",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=ALL_SOURCES,
        dest="sources",
        help="Restrict to a source (repeatable). Default: all sources.",
    )
    parser.add_argument(
        "--station",
        action="append",
        dest="stations",
        metavar="SLUG",
        help=(
            "Restrict to a station by slug (repeatable). Default: all "
            "configured stations (e.g. 987fm, class95, yes933)."
        ),
    )
    parser.add_argument("--config", help="Path to a TOML config file.")
    parser.add_argument(
        "--audio",
        action="store_true",
        help=(
            "Force-enable the event-driven audio path even when the config "
            "leaves audio disabled. Under --dry-run it demonstrates a rich "
            "alert from the bundled fixtures and never touches ffmpeg/network."
        ),
    )
    parser.add_argument(
        "--db",
        default=_DB_UNSET,
        metavar="PATH",
        help=(
            "SQLite dedupe database path (default: hotline.db). When passed "
            "explicitly it is used even under --dry-run, so repeat runs dedupe; "
            "plain --dry-run with no --db uses an in-memory store."
        ),
    )


def _db_path(args: argparse.Namespace) -> str:
    """Return the configured db path, or the default when --db was unset."""
    return DEFAULT_DB_PATH if args.db is _DB_UNSET else args.db


def _store_for(args: argparse.Namespace) -> Store:
    """Build the dedupe :class:`Store` honouring --dry-run and --db.

    A plain ``--dry-run`` (no explicit ``--db``) uses an in-memory store so the
    offline demo is repeatable. Passing ``--db PATH`` always uses that on-disk
    path, even under ``--dry-run``, so a second run dedupes to zero.
    """
    if args.dry_run and args.db is _DB_UNSET:
        return Store(":memory:")
    return Store(_db_path(args))


def _selected_sources(args: argparse.Namespace) -> tuple[str, ...]:
    """Return the selected source names, defaulting to all of them."""
    return tuple(args.sources) if args.sources else ALL_SOURCES


#: Maps a station language to a Whisper language hint (``None`` auto-detects).
_LANGUAGE_MAP = {"en": "en", "zh": "zh"}


def lang_for(station: Station) -> str | None:
    """Return the Whisper language hint for ``station``.

    ``en`` -> ``"en"``, ``zh`` -> ``"zh"``; ``bilingual`` and any unknown value
    map to ``None`` so Whisper auto-detects the language.
    """
    return _LANGUAGE_MAP.get(station.language)


def _selected_stations(args: argparse.Namespace, config: Config) -> list[Station]:
    """Return the stations to poll, filtered by the repeatable ``--station``.

    Defaults to every configured station. A ``--station SLUG`` that matches no
    configured station contributes nothing (the filter is a pure subset).
    """
    stations = list(config.stations)
    wanted = getattr(args, "stations", None)
    if not wanted:
        return stations
    wanted_set = set(wanted)
    return [station for station in stations if station.slug in wanted_set]


def _station_config(config: Config, station: Station) -> Config:
    """Return a per-station view of ``config`` with the station's targets.

    The global ``[poll]``/``[audio]``/``[summary]``/secret settings are kept;
    only the source-targeting and per-station stream fields are overlaid so
    :func:`poll_web`/:func:`poll_sitemap` poll this station's pages.
    """
    return replace(
        config,
        contest_urls=list(station.contest_urls),
        feed_url=station.feed_url,
        sitemap_url=station.sitemap_url,
        audio_stream_url=station.stream_url,
        audio_enabled=station.audio_enabled,
    )


def _tag_item(item: Item, station: Station) -> Item:
    """Return ``item`` tagged with the station so dedupe distinguishes stations.

    The station name is prefixed onto the title and the slug is appended to the
    URL as a fragment, so two stations surfacing identical contest text hash to
    distinct dedupe keys and the alert names the station.
    """
    separator = "&" if "#" in item.url else "#"
    return Item(
        title=f"[{station.name}] {item.title}",
        url=f"{item.url}{separator}station={station.slug}",
        text=item.text,
        published=item.published,
        source=item.source,
    )


def _iter_items(
    config: Config, sources: tuple[str, ...], stations: list[Station]
) -> Iterator[Item]:
    """Yield items from each selected live source, per station.

    Web and sitemap pages are polled per station (with items tagged by station
    slug so dedupe treats identical text from two stations as distinct). The
    social and audio-window sources remain global/no-op here; the event-driven
    per-station audio path runs separately in :func:`_run_audio`.
    """
    for station in stations:
        station_config = _station_config(config, station)
        if "web" in sources:
            for item in poll_web(station_config):
                yield _tag_item(item, station)
        if "sitemap" in sources:
            for item in poll_sitemap(station_config):
                yield _tag_item(item, station)

    if "social" in sources:
        yield from poll_social(config)
    if "audio" in sources:
        # Live stream fetch/decoding is out of scope here; transcribe_stream is
        # a no-op unless audio is enabled and real windows are supplied.
        yield from transcribe_stream(config, windows=iter_windows([]))


def _iter_fixture_items(sources: tuple[str, ...]) -> Iterator[Item]:
    """Yield items parsed from the bundled fixtures (offline fallback)."""
    if "web" in sources:
        for name in ("contest_page.html", "giveaway_page.html", "closed_page.html"):
            path = _FIXTURES_DIR / name
            yield parse_html(path.read_text(encoding="utf-8"), path.as_uri())
    if "audio" in sources:
        transcript = (_FIXTURES_DIR / "transcript.txt").read_text(encoding="utf-8")
        windows = iter_windows(transcript.splitlines())
        for index, window in enumerate(windows):
            yield Item(
                title=f"Audio window {index}",
                url=f"fixtures/transcript.txt#t={index * 10}",
                text=window,
                published=None,
                source="audio",
            )


def _config_has_live_targets(config: Config) -> bool:
    """Return whether the config points at any real source to poll."""
    return bool(
        config.contest_urls
        or config.feed_url
        or config.sitemap_url
        or config.x_bearer
        or config.ig_token
        or (config.audio_enabled and config.audio_stream_url)
    )


#: Synthetic station backing the offline ``once --dry-run`` fixtures demo so the
#: demo output (titles, '987FM' mention, audio headline) stays byte-identical.
_DRY_RUN_STATION = Station(
    name="987FM",
    slug="987fm",
    language="en",
    stream_url="https://22903.live.streamtheworld.com/987FM_PREM.aac",
    audio_enabled=True,
)


def _run_poll(args: argparse.Namespace, config: Config, store: Store) -> int:
    """Run one polling pass over the selected sources and stations.

    Detects giveaway callouts, dedupes via the store, and notifies (or prints
    in dry-run). When the audio path is active it fires after the web/sitemap
    pass (event-driven on a fresh detection, or always in continuous mode).
    Returns the count of fresh detections notified.

    The offline ``--dry-run`` fixtures fallback maps to a single synthetic
    ``987FM`` station so its output is unchanged, and the audio trigger runs
    once for that station.
    """
    sources = _selected_sources(args)
    stations = _selected_stations(args, config)

    use_fixtures = args.dry_run and not _config_has_live_targets(config)
    if use_fixtures:
        items = _iter_fixture_items(sources)
        audio_stations = [_DRY_RUN_STATION]
    else:
        items = _iter_items(config, sources, stations)
        audio_stations = stations

    notified = 0
    for item in items:
        detection = detect(item.text, item.source)
        if detection is None:
            continue
        hash_ = item_hash(item)
        if not store.should_notify(hash_):
            continue
        _emit(detection, item, config, dry_run=args.dry_run)
        store.mark_notified(hash_)
        notified += 1

    for station in audio_stations:
        notified += _run_audio(args, config, store, station, web_fired=notified > 0)

    return notified


def _audio_active(args: argparse.Namespace, config: Config) -> bool:
    """Return whether the event-driven audio path should run this pass."""
    return bool(getattr(args, "audio", False) or config.audio_enabled)


def _run_audio(
    args: argparse.Namespace,
    config: Config,
    store: Store,
    station: Station,
    *,
    web_fired: bool,
) -> int:
    """Run the event-driven audio path for one station in one poll pass.

    Fires when audio is active (``--audio`` or ``config.audio_enabled``) and
    either a web/sitemap detection fired this pass or ``audio_mode`` is
    ``"continuous"``. A station with no usable stream (``audio_enabled`` false
    or an empty ``stream_url``) is skipped cleanly. In ``--dry-run`` the
    transcript and clip come from the bundled fixtures so no ffmpeg or network
    is touched. Returns 1 if a fresh audio detection was alerted, else 0.
    """
    forced = bool(getattr(args, "audio", False))
    if not _audio_active(args, config):
        return 0
    # Fire when a web/sitemap detection triggered this pass, in continuous
    # mode, or whenever the user explicitly asked for audio with --audio (a
    # manual capture-now request that should not depend on a web detection).
    if not (web_fired or config.audio_mode == "continuous" or forced):
        return 0

    if args.dry_run:
        transcript = (_FIXTURES_DIR / "callout_transcript.txt").read_text(encoding="utf-8")
        clip_path = _FIXTURES_DIR / "audio_clip.ogg"
    else:
        # --audio force-enables capture for a station that has a stream URL even
        # when its config leaves audio_enabled False; otherwise respect the flag.
        if not station.stream_url or (not station.audio_enabled and not forced):
            return 0
        transcript, clip = handle_audio_trigger(
            config, stream_url=station.stream_url, language=lang_for(station)
        )
        if not transcript or clip is None:
            return 0
        clip_path = clip

    detection = detect(transcript, "audio")
    if detection is None:
        return 0

    stream_url = (station.stream_url if not args.dry_run else config.audio_stream_url) or (
        config.audio_stream_url or "audio-stream"
    )
    item = Item(
        title=f"{station.name} on-air callout",
        url=f"{stream_url}#audio&station={station.slug}",
        text=transcript,
        published=None,
        source="audio",
    )
    hash_ = item_hash(item)
    if not store.should_notify(hash_):
        return 0

    summary = summarize(transcript, detection, config)
    dry_run = args.dry_run or not (config.telegram_token and config.chat_id)
    notify_rich(summary, detection, transcript, clip_path, config, dry_run=dry_run)
    store.mark_notified(hash_)
    return 1


def _emit(detection: Detection, item: Item, config: Config, *, dry_run: bool) -> None:
    """Notify for a detection, falling back to printing when unconfigured."""
    if dry_run or not (config.telegram_token and config.chat_id):
        notify(detection, item, config, dry_run=True)
    else:
        notify(detection, item, config, dry_run=False)


def cmd_once(args: argparse.Namespace, config: Config) -> int:
    """Handle the ``once`` subcommand: a single polling pass.

    A plain ``--dry-run`` keeps dedupe state in an in-memory store so the
    offline demo is repeatable. Passing ``--db PATH`` uses that on-disk
    database even under ``--dry-run`` so repeat runs dedupe to zero.
    """
    store = _store_for(args)
    try:
        count = _run_poll(args, config, store)
    finally:
        store.close()
    print(f"Done: {count} detection(s) notified.")
    return 0


def cmd_watch(args: argparse.Namespace, config: Config) -> int:
    """Handle the ``watch`` subcommand: poll forever on an interval.

    A plain ``--dry-run`` keeps dedupe state in an in-memory store so no
    on-disk database is written; passing ``--db PATH`` uses that path instead.
    """
    interval = args.interval
    store = _store_for(args)
    print(f"Watching every {interval}s (Ctrl-C to stop).")
    try:
        while True:
            count = _run_poll(args, config, store)
            store.prune()
            print(f"Poll complete: {count} new detection(s).")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        store.close()


def cmd_test_alert(args: argparse.Namespace, config: Config) -> int:
    """Handle the ``test-alert`` subcommand: send a sample alert."""
    item = Item(
        title="987FM test giveaway",
        url="https://example.invalid/contest",
        text="call now to win tickets, phone lines are open",
        published=None,
        source="test",
    )
    detection = Detection(
        text=item.text,
        score=1.0,
        matched_terms=["call now", "phone lines", "win", "tickets"],
        source="test",
    )
    if args.dry_run:
        notify(detection, item, config, dry_run=True)
        print("Dry-run: no message sent.")
        return 0
    if not (config.telegram_token and config.chat_id):
        print("Cannot send: set HOTLINE_TELEGRAM_TOKEN and HOTLINE_CHAT_ID, or use --dry-run.")
        return 1
    notify(detection, item, config, dry_run=False)
    print("Test alert sent.")
    return 0


def _configure_logging(verbosity: int) -> None:
    """Route library logs to stderr based on ``-v`` count.

    Args:
        verbosity: ``0`` leaves logging unconfigured (quiet, as before), ``1``
            enables INFO, ``2`` or more enables DEBUG. Logs go to stderr so they
            never mix with the stdout result lines or any piped output.
    """
    if verbosity <= 0:
        return
    level = logging.INFO if verbosity == 1 else logging.DEBUG
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to a subcommand handler.

    Args:
        argv: Argument list (excluding the program name). Defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        A process exit code: ``0`` on success, non-zero on failure.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    # ``-v`` is accepted both before and after the subcommand. With argparse
    # ``parents=``, the position-specific value can be shadowed, so take the
    # larger of the two counts from an independent pre-scan.
    pre = argparse.ArgumentParser(add_help=False)
    _add_verbose_flag(pre)
    scan_argv = sys.argv[1:] if argv is None else argv
    global_verbose, _ = pre.parse_known_args(scan_argv)
    _configure_logging(max(args.verbose, global_verbose.verbose))
    config = load_config(args.config)
    return args.func(args, config)
