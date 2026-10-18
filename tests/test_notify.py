"""Tests for hotline.notify."""

from __future__ import annotations

import pytest

from hotline.config import Config
from hotline.detect import Detection
from hotline.notify import format_alert, notify, send_telegram
from hotline.sources import Item


def _detection() -> Detection:
    return Detection(
        text="call now to win tickets",
        score=0.83,
        matched_terms=["call now", "win", "tickets"],
        source="web",
    )


def _item() -> Item:
    return Item(
        title="987FM Contest",
        url="https://example.test/contest",
        text="call now to win tickets",
        published=None,
        source="web",
    )


def test_format_alert_contains_key_fields() -> None:
    message = format_alert(_detection(), _item())
    assert "987FM Contest" in message
    assert "https://example.test/contest" in message
    assert "call now" in message
    assert "0.83" in message


def test_dry_run_returns_text_without_calling_post(make_sender, capsys) -> None:
    post = make_sender()
    config = Config(telegram_token="tok", chat_id="chat")

    message = notify(_detection(), _item(), config, dry_run=True, post=post)

    assert "987FM Contest" in message
    assert post.calls == []
    # Dry run prints the message.
    assert "987FM Contest" in capsys.readouterr().out


def test_real_path_calls_post_once_with_url_and_payload(make_sender) -> None:
    post = make_sender()
    config = Config(telegram_token="secret-token", chat_id="chat-42")

    notify(_detection(), _item(), config, dry_run=False, post=post)

    assert len(post.calls) == 1
    url, payload = post.calls[0]
    assert "secret-token" in url
    assert url.endswith("/sendMessage")
    assert payload["chat_id"] == "chat-42"
    assert "987FM Contest" in payload["text"]


def test_missing_credentials_raises(make_sender) -> None:
    post = make_sender()
    config = Config()  # no token / chat id
    with pytest.raises(ValueError):
        notify(_detection(), _item(), config, dry_run=False, post=post)
    assert post.calls == []


def test_send_telegram_builds_url(make_sender) -> None:
    post = make_sender()
    send_telegram("hello", "abc123", "chat", post=post)
    url, payload = post.calls[0]
    assert url == "https://api.telegram.org/botabc123/sendMessage"
    assert payload == {"chat_id": "chat", "text": "hello"}
