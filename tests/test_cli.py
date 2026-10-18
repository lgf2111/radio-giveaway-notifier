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
