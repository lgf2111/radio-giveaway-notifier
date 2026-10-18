"""Manual end-to-end check: capture a real 987FM clip and send it to Telegram.

Run this in YOUR terminal where HOTLINE_TELEGRAM_TOKEN and HOTLINE_CHAT_ID are
exported. It captures a short clip from the live stream, transcribes it, builds
a rich alert (summary + transcript + voice note) with a FORCED detection so you
can confirm the full delivery path — including the attached voice message —
without waiting for a real on-air giveaway.

    uv run --extra audio python scripts/verify_voice_alert.py

This is a throwaway verification helper, not part of the package.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hotline.audio_capture import capture_clip
from hotline.config import load_config
from hotline.detect import Detection
from hotline.notify import notify_rich
from hotline.sources.audio import transcribe_clip
from hotline.summarize import summarize

STREAM = "https://22903.live.streamtheworld.com/987FM_PREM.aac"


def main() -> int:
    config = load_config(None)
    if not (config.telegram_token and config.chat_id):
        print("Set HOTLINE_TELEGRAM_TOKEN and HOTLINE_CHAT_ID first.")
        return 1

    out = Path(tempfile.gettempdir()) / "hotline_voice_check.ogg"
    print("Capturing 20s from 987FM ...")
    clip = capture_clip(STREAM, 20, out)
    if clip is None:
        print("Capture failed (is ffmpeg installed?).")
        return 1
    print(f"Captured {clip} ({clip.stat().st_size} bytes). Transcribing ...")

    transcript = transcribe_clip(clip, language="en") or "(no speech detected in this clip)"
    print(f"Transcript: {transcript[:200]}")

    # Forced detection so the alert fires regardless of clip content.
    detection = Detection(
        text=transcript,
        score=1.0,
        matched_terms=["call now", "win", "tickets"],
        source="audio",
    )
    summary = summarize(transcript, detection, config)
    print("Sending rich alert (text + voice note) to Telegram ...")
    notify_rich(summary, detection, transcript, clip, config, dry_run=False)
    print("Sent. Check your Telegram for the message and the voice note.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
