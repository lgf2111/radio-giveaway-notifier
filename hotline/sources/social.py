"""Social source: token-gated X / Instagram poller.

:func:`poll_social` is a no-op unless a token is configured. When
``config.x_bearer`` is set it fetches a public X endpoint; when
``config.ig_token`` is set it fetches a public Instagram endpoint. All HTTP
goes through an injectable ``fetch`` callable, so tests never touch the
network. With no tokens configured the generator yields nothing and never
raises.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hotline.config import Config
from hotline.sources import Item

#: Public X (Twitter) recent-search endpoint used to find contest posts.
X_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
#: Public Instagram Graph API media endpoint.
IG_MEDIA_URL = "https://graph.instagram.com/me/media"

#: Fetcher signature: ``(url, headers) -> response body text``.
Fetch = Callable[[str, dict[str, str]], str]


def _default_fetch(url: str, headers: dict[str, str], *, timeout: float = 10.0) -> str:
    """Fetch ``url`` with the given headers and return the body text."""
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - trusted API endpoints
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _fetch_x(fetch: Fetch, bearer: str) -> list[Item]:
    """Fetch recent public X posts and map them to :class:`Item` records."""
    query = urlencode(
        {"query": "987FM (giveaway OR contest OR tickets)", "tweet.fields": "created_at"}
    )
    url = f"{X_SEARCH_URL}?{query}"
    headers = {"Authorization": f"Bearer {bearer}"}
    payload = json.loads(fetch(url, headers))

    items: list[Item] = []
    for post in payload.get("data", []):
        post_id = str(post.get("id", ""))
        text = str(post.get("text", ""))
        items.append(
            Item(
                title=text[:80] or f"X post {post_id}",
                url=f"https://x.com/i/web/status/{post_id}",
                text=text,
                published=post.get("created_at"),
                source="x",
            )
        )
    return items


def _fetch_ig(fetch: Fetch, token: str) -> list[Item]:
    """Fetch recent public Instagram media and map them to :class:`Item`."""
    query = urlencode({"fields": "id,caption,permalink,timestamp", "access_token": token})
    url = f"{IG_MEDIA_URL}?{query}"
    payload = json.loads(fetch(url, {}))

    items: list[Item] = []
    for media in payload.get("data", []):
        media_id = str(media.get("id", ""))
        caption = str(media.get("caption", ""))
        items.append(
            Item(
                title=caption[:80] or f"Instagram post {media_id}",
                url=str(media.get("permalink", "")) or f"https://instagram.com/p/{media_id}",
                text=caption,
                published=media.get("timestamp"),
                source="instagram",
            )
        )
    return items


def poll_social(config: Config, fetch: Fetch = _default_fetch) -> Iterator[Item]:
    """Yield :class:`Item` records from configured social endpoints.

    Args:
        config: Runtime configuration providing optional ``x_bearer`` and
            ``ig_token`` secrets.
        fetch: Callable ``(url, headers) -> body text``. Defaults to a stdlib
            urllib fetcher; injectable for tests.

    Yields:
        :class:`Item` records from each configured platform. Yields nothing and
        raises nothing when no tokens are configured.
    """
    if config.x_bearer:
        yield from _fetch_x(fetch, config.x_bearer)
    if config.ig_token:
        yield from _fetch_ig(fetch, config.ig_token)
