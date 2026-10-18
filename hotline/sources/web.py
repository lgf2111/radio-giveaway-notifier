"""Web source: robots-aware HTML poller that yields :class:`Item` records.

:func:`poll_web` iterates the configured contest/giveaway URLs (plus an
optional feed URL), skips any URL disallowed by ``robots.txt``, fetches each
page with a polite configurable User-Agent, and parses it into an
:class:`Item`. All I/O goes through injectable callables (``fetch`` and
``robots_checker``) so tests run entirely offline.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from urllib import robotparser
from urllib.request import Request, urlopen

from hotline.config import Config
from hotline.sources import Item

#: Tags whose text content should never be treated as visible page text. In
#: addition to non-content tags (``script``/``style``/``head``/``title``) this
#: includes chrome regions (``nav``/``header``/``footer``/``aside``/
#: ``noscript``) whose copy is site boilerplate rather than contest text.
_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "head",
        "title",
        "nav",
        "header",
        "footer",
        "aside",
        "noscript",
    }
)

#: Case-insensitive substrings in a ``class``/``id`` attribute that mark an
#: element as chrome (navigation, sharing, social, footer) to be skipped.
_CHROME_ATTR_KEYWORDS = ("share", "social", "footer", "nav", "menu", "breadcrumb")


def fetch_url(url: str, user_agent: str, *, timeout: float = 10.0) -> str:
    """Fetch ``url`` over HTTP(S) with a polite User-Agent.

    Args:
        url: Absolute URL to fetch.
        user_agent: User-Agent header value to send.
        timeout: Socket timeout in seconds.

    Returns:
        The decoded response body as text.
    """
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme is caller-controlled
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def robots_allowed(url: str, user_agent: str, checker: object | None = None) -> bool:
    """Return whether ``robots.txt`` permits fetching ``url``.

    Args:
        url: Absolute URL to check.
        user_agent: User-Agent to evaluate the rules against.
        checker: Optional object exposing ``can_fetch(user_agent, url)``.
            Defaults to a :class:`urllib.robotparser.RobotFileParser` loaded
            from the URL's ``/robots.txt``. Injectable for tests.

    Returns:
        ``True`` if fetching is allowed (or robots cannot be determined),
        ``False`` if explicitly disallowed.
    """
    if checker is None:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        parser = robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
        except OSError:
            # If robots.txt cannot be fetched, default to allowing.
            return True
        checker = parser

    return bool(checker.can_fetch(user_agent, url))


#: HTML void elements, which never receive a matching end tag.
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


def _attrs_mark_chrome(attrs: list[tuple[str, str | None]]) -> bool:
    """Return whether a start tag's ``class``/``id`` attributes mark it as chrome.

    Args:
        attrs: The ``(name, value)`` attribute pairs from :meth:`handle_starttag`.

    Returns:
        ``True`` if any ``class`` or ``id`` attribute value contains (as a
        case-insensitive substring) one of :data:`_CHROME_ATTR_KEYWORDS`.
    """
    for name, value in attrs:
        if name not in ("class", "id") or not value:
            continue
        lowered = value.lower()
        if any(keyword in lowered for keyword in _CHROME_ATTR_KEYWORDS):
            return True
    return False


class _TextExtractor(HTMLParser):
    """Extract the ``<title>`` and visible body text from an HTML document.

    Chrome regions (``nav``/``header``/``footer``/``aside``/``noscript`` and
    any element whose ``class``/``id`` names a share/social/nav region) are
    skipped so site boilerplate never reaches the scorer.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        # Per-element record of whether each open tag started a skip region, so
        # end tags can close the right region even when markup nests or is
        # unbalanced.
        self._skip_stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Void elements never get an end tag, so they must not push onto the
        # skip stack (doing so would desync it against the end tags).
        if tag in _VOID_TAGS:
            return
        is_skip = tag in _SKIP_TAGS or _attrs_mark_chrome(attrs)
        self._skip_stack.append(is_skip)
        if is_skip:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags (``<tag/>``) open and close in one event, so they
        # carry no text and never affect the skip stack.
        return

    def handle_endtag(self, tag: str) -> None:
        if self._skip_stack:
            was_skip = self._skip_stack.pop()
            if was_skip and self._skip_depth > 0:
                self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._skip_depth == 0:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        """The collapsed ``<title>`` text (empty string if absent)."""
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        """The collapsed visible body text."""
        return " ".join(self.text_parts).strip()


def parse_html(html: str, url: str, source: str = "web") -> Item:
    """Parse an HTML document into an :class:`Item`.

    Args:
        html: Raw HTML document text.
        url: URL the document was fetched from.
        source: Source identifier to record on the item.

    Returns:
        An :class:`Item` whose ``title`` is the ``<title>`` (falling back to
        the URL) and whose ``text`` is the visible body text.
    """
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    title = extractor.title or url
    return Item(title=title, url=url, text=extractor.text, published=None, source=source)


def poll_web(
    config: Config,
    fetch: Callable[[str, str], str] = fetch_url,
    robots_checker: Callable[[str, str], bool] = robots_allowed,
) -> Iterator[Item]:
    """Yield :class:`Item` records for each allowed configured web URL.

    Args:
        config: Runtime configuration providing ``contest_urls``, an optional
            ``feed_url``, and the ``user_agent`` to send.
        fetch: Callable ``(url, user_agent) -> html``. Defaults to
            :func:`fetch_url`; injectable for tests.
        robots_checker: Callable ``(url, user_agent) -> bool``. Defaults to
            :func:`robots_allowed`; injectable for tests.

    Yields:
        One :class:`Item` per fetched URL that robots.txt permits. A URL that
        fails to fetch (network error, bad status, timeout) is logged to stderr
        and skipped so one bad URL never aborts the whole poll.
    """
    urls = list(config.contest_urls)
    if config.feed_url:
        urls.append(config.feed_url)

    for url in urls:
        try:
            if not robots_checker(url, config.user_agent):
                continue
            html = fetch(url, config.user_agent)
        except Exception as exc:  # noqa: BLE001 - one bad URL must not abort the pass
            print(f"hotline: skipping {url}: {exc}", file=sys.stderr)
            continue
        yield parse_html(html, url)
