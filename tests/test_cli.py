"""Tests for the CLI wiring in :mod:`hotline.cli`.

All runs are offline: ``once --dry-run`` falls back to the bundled fixtures,
and no test performs network I/O.
"""

from __future__ import annotations

import pytest

from hotline import cli
from hotline.sources import Item
from hotline.store import Store, item_hash


def test_once_dry_run_prints_detections(capsys, monkeypatch, tmp_path):
    """``once --dry-run`` returns 0 and prints fixture-backed detections."""
    monkeypatch.chdir(tmp_path)  # keep the dedupe db out of the repo

    rc = cli.main(["once", "--dry-run"])

    assert rc == 0
    out = capsys.readouterr().out
    # The active contest fixture should fire and be reported.
    assert "Giveaway alert" in out
    assert "987FM" in out
    # Summary line is always printed.
    assert "detection(s) notified" in out


def test_once_dry_run_notifies_multiple(capsys, monkeypatch, tmp_path):
    """The contest + giveaway + audio fixtures all produce detections."""
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["once", "--dry-run"])

    assert rc == 0
    out = capsys.readouterr().out
    # contest_page, giveaway_page, and the audio window all score above
    # threshold; closed_page is suppressed by negation -> at least 3 alerts.
    assert out.count("Giveaway alert") >= 3


def test_once_dry_run_audio_emits_rich_alert(capsys, monkeypatch, tmp_path):
    """``once --dry-run --audio`` emits a rich fixture-backed audio alert.

    No ffmpeg or network is touched: the transcript and clip come from the
    bundled fixtures. The 3 web/audio-window detections still fire too.
    """
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["once", "--dry-run", "--audio"])

    assert rc == 0
    out = capsys.readouterr().out
    # The usual fixture detections are still reported.
    assert out.count("Giveaway alert") >= 3
    # Plus a rich audio alert built from callout_transcript.txt + audio_clip.ogg.
    assert "987FM giveaway" in out  # summary headline
    assert "Action:" in out
    assert "would attach" in out
    assert "audio_clip.ogg" in out


def test_once_dry_run_without_audio_has_no_rich_alert(capsys, monkeypatch, tmp_path):
    """Plain ``once --dry-run`` prints >=3 detections and no rich audio alert."""
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["once", "--dry-run"])

    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("Giveaway alert") >= 3
    assert "would attach" not in out


def test_source_web_restricts_sources(capsys, monkeypatch, tmp_path):
    """``--source web`` excludes the audio fixture detections."""
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["once", "--dry-run", "--source", "web"])

    assert rc == 0
    out = capsys.readouterr().out
    # Web fixtures still fire, but no audio-window items should appear.
    assert "Giveaway alert" in out
    assert "Audio window" not in out


def test_once_dry_run_with_db_dedupes_on_second_run(capsys, monkeypatch, tmp_path):
    """``once --dry-run --db PATH`` prints 3 first, then 0 on a repeat run."""
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "demo.db"

    rc = cli.main(["once", "--dry-run", "--db", str(db)])
    assert rc == 0
    first = capsys.readouterr().out
    assert first.count("Giveaway alert") >= 3

    # Second run against the same on-disk db dedupes everything away.
    rc = cli.main(["once", "--dry-run", "--db", str(db)])
    assert rc == 0
    second = capsys.readouterr().out
    assert "Giveaway alert" not in second
    assert "Done: 0 detection(s) notified." in second


def test_once_dry_run_no_db_is_repeatable(capsys, monkeypatch, tmp_path):
    """Plain ``--dry-run`` (no --db) uses an in-memory store every time."""
    monkeypatch.chdir(tmp_path)

    cli.main(["once", "--dry-run"])
    first = capsys.readouterr().out
    cli.main(["once", "--dry-run"])
    second = capsys.readouterr().out

    assert first.count("Giveaway alert") >= 3
    assert second.count("Giveaway alert") >= 3


def _args(argv):
    """Parse ``argv`` into the CLI namespace without dispatching."""
    return cli.build_parser().parse_args(argv)


