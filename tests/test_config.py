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


def test_audio_and_summary_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    config = load_config(missing, env={})
    assert config.audio_model_size == "base"
    assert config.audio_compute_type == "int8"
    assert config.audio_clip_seconds == 45
    assert config.audio_mode == "event"
    assert config.audio_capture_format == "opus"
    assert config.audio_gate_enabled is True
    assert config.audio_gate_min_confidence == 0.6
    assert config.audio_gate_backend == "builtin"
    assert config.summary_mode == "rules"
    assert config.summary_api_base is None
    assert config.summary_model is None
    assert config.summary_api_key is None


def test_audio_and_summary_toml_loaded(tmp_path: Path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[audio]
enabled = true
stream_url = "https://example.test/987.aac"
mode = "interval"
model_size = "small"
compute_type = "float16"
clip_seconds = 30
capture_format = "ogg"

gate_enabled = false
gate_min_confidence = 0.8
gate_backend = "silero"

[summary]
mode = "llm"
api_base = "https://api.example.test/v1"
model = "gpt-4o-mini"
""",
        encoding="utf-8",
    )
    config = load_config(toml, env={})
    assert config.audio_enabled is True
    assert config.audio_stream_url == "https://example.test/987.aac"
    assert config.audio_gate_enabled is False
    assert config.audio_gate_min_confidence == 0.8
    assert config.audio_gate_backend == "silero"
    assert config.audio_mode == "interval"
    assert config.audio_model_size == "small"
    assert config.audio_compute_type == "float16"
    assert config.audio_clip_seconds == 30
    assert config.audio_capture_format == "ogg"
    assert config.summary_mode == "llm"
    assert config.summary_api_base == "https://api.example.test/v1"
    assert config.summary_model == "gpt-4o-mini"


def test_summary_api_key_is_env_only(tmp_path: Path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[summary]
mode = "llm"
api_key = "should-be-ignored"
""",
        encoding="utf-8",
    )
    config = load_config(toml, env={"HOTLINE_SUMMARY_API_KEY": "secret"})
    assert config.summary_api_key == "secret"

    config_no_env = load_config(toml, env={})
    assert config_no_env.summary_api_key is None


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
