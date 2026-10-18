"""Tests for Telegram media delivery: send_voice and notify_rich.

All HTTP is injected, so no test touches the network. The audio clip is the
tiny bundled ``fixtures/audio_clip.ogg`` placeholder.
"""

from __future__ import annotations

import pytest

from hotline.config import Config
from hotline.detect import Detection
from hotline.notify import notify_rich, send_voice
from hotline.summarize import Summary


def _detection() -> Detection:
    return Detection(
        text="phone lines are open, call now on 6123 4567 to win tickets",
        score=0.83,
        matched_terms=["phone lines", "call now", "win", "tickets"],
        source="audio",
    )


def _summary() -> Summary:
    return Summary(
        headline="📞 987FM giveaway — call 6123 4567 now to win tickets",
        action="Call 6123 4567 now",
        details="phone lines are open, call now on 6123 4567 to win tickets",
    )


def test_send_voice_posts_to_sendvoice_endpoint(make_multipart_sender, fixtures_dir) -> None:
    sender = make_multipart_sender()
    config = Config(telegram_token="secret-token", chat_id="chat-42")
    clip = fixtures_dir / "audio_clip.ogg"

    send_voice(config, clip, "a caption", sender=sender)

    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["url"] == "https://api.telegram.org/botsecret-token/sendVoice"
    assert call["fields"]["chat_id"] == "chat-42"
    assert call["fields"]["caption"] == "a caption"
    assert call["filename"] == "audio_clip.ogg"
    assert call["file_bytes"] == clip.read_bytes()


def test_send_voice_requires_credentials(make_multipart_sender, fixtures_dir) -> None:
    sender = make_multipart_sender()
    config = Config()  # no token / chat id
    with pytest.raises(ValueError):
        send_voice(config, fixtures_dir / "audio_clip.ogg", "cap", sender=sender)
    assert sender.calls == []


def test_notify_rich_sends_text_then_voice(
    make_sender, make_multipart_sender, fixtures_dir
) -> None:
    post = make_sender()
    sender = make_multipart_sender()
    config = Config(telegram_token="tok", chat_id="chat")
    clip = fixtures_dir / "audio_clip.ogg"

    message = notify_rich(
        _summary(),
        _detection(),
        "phone lines are open, call now on 6123 4567 to win tickets",
        clip,
        config,
        dry_run=False,
        post=post,
        sender=sender,
    )

    # Text part sent first via sendMessage.
    assert len(post.calls) == 1
    text_url, text_payload = post.calls[0]
    assert text_url.endswith("/sendMessage")
    assert text_payload["chat_id"] == "chat"
    assert "987FM giveaway" in text_payload["text"]
    assert "Call 6123 4567 now" in text_payload["text"]
    # Voice part sent second via sendVoice.
    assert len(sender.calls) == 1
    assert sender.calls[0]["url"].endswith("/sendVoice")
    assert "987FM giveaway" in message


def test_notify_rich_dry_run_prints_and_sends_nothing(
    make_sender, make_multipart_sender, fixtures_dir, capsys
) -> None:
    post = make_sender()
    sender = make_multipart_sender()
    config = Config(telegram_token="tok", chat_id="chat")
    clip = fixtures_dir / "audio_clip.ogg"
    transcript = "phone lines are open, call now on 6123 4567 to win tickets"

    notify_rich(
        _summary(),
        _detection(),
        transcript,
        clip,
        config,
        dry_run=True,
        post=post,
        sender=sender,
    )

    out = capsys.readouterr().out
    assert "987FM giveaway" in out  # summary headline
    assert "Call 6123 4567 now" in out  # action
    assert transcript in out  # transcript excerpt
    assert f"would attach {clip}" in out
    # Nothing was sent in dry-run.
    assert post.calls == []
    assert sender.calls == []