def test_iter_items_polls_every_station_and_tags(
    make_multi_station_config, make_station, monkeypatch
):
    """Both stations are polled and their items carry the station tag."""
    station_a = make_station(name="Station A", slug="a", contest_urls=["https://a.test/win"])
    station_b = make_station(name="Station B", slug="b", contest_urls=["https://b.test/win"])
    config = make_multi_station_config([station_a, station_b])

    polled = []

    def fake_poll_web(station_config):
        url = station_config.contest_urls[0]
        polled.append(url)
        yield Item(
            title="Win tickets",
            url=url,
            text="call now to win tickets",
            published=None,
            source="web",
        )

    monkeypatch.setattr(cli, "poll_web", fake_poll_web)
    items = list(cli._iter_items(config, ("web",), config.stations))

    # Both stations' contest URLs were polled.
    assert polled == ["https://a.test/win", "https://b.test/win"]
    assert len(items) == 2
    # Items are tagged so the station appears in title and URL.
    assert items[0].title.startswith("[Station A]")
    assert "station=a" in items[0].url
    assert items[1].title.startswith("[Station B]")
    assert "station=b" in items[1].url


def test_dedupe_distinguishes_identical_text_across_stations(
    make_multi_station_config, make_station, monkeypatch
):
    """Two stations surfacing identical contest text dedupe independently."""
    station_a = make_station(name="Station A", slug="a", contest_urls=["https://a.test/win"])
    station_b = make_station(name="Station B", slug="b", contest_urls=["https://b.test/win"])
    config = make_multi_station_config([station_a, station_b])

    def fake_poll_web(station_config):
        # Identical title/url/text for both stations: only the per-station tag
        # applied by _iter_items can make them dedupe distinctly.
        yield Item(
            title="Win",
            url="https://shared.test/win",
            text="call now to win tickets",
            published=None,
            source="web",
        )

    monkeypatch.setattr(cli, "poll_web", fake_poll_web)
    items = list(cli._iter_items(config, ("web",), config.stations))
    assert len(items) == 2
    assert item_hash(items[0]) != item_hash(items[1])


def test_station_filter_restricts(make_multi_station_config, make_station):
    """``--station`` restricts polling to the named station(s)."""
    station_a = make_station(name="Station A", slug="a", contest_urls=["https://a.test/win"])
    station_b = make_station(name="Station B", slug="b", contest_urls=["https://b.test/win"])
    config = make_multi_station_config([station_a, station_b])

    selected = cli._selected_stations(_args(["once", "--station", "b"]), config)
    assert [s.slug for s in selected] == ["b"]

    both = cli._selected_stations(_args(["once"]), config)
    assert [s.slug for s in both] == ["a", "b"]


def test_station_without_stream_skips_audio(make_multi_station_config, make_station):
    """A station with no stream (audio disabled) skips audio without error."""
    silent = make_station(name="LOVE 972", slug="love972", stream_url=None, audio_enabled=False)
    config = make_multi_station_config([silent], telegram_token="tok", chat_id="chat")
    store = Store(":memory:")
    args = _args(["once", "--audio"])

    # web_fired=True so the audio path would run if the station allowed it.
    fired = cli._run_audio(args, config, store, silent, web_fired=True)
    assert fired == 0
    store.close()


def test_eligible_audio_stations_continuous_selects_streamable(
    make_multi_station_config, make_station
):
    """Continuous mode selects every station with a stream + audio_enabled."""
    a = make_station(name="A", slug="a", stream_url="https://s.test/a.aac", audio_enabled=True)
    b = make_station(name="B", slug="b", stream_url="https://s.test/b.aac", audio_enabled=True)
    silent = make_station(name="C", slug="c", stream_url=None, audio_enabled=False)
    config = make_multi_station_config([a, b, silent], audio_mode="continuous")
    args = _args(["once"])

    # No web detection fired, but continuous mode runs audio anyway.
    eligible = cli._eligible_audio_stations(args, config, config.stations, web_fired=False)
    assert [s.slug for s in eligible] == ["a", "b"]


def test_eligible_audio_stations_event_mode_requires_web_fired(
    make_multi_station_config, make_station
):
    """In event mode audio only runs when a web detection fired this pass."""
    a = make_station(name="A", slug="a", stream_url="https://s.test/a.aac", audio_enabled=True)
    config = make_multi_station_config([a], audio_mode="event", audio_enabled=True)
    args = _args(["once"])

    assert cli._eligible_audio_stations(args, config, config.stations, web_fired=False) == []
    fired = cli._eligible_audio_stations(args, config, config.stations, web_fired=True)
    assert [s.slug for s in fired] == ["a"]


