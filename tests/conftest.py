"""Shared pytest fixtures and helpers.

Provides access to the repo ``fixtures/`` directory and small fake-factory
helpers for the injectable I/O callables (fetch, robots, sender, transcriber).
No test performs network I/O.
"""

from __future__ import annotations

import subprocess
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
def make_station():
    """Return a factory building a :class:`~hotline.config.Station`.

    Sensible defaults (``language="en"``, no stream) keep call sites short; any
    field can be overridden by keyword.
    """
    from hotline.config import Station

    def _factory(
        name: str = "987FM",
        slug: str = "987fm",
        language: str = "en",
        stream_url: str | None = None,
        contest_urls: list[str] | None = None,
        sitemap_url: str | None = None,
        feed_url: str | None = None,
        audio_enabled: bool = False,
    ) -> Station:
        return Station(
            name=name,
            slug=slug,
            language=language,
            stream_url=stream_url,
            contest_urls=list(contest_urls or []),
            sitemap_url=sitemap_url,
            feed_url=feed_url,
            audio_enabled=audio_enabled,
        )

    return _factory


@pytest.fixture
def make_multi_station_config(make_station):
    """Return a factory building a multi-station :class:`~hotline.config.Config`.

    Takes an iterable of :class:`~hotline.config.Station` (or none, in which
    case two fake stations are created) plus any flat ``Config`` overrides, and
    mirrors the first station's targeting into the flat fields the way
    ``load_config`` does.
    """
    from hotline.config import Config, Station

    def _factory(stations: list[Station] | None = None, **overrides) -> Config:
        if stations is None:
            stations = [
                make_station(name="Station A", slug="a", contest_urls=["https://a.test/win"]),
                make_station(name="Station B", slug="b", contest_urls=["https://b.test/win"]),
            ]
        first = stations[0]
        base = dict(
            contest_urls=list(first.contest_urls),
            feed_url=first.feed_url,
            sitemap_url=first.sitemap_url,
            audio_stream_url=first.stream_url,
            audio_enabled=first.audio_enabled,
            stations=list(stations),
        )
        base.update(overrides)
        return Config(**base)

    return _factory


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
def make_sitemap_fetcher():
    """Return a factory building a fake fetcher for the sitemap source.

    The factory takes the sitemap URL, the sitemap XML body, and a
    ``{page_url: html}`` mapping. The returned ``fetch(url, user_agent) -> body``
    serves the sitemap XML for the sitemap URL and the matching HTML for page
    URLs, records calls on ``fetch.calls``, and raises for unknown URLs so a
    test can assert exactly which URLs were fetched.
    """

    def _factory(
        sitemap_url: str,
        sitemap_xml: str,
        pages: dict[str, str],
    ) -> Callable[[str, str], str]:
        def _fetch(url: str, user_agent: str) -> str:
            _fetch.calls.append((url, user_agent))  # type: ignore[attr-defined]
            if url == sitemap_url:
                return sitemap_xml
            if url in pages:
                return pages[url]
            raise AssertionError(f"no fake response configured for {url}")

        _fetch.calls = []  # type: ignore[attr-defined]
        return _fetch

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
def make_multipart_sender():
    """Return a factory building a fake Telegram multipart (sendVoice) sender.

    The returned ``sender(url, fields, filename, file_bytes) -> dict`` records
    each call on ``sender.calls`` (as a dict of endpoint/fields/filename/bytes)
    and returns a canned ``{"ok": True}`` response. No network I/O.
    """

    def _factory() -> Callable[[str, dict[str, str], str, bytes], dict]:
        def _send(url: str, fields: dict[str, str], filename: str, file_bytes: bytes) -> dict:
            _send.calls.append(  # type: ignore[attr-defined]
                {
                    "url": url,
                    "fields": fields,
                    "filename": filename,
                    "file_bytes": file_bytes,
                }
            )
            return {"ok": True}

        _send.calls = []  # type: ignore[attr-defined]
        return _send

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


@pytest.fixture
def fake_runner():
    """Return a factory building a fake ``subprocess.run`` for ffmpeg.

    The factory takes an optional ``returncode`` (default 0). The returned
    ``run(argv, **kwargs) -> CompletedProcess`` records the argv list it was
    called with on ``run.calls``, writes a stub file at the ffmpeg output path
    (the last argv element), and returns a ``CompletedProcess`` with the given
    return code. No real ffmpeg is invoked.
    """

    def _factory(returncode: int = 0) -> Callable[..., subprocess.CompletedProcess]:
        def _run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            _run.calls.append(argv)  # type: ignore[attr-defined]
            if returncode == 0:
                out_path = Path(argv[-1])
                out_path.write_bytes(b"stub-audio")
            return subprocess.CompletedProcess(argv, returncode, stdout=b"", stderr=b"")

        _run.calls = []  # type: ignore[attr-defined]
        return _run

    return _factory


@pytest.fixture
def fake_classifier():
    """Return a factory building a fake music-vs-speech classifier.

    The factory takes a :class:`~hotline.speech_gate.Classification` (or
    ``is_speech`` / ``confidence`` / ``reason`` kwargs) and returns a
    ``classify(path) -> Classification`` callable recording the paths it was
    called with on ``classify.calls``.
    """
    from hotline.speech_gate import Classification

    def _factory(
        classification: Classification | None = None,
        *,
        is_speech: bool = True,
        confidence: float = 0.9,
        reason: str = "fake classification",
    ) -> Callable[[object], Classification]:
        result = classification or Classification(
            is_speech=is_speech, confidence=confidence, reason=reason
        )

        def _classify(path: object) -> Classification:
            _classify.calls.append(path)  # type: ignore[attr-defined]
            return result

        _classify.calls = []  # type: ignore[attr-defined]
        return _classify

    return _factory


@pytest.fixture
def fake_pcm_decoder():
    """Return a factory building a fake PCM decoder (path -> samples).

    The factory takes a ``list[float]`` of synthetic samples and returns a
    ``decoder(path) -> list[float]`` callable recording the paths it was called
    with on ``decoder.calls``. No ffmpeg is invoked.
    """

    def _factory(samples: list[float]) -> Callable[[object], list[float]]:
        def _decode(path: object) -> list[float]:
            _decode.calls.append(path)  # type: ignore[attr-defined]
            return list(samples)

        _decode.calls = []  # type: ignore[attr-defined]
        return _decode

    return _factory


@pytest.fixture
def fake_clip_transcriber():
    """Return a factory building a fake clip transcriber (path -> text).

    Distinct from :func:`make_transcriber` (which echoes window text): this
    takes fixed transcript text and returns it for any audio path, recording
    the paths it was called with on ``transcriber.calls``.
    """

    def _factory(text: str) -> Callable[[str], str]:
        def _transcribe(path: str) -> str:
            _transcribe.calls.append(path)  # type: ignore[attr-defined]
            return text

        _transcribe.calls = []  # type: ignore[attr-defined]
        return _transcribe

    return _factory
