"""Tests for hotline.sources.sitemap.

All runs are offline: the sitemap XML and page HTML come from fixtures via an
injected fetcher, and robots checks are injected. No test performs network I/O.
"""

from __future__ import annotations

from hotline.config import Config
from hotline.sources.sitemap import (
    is_987_giveaway_url,
    parse_sitemap_locs,
    poll_sitemap,
)

SITEMAP_URL = "https://www.melisten.sg/sitemap.xml"

MATCH_URLS = [
    "https://www.melisten.sg/radio/987/987-giveaway-win-tickets-1234567",
    "https://www.melisten.sg/radio/987/987-contest-prize-draw-2345678",
]
NON_MATCH_987 = "https://www.melisten.sg/radio/987/987-weekday-schedule-3456789"
OTHER_STATION = "https://www.melisten.sg/radio/class95/class-95-giveaway-pickle-beats-3485961"

# Real false positive: "win" only appears as a substring of the token
# "growing", so whole-token matching must REJECT this podcast page.
FALSE_POSITIVE_987 = (
    "https://www.melisten.sg/radio/987/"
    "growing-beside-each-other-sonzz-joakim-gomez-sojo-987fm-9-3490431"
)
# A genuine giveaway slug under /radio/987/ must be ACCEPTED.
GIVEAWAY_987 = "https://www.melisten.sg/radio/987/class-95-giveaway-pickle-beats-3485961"


def _pages(read_fixture) -> dict[str, str]:
    """Serve giveaway HTML for every candidate page URL."""
    html = read_fixture("giveaway_page.html")
    return {
        MATCH_URLS[0]: html,
        MATCH_URLS[1]: html,
        NON_MATCH_987: html,
        OTHER_STATION: html,
    }


def test_parse_sitemap_locs_handles_namespace(read_fixture) -> None:
    locs = parse_sitemap_locs(read_fixture("sitemap.xml"))
    assert MATCH_URLS[0] in locs
    assert OTHER_STATION in locs
    assert len(locs) == 4


def test_is_987_giveaway_url_filters() -> None:
    assert is_987_giveaway_url(MATCH_URLS[0]) is True
    assert is_987_giveaway_url(MATCH_URLS[1]) is True
    # Non-matching slug under /radio/987/ is rejected.
    assert is_987_giveaway_url(NON_MATCH_987) is False
    # Matching slug under a different station is rejected.
    assert is_987_giveaway_url(OTHER_STATION) is False


def test_is_987_giveaway_url_matches_whole_tokens_only() -> None:
    # "win" inside "growing" is a substring, not a whole token -> rejected.
    assert is_987_giveaway_url(FALSE_POSITIVE_987) is False
    # A real "giveaway" token under /radio/987/ -> accepted.
    assert is_987_giveaway_url(GIVEAWAY_987) is True


def test_poll_sitemap_yields_only_matching_987_pages(
    read_fixture, make_sitemap_fetcher, make_robots
) -> None:
    fetch = make_sitemap_fetcher(SITEMAP_URL, read_fixture("sitemap.xml"), _pages(read_fixture))
    config = Config(sitemap_url=SITEMAP_URL, user_agent="hotline-test/0.1")

    items = list(poll_sitemap(config, fetch=fetch, robots_checker=make_robots()))

    assert [i.url for i in items] == MATCH_URLS
    assert all(i.source == "sitemap" for i in items)
    # Only the sitemap plus the two matching pages were ever fetched.
    fetched = [url for url, _ua in fetch.calls]
    assert fetched == [SITEMAP_URL, *MATCH_URLS]
    assert NON_MATCH_987 not in fetched
    assert OTHER_STATION not in fetched
    # Polite configurable User-Agent is forwarded.
    assert all(ua == "hotline-test/0.1" for _url, ua in fetch.calls)


def test_poll_sitemap_empty_when_unconfigured(make_sitemap_fetcher, read_fixture) -> None:
    fetch = make_sitemap_fetcher(SITEMAP_URL, read_fixture("sitemap.xml"), {})
    config = Config(sitemap_url=None)

    assert list(poll_sitemap(config, fetch=fetch)) == []
    assert fetch.calls == []


def test_poll_sitemap_survives_one_bad_page(read_fixture, make_robots, capsys) -> None:
    sitemap_xml = read_fixture("sitemap.xml")
    html = read_fixture("giveaway_page.html")

    def fetch(url: str, user_agent: str) -> str:
        if url == SITEMAP_URL:
            return sitemap_xml
        if url == MATCH_URLS[0]:
            raise OSError("boom")
        return html

    config = Config(sitemap_url=SITEMAP_URL)
    items = list(poll_sitemap(config, fetch=fetch, robots_checker=make_robots()))

    # The failing first page is skipped; the second matching page still yields.
    assert [i.url for i in items] == [MATCH_URLS[1]]
    assert MATCH_URLS[0] in capsys.readouterr().err


def test_poll_sitemap_skips_robots_disallowed_page(
    read_fixture, make_sitemap_fetcher, make_robots
) -> None:
    fetch = make_sitemap_fetcher(SITEMAP_URL, read_fixture("sitemap.xml"), _pages(read_fixture))
    robots = make_robots(disallowed={MATCH_URLS[0]})
    config = Config(sitemap_url=SITEMAP_URL)

    items = list(poll_sitemap(config, fetch=fetch, robots_checker=robots))

    assert [i.url for i in items] == [MATCH_URLS[1]]
    # The disallowed page was never fetched.
    assert MATCH_URLS[0] not in [url for url, _ua in fetch.calls]


def test_poll_sitemap_skips_when_sitemap_robots_disallowed(
    read_fixture, make_sitemap_fetcher, make_robots
) -> None:
    fetch = make_sitemap_fetcher(SITEMAP_URL, read_fixture("sitemap.xml"), _pages(read_fixture))
    robots = make_robots(disallowed={SITEMAP_URL})
    config = Config(sitemap_url=SITEMAP_URL)

    items = list(poll_sitemap(config, fetch=fetch, robots_checker=robots))

    assert items == []
    # The sitemap was never fetched because robots disallowed it.
    assert fetch.calls == []


def test_poll_sitemap_survives_bad_sitemap_fetch(make_robots, capsys) -> None:
    def fetch(url: str, user_agent: str) -> str:
        raise OSError("sitemap down")

    config = Config(sitemap_url=SITEMAP_URL)
    items = list(poll_sitemap(config, fetch=fetch, robots_checker=make_robots()))

    assert items == []
    assert SITEMAP_URL in capsys.readouterr().err
