"""Telegram notifier for giveaway detections.

:func:`notify` formats a detection into a human-readable alert and either
prints it (``dry_run``) or sends it via the Telegram Bot API. The HTTP POST is
done through an injectable callable so tests never touch the network, and the
bot token / chat id come from configuration (sourced from env vars), never
from code.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hotline.config import Config
from hotline.detect import Detection
from hotline.sources import Item

#: Telegram Bot API base; the token is interpolated at call time.
TELEGRAM_API_BASE = "https://api.telegram.org"

#: POST signature: ``(url, payload) -> decoded JSON response dict``.
Post = Callable[[str, dict[str, str]], dict]


def _default_post(url: str, payload: dict[str, str], *, timeout: float = 10.0) -> dict:
    """POST ``payload`` as form data to ``url`` and return the JSON response."""
    data = urlencode(payload).encode("utf-8")
    request = Request(url, data=data, method="POST")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed telegram host
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


def format_alert(detection: Detection, item: Item) -> str:
    """Render a readable alert message for a detection.

    Args:
        detection: The scored detection to report.
        item: The source item the detection came from.

    Returns:
        A multi-line message with title, URL, matched terms, and score.
    """
    matched = ", ".join(detection.matched_terms) if detection.matched_terms else "none"
    return (
        "\U0001f3b5 Giveaway alert\n"
        f"Title: {item.title}\n"
        f"URL: {item.url}\n"
        f"Source: {detection.source}\n"
        f"Score: {detection.score:.2f}\n"
        f"Matched: {matched}"
    )


def send_telegram(text: str, token: str, chat_id: str, post: Post = _default_post) -> dict:
    """Send ``text`` to a Telegram chat via the Bot API.

    Args:
        text: Message body.
        token: Bot token (e.g. from ``HOTLINE_TELEGRAM_TOKEN``).
        chat_id: Destination chat id (e.g. from ``HOTLINE_CHAT_ID``).
        post: Callable ``(url, payload) -> response dict``. Defaults to a stdlib
            urllib POST; injectable for tests.

    Returns:
        The decoded Telegram API response.
    """
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    return post(url, payload)


def notify(
    detection: Detection,
    item: Item,
    config: Config,
    dry_run: bool = False,
    post: Post = _default_post,
) -> str:
    """Format and deliver an alert for a detection.

    Args:
        detection: The detection to report.
        item: The source item the detection came from.
        config: Runtime configuration providing ``telegram_token`` and
            ``chat_id`` (both sourced from env vars).
        dry_run: When ``True``, print and return the message without sending.
        post: Injectable POST callable passed through to :func:`send_telegram`.

    Returns:
        The formatted alert message.

    Raises:
        ValueError: If sending is requested but the token or chat id is missing.
    """
    message = format_alert(detection, item)

    if dry_run:
        print(message)
        return message

    if not config.telegram_token or not config.chat_id:
        raise ValueError(
            "Telegram token and chat id are required to send alerts "
            "(set HOTLINE_TELEGRAM_TOKEN and HOTLINE_CHAT_ID)."
        )

    send_telegram(message, config.telegram_token, config.chat_id, post=post)
    return message
