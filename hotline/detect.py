"""Giveaway detection: score free text for radio-contest callouts.

Scoring is a weighted sum of matched positive terms, normalized to ``0.0..1.0``
by a fixed cap. Matching is case-insensitive; multi-word terms match as
contiguous phrases. If any negation term is present anywhere in the text the
score is forced to ``0.0`` with no matched terms, so "the contest is closed"
never fires.

Positive-term weight table:

==============  ======  =======
term            weight  kind
==============  ======  =======
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
==============  ======  =======

Negation terms: ``closed``, ``no longer``, ``ended``.

The raw weight sum is normalized as ``min(1.0, raw / SCORE_CAP)`` with
``SCORE_CAP = 6.0`` so a single strong phrase such as "call now" (weight 3)
reaches ``0.5`` and clears the default threshold.

A :class:`Detection` additionally requires at least one matched multi-word
phrase term (``call now``, ``call in``, ``first caller``, ``phone lines``,
``text in``). This gate keeps keyword-only hits such as "contest" + "whatsapp"
(which sum to ``0.5``) from firing, since site chrome routinely mentions those
single keywords.
"""

from __future__ import annotations

from dataclasses import dataclass

SCORE_CAP = 6.0
DEFAULT_THRESHOLD = 0.5

TERM_WEIGHTS: dict[str, int] = {
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
}

NEGATION_TERMS: tuple[str, ...] = ("closed", "no longer", "ended")

#: Multi-word phrase terms. A detection requires at least one of these, so a
#: single weight-2 keyword (``giveaway``/``contest``) alone never fires.
PHRASE_TERMS: frozenset[str] = frozenset(term for term in TERM_WEIGHTS if " " in term)


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
        matched term is a multi-word phrase (see :data:`PHRASE_TERMS`), else
        ``None``. The phrase requirement stops keyword-only chrome such as
        "contest" + "whatsapp" from firing even when it reaches the threshold.
    """
    score, matched_terms = score_text(text)
    if score < threshold:
        return None
    if not any(term in PHRASE_TERMS for term in matched_terms):
        return None
    return Detection(text=text, score=score, matched_terms=matched_terms, source=source)
