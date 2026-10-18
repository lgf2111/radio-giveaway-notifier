"""Event-driven audio trigger orchestration.

:func:`handle_audio_trigger` is the single composition point that turns the
live stream into a transcript: it captures ``config.audio_clip_seconds`` of
``config.audio_stream_url`` to a working ``.ogg`` file, runs a cheap
music-vs-speech gate to skip transcribing songs, and transcribes the rest. The
capture, gate, and transcription steps are injected so tests drive the whole
flow offline with fakes, and so a degraded capture (missing ffmpeg/whisper)
collapses to ``("", None)`` instead of raising.

This module deliberately does **not** import :mod:`hotline.cli`; the dependency
runs the other way (``cli`` imports ``pipeline``), avoiding a cycle.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from hotline.audio_capture import capture_clip
from hotline.config import Config
from hotline.sources.audio import transcribe_clip
from hotline.speech_gate import Classification, classify_clip

logger = logging.getLogger(__name__)

#: Capture signature: ``(stream_url, seconds, out_path) -> Path | None``.
Capture = Callable[[str, int, str], "Path | None"]

#: Transcribe signature: ``(audio_path) -> transcript text``.
Transcribe = Callable[["str | Path"], str]

#: Classify signature: ``(audio_path) -> Classification`` (music-vs-speech gate).
Classify = Callable[["str | Path"], Classification]


def _default_capture(stream_url: str, seconds: int, out_path: str) -> Path | None:
    """Capture a clip with the real ffmpeg-backed :func:`capture_clip`."""
    return capture_clip(stream_url, seconds, out_path)


def handle_audio_trigger(
    config: Config,
    *,
    language: str | None = None,
    stream_url: str | None = None,
    capture: Capture = _default_capture,
    classify: Classify = classify_clip,
    transcribe: Transcribe | None = None,
    now: Callable[[], datetime] = datetime.now,
) -> tuple[str, Path | None]:
    """Capture a clip from the configured stream and transcribe it.

    Between capture and transcription the clip passes through the music-vs-speech
    gate when ``config.audio_gate_enabled`` is set. The gate transcribes by
    default and only SKIPS the clip when it is *confidently* music — ``is_speech``
    is ``False`` and ``confidence`` meets ``config.audio_gate_min_confidence``. A
    skip returns ``("", clip_path)`` so an empty transcript suppresses any
    detection/alert while the clip path stays informative. The gate is
    speech-biased and fails open, so an ambiguous or undecodable clip is always
    transcribed.

    Args:
        config: Runtime configuration supplying ``audio_stream_url``,
            ``audio_clip_seconds``, and the ``audio_gate_*`` settings.
        language: Whisper language hint forwarded to the default transcriber
            (e.g. ``"en"``, ``"zh"``). ``None`` lets Whisper auto-detect. Only
            applied on the default :func:`transcribe_clip` path; an injected
            ``transcribe`` callable is called unchanged as ``(path) -> str``.
        stream_url: Per-station stream URL override. When provided it is
            captured instead of ``config.audio_stream_url``.
        capture: Injectable capture callable
            ``(stream_url, seconds, out_path) -> Path | None``. Returns ``None``
            when ffmpeg is unavailable or capture fails.
        classify: Injectable music-vs-speech gate ``(audio_path) -> Classification``.
            Consulted only when ``config.audio_gate_enabled`` is true.
        transcribe: Injectable transcriber ``(audio_path) -> str``. When
            ``None`` (the default) the real :func:`transcribe_clip` runs with
            the ``language`` hint; an injected callable is used as-is.
        now: Injectable clock used to name the working clip file uniquely.

    Returns:
        A ``(transcript, clip_path)`` tuple. When capture degrades to ``None``
        (ffmpeg/whisper missing or capture failure) returns ``("", None)``. When
        the gate skips confident music returns ``("", clip_path)``.
    """
    stream_url = stream_url or config.audio_stream_url
    if not stream_url:
        logger.info("pipeline: no audio_stream_url configured; skipping audio trigger")
        return "", None

    stamp = now().strftime("%Y%m%d-%H%M%S-%f")
    out_path = str(Path(tempfile.gettempdir()) / f"hotline-clip-{stamp}.ogg")

    clip_path = capture(stream_url, config.audio_clip_seconds, out_path)
    if clip_path is None:
        logger.info("pipeline: audio capture unavailable; skipping audio trigger")
        return "", None

    if config.audio_gate_enabled:
        if config.audio_gate_backend != "builtin":
            logger.warning(
                "pipeline: audio_gate_backend=%r is not implemented; "
                "falling back to the builtin DSP gate",
                config.audio_gate_backend,
            )
        result = classify(clip_path)
        if not result.is_speech and result.confidence >= config.audio_gate_min_confidence:
            logger.info(
                "pipeline: gate classified clip as music (confidence=%.2f); "
                "skipping transcription (%s)",
                result.confidence,
                result.reason,
            )
            return "", clip_path

    if transcribe is None:
        # Default path: forward the language hint to the real transcriber.
        transcript = transcribe_clip(clip_path, language=language)
    else:
        # Injected transcriber stays (path) -> str and is called unchanged.
        transcript = transcribe(clip_path)
    return transcript, clip_path
