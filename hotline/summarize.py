"""Summarize a giveaway callout transcript into an actionable alert.

:func:`summarize` turns a raw transcript plus its :class:`~hotline.detect.Detection`
into a :class:`Summary` with a headline, a concrete action, and detail text.

Two modes:

* ``rules`` (default): a deterministic, offline pass that regex-extracts a
  contact number, infers the action from the detection's matched terms, and
  pulls the prize out of the transcript. No network, no dependencies.
* ``llm``: when ``config.summary_mode == "llm"``, POST the transcript to an
  OpenAI-compatible ``/chat/completions`` endpoint through an injectable
  stdlib-urllib sender. *Any* failure falls back to the rules summary, so the
  LLM path can never break alerting.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.request import Request, urlopen

from hotline.config import Config
from hotline.detect import Detection

logger = logging.getLogger(__name__)

#: LLM sender signature: ``(url, payload, headers) -> decoded JSON response``.
Sender = Callable[[str, dict, dict[str, str]], dict]

#: Matched terms that imply a phone call.
_CALL_TERMS = frozenset({"call now", "call in", "first caller", "phone lines"})

#: Matched terms that imply texting / WhatsApp.
_TEXT_TERMS = frozenset({"text in", "whatsapp"})

#: Singapore phone / shortcode patterns, tried in order.
_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # whatsapp <number>
    re.compile(r"whatsapp\s+(?:us\s+(?:at\s+|on\s+)?)?(\+?65[\s-]?)?(\d{4}[\s-]?\d{4})", re.I),
    # +65 6123 4567 or 6123 4567 (8 digits, optional space/dash grouping)
    re.compile(r"(?:\+?65[\s-]?)?(\d{4}[\s-]?\d{4})\b"),
    # SMS shortcode: "text ... to 7XXXX" (5-6 digit shortcode)
    re.compile(r"\bto\s+(\d{5,6})\b", re.I),
)

#: Prize phrase: text after "win"/"tickets to"/"a pair of", up to ~8 words.
_PRIZE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwin\s+(?:a\s+|an\s+|the\s+)?([\w'&-]+(?:\s+[\w'&-]+){0,7})", re.I),
    re.compile(r"\btickets\s+to\s+(?:the\s+)?([\w'&-]+(?:\s+[\w'&-]+){0,7})", re.I),
)


@dataclass(frozen=True)
class Summary:
    """A human-readable, actionable summary of a giveaway callout.

    Attributes:
        headline: One-line alert headline (e.g. with the number and prize).
        action: The concrete action the listener should take now.
        details: Supporting detail text (typically the transcript excerpt).
    """

    headline: str
    action: str
    details: str


def _extract_number(transcript: str) -> str | None:
    """Return the first contact number found in ``transcript``, or ``None``."""
    for pattern in _NUMBER_PATTERNS:
        match = pattern.search(transcript)
        if match:
            # Use the last captured group (the digits themselves).
            groups = [g for g in match.groups() if g]
            digits = groups[-1] if groups else match.group(0)
            return re.sub(r"\s+", " ", digits.strip())
    return None


def _extract_prize(transcript: str) -> str | None:
    """Return a short prize phrase from ``transcript``, or ``None``."""
    for pattern in _PRIZE_PATTERNS:
        match = pattern.search(transcript)
        if match:
            prize = match.group(1).strip().rstrip(".,!")
            if prize:
                return prize
    return None


def _infer_action(matched_terms: list[str], number: str | None) -> str:
    """Infer the listener's next action from matched terms + number."""
    target = number or "the station line"
    if any(term in _CALL_TERMS for term in matched_terms):
        return f"Call {target} now"
    if any(term in _TEXT_TERMS for term in matched_terms):
        return f"Text/WhatsApp {target}"
    return f"Contact {target} now"


def _rules_summary(transcript: str, detection: Detection) -> Summary:
    """Build a deterministic rules-based :class:`Summary`."""
    number = _extract_number(transcript)
    prize = _extract_prize(transcript)
    action = _infer_action(detection.matched_terms, number)

    headline_parts = ["\U0001f4de 987FM giveaway"]
    verb = action.lower()
    if prize:
        headline_parts.append(f"— {verb} to win {prize}")
    else:
        headline_parts.append(f"— {verb}")
    headline = " ".join(headline_parts)

    details = transcript.strip()
    return Summary(headline=headline, action=action, details=details)


def _llm_summary(transcript: str, config: Config, sender: Sender) -> Summary:
    """Build a :class:`Summary` from an OpenAI-compatible chat endpoint."""
    base = (config.summary_api_base or "").rstrip("/")
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.summary_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.summary_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You summarize a radio giveaway callout into a one-line "
                    "headline, a concrete action, and brief details."
                ),
            },
            {"role": "user", "content": transcript},
        ],
    }
    response = sender(url, payload, headers)
    content = response["choices"][0]["message"]["content"].strip()
    first_line, _, rest = content.partition("\n")
    return Summary(
        headline=first_line.strip(),
        action=rest.strip() or first_line.strip(),
        details=transcript.strip(),
    )


def _default_sender(
    url: str, payload: dict, headers: dict[str, str], *, timeout: float = 15.0
) -> dict:
    """POST ``payload`` as JSON to ``url`` and return the decoded response."""
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - configurable LLM host
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


def summarize(
    transcript: str,
    detection: Detection,
    config: Config | None = None,
    *,
    sender: Sender | None = None,
) -> Summary:
    """Summarize a callout ``transcript`` into an actionable :class:`Summary`.

    Args:
        transcript: The transcribed on-air callout text.
        detection: The detection whose matched terms drive the inferred action.
        config: Runtime configuration. When ``None`` or ``summary_mode`` is not
            ``"llm"``, the deterministic rules path is used.
        sender: Injectable LLM POST callable ``(url, payload, headers) -> dict``.
            Defaults to a stdlib-urllib sender; only used in ``llm`` mode.

    Returns:
        A :class:`Summary`. In ``llm`` mode, any exception falls back to the
        rules summary, so alerting never breaks.
    """
    if config is not None and config.summary_mode == "llm":
        try:
            return _llm_summary(transcript, config, sender or _default_sender)
        except Exception:
            logger.warning("summarize: LLM summary failed; falling back to rules", exc_info=True)
    return _rules_summary(transcript, detection)
