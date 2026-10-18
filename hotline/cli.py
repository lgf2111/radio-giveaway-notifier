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
import time
from collections.abc import Iterator
from pathlib import Path

from hotline import __version__
from hotline.config import Config, load_config
from hotline.detect import Detection, detect
from hotline.notify import notify
from hotline.sources import Item
from hotline.sources.audio import iter_windows, transcribe_stream
from hotline.sources.sitemap import poll_sitemap
from hotline.sources.social import poll_social
from hotline.sources.web import parse_html, poll_web
from hotline.store import Store, item_hash

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
        description="Watch 987FM for radio giveaways and alert via Telegram.",
    )
    parser.add_argument("--version", action="version", version=f"hotline {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    once = subparsers.add_parser("once", help="Poll all sources once and notify.")
    _add_common_flags(once)
    once.set_defaults(func=cmd_once)

    watch = subparsers.add_parser("watch", help="Poll repeatedly on an interval.")
    _add_common_flags(watch)
    watch.add_argument(
        "--interval",
        type=int,
        default=45,
        help="Seconds between polls (default: 45).",
    )
    watch.set_defaults(func=cmd_watch)

    test_alert = subparsers.add_parser(
        "test-alert", help="Send (or dry-run) a sample Telegram alert."
    )
    test_alert.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the alert instead of sending it.",
    )
    test_alert.add_argument("--config", help="Path to a TOML config file.")
    test_alert.set_defaults(func=cmd_test_alert)

    return parser


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
        help="Restrict to a source (repeatable). Default: all three.",
    )
    parser.add_argument("--config", help="Path to a TOML config file.")
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


def _iter_items(config: Config, sources: tuple[str, ...]) -> Iterator[Item]:
    """Yield items from each selected live source."""
    if "web" in sources:
        yield from poll_web(config)
    if "sitemap" in sources:
        yield from poll_sitemap(config)
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


def _run_poll(args: argparse.Namespace, config: Config, store: Store) -> int:
    """Run one polling pass over the selected sources.

    Detects giveaway callouts, dedupes via the store, and notifies (or prints
    in dry-run). Returns the count of fresh detections notified.
    """
    sources = _selected_sources(args)

    use_fixtures = args.dry_run and not _config_has_live_targets(config)
    items = _iter_fixture_items(sources) if use_fixtures else _iter_items(config, sources)

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

    return notified


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
    config = load_config(args.config)
    return args.func(args, config)
