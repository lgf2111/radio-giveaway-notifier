"""Audio source: feature-flagged, lazy transcription of the live stream.

This module is optional and degrades gracefully. When ``config.audio_enabled``
is ``False`` it logs once and yields nothing. When enabled it transcribes the
stream in fixed windows and runs the resulting text through detection upstream.

The heavy dependency (``faster-whisper``) is imported *lazily inside* the
function so importing this module never requires it. If the import fails the
source logs once and yields nothing instead of raising. Tests supply a fake
``transcriber`` callable and never load audio or hit the network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from hotline.config import Config
from hotline.sources import Item

logger = logging.getLogger(__name__)

#: Default transcription window length in seconds.
DEFAULT_WINDOW_SECONDS = 10

#: A transcriber turns one window (its index + text/sample payload) into text.
Transcriber = Callable[[str], str]

#: A clip transcriber turns a path to an audio file into transcript text.
ClipTranscriber = Callable[[str], str]


def transcribe_clip(
    audio_path: str | Path,
    *,
    model_size: str = "base",
    compute_type: str = "int8",
    transcriber: ClipTranscriber | None = None,
) -> str:
    """Transcribe an audio *file* into text.

    Args:
        audio_path: Path to a captured audio clip on disk.
        model_size: faster-whisper model size (e.g. ``"base"``). Used only when
            no ``transcriber`` is injected.
        compute_type: faster-whisper compute type (e.g. ``"int8"``). Used only
            when no ``transcriber`` is injected.
        transcriber: Callable ``(path) -> transcript``. When provided it is used
            directly; otherwise a real faster-whisper model is built lazily.

    Returns:
        The transcript text, or ``""`` (after logging once) when
        ``faster-whisper`` is not installed.
    """
    if transcriber is not None:
        return transcriber(str(audio_path))

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning(
            "audio: faster-whisper is not installed; cannot transcribe clip. "
            "Install the 'audio' extra to enable transcription."
        )
        return ""

    model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    segments, _info = model.transcribe(str(audio_path))
    return " ".join(segment.text for segment in segments).strip()


def iter_windows(
    lines_or_stream: Iterable[str], window_seconds: int = DEFAULT_WINDOW_SECONDS
) -> Iterator[str]:
    """Split a transcript-like iterable into fixed-duration windows.

    Each input line is treated as roughly one second of audio, so
    ``window_seconds`` consecutive non-empty lines are joined into one window.
    This keeps the windowing pure and testable over ``fixtures/transcript.txt``
    without any real audio decoding.

    Args:
        lines_or_stream: Iterable of text lines (e.g. an open transcript file).
        window_seconds: Number of lines to group per window.

    Yields:
        The joined text of each window, in order.
    """
    if window_seconds < 1:
        raise ValueError("window_seconds must be >= 1")

    buffer: list[str] = []
    for raw in lines_or_stream:
        line = raw.strip()
        if not line:
            continue
        buffer.append(line)
        if len(buffer) >= window_seconds:
            yield " ".join(buffer)
            buffer = []
    if buffer:
        yield " ".join(buffer)


def _build_whisper_transcriber(config: Config) -> Transcriber | None:
    """Build a real faster-whisper transcriber, or ``None`` if unavailable.

    The import is performed here so the dependency stays optional. Returns
    ``None`` (after logging) when ``faster-whisper`` is not installed.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning(
            "audio: faster-whisper is not installed; audio source disabled. "
            "Install the 'audio' extra to enable transcription."
        )
        return None

    model = WhisperModel("base")

    def _transcribe(window: str) -> str:
        segments, _info = model.transcribe(window)
        return " ".join(segment.text for segment in segments).strip()

    return _transcribe


def transcribe_stream(
    config: Config,
    transcriber: Transcriber | None = None,
    source: str = "audio",
    *,
    windows: Iterable[str] | None = None,
) -> Iterator[Item]:
    """Yield :class:`Item` records transcribed from the audio stream.

    Args:
        config: Runtime configuration; ``audio_enabled`` gates the whole source
            and ``audio_stream_url`` identifies the stream.
        transcriber: Callable ``(window_text) -> transcript``. When ``None`` a
            real faster-whisper transcriber is built lazily; a missing
            dependency degrades to yielding nothing.
        source: Source identifier recorded on produced items.
        windows: Optional iterable of pre-split window payloads. When ``None``
            the stream URL's content would be windowed in production; tests
            pass windows directly (e.g. from ``iter_windows`` over a transcript).

    Yields:
        One :class:`Item` per non-empty transcribed window. Yields nothing
        (without raising) when audio is disabled or the dependency is missing.
    """
    if not config.audio_enabled:
        logger.info("audio: disabled (audio_enabled is False); yielding nothing")
        return

    if transcriber is None:
        transcriber = _build_whisper_transcriber(config)
        if transcriber is None:
            return

    stream_url = config.audio_stream_url or "audio-stream"
    source_windows = windows if windows is not None else []

    for index, window in enumerate(source_windows):
        text = transcriber(window).strip()
        if not text:
            continue
        yield Item(
            title=f"Audio window {index}",
            url=f"{stream_url}#t={index * DEFAULT_WINDOW_SECONDS}",
            text=text,
            published=None,
            source=source,
        )