def test_eligible_audio_stations_force_includes_disabled_with_stream(
    make_multi_station_config, make_station
):
    """``--audio`` force-enables a station that has a stream but audio_enabled off."""
    forced_ok = make_station(
        name="A", slug="a", stream_url="https://s.test/a.aac", audio_enabled=False
    )
    no_stream = make_station(name="B", slug="b", stream_url=None, audio_enabled=False)
    config = make_multi_station_config([forced_ok, no_stream])
    args = _args(["once", "--audio"])

    eligible = cli._eligible_audio_stations(args, config, config.stations, web_fired=False)
    # The streamless station is still excluded; the one with a stream is forced in.
    assert [s.slug for s in eligible] == ["a"]


def test_continuous_pass_captures_all_eligible_and_processes(
    make_multi_station_config, make_station, monkeypatch, tmp_path
):
    """A continuous multi-station pass captures every eligible station and
    processes each sequentially, producing one alert per station."""
    monkeypatch.chdir(tmp_path)
    a = make_station(
        name="Station A", slug="a", stream_url="https://s.test/a.aac", audio_enabled=True
    )
    b = make_station(
        name="Station B", slug="b", stream_url="https://s.test/b.aac", audio_enabled=True
    )
    # No telegram token/chat => notify_rich prints (dry-run) instead of POSTing,
    # keeping the test offline while still counting fresh alerts.
    config = make_multi_station_config([a, b], audio_mode="continuous")

    captured: list[str] = []

    def fake_capture_concurrently(stations, cfg, **kwargs):
        captured.extend(s.slug for s in stations)
        return {s.slug: tmp_path / f"{s.slug}.ogg" for s in stations}

    triggered: list[tuple[str | None, object]] = []

    def fake_trigger(cfg, *, stream_url=None, language=None, capture, **kwargs):
        clip = capture()  # the pre-captured path hook
        triggered.append((stream_url, clip))
        return "call now to win tickets", clip

    monkeypatch.setattr(cli, "capture_clips_concurrently", fake_capture_concurrently)
    monkeypatch.setattr(cli, "handle_audio_trigger", fake_trigger)

    store = Store(":memory:")
    args = _args(["once"])
    notified = cli._run_poll(args, config, store)
    store.close()

    # Both eligible stations captured, and both processed into fresh alerts.
    assert captured == ["a", "b"]
    assert notified == 2
    assert [t[0] for t in triggered] == ["https://s.test/a.aac", "https://s.test/b.aac"]


def test_continuous_pass_transcription_only_for_speech(
    make_multi_station_config, make_station, monkeypatch, tmp_path
):
    """Whisper (via the trigger) only yields a transcript for speech clips; a
    music clip returns no transcript and produces no alert."""
    monkeypatch.chdir(tmp_path)
    speechy = make_station(
        name="Speechy", slug="sp", stream_url="https://s.test/sp.aac", audio_enabled=True
    )
    musicy = make_station(
        name="Musicy", slug="mu", stream_url="https://s.test/mu.aac", audio_enabled=True
    )
    config = make_multi_station_config([speechy, musicy], audio_mode="continuous")

    def fake_capture_concurrently(stations, cfg, **kwargs):
        return {s.slug: tmp_path / f"{s.slug}.ogg" for s in stations}

    transcribed: list[str] = []

    def fake_trigger(cfg, *, stream_url=None, language=None, capture, **kwargs):
        clip = capture()
        # Music station: gate skips transcription -> empty transcript, clip kept.
        if stream_url.endswith("mu.aac"):
            return "", clip
        transcribed.append(stream_url)
        return "call now to win tickets", clip

    monkeypatch.setattr(cli, "capture_clips_concurrently", fake_capture_concurrently)
    monkeypatch.setattr(cli, "handle_audio_trigger", fake_trigger)

    store = Store(":memory:")
    notified = cli._run_poll(_args(["once"]), config, store)
    store.close()

    # Only the speech station alerts; the music station is gated out.
    assert transcribed == ["https://s.test/sp.aac"]
    assert notified == 1


