"""Tests that HTML chrome (footer, share/social bars, nav) is stripped.

These run entirely offline against the ``chrome_page.html`` fixture: its only
contest-ish words ("Contest T&C's", "Whatsapp") live in a footer and a
share/social bar, mirroring the real melisten podcast page that raised a false
alert. After stripping, that text must not reach the scorer, and the real
contest fixtures must still detect (a guard against over-stripping).
"""

from __future__ import annotations

from hotline.detect import detect
from hotline.sources.web import parse_html


def test_chrome_text_stripped_and_no_detection(read_fixture) -> None:
    html = read_fixture("chrome_page.html")
    item = parse_html(html, "https://example.test/chrome")

    # Footer T&Cs and the share/social Whatsapp strings are gone.
    assert "Contest" not in item.text
    assert "T&C" not in item.text
    assert "Whatsapp" not in item.text
    # Real main-content copy survives.
    assert "Song of the Day" in item.text

    # With no real contest copy and chrome stripped, nothing fires.
    assert detect(item.text, item.source) is None


def test_real_contest_fixtures_still_detect(read_fixture) -> None:
    contest = parse_html(read_fixture("contest_page.html"), "https://example.test/contest")
    giveaway = parse_html(read_fixture("giveaway_page.html"), "https://example.test/giveaway")

    assert detect(contest.text, contest.source) is not None
    assert detect(giveaway.text, giveaway.source) is not None
