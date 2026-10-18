"""Tests for the CLI wiring in :mod:`hotline.cli`.

All runs are offline: ``once --dry-run`` falls back to the bundled fixtures,
and no test performs network I/O.
"""

from __future__ import annotations

import pytest

from hotline import cli


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
