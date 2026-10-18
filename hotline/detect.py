"""Giveaway detection: score free text for radio-contest callouts.

Detection is bilingual: it covers English and Mandarin Chinese callouts using
plain case-insensitive substring matching (stdlib only, no segmentation
library). Scoring is a weighted sum of matched positive terms, normalized to
``0.0..1.0`` by a fixed cap. English multi-word terms match as contiguous
phrases; Chinese terms match as substrings (CJK text is unaffected by
lower-casing). If any negation term is present anywhere in the text the score
is forced to ``0.0`` with no matched terms, so "the contest is closed" (or its
Chinese equivalents) never fires.

Positive-term weight table:

==============  ======  ========
term            weight  kind
==============  ======  ========
call now        3       phrase
first caller    3       phrase
phone lines     2       phrase
call in         2       phrase
text in         2       phrase
giveaway        2       keyword
contest         2       keyword
whatsapp        1       keyword
win             1       keyword
tickets         1       keyword
现在打电话      3       phrase
第一位          3       phrase
第一名          3       phrase
拨打热线        2       phrase
热线电话        2       phrase
发短信          2       phrase
马上打电话      2       phrase
热线            2       keyword
来电            1       keyword
短信            1       keyword
微信            1       keyword
赢              2       keyword
门票            1       keyword
票              1       keyword
送出            2       keyword
赠送            2       keyword
比赛            2       keyword
奖品            2       keyword
==============  ======  ========

Negation terms: ``closed``, ``no longer``, ``ended``, ``已结束``, ``结束了``,
``已截止``, ``不再``.

The raw weight sum is normalized as ``min(1.0, raw / SCORE_CAP)`` with
``SCORE_CAP = 6.0`` so a single strong phrase such as "call now" (weight 3)
reaches ``0.5`` and clears the default threshold.

A :class:`Detection` additionally requires at least one matched phrase term
(see :data:`PHRASE_TERMS`: the English multi-word phrases plus the designated
Chinese phrases). This gate keeps keyword-only hits such as "contest" +
"whatsapp" (which sum to ``0.5``) from firing, since site chrome routinely
mentions those single keywords.
"""

from __future__ import annotations

from dataclasses import dataclass

SCORE_CAP = 6.0
DEFAULT_THRESHOLD = 0.5

TERM_WEIGHTS: dict[str, int] = {
    # English terms (insertion order preserved so English matched_terms
    # ordering is unchanged).
    "call now": 3,
    "first caller": 3,
    "phone lines": 2,
    "call in": 2,
    "text in": 2,
    "giveaway": 2,
    "contest": 2,
    "whatsapp": 1,
    "win": 1,
    "tickets": 1,
    # Mandarin Chinese phrases.
    "现在打电话": 3,
    "第一位": 3,
    "第一名": 3,
    "拨打热线": 2,
    "热线电话": 2,
    "发短信": 2,
    "马上打电话": 2,
    # Mandarin Chinese keywords.
    "热线": 2,
    "来电": 1,
    "短信": 1,
    "微信": 1,
    "赢": 2,
    "门票": 1,
    "票": 1,
    "送出": 2,
    "赠送": 2,
    "比赛": 2,
    "奖品": 2,
}

NEGATION_TERMS: tuple[str, ...] = (
    "closed",
    "no longer",
    "ended",
    "已结束",
    "结束了",
    "已截止",
    "不再",
)

#: Phrase terms. A detection requires at least one of these, so a single
#: weight-2 keyword (``giveaway``/``contest``/``奖品``/``比赛``) alone never
#: fires. Listed explicitly rather than derived from whitespace because Chinese
#: phrases contain no spaces.
PHRASE_TERMS: frozenset[str] = frozenset(
    {
        "call now",
        "first caller",
        "phone lines",
        "call in",
        "text in",
        "现在打电话",
        "第一位",
        "第一名",
        "拨打热线",
        "热线电话",
        "发短信",
        "马上打电话",
    }
)


@dataclass(frozen=True)
class Detection:
    """A positive detection produced by :func:`detect`.

    Attributes:
        text: The text that was scored.
        score: Normalized score in ``0.0..1.0``.
        matched_terms: Positive terms that matched, in table order.
        source: Short source identifier the text came from.
    """

    text: str
    score: float
    matched_terms: list[str]
    source: str


def score_text(text: str) -> tuple[float, list[str]]:
    """Score ``text`` for giveaway callouts.

    Args:
        text: Free text to evaluate.

    Returns:
        A ``(score, matched_terms)`` tuple. ``score`` is normalized to
        ``0.0..1.0``. If any negation term is present, returns ``(0.0, [])``.
    """
    lowered = text.lower()

    if any(negation in lowered for negation in NEGATION_TERMS):
        return 0.0, []

    matched_terms: list[str] = []
    raw = 0
    for term, weight in TERM_WEIGHTS.items():
        if term in lowered:
            matched_terms.append(term)
            raw += weight

    score = min(1.0, raw / SCORE_CAP)
    return score, matched_terms


def detect(text: str, source: str, threshold: float = DEFAULT_THRESHOLD) -> Detection | None:
    """Return a :class:`Detection` if ``text`` scores at or above ``threshold``.

    Args:
        text: Free text to evaluate.
        source: Short source identifier for the resulting detection.
        threshold: Minimum normalized score required to fire. Defaults to 0.5.

    Returns:
        A :class:`Detection` when the score meets ``threshold`` AND at least one
        matched term is a phrase (see :data:`PHRASE_TERMS`), else ``None``. The
        phrase requirement stops keyword-only chrome such as "contest" +
        "whatsapp" from firing even when it reaches the threshold.
    """
    score, matched_terms = score_text(text)
    if score < threshold:
        return None
    if not any(term in PHRASE_TERMS for term in matched_terms):
        return None
    return Detection(text=text, score=score, matched_terms=matched_terms, source=source)