def test_continuous_pass_forwards_per_station_language(
    make_multi_station_config, make_station, monkeypatch, tmp_path
):
    """Each station's language hint reaches the trigger (en vs zh)."""
    monkeypatch.chdir(tmp_path)
    en = make_station(
        name="EN",
        slug="en",
        language="en",
        stream_url="https://s.test/en.aac",
        audio_enabled=True,
    )
    zh = make_station(
        name="ZH",
        slug="zh",
        language="zh",
        stream_url="https://s.test/zh.aac",
        audio_enabled=True,
    )
    config = make_multi_station_config([en, zh], audio_mode="continuous")

    def fake_capture_concurrently(stations, cfg, **kwargs):
        return {s.slug: tmp_path / f"{s.slug}.ogg" for s in stations}

    langs: dict[str, object] = {}

    def fake_trigger(cfg, *, stream_url=None, language=None, capture, **kwargs):
        clip = capture()
        langs[stream_url] = language
        return "call now to win tickets", clip

    monkeypatch.setattr(cli, "capture_clips_concurrently", fake_capture_concurrently)
    monkeypatch.setattr(cli, "handle_audio_trigger", fake_trigger)

    store = Store(":memory:")
    cli._run_poll(_args(["once"]), config, store)
    store.close()

    assert langs["https://s.test/en.aac"] == "en"
    assert langs["https://s.test/zh.aac"] == "zh"


def test_continuous_pass_dedupes_per_station(
    make_multi_station_config, make_station, monkeypatch, tmp_path
):
    """Two stations with identical transcripts still produce two distinct
    alerts (dedupe keys include the station slug)."""
    monkeypatch.chdir(tmp_path)
    a = make_station(name="A", slug="a", stream_url="https://s.test/a.aac", audio_enabled=True)
    b = make_station(name="B", slug="b", stream_url="https://s.test/b.aac", audio_enabled=True)
    config = make_multi_station_config([a, b], audio_mode="continuous")

    def fake_capture_concurrently(stations, cfg, **kwargs):
        return {s.slug: tmp_path / f"{s.slug}.ogg" for s in stations}

    def fake_trigger(cfg, *, stream_url=None, language=None, capture, **kwargs):
        clip = capture()
        # Identical transcript for both stations.
        return "call now to win tickets", clip

    monkeypatch.setattr(cli, "capture_clips_concurrently", fake_capture_concurrently)
    monkeypatch.setattr(cli, "handle_audio_trigger", fake_trigger)

    store = Store(":memory:")
    notified = cli._run_poll(_args(["once"]), config, store)
    store.close()

    # Both alert despite identical transcripts: per-station dedupe keys differ.
    assert notified == 2


def test_process_station_clip_none_clip_is_skipped(
    make_multi_station_config, make_station, monkeypatch, tmp_path
):
    """A None clip (capture failed for that station) processes to 0 alerts and
    never invokes the trigger."""
    monkeypatch.chdir(tmp_path)
    a = make_station(name="A", slug="a", stream_url="https://s.test/a.aac", audio_enabled=True)
    config = make_multi_station_config([a], telegram_token="tok", chat_id="chat")

    def boom(*a, **k):
        raise AssertionError("trigger must not run for a None clip")

    monkeypatch.setattr(cli, "handle_audio_trigger", boom)
    store = Store(":memory:")
    fired = cli._process_station_clip(_args(["once"]), config, store, a, None)
    store.close()
    assert fired == 0


def test_lang_for_maps_languages(make_station):
    assert cli.lang_for(make_station(language="en")) == "en"
    assert cli.lang_for(make_station(language="zh")) == "zh"
    assert cli.lang_for(make_station(language="bilingual")) is None
    assert cli.lang_for(make_station(language="xx")) is None


def test_unknown_subcommand_returns_nonzero():
    """An unknown subcommand exits with a non-zero code via argparse."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bogus"])
    assert excinfo.value.code != 0


def test_no_subcommand_returns_nonzero():
    """Invoking with no subcommand is a usage error (non-zero)."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code != 0


def test_test_alert_dry_run(capsys, monkeypatch, tmp_path):
    """``test-alert --dry-run`` prints a sample alert and sends nothing."""
    monkeypatch.chdir(tmp_path)

    rc = cli.main(["test-alert", "--dry-run"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Giveaway alert" in out
    assert "no message sent" in out
