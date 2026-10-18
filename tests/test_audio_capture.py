"""Tests for hotline.audio_capture (no real ffmpeg)."""

from __future__ import annotations

from pathlib import Path

from hotline import audio_capture
from hotline.config import DEFAULT_USER_AGENT

STREAM_URL = "https://22903.live.streamtheworld.com/987FM_PREM.aac"


def test_ffmpeg_available_uses_injected_which() -> None:
    assert audio_capture.ffmpeg_available(which=lambda _name: "/usr/bin/ffmpeg") is True
    assert audio_capture.ffmpeg_available(which=lambda _name: None) is False


def test_capture_clip_builds_exact_argv(tmp_path, fake_runner, monkeypatch) -> None:
    monkeypatch.setattr(audio_capture, "ffmpeg_available", lambda: True)
    runner = fake_runner()
    out = tmp_path / "clip.ogg"

    result = audio_capture.capture_clip(STREAM_URL, 45, out, runner=runner)

    assert result == Path(out)
    assert out.read_bytes() == b"stub-audio"
    assert runner.calls == [
        [
            "ffmpeg",
            "-user_agent",
            DEFAULT_USER_AGENT,
            "-i",
            STREAM_URL,
            "-t",
            "45",
            "-c:a",
            "libopus",
            "-y",
            str(out),
        ]
    ]


def test_capture_clip_returns_none_when_ffmpeg_missing(tmp_path, fake_runner, monkeypatch) -> None:
    monkeypatch.setattr(audio_capture, "ffmpeg_available", lambda: False)
    runner = fake_runner()
    out = tmp_path / "clip.ogg"

    result = audio_capture.capture_clip(STREAM_URL, 10, out, runner=runner)

    assert result is None
    assert runner.calls == []
    assert not out.exists()


def test_capture_clip_returns_none_on_nonzero_exit(tmp_path, fake_runner, monkeypatch) -> None:
    monkeypatch.setattr(audio_capture, "ffmpeg_available", lambda: True)
    runner = fake_runner(returncode=1)
    out = tmp_path / "clip.ogg"

    result = audio_capture.capture_clip(STREAM_URL, 10, out, runner=runner)

    assert result is None
    assert len(runner.calls) == 1


def test_capture_clip_returns_none_when_runner_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(audio_capture, "ffmpeg_available", lambda: True)

    def _boom(argv, **kwargs):
        raise OSError("ffmpeg blew up")

    result = audio_capture.capture_clip(STREAM_URL, 10, tmp_path / "clip.ogg", runner=_boom)
    assert result is None
