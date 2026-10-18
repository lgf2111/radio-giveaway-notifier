"""Tests for hotline.sources.audio.transcribe_clip (no real whisper)."""

from __future__ import annotations

import sys

from hotline.sources.audio import transcribe_clip


def test_transcribe_clip_uses_injected_transcriber(fake_clip_transcriber) -> None:
    transcriber = fake_clip_transcriber("call now to win tickets")
    text = transcribe_clip("/tmp/clip.ogg", transcriber=transcriber)
    assert text == "call now to win tickets"
    assert transcriber.calls == ["/tmp/clip.ogg"]


def test_transcribe_clip_returns_empty_on_missing_dependency(monkeypatch) -> None:
    # A None entry makes the lazy `from faster_whisper import WhisperModel`
    # raise ImportError, which must degrade to "".
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert transcribe_clip("/tmp/clip.ogg") == ""
