"""Capture a short audio clip from the live stream with ffmpeg.

``ffmpeg`` is a *system* dependency (installed via apt/brew), never pip, so it
may be absent. This module degrades gracefully: :func:`capture_clip` returns
``None`` (after logging once) when ffmpeg is missing, when the runner raises,
or when ffmpeg exits non-zero — it never raises.

The ffmpeg command is built as an argv *list* and passed to the runner without
a shell, so stream URLs and user agents can never be interpreted as shell
syntax. The runner (``subprocess.run`` by default) is injectable so tests can
assert the exact argv and write a stub file without touching real ffmpeg.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from hotline.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

#: Type of the injectable process runner (mirrors ``subprocess.run``).
Runner = Callable[..., subprocess.CompletedProcess]


def ffmpeg_available(which: Callable[[str], str | None] = shutil.which) -> bool:
    """Return whether an ``ffmpeg`` binary is resolvable on ``PATH``.

    Args:
        which: Lookup callable, defaulting to :func:`shutil.which`. Injectable
            so tests can simulate a missing binary.

    Returns:
        ``True`` if ffmpeg is found, else ``False``.
    """
    return which("ffmpeg") is not None


def capture_clip(
    stream_url: str,
    seconds: int,
    out_path: str | Path,
    *,
    runner: Runner = subprocess.run,
    user_agent: str = DEFAULT_USER_AGENT,
) -> Path | None:
    """Capture ``seconds`` of ``stream_url`` into ``out_path`` as Opus audio.

    Args:
        stream_url: URL of the live audio stream ffmpeg reads directly.
        seconds: Clip duration in seconds.
        out_path: Destination file path for the captured clip.
        runner: Process runner (``subprocess.run`` by default); injectable for
            tests. Must accept an argv list and ``capture_output``.
        user_agent: Polite User-Agent sent to the stream via ``-user_agent``.

    Returns:
        ``Path(out_path)`` on success, or ``None`` (after logging once) when
        ffmpeg is unavailable, the runner raises, or ffmpeg exits non-zero.
    """
    if not ffmpeg_available():
        logger.warning(
            "audio_capture: ffmpeg not found on PATH; cannot capture clip. "
            "Install ffmpeg (apt/brew) to enable audio capture."
        )
        return None

    out = Path(out_path)
    argv = [
        "ffmpeg",
        "-user_agent",
        user_agent,
        "-i",
        stream_url,
        "-t",
        str(seconds),
        "-c:a",
        "libopus",
        "-y",
        str(out),
    ]

    try:
        result = runner(argv, capture_output=True)
    except Exception:
        logger.warning("audio_capture: ffmpeg runner raised; returning None", exc_info=True)
        return None

    if result.returncode != 0:
        logger.warning(
            "audio_capture: ffmpeg exited with code %s; returning None",
            result.returncode,
        )
        return None

    return out
