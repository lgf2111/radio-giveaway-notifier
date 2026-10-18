"""Tests for hotline.detect."""

from __future__ import annotations

from hotline.detect import Detection, detect, score_text
from hotline.sources.web import parse_html


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


def test_keyword_only_at_threshold_does_not_fire() -> None:
    # contest(2)+whatsapp(1) = 3/6 = 0.5 clears the threshold but has no
    # multi-word phrase, so detect() must gate it to None.
    score, matched = score_text("contest whatsapp")
    assert score == 0.5
    assert matched == ["contest", "whatsapp"]
    assert detect("contest whatsapp", "web") is None


def test_phrase_plus_keywords_still_fires() -> None:
    detection = detect("call now win tickets", "web")
    assert detection is not None
    assert "call now" in detection.matched_terms


def test_phrase_gate_is_case_insensitive() -> None:
    assert detect("CALL NOW win", "web") is not None


def test_chinese_callout_fires() -> None:
    # 现在打电话(3, phrase) + 赢(2) -> 5/6 clears threshold and has a phrase.
    detection = detect("现在打电话到6123 4567，赢门票！", "audio")
    assert isinstance(detection, Detection)
    assert detection.score >= 0.5
    assert "现在打电话" in detection.matched_terms


def test_chinese_negations_each_suppress() -> None:
    for negation in ("已结束", "结束了", "已截止", "不再"):
        text = f"现在打电话 赢 门票 比赛{negation}"
        score, matched = score_text(text)
        assert score == 0.0
        assert matched == []
        assert detect(text, "web") is None


def test_chinese_keyword_only_does_not_fire() -> None:
    # 奖品(2)+比赛(2) = 4/6 clears the threshold but has no phrase term, so
    # detect() must gate it to None (parity with "contest"+"whatsapp").
    score, matched = score_text("奖品 比赛")
    assert score >= 0.5
    assert matched == ["比赛", "奖品"]
    assert detect("奖品 比赛", "web") is None


def test_chinese_contest_fixture_detects(read_fixture) -> None:
    item = parse_html(read_fixture("contest_page_zh.html"), "https://example.test/contest-zh")
    detection = detect(item.text, "web")
    assert detection is not None
    assert detection.score >= 0.5
    assert any(term in detection.matched_terms for term in ("现在打电话", "热线电话", "第一位"))
