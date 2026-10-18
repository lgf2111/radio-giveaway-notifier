"""Tests for hotline.sources.web."""

from __future__ import annotations

from hotline.config import Config
from hotline.detect import detect
from hotline.sources.web import parse_html, poll_web


def test_parse_contest_page_drives_detection(read_fixture) -> None:
    html = read_fixture("contest_page.html")
    item = parse_html(html, "https://example.test/contest")
    assert item.source == "web"
    assert item.url == "https://example.test/contest"
    assert "987FM Contest" in item.title
    # Script text must be excluded from the visible text.
    assert "ignored inside script" not in item.text
    assert "call now" in item.text.lower()
    detection = detect(item.text, item.source)
    assert detection is not None
    assert detection.score >= 0.5


def test_parse_giveaway_page_detects(read_fixture) -> None:
    html = read_fixture("giveaway_page.html")
    item = parse_html(html, "https://example.test/giveaway")
    detection = detect(item.text, item.source)
    assert detection is not None
    assert "giveaway" in detection.matched_terms


def test_parse_closed_page_suppressed(read_fixture) -> None:
    html = read_fixture("closed_page.html")
    item = parse_html(html, "https://example.test/closed")
    # Negation terms present -> detection suppressed to None.
    assert detect(item.text, item.source) is None


def test_poll_web_yields_items_for_allowed_urls(read_fixture, make_fetcher, make_robots) -> None:
    urls = ["https://example.test/contest", "https://example.test/giveaway"]
    fetch = make_fetcher(
        {
            urls[0]: read_fixture("contest_page.html"),
            urls[1]: read_fixture("giveaway_page.html"),
        }
    )
    robots = make_robots()
    config = Config(contest_urls=urls, user_agent="hotline-test/0.1")

    items = list(poll_web(config, fetch=fetch, robots_checker=robots))
    assert [i.url for i in items] == urls
    # Polite configurable User-Agent is forwarded to the fetcher.
    assert all(ua == "hotline-test/0.1" for _url, ua in fetch.calls)


def test_poll_web_includes_feed_url(read_fixture, make_fetcher, make_robots) -> None:
    config = Config(
        contest_urls=["https://example.test/contest"],
        feed_url="https://example.test/feed",
    )
    fetch = make_fetcher(
        {
            "https://example.test/contest": read_fixture("contest_page.html"),
            "https://example.test/feed": read_fixture("giveaway_page.html"),
        }
    )
    items = list(poll_web(config, fetch=fetch, robots_checker=make_robots()))
    assert [i.url for i in items] == [
        "https://example.test/contest",
        "https://example.test/feed",
    ]


def test_poll_web_skips_robots_disallowed(read_fixture, make_fetcher, make_robots) -> None:
    blocked = "https://example.test/blocked"
    allowed = "https://example.test/contest"
    fetch = make_fetcher({allowed: read_fixture("contest_page.html")})
    robots = make_robots(disallowed={blocked})
    config = Config(contest_urls=[blocked, allowed])

    items = list(poll_web(config, fetch=fetch, robots_checker=robots))
    assert [i.url for i in items] == [allowed]
    # The blocked URL was never fetched.
    assert all(url != blocked for url, _ua in fetch.calls)
