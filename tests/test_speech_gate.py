"""Tests for the music-vs-speech gate.

Fully offline: synthetic PCM is generated in-test with :mod:`math` and a seeded
:class:`random.Random`, decoders are injected, and no ffmpeg/network/whisper/
numpy is touched. The decision rule is speech-biased and fails open, which these
tests assert directly.
"""

from __future__ import annotations

import math
import random

from hotline.speech_gate import (
    FRAME_SIZE,
    Classification,
    _fft,
    classify_clip,
    classify_pcm,
)

SAMPLE_RATE = 16000


def _sine(freq: float, n: int, *, amplitude: float = 0.5) -> list[float]:
    """Return ``n`` samples of a sine at ``freq`` Hz."""
    return [amplitude * math.sin(2.0 * math.pi * freq * i / SAMPLE_RATE) for i in range(n)]


def test_fft_peaks_at_expected_bin() -> None:
    # A pure sine at freq f over one FRAME_SIZE window peaks at bin
    # f * FRAME_SIZE / sample_rate. Pick a freq landing on an exact bin.
    target_bin = 64
    freq = target_bin * SAMPLE_RATE / FRAME_SIZE
    frame = _sine(freq, FRAME_SIZE, amplitude=1.0)

    spectrum = _fft([complex(value, 0.0) for value in frame])
    magnitudes = [abs(bin_) for bin_ in spectrum[: FRAME_SIZE // 2]]

    peak_bin = max(range(len(magnitudes)), key=lambda i: magnitudes[i])
    assert peak_bin == target_bin


def test_fft_length_must_be_power_of_two() -> None:
    try:
        _fft([complex(0.0) for _ in range(3)])
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError for non power-of-two length")


def test_synthetic_music_classifies_as_music() -> None:
    rng = random.Random(1234)
    total = FRAME_SIZE * 40
    # Rich, steady multi-tone chord plus broadband noise => high, flat spectrum
    # with low energy modulation: music-like.
    tones = [220.0, 330.0, 440.0, 550.0, 660.0, 880.0, 1100.0]
    samples: list[float] = []
    for i in range(total):
        value = sum(0.15 * math.sin(2.0 * math.pi * f * i / SAMPLE_RATE) for f in tones)
        value += rng.uniform(-0.3, 0.3)
        samples.append(value)

    result = classify_pcm(samples, SAMPLE_RATE)

    assert result.is_speech is False
    assert result.confidence >= 0.6


def test_synthetic_speech_classifies_as_speech() -> None:
    # Amplitude-modulated voiced bursts separated by silent pauses: peaky
    # spectrum and high energy modulation => speech-like.
    samples: list[float] = []
    fundamental = 150.0
    pos = 0
    for _burst in range(8):
        # Voiced burst: fundamental + a couple of harmonics.
        for i in range(FRAME_SIZE * 2):
            t = (pos + i) / SAMPLE_RATE
            value = (
                0.6 * math.sin(2.0 * math.pi * fundamental * t)
                + 0.2 * math.sin(2.0 * math.pi * 2 * fundamental * t)
                + 0.1 * math.sin(2.0 * math.pi * 3 * fundamental * t)
            )
            samples.append(value)
        pos += FRAME_SIZE * 2
        # Silent pause between bursts.
        samples.extend(0.0 for _ in range(FRAME_SIZE * 2))
        pos += FRAME_SIZE * 2

    result = classify_pcm(samples, SAMPLE_RATE)

    assert result.is_speech is True


def test_silence_fails_open_to_speech() -> None:
    samples = [0.0] * (FRAME_SIZE * 20)
    result = classify_pcm(samples, SAMPLE_RATE)
    assert result.is_speech is True
    assert result.confidence <= 0.5


def test_classify_clip_with_injected_music_decoder(fake_pcm_decoder) -> None:
    rng = random.Random(99)
    total = FRAME_SIZE * 40
    tones = [220.0, 330.0, 440.0, 550.0, 660.0, 880.0, 1100.0]
    samples = [
        sum(0.15 * math.sin(2.0 * math.pi * f * i / SAMPLE_RATE) for f in tones)
        + rng.uniform(-0.3, 0.3)
        for i in range(total)
    ]
    decoder = fake_pcm_decoder(samples)

    result = classify_clip("clip.ogg", decoder=decoder)

    assert result.is_speech is False
    assert decoder.calls == ["clip.ogg"]


def test_classify_clip_decoder_raises_fails_open() -> None:
    def broken_decoder(path: object) -> list[float]:
        raise RuntimeError("ffmpeg blew up")

    result = classify_clip("clip.ogg", decoder=broken_decoder)

    assert isinstance(result, Classification)
    assert result.is_speech is True
    assert result.confidence <= 0.5


def test_classify_clip_empty_decode_fails_open(fake_pcm_decoder) -> None:
    decoder = fake_pcm_decoder([])

    result = classify_clip("clip.ogg", decoder=decoder)

    assert result.is_speech is True
    assert result.confidence <= 0.5
