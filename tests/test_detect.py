"""Tests for hotline.detect."""

from __future__ import annotations

from hotline.detect import Detection, detect, score_text


def test_positive_text_scores_above_threshold() -> None:
    detection = detect("call now, first caller wins tickets", "web")
    assert isinstance(detection, Detection)
    assert detection.score >= 0.5
    assert detection.source == "web"
    assert "call now" in detection.matched_terms


def test_single_strong_phrase_clears_threshold() -> None:
    score, matched = score_text("just call now")
    assert score == 0.5
    assert matched == ["call now"]
    assert detect("just call now", "web") is not None


def test_negation_suppresses_to_zero() -> None:
    text = "call now first caller win tickets but the contest is closed"
    score, matched = score_text(text)
    assert score == 0.0
    assert matched == []
    assert detect(text, "web") is None


def test_negation_terms_each_suppress() -> None:
    for negation in ("closed", "no longer", "ended"):
        assert detect(f"call now first caller {negation}", "web") is None


def test_matched_terms_exact_for_known_string() -> None:
    score, matched = score_text("win tickets in our giveaway contest")
    # win(1)+tickets(1)+giveaway(2)+contest(2) = 6 -> capped 1.0
    assert matched == ["giveaway", "contest", "win", "tickets"]
    assert score == 1.0


def test_case_insensitive() -> None:
    lower = score_text("call now")
    upper = score_text("CALL NOW")
    assert lower == upper
    assert upper[0] == 0.5


def test_phrase_vs_keyword() -> None:
    # "call now" is a phrase; words apart should not match the phrase.
    score, matched = score_text("call me and do it now")
    assert "call now" not in matched


def test_below_threshold_returns_none() -> None:
    # single weak keyword "win" -> 1/6 ~= 0.166 < 0.5
    assert detect("you could win", "web") is None
