"""Tests for hotline.sources.social."""

from __future__ import annotations

import json

from hotline.config import Config
from hotline.sources.social import poll_social


def test_no_tokens_yields_nothing(make_social_fetcher) -> None:
    fetch = make_social_fetcher({})
    config = Config()
    items = list(poll_social(config, fetch=fetch))
    assert items == []
    # Never attempted a fetch.
    assert fetch.calls == []


def test_x_token_yields_items(make_social_fetcher) -> None:
    body = json.dumps(
        {
            "data": [
                {
                    "id": "111",
                    "text": "Giveaway! Call now to win tickets",
                    "created_at": "2026-01-01",
                }
            ]
        }
    )
    fetch = make_social_fetcher({"api.twitter.com": body})
    config = Config(x_bearer="x-secret")

    items = list(poll_social(config, fetch=fetch))
    assert len(items) == 1
    assert items[0].source == "x"
    assert "111" in items[0].url
    assert "win tickets" in items[0].text
    # Bearer token forwarded in the Authorization header.
    _url, headers = fetch.calls[0]
    assert headers["Authorization"] == "Bearer x-secret"


def test_ig_token_yields_items(make_social_fetcher) -> None:
    body = json.dumps(
        {
            "data": [
                {
                    "id": "222",
                    "caption": "Our contest is live, text in to enter",
                    "permalink": "https://instagram.com/p/abc",
                    "timestamp": "2026-02-02",
                }
            ]
        }
    )
    fetch = make_social_fetcher({"graph.instagram.com": body})
    config = Config(ig_token="ig-secret")

    items = list(poll_social(config, fetch=fetch))
    assert len(items) == 1
    assert items[0].source == "instagram"
    assert items[0].url == "https://instagram.com/p/abc"
    assert "text in" in items[0].text


def test_both_tokens_yield_from_both(make_social_fetcher) -> None:
    x_body = json.dumps({"data": [{"id": "1", "text": "contest"}]})
    ig_body = json.dumps({"data": [{"id": "2", "caption": "giveaway"}]})
    fetch = make_social_fetcher({"api.twitter.com": x_body, "graph.instagram.com": ig_body})
    config = Config(x_bearer="x", ig_token="ig")

    items = list(poll_social(config, fetch=fetch))
    sources = {i.source for i in items}
    assert sources == {"x", "instagram"}
