"""Tests for the event-driven audio pipeline orchestration.

Capture and transcription are injected, so no ffmpeg/whisper/network runs.
The end-to-end tests wire a fake web detection through the audio trigger,
detection, summarization, and rich notify, asserting a single alert and
Store-backed dedupe on a repeat.
"""

from __future__ import annotations

from pathlib import Path

from hotline.config import Config
from hotline.detect import detect
from hotline.notify import notify_rich
from hotline.pipeline import handle_audio_trigger
from hotline.sources import Item
from hotline.store import Store, item_hash
from hotline.summarize import summarize


def _config() -> Config:
    return Config(
        audio_enabled=True,
        audio_stream_url="https://22903.live.streamtheworld.com/987FM_PREM.aac",
        audio_clip_seconds=30,
        telegram_token="tok",
        chat_id="chat",
    )


def test_handle_audio_trigger_returns_transcript_and_clip(fake_clip_transcriber, tmp_path) -> None:
    config = _config()
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"stub")

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        assert stream_url == config.audio_stream_url
        assert seconds == 30
        return clip

    transcribe = fake_clip_transcriber("phone lines open, call now to win tickets")

    transcript, clip_path = handle_audio_trigger(config, capture=capture, transcribe=transcribe)

    assert transcript == "phone lines open, call now to win tickets"
    assert clip_path == clip
    assert transcribe.calls == [clip]


def test_handle_audio_trigger_degrades_when_capture_none(fake_clip_transcriber) -> None:
    config = _config()

    def capture(stream_url: str, seconds: int, out_path: str) -> None:
        return None

    transcribe = fake_clip_transcriber("unused")

    transcript, clip_path = handle_audio_trigger(config, capture=capture, transcribe=transcribe)

    assert transcript == ""
    assert clip_path is None
    # Transcription is skipped when there is no clip.
    assert transcribe.calls == []


def test_end_to_end_fires_one_rich_alert_and_dedupes(
    fake_clip_transcriber, make_sender, make_multipart_sender, fixtures_dir, tmp_path
) -> None:
    config = _config()
    transcript = (fixtures_dir / "callout_transcript.txt").read_text(encoding="utf-8")
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"stub")

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        return clip

    transcribe = fake_clip_transcriber(transcript)
    store = Store(":memory:")
    post = make_sender()
    sender = make_multipart_sender()

    def run_once() -> int:
        # Simulate a web detection having fired, then run the audio trigger.
        got_transcript, got_clip = handle_audio_trigger(
            config, capture=capture, transcribe=transcribe
        )
        detection = detect(got_transcript, "audio")
        assert detection is not None
        item = Item(
            title="987FM on-air callout",
            url=f"{config.audio_stream_url}#audio",
            text=got_transcript,
            published=None,
            source="audio",
        )
        hash_ = item_hash(item)
        if not store.should_notify(hash_):
            return 0
        summary = summarize(got_transcript, detection, config)
        notify_rich(
            summary,
            detection,
            got_transcript,
            got_clip,
            config,
            dry_run=False,
            post=post,
            sender=sender,
        )
        store.mark_notified(hash_)
        return 1

    first = run_once()
    second = run_once()

    assert first == 1
    assert second == 0
    # Exactly one text + one voice message overall.
    assert len(post.calls) == 1
    assert len(sender.calls) == 1
    store.close()
