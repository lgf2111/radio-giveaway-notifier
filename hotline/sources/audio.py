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
import threading
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from hotline.config import Config
from hotline.sources import Item

logger = logging.getLogger(__name__)

#: Process-wide cache of built faster-whisper models, keyed by
#: ``(model_size, compute_type)``. Building a ``WhisperModel`` loads weights
#: from disk and (unless cached) checks the model revision over the network, so
#: a long-running ``watch`` must reuse one instance across every clip instead of
#: rebuilding per cycle. Guarded by ``_MODEL_LOCK`` because station captures run
#: concurrently and may race to build the first model.
_MODEL_CACHE: dict[tuple[str, str], Any] = {}
_MODEL_LOCK = threading.Lock()


def _get_whisper_model(model_size: str, compute_type: str) -> Any:
    """Return a cached ``WhisperModel`` for the given size/compute type.

    Builds the model once per ``(model_size, compute_type)`` and reuses it for
    the life of the process. faster-whisper models are safe to call
    concurrently for inference; only construction is serialised here.

    The model is built once and reused, and once its files are cached on disk
    it is loaded with ``local_files_only=True`` so neither construction nor
    transcription makes a Hugging Face network request. On the very first run,
    when the model is not yet downloaded, that offline load raises and we retry
    once online to fetch it; every later process start is fully offline.
    """
    from faster_whisper import WhisperModel

    key = (model_size, compute_type)
    model = _MODEL_CACHE.get(key)
    if model is not None:
        return model
    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            logger.info(
                "audio: loading faster-whisper model (size=%s, compute_type=%s); "
                "cached for the life of the process",
                model_size,
                compute_type,
            )
            try:
                # Prefer a fully offline load: no HF revision check per cycle.
                model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type=compute_type,
                    local_files_only=True,
                )
            except Exception as exc:  # noqa: BLE001 - first-run download fallback
                logger.info(
                    "audio: model not cached locally (%s); downloading once from "
                    "Hugging Face, then future loads are offline",
                    exc,
                )
                model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type=compute_type,
                    local_files_only=False,
                )
            _MODEL_CACHE[key] = model
        return model


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
    language: str | None = None,
    transcriber: ClipTranscriber | None = None,
) -> str:
    """Transcribe an audio *file* into text.

    Args:
        audio_path: Path to a captured audio clip on disk.
        model_size: faster-whisper model size (e.g. ``"base"``). Used only when
            no ``transcriber`` is injected.
        compute_type: faster-whisper compute type (e.g. ``"int8"``). Used only
            when no ``transcriber`` is injected.
        language: Whisper language hint (e.g. ``"en"``, ``"zh"``). ``None``
            lets Whisper auto-detect the language. Used only when no
            ``transcriber`` is injected.
        transcriber: Callable ``(path) -> transcript``. When provided it is used
            directly (unchanged); otherwise a real faster-whisper model is built
            lazily.

    Returns:
        The transcript text, or ``""`` (after logging once) when
        ``faster-whisper`` is not installed.
    """
    if transcriber is not None:
        return transcriber(str(audio_path))

    try:
        import faster_whisper  # noqa: F401  (availability probe)
    except ImportError:
        logger.warning(
            "audio: faster-whisper is not installed; cannot transcribe clip. "
            "Install the 'audio' extra to enable transcription."
        )
        return ""

    audio_input = _decode_to_pcm(audio_path)
    if audio_input is None:
        # ffmpeg/numpy unavailable: fall back to faster-whisper's own decoder
        # (PyAV). Works when a PyAV build compatible with the installed
        # faster-whisper is present; otherwise logs and returns "".
        audio_input = str(audio_path)

    model = _get_whisper_model(model_size, compute_type)
    try:
        segments, _info = model.transcribe(audio_input, language=language)
    except TypeError as exc:
        # Known faster-whisper/PyAV incompatibility: av.open() dropped the
        # metadata_errors kwarg in PyAV 13+. This only fires on the string-path
        # fallback above; the PCM-array path avoids PyAV entirely.
        logger.warning(
            "audio: could not decode clip for transcription (%s). Ensure ffmpeg "
            "is installed so clips are decoded without PyAV.",
            exc,
        )
        return ""
    return " ".join(segment.text for segment in segments).strip()


def _decode_to_pcm(audio_path: str | Path):
    """Decode an audio file to a mono 16 kHz float32 numpy array via ffmpeg.

    Returns the numpy array faster-whisper accepts directly, bypassing PyAV's
    ``av.open()`` (whose API varies across versions). Returns ``None`` when
    ffmpeg or numpy is unavailable, or on any decode failure, so the caller can
    fall back to faster-whisper's built-in decoder.
    """
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        return None
    try:
        import numpy as np
    except ImportError:
        return None

    argv = [
        "ffmpeg",
        "-nostdin",
        "-threads",
        "1",
        "-i",
        str(audio_path),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-",
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("audio: ffmpeg PCM decode failed (%s)", exc)
        return None
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


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
