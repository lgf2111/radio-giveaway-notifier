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


def _config(**overrides) -> Config:
    base = dict(
        audio_enabled=True,
        audio_stream_url="https://22903.live.streamtheworld.com/987FM_PREM.aac",
        audio_clip_seconds=30,
        telegram_token="tok",
        chat_id="chat",
    )
    base.update(overrides)
    return Config(**base)


def test_handle_audio_trigger_returns_transcript_and_clip(
    fake_clip_transcriber, fake_classifier, tmp_path
) -> None:
    config = _config()
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"stub")

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        assert stream_url == config.audio_stream_url
        assert seconds == 30
        return clip

    classify = fake_classifier(is_speech=True)
    transcribe = fake_clip_transcriber("phone lines open, call now to win tickets")

    transcript, clip_path = handle_audio_trigger(
        config, capture=capture, classify=classify, transcribe=transcribe
    )

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
    fake_clip_transcriber,
    fake_classifier,
    make_sender,
    make_multipart_sender,
    fixtures_dir,
    tmp_path,
) -> None:
    config = _config()
    transcript = (fixtures_dir / "callout_transcript.txt").read_text(encoding="utf-8")
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"stub")

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        return clip

    classify = fake_classifier(is_speech=True)
    transcribe = fake_clip_transcriber(transcript)
    store = Store(":memory:")
    post = make_sender()
    sender = make_multipart_sender()

    def run_once() -> int:
        # Simulate a web detection having fired, then run the audio trigger.
        got_transcript, got_clip = handle_audio_trigger(
            config, capture=capture, classify=classify, transcribe=transcribe
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


def test_handle_audio_trigger_honors_stream_url_override(
    fake_clip_transcriber, fake_classifier, tmp_path
) -> None:
    config = _config()
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"stub")
    seen: dict[str, object] = {}

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        seen["stream_url"] = stream_url
        return clip

    classify = fake_classifier(is_speech=True)
    transcribe = fake_clip_transcriber("call now to win tickets")

    override = "https://22903.live.streamtheworld.com/YES933_PREM.aac"
    transcript, clip_path = handle_audio_trigger(
        config,
        stream_url=override,
        capture=capture,
        classify=classify,
        transcribe=transcribe,
    )

    # The per-station override wins over config.audio_stream_url.
    assert seen["stream_url"] == override
    assert transcript == "call now to win tickets"
    assert clip_path == clip


def test_handle_audio_trigger_forwards_language_to_default_transcriber(
    fake_classifier, monkeypatch, tmp_path
) -> None:
    import hotline.pipeline as pipeline

    config = _config()
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"stub")

    recorded: dict[str, object] = {}

    def fake_transcribe_clip(path, *, language=None):
        recorded["path"] = path
        recorded["language"] = language
        return "ni hao da dian hua"

    # Patch the module-level default transcriber the None-path resolves to.
    monkeypatch.setattr(pipeline, "transcribe_clip", fake_transcribe_clip)

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        return clip

    classify = fake_classifier(is_speech=True)

    # transcribe left as None => default path => language is forwarded.
    transcript, clip_path = handle_audio_trigger(
        config, language="zh", capture=capture, classify=classify
    )

    assert transcript == "ni hao da dian hua"
    assert recorded["path"] == clip
    assert recorded["language"] == "zh"


def test_injected_transcriber_is_called_without_language(
    fake_clip_transcriber, fake_classifier, tmp_path
) -> None:
    config = _config()
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"stub")

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        return clip

    classify = fake_classifier(is_speech=True)
    transcribe = fake_clip_transcriber("call now to win tickets")

    # An injected (path)->str transcriber is used unchanged even with a language.
    transcript, _ = handle_audio_trigger(
        config, language="zh", capture=capture, classify=classify, transcribe=transcribe
    )

    assert transcript == "call now to win tickets"
    assert transcribe.calls == [clip]


def _clip(tmp_path) -> Path:
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"stub")
    return clip


def test_gate_skips_transcription_on_confident_music(
    fake_clip_transcriber, fake_classifier, tmp_path
) -> None:
    config = _config(audio_gate_enabled=True, audio_gate_min_confidence=0.6)
    clip = _clip(tmp_path)

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        return clip

    classify = fake_classifier(is_speech=False, confidence=0.9)
    transcribe = fake_clip_transcriber("should not be called")

    transcript, clip_path = handle_audio_trigger(
        config, capture=capture, classify=classify, transcribe=transcribe
    )

    assert transcript == ""
    assert clip_path == clip
    assert transcribe.calls == []
    assert classify.calls == [clip]


def test_gate_transcribes_on_speech(fake_clip_transcriber, fake_classifier, tmp_path) -> None:
    config = _config(audio_gate_enabled=True, audio_gate_min_confidence=0.6)
    clip = _clip(tmp_path)

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        return clip

    classify = fake_classifier(is_speech=True, confidence=0.9)
    transcribe = fake_clip_transcriber("call now to win tickets")

    transcript, clip_path = handle_audio_trigger(
        config, capture=capture, classify=classify, transcribe=transcribe
    )

    assert transcript == "call now to win tickets"
    assert clip_path == clip
    assert transcribe.calls == [clip]


def test_gate_transcribes_when_music_below_min_confidence(
    fake_clip_transcriber, fake_classifier, tmp_path
) -> None:
    # Music verdict but below the min confidence => speech-bias => transcribe.
    config = _config(audio_gate_enabled=True, audio_gate_min_confidence=0.6)
    clip = _clip(tmp_path)

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        return clip

    classify = fake_classifier(is_speech=False, confidence=0.4)
    transcribe = fake_clip_transcriber("call now to win tickets")

    transcript, clip_path = handle_audio_trigger(
        config, capture=capture, classify=classify, transcribe=transcribe
    )

    assert transcript == "call now to win tickets"
    assert transcribe.calls == [clip]


def test_gate_disabled_always_transcribes_without_consulting_classifier(
    fake_clip_transcriber, fake_classifier, tmp_path
) -> None:
    config = _config(audio_gate_enabled=False)
    clip = _clip(tmp_path)

    def capture(stream_url: str, seconds: int, out_path: str) -> Path:
        return clip

    # Confident music, but gate is disabled => classifier must not be consulted.
    classify = fake_classifier(is_speech=False, confidence=0.99)
    transcribe = fake_clip_transcriber("call now to win tickets")

    transcript, clip_path = handle_audio_trigger(
        config, capture=capture, classify=classify, transcribe=transcribe
    )

    assert transcript == "call now to win tickets"
    assert transcribe.calls == [clip]
    assert classify.calls == []
