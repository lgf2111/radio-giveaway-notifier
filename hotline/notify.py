"""Telegram notifier for giveaway detections.

:func:`notify` formats a detection into a human-readable alert and either
prints it (``dry_run``) or sends it via the Telegram Bot API. The HTTP POST is
done through an injectable callable so tests never touch the network, and the
bot token / chat id come from configuration (sourced from env vars), never
from code.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hotline.config import Config
from hotline.detect import Detection
from hotline.sources import Item
from hotline.summarize import Summary

#: Telegram Bot API base; the token is interpolated at call time.
TELEGRAM_API_BASE = "https://api.telegram.org"

#: POST signature: ``(url, payload) -> decoded JSON response dict``.
Post = Callable[[str, dict[str, str]], dict]

#: Multipart sender signature used by :func:`send_voice`:
#: ``(url, fields, filename, file_bytes) -> decoded JSON response dict``.
MultipartSender = Callable[[str, dict[str, str], str, bytes], dict]

#: Max characters of transcript included in a rich alert before truncation.
_TRANSCRIPT_LIMIT = 500


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


def _build_multipart(fields: dict[str, str], filename: str, file_bytes: bytes) -> tuple[bytes, str]:
    """Build a ``multipart/form-data`` body and its content-type header.

    Args:
        fields: Plain text form fields (e.g. ``chat_id``, ``caption``).
        filename: Name advertised for the uploaded ``voice`` file part.
        file_bytes: Raw bytes of the audio clip to attach.

    Returns:
        A ``(body, content_type)`` tuple ready for an HTTP POST.
    """
    boundary = uuid.uuid4().hex
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        parts.append(b"")
        parts.append(value.encode("utf-8"))
    parts.append(f"--{boundary}".encode())
    parts.append(f'Content-Disposition: form-data; name="voice"; filename="{filename}"'.encode())
    parts.append(b"Content-Type: application/octet-stream")
    parts.append(b"")
    parts.append(file_bytes)
    parts.append(f"--{boundary}--".encode())
    parts.append(b"")
    body = crlf.join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _default_multipart_sender(
    url: str,
    fields: dict[str, str],
    filename: str,
    file_bytes: bytes,
    *,
    timeout: float = 30.0,
) -> dict:
    """POST a multipart body to ``url`` with stdlib urllib and return the JSON."""
    body, content_type = _build_multipart(fields, filename, file_bytes)
    request = Request(url, data=body, method="POST")
    request.add_header("Content-Type", content_type)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed telegram host
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


def send_voice(
    config: Config,
    audio_path: str | Path,
    caption: str,
    *,
    sender: MultipartSender = _default_multipart_sender,
) -> dict:
    """Send an audio clip as a Telegram voice message.

    Builds a ``multipart/form-data`` POST (stdlib only) to the ``sendVoice``
    endpoint carrying ``chat_id``, ``caption``, and the clip bytes.

    Args:
        config: Runtime configuration supplying ``telegram_token`` and
            ``chat_id`` (both sourced from env vars).
        audio_path: Path to the captured audio clip to upload.
        caption: Caption shown alongside the voice message.
        sender: Injectable multipart POST callable
            ``(url, fields, filename, file_bytes) -> dict``. Defaults to a
            stdlib-urllib sender; injectable so tests never touch the network.

    Returns:
        The decoded Telegram API response.

    Raises:
        ValueError: If the token or chat id is missing.
    """
    if not config.telegram_token or not config.chat_id:
        raise ValueError(
            "Telegram token and chat id are required to send voice clips "
            "(set HOTLINE_TELEGRAM_TOKEN and HOTLINE_CHAT_ID)."
        )
    path = Path(audio_path)
    url = f"{TELEGRAM_API_BASE}/bot{config.telegram_token}/sendVoice"
    fields = {"chat_id": config.chat_id, "caption": caption}
    return sender(url, fields, path.name, path.read_bytes())


def _rich_text(summary: Summary, transcript: str) -> str:
    """Compose the text part of a rich alert from a summary + transcript."""
    excerpt = transcript.strip()
    if len(excerpt) > _TRANSCRIPT_LIMIT:
        excerpt = excerpt[:_TRANSCRIPT_LIMIT].rstrip() + "…"
    return f"{summary.headline}\nAction: {summary.action}\nHeard: {excerpt}"


def notify_rich(
    summary: Summary,
    detection: Detection,
    transcript: str,
    audio_path: str | Path,
    config: Config,
    *,
    dry_run: bool = False,
    post: Post = _default_post,
    sender: MultipartSender = _default_multipart_sender,
) -> str:
    """Deliver a rich audio alert: a summary text message plus a voice clip.

    Sends two Telegram messages in order: (1) the summary headline, action, and
    a trimmed transcript via :func:`send_telegram`, then (2) the captured clip
    via :func:`send_voice`. In ``dry_run`` it prints all three parts (summary,
    transcript, and a ``would attach <path>`` line) and sends nothing.

    Args:
        summary: The actionable :class:`~hotline.summarize.Summary`.
        detection: The detection the transcript produced (included for context).
        transcript: The transcribed on-air callout text.
        audio_path: Path to the captured audio clip to attach.
        config: Runtime configuration supplying Telegram credentials.
        dry_run: When ``True``, print and return the message without sending.
        post: Injectable POST callable for the text part.
        sender: Injectable multipart sender for the voice part.

    Returns:
        The formatted text part of the rich alert.

    Raises:
        ValueError: If sending is requested but the token or chat id is missing.
    """
    message = _rich_text(summary, transcript)
    caption = summary.headline

    if dry_run:
        print(message)
        print(f"would attach {audio_path}")
        return message

    if not config.telegram_token or not config.chat_id:
        raise ValueError(
            "Telegram token and chat id are required to send alerts "
            "(set HOTLINE_TELEGRAM_TOKEN and HOTLINE_CHAT_ID)."
        )

    send_telegram(message, config.telegram_token, config.chat_id, post=post)
    send_voice(config, audio_path, caption, sender=sender)
    return message
