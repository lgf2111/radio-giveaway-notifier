"""Shared pytest fixtures and helpers.

Provides access to the repo ``fixtures/`` directory and small fake-factory
helpers for the injectable I/O callables (fetch, robots, sender, transcriber).
No test performs network I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the repo ``fixtures/`` directory."""
    return FIXTURES_DIR


@pytest.fixture
def read_fixture():
    """Return a reader that loads a fixture file's text by name."""

    def _read(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return _read


@pytest.fixture
def make_fetcher():
    """Return a factory building a fake web fetcher.

    The factory takes a ``{url: body}`` mapping and returns a
    ``fetch(url, user_agent) -> body`` callable that records the User-Agents it
    was called with on ``fetch.calls``.
    """

    def _factory(responses: dict[str, str]) -> Callable[[str, str], str]:
        def _fetch(url: str, user_agent: str) -> str:
            _fetch.calls.append((url, user_agent))  # type: ignore[attr-defined]
            return responses[url]

        _fetch.calls = []  # type: ignore[attr-defined]
        return _fetch

    return _factory


@pytest.fixture
def make_robots():
    """Return a factory building a fake robots checker.

    The factory takes an optional set of disallowed URLs and returns a
    ``robots_checker(url, user_agent) -> bool`` callable.
    """

    def _factory(disallowed: set[str] | None = None) -> Callable[[str, str], bool]:
        blocked = disallowed or set()

        def _checker(url: str, user_agent: str) -> bool:
            return url not in blocked

        return _checker

    return _factory


@pytest.fixture
def make_social_fetcher():
    """Return a factory building a fake social fetcher.

    The factory takes a ``{url_prefix: body}`` mapping; the returned
    ``fetch(url, headers) -> body`` matches the first prefix contained in the
    requested URL and records calls on ``fetch.calls``.
    """

    def _factory(responses: dict[str, str]) -> Callable[[str, dict[str, str]], str]:
        def _fetch(url: str, headers: dict[str, str]) -> str:
            _fetch.calls.append((url, headers))  # type: ignore[attr-defined]
            for prefix, body in responses.items():
                if prefix in url:
                    return body
            raise AssertionError(f"no fake response configured for {url}")

        _fetch.calls = []  # type: ignore[attr-defined]
        return _fetch

    return _factory


@pytest.fixture
def make_sender():
    """Return a factory building a fake Telegram POST sender.

    The returned ``post(url, payload) -> dict`` records each call on
    ``post.calls`` and returns a canned ``{"ok": True}`` response.
    """

    def _factory() -> Callable[[str, dict[str, str]], dict]:
        def _post(url: str, payload: dict[str, str]) -> dict:
            _post.calls.append((url, payload))  # type: ignore[attr-defined]
            return {"ok": True}

        _post.calls = []  # type: ignore[attr-defined]
        return _post

    return _factory


@pytest.fixture
def make_transcriber():
    """Return a factory building a fake audio transcriber.

    The returned ``transcriber(window) -> text`` echoes the window text back
    (or applies an optional transform), recording calls on ``transcriber.calls``.
    """

    def _factory(
        transform: Callable[[str], str] | None = None,
    ) -> Callable[[str], str]:
        def _transcribe(window: str) -> str:
            _transcribe.calls.append(window)  # type: ignore[attr-defined]
            return transform(window) if transform else window

        _transcribe.calls = []  # type: ignore[attr-defined]
        return _transcribe

    return _factory
