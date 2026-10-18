"""Tests for hotline.sources.audio."""

from __future__ import annotations

import sys

from hotline.config import Config
from hotline.sources.audio import iter_windows, transcribe_stream


def test_iter_windows_splits_into_fixed_windows() -> None:
    lines = [f"line {n}" for n in range(25)]
    windows = list(iter_windows(lines, window_seconds=10))
    # 25 lines -> two full 10-line windows + one 5-line remainder.
    assert len(windows) == 3
    assert windows[0] == " ".join(f"line {n}" for n in range(10))
    assert windows[2] == " ".join(f"line {n}" for n in range(20, 25))


def test_iter_windows_skips_blank_lines(read_fixture) -> None:
    transcript = read_fixture("transcript.txt")
    windows = list(iter_windows(transcript.splitlines(), window_seconds=10))
    # Three non-empty lines fit into a single 10s window.
    assert len(windows) == 1
    assert "call now to win tickets" in windows[0]


def test_transcribe_stream_disabled_yields_nothing(make_transcriber) -> None:
    config = Config(audio_enabled=False, audio_stream_url="https://example.test/stream.mp3")
    transcriber = make_transcriber()
    items = list(transcribe_stream(config, transcriber=transcriber, windows=["call now"]))
    assert items == []
    # Transcriber never invoked when disabled.
    assert transcriber.calls == []


def test_transcribe_stream_yields_items_with_fake_transcriber(
    read_fixture, make_transcriber
) -> None:
    config = Config(audio_enabled=True, audio_stream_url="https://example.test/stream.mp3")
    transcriber = make_transcriber()
    windows = list(iter_windows(read_fixture("transcript.txt").splitlines()))

    items = list(transcribe_stream(config, transcriber=transcriber, windows=windows))
    assert len(items) == 1
    assert items[0].source == "audio"
    assert "call now to win tickets" in items[0].text
    assert items[0].url.startswith("https://example.test/stream.mp3#t=")


def test_transcribe_stream_skips_empty_transcripts(make_transcriber) -> None:
    config = Config(audio_enabled=True)
    transcriber = make_transcriber(transform=lambda _window: "   ")
    items = list(transcribe_stream(config, transcriber=transcriber, windows=["anything"]))
    assert items == []


def test_transcribe_stream_degrades_on_missing_dependency(monkeypatch) -> None:
    # Simulate faster_whisper being unavailable: a None entry makes the
    # lazy `from faster_whisper import WhisperModel` raise ImportError.
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    config = Config(audio_enabled=True)
    # No transcriber injected -> falls back to the lazy import, which fails.
    items = list(transcribe_stream(config, windows=["call now to win tickets"]))
    assert items == []
