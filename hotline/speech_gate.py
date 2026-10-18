"""Lightweight music-vs-speech gate run before Whisper transcription.

The gate's job is to keep the expensive Whisper step off songs: it runs a
cheap, pure-stdlib DSP classifier over a captured clip and lets the pipeline
SKIP transcription only when the clip is *confidently* music. Everything here
is deliberately simple and dependency-free (``math``, ``cmath``, ``struct``,
``array``, ``wave`` — NO numpy, NO new pip deps). ffmpeg is only used to decode
a clip to PCM and is optional/injectable.

Two safety properties guide every decision:

* **Speech-biased.** We return ``MUSIC`` only when the music evidence is strong
  and consistent; anything ambiguous (silence, short/odd input, mixed frames)
  classifies as ``SPEECH`` so a giveaway callout is never gated out.
* **Fail-open.** If ffmpeg is missing, the decoder raises, or decoding yields no
  samples, :func:`classify_clip` returns ``SPEECH`` at low confidence instead of
  raising — a broken gate still lets transcription run.

Features computed per short frame: short-time RMS energy, zero-crossing rate
(ZCR), and spectral flatness over a compact pure-Python radix-2 FFT. Spectral
flatness is the primary music discriminator — tonal/steady music has high, flat
spectra while speech is spikier with energy pauses. An energy-variance
(modulation) term reinforces the speech bias. The threshold constants below are
the tunable surface; the decision rule and bias direction are fixed.
"""

from __future__ import annotations

import cmath
import logging
import math
import subprocess
from array import array
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from hotline.audio_capture import ffmpeg_available
from hotline.config import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)

#: FFT/frame length in samples. A power of two so the radix-2 FFT applies
#: directly. 1024 samples @ 16 kHz is ~64 ms — long enough for stable spectral
#: statistics, short enough to stay cheap.
FRAME_SIZE = 1024

#: Mean spectral flatness at or above this is treated as music-like. Flatness is
#: in ``[0, 1]``; tonal/steady music trends high, speech trends lower. Tuned so
#: real speech stays below and sustained multi-tone/broadband music clears it.
SPECTRAL_FLATNESS_MUSIC_THRESHOLD = 0.35

#: Frames with RMS below this are treated as silence and ignored (not counted as
#: music). Keeps dead air before a callout from ever reading as music.
SILENCE_RMS_THRESHOLD = 1e-4

#: Minimum number of non-silent (voiced) frames required before a MUSIC verdict
#: is even allowed. Below this there is not enough signal to be confident, so we
#: fail open to speech.
MIN_VOICED_FRAMES = 4

#: Upper bound on the normalised energy-variance (modulation) of voiced frames
#: for a MUSIC verdict. Speech bursts between pauses produce high modulation;
#: steady music produces low modulation. High modulation blocks a music verdict.
ENERGY_MODULATION_MUSIC_MAX = 0.5


@dataclass(frozen=True)
class Classification:
    """Result of a music-vs-speech decision.

    Attributes:
        is_speech: ``True`` when the clip should be transcribed (speech, or any
            uncertain/fail-open case). ``False`` only on a confident music
            verdict.
        confidence: Confidence in the verdict, in ``[0.0, 1.0]``. The pipeline
            skips transcription only when ``is_speech`` is ``False`` *and* this
            meets the configured minimum.
        reason: Short human-readable explanation of the decision, for logs.
    """

    is_speech: bool
    confidence: float
    reason: str


#: Decoder signature: ``(audio_path) -> list of mono float samples``.
PcmDecoder = Callable[["str | Path"], list[float]]


def _fft(samples: Sequence[complex]) -> list[complex]:
    """Return the radix-2 FFT of ``samples``.

    A compact recursive Cooley-Tukey FFT using :mod:`cmath` (Python's stdlib has
    no FFT). The input length must be a power of two; callers frame the signal to
    :data:`FRAME_SIZE` so this always holds. Kept small and self-contained on
    purpose — it is exercised directly by a known-signal test.

    Args:
        samples: Complex (or real) samples whose length is a power of two.

    Returns:
        The complex frequency-domain spectrum, same length as the input.
    """
    n = len(samples)
    if n <= 1:
        return list(samples)
    if n & (n - 1) != 0:
        raise ValueError(f"FFT length must be a power of two, got {n}")

    even = _fft(samples[0::2])
    odd = _fft(samples[1::2])
    spectrum = [0j] * n
    half = n // 2
    for k in range(half):
        twiddle = cmath.exp(-2j * math.pi * k / n) * odd[k]
        spectrum[k] = even[k] + twiddle
        spectrum[k + half] = even[k] - twiddle
    return spectrum


