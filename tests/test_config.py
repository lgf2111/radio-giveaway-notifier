"""Tests for hotline.config."""

from __future__ import annotations

from pathlib import Path

from hotline.config import DEFAULT_POLL_INTERVAL, DEFAULT_STATIONS, Config, load_config


def test_defaults_when_no_toml(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    config = load_config(missing, env={})
    # Identical to Config() apart from the default station list (which load_config
    # synthesizes from DEFAULT_STATIONS when no TOML is present).
    assert config == Config(stations=list(DEFAULT_STATIONS))
    assert config.poll_interval == DEFAULT_POLL_INTERVAL == 45
    assert config.contest_urls == []
    assert config.telegram_token is None


def test_no_toml_yields_default_stations(tmp_path: Path) -> None:
    missing = tmp_path / "nope.toml"
    config = load_config(missing, env={})
    assert config.stations == list(DEFAULT_STATIONS)
    assert len(config.stations) == 8
    slugs = [s.slug for s in config.stations]
    assert slugs == [
        "class95",
        "987fm",
        "gold905",
        "kiss92",
        "onefm",
        "yes933",
        "love972",
        "jia883",
    ]


def test_default_stations_verified_vs_user_supplied() -> None:
    by_slug = {s.slug: s for s in DEFAULT_STATIONS}
    # The 4 Mediacorp stations carry verified streamtheworld stream URLs.
    for slug in ("class95", "987fm", "gold905", "yes933"):
        assert by_slug[slug].stream_url is not None
        assert "streamtheworld.com" in by_slug[slug].stream_url
        assert by_slug[slug].audio_enabled is True
    # The other 4 have no stream URL yet and audio stays off.
    for slug in ("kiss92", "onefm", "love972", "jia883"):
        assert by_slug[slug].stream_url is None
        assert by_slug[slug].audio_enabled is False
    # Only 987fm carries the melisten contest page + sitemap by default.
    assert by_slug["987fm"].contest_urls == ["https://www.melisten.sg/radio/987"]
    assert by_slug["987fm"].sitemap_url == "https://www.melisten.sg/sitemap.xml"
    assert by_slug["class95"].contest_urls == []
    assert by_slug["class95"].sitemap_url is None


def test_station_tables_parse_to_station_list(tmp_path: Path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[[station]]
name = "987FM"
slug = "987fm"
language = "en"
stream_url = "https://example.test/987.aac"
audio_enabled = true
contest_urls = ["https://example.test/987"]
sitemap_url = "https://example.test/sitemap.xml"

[[station]]
name = "YES 933"
language = "zh"
stream_url = "https://example.test/yes933.aac"
audio_enabled = true

[[station]]
name = "Kiss92"
language = "en"
stream_url = ""
audio_enabled = false
""",
        encoding="utf-8",
    )
    config = load_config(toml, env={})
    assert len(config.stations) == 3

    first, second, third = config.stations
    assert first.name == "987FM"
    assert first.slug == "987fm"
    assert first.language == "en"
    assert first.stream_url == "https://example.test/987.aac"
    assert first.audio_enabled is True
    assert first.contest_urls == ["https://example.test/987"]
    assert first.sitemap_url == "https://example.test/sitemap.xml"

    # Slug derived from the name when absent.
    assert second.slug == "yes933"
    assert second.language == "zh"

    # Empty stream_url parses to None (no verified stream yet).
    assert third.slug == "kiss92"
    assert third.stream_url is None
    assert third.audio_enabled is False

    # The first station's targeting is mirrored into the flat fields so the
    # single-station audio pipeline + fixtures demo keep working.
    assert config.contest_urls == ["https://example.test/987"]
    assert config.sitemap_url == "https://example.test/sitemap.xml"
    assert config.audio_stream_url == "https://example.test/987.aac"
    assert config.audio_enabled is True


def test_legacy_single_station_yields_one_station(tmp_path: Path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[source]
contest_urls = ["https://example.test/987"]
sitemap_url = "https://example.test/sitemap.xml"

[audio]
enabled = true
stream_url = "https://example.test/987.aac"
""",
        encoding="utf-8",
    )
    config = load_config(toml, env={})
    assert len(config.stations) == 1
    station = config.stations[0]
    assert station.name == "987FM"
    assert station.slug == "987fm"
    assert station.language == "en"
    assert station.stream_url == "https://example.test/987.aac"
    assert station.contest_urls == ["https://example.test/987"]
    assert station.sitemap_url == "https://example.test/sitemap.xml"
    assert station.audio_enabled is True
    # Flat fields stay populated exactly as before.
    assert config.contest_urls == ["https://example.test/987"]
    assert config.sitemap_url == "https://example.test/sitemap.xml"
    assert config.audio_stream_url == "https://example.test/987.aac"
    assert config.audio_enabled is True


def test_station_secrets_never_read_from_toml(tmp_path: Path) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[[station]]
name = "987FM"
slug = "987fm"
language = "en"
telegram_token = "should-be-ignored"
chat_id = "also-ignored"
""",
        encoding="utf-8",
    )
    config = load_config(toml, env={})
    assert config.telegram_token is None
    assert config.chat_id is None
    # The bogus secret keys are not surfaced on the Station either.
    assert not hasattr(config.stations[0], "telegram_token")


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


def test_dotenv_file_populates_secrets(tmp_path: Path) -> None:
    """Secrets present only in a .env file are loaded when env is not injected."""
    missing_toml = tmp_path / "nope.toml"
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "HOTLINE_TELEGRAM_TOKEN=tok123\n"
        'HOTLINE_CHAT_ID="555"\n'
        "# a comment line\n"
        "export HOTLINE_SUMMARY_API_KEY=apikey\n",
        encoding="utf-8",
    )
    config = load_config(missing_toml, dotenv_path=dotenv)
    assert config.telegram_token == "tok123"
    assert config.chat_id == "555"
    assert config.summary_api_key == "apikey"


def test_injected_env_ignores_dotenv(tmp_path: Path) -> None:
    """An injected env mapping bypasses .env entirely (test isolation)."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("HOTLINE_TELEGRAM_TOKEN=fromfile\n", encoding="utf-8")
    config = load_config(tmp_path / "nope.toml", env={}, dotenv_path=dotenv)
    assert config.telegram_token is None
