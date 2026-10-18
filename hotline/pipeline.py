"""Event-driven audio trigger orchestration.

:func:`handle_audio_trigger` is the single composition point that turns the
live stream into a transcript: it captures ``config.audio_clip_seconds`` of
``config.audio_stream_url`` to a working ``.ogg`` file and transcribes it. Both
the capture and transcription steps are injected so tests drive the whole flow
offline with fakes, and so a degraded capture (missing ffmpeg/whisper) collapses
to ``("", None)`` instead of raising.

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

logger = logging.getLogger(__name__)

#: Capture signature: ``(stream_url, seconds, out_path) -> Path | None``.
Capture = Callable[[str, int, str], "Path | None"]

#: Transcribe signature: ``(audio_path) -> transcript text``.
Transcribe = Callable[["str | Path"], str]


def _default_capture(stream_url: str, seconds: int, out_path: str) -> Path | None:
    """Capture a clip with the real ffmpeg-backed :func:`capture_clip`."""
    return capture_clip(stream_url, seconds, out_path)


def handle_audio_trigger(
    config: Config,
    *,
    capture: Capture = _default_capture,
    transcribe: Transcribe = transcribe_clip,
    now: Callable[[], datetime] = datetime.now,
) -> tuple[str, Path | None]:
    """Capture a clip from the configured stream and transcribe it.

    Args:
        config: Runtime configuration supplying ``audio_stream_url`` and
            ``audio_clip_seconds``.
        capture: Injectable capture callable
            ``(stream_url, seconds, out_path) -> Path | None``. Returns ``None``
            when ffmpeg is unavailable or capture fails.
        transcribe: Injectable transcriber ``(audio_path) -> str``.
        now: Injectable clock used to name the working clip file uniquely.

    Returns:
        A ``(transcript, clip_path)`` tuple. When capture degrades to ``None``
        (ffmpeg/whisper missing or capture failure) returns ``("", None)`` so
        callers can skip the audio path without special-casing exceptions.
    """
    stream_url = config.audio_stream_url
    if not stream_url:
        logger.info("pipeline: no audio_stream_url configured; skipping audio trigger")
        return "", None

    stamp = now().strftime("%Y%m%d-%H%M%S-%f")
    out_path = str(Path(tempfile.gettempdir()) / f"hotline-clip-{stamp}.ogg")

    clip_path = capture(stream_url, config.audio_clip_seconds, out_path)
    if clip_path is None:
        logger.info("pipeline: audio capture unavailable; skipping audio trigger")
        return "", None

    transcript = transcribe(clip_path)
    return transcript, clip_path