def _rms(frame: Sequence[float]) -> float:
    """Return the root-mean-square energy of ``frame`` (0.0 for an empty frame)."""
    if not frame:
        return 0.0
    total = math.fsum(sample * sample for sample in frame)
    return math.sqrt(total / len(frame))


def _zero_crossing_rate(frame: Sequence[float]) -> float:
    """Return the zero-crossing rate of ``frame`` in ``[0, 1]``.

    The fraction of adjacent sample pairs whose sign changes. High for noisy or
    unvoiced sounds, informative as a secondary speech/music cue.
    """
    if len(frame) < 2:
        return 0.0
    crossings = 0
    for prev, curr in zip(frame, frame[1:], strict=False):
        if (prev >= 0.0) != (curr >= 0.0):
            crossings += 1
    return crossings / (len(frame) - 1)


def _spectral_flatness(magnitudes: Sequence[float]) -> float:
    """Return the spectral flatness of a magnitude spectrum in ``[0, 1]``.

    Flatness is the ratio of the geometric mean to the arithmetic mean of the
    spectral magnitudes. A flat (white/broadband or richly tonal) spectrum tends
    toward 1.0; a peaky spectrum tends toward 0.0. Guarded against zeros so a
    silent or empty spectrum returns 0.0 rather than raising.

    Args:
        magnitudes: Non-negative magnitude-spectrum values.

    Returns:
        The spectral flatness, or 0.0 when there is no positive energy.
    """
    positive = [m for m in magnitudes if m > 0.0]
    if not positive:
        return 0.0
    arithmetic_mean = math.fsum(positive) / len(positive)
    if arithmetic_mean <= 0.0:
        return 0.0
    log_mean = math.fsum(math.log(m) for m in positive) / len(positive)
    geometric_mean = math.exp(log_mean)
    return geometric_mean / arithmetic_mean


