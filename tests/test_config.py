"""Tests for hotline.config."""

from __future__ import annotations

from pathlib import Path

from hotline.config import DEFAULT_POLL_INTERVAL, Config, load_config


def test_defaults_when_no_toml(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    config = load_config(missing, env={})
    assert config == Config()
    assert config.poll_interval == DEFAULT_POLL_INTERVAL == 45
    assert config.contest_urls == []
    assert config.telegram_token is None


def test_toml_values_loaded(tmp_path: Path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[source]
contest_urls = ["https://example.test/contests", "https://example.test/win"]
feed_url = "https://example.test/feed.xml"
user_agent = "hotline-test/1.0"

[poll]
interval = 30

[audio]
enabled = true
stream_url = "https://example.test/987.mp3"
""",
        encoding="utf-8",
    )
    config = load_config(toml, env={})
    assert config.contest_urls == [
        "https://example.test/contests",
        "https://example.test/win",
    ]
    assert config.feed_url == "https://example.test/feed.xml"
    assert config.user_agent == "hotline-test/1.0"
    assert config.poll_interval == 30
    assert config.audio_enabled is True
    assert config.audio_stream_url == "https://example.test/987.mp3"


def test_env_secrets_merged(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    env = {
        "HOTLINE_TELEGRAM_TOKEN": "tok",
        "HOTLINE_CHAT_ID": "123",
        "HOTLINE_X_BEARER": "xbear",
        "HOTLINE_IG_TOKEN": "igtok",
    }
    config = load_config(missing, env=env)
    assert config.telegram_token == "tok"
    assert config.chat_id == "123"
    assert config.x_bearer == "xbear"
    assert config.ig_token == "igtok"


def test_secrets_never_read_from_toml(tmp_path: Path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[source]
contest_urls = ["https://example.test/contests"]
telegram_token = "should-be-ignored"
chat_id = "should-be-ignored"

[secrets]
telegram_token = "also-ignored"
""",
        encoding="utf-8",
    )
    config = load_config(toml, env={})
    assert config.telegram_token is None
    assert config.chat_id is None
