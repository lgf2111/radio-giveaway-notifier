"""Sitemap source: discover 987FM giveaway pages from a sitemap and poll them.

:func:`poll_sitemap` fetches a sitemap XML document, parses its ``<loc>``
entries with :mod:`xml.etree.ElementTree` (handling the sitemap namespace),
keeps only URLs whose path is under ``/radio/987/`` and whose slug matches the
giveaway keyword pattern, then fetches each matching page and parses it into an
:class:`Item`.

All I/O goes through injectable callables (``fetch`` and ``robots_checker``)
that share the same defaults as :func:`hotline.sources.web.poll_web`, so the
whole source is exercised offline in tests. Robots rules are honoured before
the sitemap fetch and before every page fetch, and a single failing fetch
(sitemap or page) never aborts the pass.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit
from xml.etree import ElementTree

from hotline.config import Config
from hotline.sources import Item
from hotline.sources.web import fetch_url, parse_html, robots_allowed

#: XML namespace used by the sitemaps.org 0.9 schema.
_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

#: Path prefix of 987FM pages we care about.
_RADIO_987_PREFIX = "/radio/987/"

#: Case-insensitive slug keywords that mark a page as a giveaway/contest.
_SLUG_PATTERN = re.compile(r"giveaway|contest|win|prize|promo", re.IGNORECASE)


def parse_sitemap_locs(xml_text: str) -> list[str]:
    """Return the ``<loc>`` URLs declared in a sitemap XML document.

    Args:
        xml_text: Raw sitemap XML text.

    Returns:
        The list of location URLs, in document order. Handles both the
        namespaced (``{http://www.sitemaps.org/schemas/sitemap/0.9}loc``) and
        bare ``loc`` element names.
    """
    root = ElementTree.fromstring(xml_text)
    locs: list[str] = []
    for loc in root.iter():
        tag = loc.tag
        if tag in (f"{{{_SITEMAP_NS}}}loc", "loc") and loc.text:
            locs.append(loc.text.strip())
    return locs


def is_987_giveaway_url(url: str) -> bool:
    """Return whether ``url`` is a 987FM giveaway-style page.

    A URL qualifies when its path is under ``/radio/987/`` and the slug
    (final path segment) matches the giveaway keyword pattern.

    Args:
        url: Absolute URL to test.
    """
    path = urlsplit(url).path
    if not path.startswith(_RADIO_987_PREFIX):
        return False
    slug = path.rsplit("/", 1)[-1]
    return _SLUG_PATTERN.search(slug) is not None


def poll_sitemap(
    config: Config,
    fetch: Callable[[str, str], str] = fetch_url,
    robots_checker: Callable[[str, str], bool] = robots_allowed,
) -> Iterator[Item]:
    """Yield :class:`Item` records for 987FM giveaway pages found via sitemap.

    Args:
        config: Runtime configuration providing ``sitemap_url`` and the
            ``user_agent`` to send. When ``sitemap_url`` is ``None`` the
            iterator is empty.
        fetch: Callable ``(url, user_agent) -> text``. Defaults to
            :func:`hotline.sources.web.fetch_url`; injectable for tests.
        robots_checker: Callable ``(url, user_agent) -> bool``. Defaults to
            :func:`hotline.sources.web.robots_allowed`; injectable for tests.

    Yields:
        One :class:`Item` (``source="sitemap"``) per matching, robots-allowed
        page that fetched successfully. A failing sitemap fetch yields nothing;
        a failing page fetch is logged to stderr and skipped so one bad URL
        never aborts the pass.
    """
    sitemap_url = config.sitemap_url
    if not sitemap_url:
        return

    try:
        if not robots_checker(sitemap_url, config.user_agent):
            return
        xml_text = fetch(sitemap_url, config.user_agent)
        locs = parse_sitemap_locs(xml_text)
    except Exception as exc:  # noqa: BLE001 - a bad sitemap must not abort the pass
        print(f"hotline: skipping sitemap {sitemap_url}: {exc}", file=sys.stderr)
        return

    for url in locs:
        if not is_987_giveaway_url(url):
            continue
        try:
            if not robots_checker(url, config.user_agent):
                continue
            html = fetch(url, config.user_agent)
        except Exception as exc:  # noqa: BLE001 - one bad URL must not abort the pass
            print(f"hotline: skipping {url}: {exc}", file=sys.stderr)
            continue
        yield parse_html(html, url, source="sitemap")