def classify_pcm(samples: Sequence[float], sample_rate: int) -> Classification:
    """Classify mono PCM ``samples`` as speech or music.

    Frames the signal into non-overlapping :data:`FRAME_SIZE` windows, drops
    silent frames (below :data:`SILENCE_RMS_THRESHOLD`), and averages spectral
    flatness over the voiced frames. The decision is speech-biased:

    * Fewer than :data:`MIN_VOICED_FRAMES` voiced frames → SPEECH (fail-open;
      not enough signal to be confident).
    * Mean flatness ≥ :data:`SPECTRAL_FLATNESS_MUSIC_THRESHOLD` *and* low
      energy modulation (≤ :data:`ENERGY_MODULATION_MUSIC_MAX`) → MUSIC, with
      confidence scaled by how far flatness clears the threshold.
    * Otherwise → SPEECH.

    Args:
        samples: Mono PCM samples, typically float32 in roughly ``[-1, 1]``.
        sample_rate: Sample rate in Hz (used only for documentation/framing; the
            decision is rate-agnostic).

    Returns:
        A :class:`Classification` with the verdict, confidence, and a reason.
    """
    voiced_flatness: list[float] = []
    voiced_energy: list[float] = []

    for start in range(0, len(samples) - FRAME_SIZE + 1, FRAME_SIZE):
        frame = samples[start : start + FRAME_SIZE]
        rms = _rms(frame)
        if rms < SILENCE_RMS_THRESHOLD:
            continue
        spectrum = _fft([complex(value, 0.0) for value in frame])
        # Use the lower half (up to Nyquist); the spectrum is conjugate-symmetric
        # for a real input.
        magnitudes = [abs(bin_) for bin_ in spectrum[: FRAME_SIZE // 2]]
        voiced_flatness.append(_spectral_flatness(magnitudes))
        voiced_energy.append(rms)

    if len(voiced_flatness) < MIN_VOICED_FRAMES:
        return Classification(
            is_speech=True,
            confidence=0.1,
            reason="insufficient signal; fail-open to speech",
        )

    mean_flatness = math.fsum(voiced_flatness) / len(voiced_flatness)
    modulation = _energy_modulation(voiced_energy)

    music_like = (
        mean_flatness >= SPECTRAL_FLATNESS_MUSIC_THRESHOLD
        and modulation <= ENERGY_MODULATION_MUSIC_MAX
    )
    if music_like:
        # Scale confidence by how decisively flatness clears the threshold,
        # clamped to [0.5, 0.99] so a bare-threshold verdict stays modest.
        headroom = (mean_flatness - SPECTRAL_FLATNESS_MUSIC_THRESHOLD) / (
            1.0 - SPECTRAL_FLATNESS_MUSIC_THRESHOLD
        )
        confidence = max(0.5, min(0.99, 0.6 + 0.4 * headroom))
        return Classification(
            is_speech=False,
            confidence=confidence,
            reason=(
                f"music-like: mean spectral flatness {mean_flatness:.2f} "
                f"(>= {SPECTRAL_FLATNESS_MUSIC_THRESHOLD}), "
                f"energy modulation {modulation:.2f}"
            ),
        )

    return Classification(
        is_speech=True,
        confidence=0.6,
        reason=(
            f"speech-like: mean spectral flatness {mean_flatness:.2f} "
            f"(< {SPECTRAL_FLATNESS_MUSIC_THRESHOLD}) or "
            f"energy modulation {modulation:.2f} (> {ENERGY_MODULATION_MUSIC_MAX})"
        ),
    )


def _energy_modulation(energies: Sequence[float]) -> float:
    """Return the coefficient of variation of frame energies (std / mean).

    A scale-free measure of how much the energy fluctuates across frames. Speech
    (bursts separated by pauses) modulates heavily; sustained music stays
    steadier. Returns 0.0 when the mean energy is non-positive.
    """
    if not energies:
        return 0.0
    mean = math.fsum(energies) / len(energies)
    if mean <= 0.0:
        return 0.0
    variance = math.fsum((e - mean) ** 2 for e in energies) / len(energies)
    return math.sqrt(variance) / mean


def _default_decoder(
    audio_path: str | Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[float]:
    """Decode ``audio_path`` to mono float32 PCM @ 16 kHz with ffmpeg.

    Builds the ffmpeg argv as a *list* (no shell) and reads raw ``f32le`` bytes
    from stdout, unpacking them into a list of floats. Raises if ffmpeg is
    unavailable or exits non-zero; :func:`classify_clip` wraps this to fail open.

    Args:
        audio_path: Path to the clip to decode.
        runner: Process runner (``subprocess.run`` by default); injectable.
        user_agent: Polite User-Agent (unused for local files but kept for
            parity with :mod:`hotline.audio_capture`).

    Returns:
        A list of mono float samples.

    Raises:
        RuntimeError: If ffmpeg is not on ``PATH`` or exits non-zero.
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH; cannot decode clip for gating")

    argv = [
        "ffmpeg",
        "-i",
        str(audio_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "f32le",
        "-",
    ]
    result = runner(argv, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg exited with code {result.returncode} while decoding clip")

    data = result.stdout or b""
    return list(array("f", data[: len(data) - (len(data) % 4)]))


def classify_clip(
    audio_path: str | Path,
    *,
    decoder: PcmDecoder | None = None,
    sample_rate: int = 16000,
) -> Classification:
    """Decode ``audio_path`` and classify it as speech or music.

    Uses ``decoder`` when injected, else the ffmpeg-backed
    :func:`_default_decoder`. The whole decode is wrapped so any failure (ffmpeg
    missing, decoder raising, or no samples produced) returns ``SPEECH`` at low
    confidence instead of raising — the gate fails open so transcription still
    runs.

    Args:
        audio_path: Path to the captured clip.
        decoder: Injectable PCM decoder ``(audio_path) -> list[float]``. Defaults
            to the ffmpeg-backed decoder.
        sample_rate: Sample rate passed through to :func:`classify_pcm`.

    Returns:
        A :class:`Classification`. On any decode failure, a fail-open SPEECH
        result with low confidence.
    """
    decode = decoder if decoder is not None else _default_decoder
    try:
        samples = decode(audio_path)
    except Exception:
        logger.info("speech_gate: decode unavailable or failed; fail-open to speech", exc_info=True)
        return Classification(
            is_speech=True,
            confidence=0.1,
            reason="decode unavailable; fail-open to speech",
        )

    if not samples:
        logger.info("speech_gate: decoder produced no samples; fail-open to speech")
        return Classification(
            is_speech=True,
            confidence=0.1,
            reason="decode unavailable; fail-open to speech",
        )

    return classify_pcm(samples, sample_rate)
