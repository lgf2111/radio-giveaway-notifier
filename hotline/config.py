"""Configuration loading for hotline.

The :class:`Config` dataclass holds all runtime settings. :func:`load_config`
reads non-secret settings from a TOML file (via :mod:`tomllib`) and overlays
secrets *only* from environment variables. Secrets are never read from TOML so
they can never be committed with a config file.

TOML layout (all tables and keys optional)::

    [source]
    contest_urls = ["https://.../contests"]
    feed_url = "https://.../feed.xml"
    sitemap_url = "https://.../sitemap.xml"
    user_agent = "hotline/0.1 (+contact)"

    [poll]
    interval = 45

    [audio]
    enabled = false
    stream_url = "https://.../987fm.mp3"

Secrets come from the environment only:
``HOTLINE_TELEGRAM_TOKEN``, ``HOTLINE_CHAT_ID``, ``HOTLINE_X_BEARER``,
``HOTLINE_IG_TOKEN``.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = "config.toml"
DEFAULT_USER_AGENT = "hotline/0.1 (+contact)"
DEFAULT_POLL_INTERVAL = 45


@dataclass
class Config:
    """Typed runtime configuration for hotline.

    Non-secret fields come from the TOML file (or defaults); secret fields
    (``telegram_token``, ``chat_id``, ``x_bearer``, ``ig_token``) come only
    from environment variables.
    """

    contest_urls: list[str] = field(default_factory=list)
    feed_url: str | None = None
    sitemap_url: str | None = None
    poll_interval: int = DEFAULT_POLL_INTERVAL
    user_agent: str = DEFAULT_USER_AGENT
    audio_stream_url: str | None = None
    audio_enabled: bool = False
    x_bearer: str | None = None
    ig_token: str | None = None
    telegram_token: str | None = None
    chat_id: str | None = None


def load_config(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Load configuration from TOML plus environment secrets.

    Args:
        path: Path to a TOML config file. Defaults to ``config.toml``. A missing
            file yields a :class:`Config` with all defaults (no error).
        env: Mapping used for secret lookups. Defaults to :data:`os.environ`;
            injectable for tests.

    Returns:
        A populated :class:`Config`.
    """
    if env is None:
        env = os.environ

    config_path = Path(path) if path is not None else Path(DEFAULT_CONFIG_PATH)

    data: dict[str, object] = {}
    if config_path.is_file():
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)

    source = _as_table(data.get("source"))
    poll = _as_table(data.get("poll"))
    audio = _as_table(data.get("audio"))

    contest_urls_raw = source.get("contest_urls", [])
    contest_urls = (
        [str(url) for url in contest_urls_raw] if isinstance(contest_urls_raw, list) else []
    )

    feed_url = source.get("feed_url")
    sitemap_url = source.get("sitemap_url")
    user_agent = source.get("user_agent", DEFAULT_USER_AGENT)

    poll_interval = poll.get("interval", DEFAULT_POLL_INTERVAL)

    audio_enabled = audio.get("enabled", False)
    audio_stream_url = audio.get("stream_url")

    return Config(
        contest_urls=contest_urls,
        feed_url=str(feed_url) if feed_url is not None else None,
        sitemap_url=str(sitemap_url) if sitemap_url is not None else None,
        poll_interval=int(poll_interval),
        user_agent=str(user_agent),
        audio_stream_url=str(audio_stream_url) if audio_stream_url is not None else None,
        audio_enabled=bool(audio_enabled),
        x_bearer=env.get("HOTLINE_X_BEARER"),
        ig_token=env.get("HOTLINE_IG_TOKEN"),
        telegram_token=env.get("HOTLINE_TELEGRAM_TOKEN"),
        chat_id=env.get("HOTLINE_CHAT_ID"),
    )


def _as_table(value: object) -> Mapping[str, object]:
    """Return ``value`` if it is a mapping, else an empty mapping."""
    if isinstance(value, Mapping):
        return value
    return {}
