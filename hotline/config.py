"""Configuration loading for hotline.

The :class:`Config` dataclass holds all runtime settings. :func:`load_config`
reads non-secret settings from a TOML file (via :mod:`tomllib`) and overlays
secrets *only* from environment variables. Secrets are never read from TOML so
they can never be committed with a config file.

Two TOML station formats are supported (plus a no-config default):

* **Multi-station** — one ``[[station]]`` array-of-tables entry per station::

      [[station]]
      name = "987FM"
      slug = "987fm"           # optional; derived from name when absent
      language = "en"          # "en" | "zh" | "bilingual"
      stream_url = "https://.../987fm.aac"
      audio_enabled = true
      contest_urls = ["https://.../987"]
      sitemap_url = "https://.../sitemap.xml"
      feed_url = "https://.../feed.xml"

  When ``[[station]]`` tables are present the first station's
  ``stream_url``/``audio_enabled``/``contest_urls``/``sitemap_url``/``feed_url``
  are mirrored into the flat :class:`Config` fields so the single-station
  audio pipeline and the offline fixtures demo keep working unchanged.

* **Legacy single-station** — the original flat ``[source]``/``[audio]`` tables
  (below) still parse; they synthesize exactly one ``987FM`` station.

* **No config** — a missing/empty file yields the 8 :data:`DEFAULT_STATIONS`.

Legacy TOML layout (all tables and keys optional)::

    [source]
    contest_urls = ["https://.../contests"]
    feed_url = "https://.../feed.xml"
    sitemap_url = "https://.../sitemap.xml"
    user_agent = "hotline/0.1 (+contact)"

    [poll]
    interval = 45

    [audio]
    enabled = false
    stream_url = "https://.../987fm.aac"
    mode = "event"
    model_size = "base"
    compute_type = "int8"
    clip_seconds = 45
    capture_format = "opus"
    gate_enabled = true
    gate_min_confidence = 0.6
    gate_backend = "builtin"

    [summary]
    mode = "rules"
    api_base = "https://api.openai.com/v1"
    model = "gpt-4o-mini"

The ``[poll]``/``[audio]``/``[summary]`` tables are always global settings,
regardless of which station format is used (only ``stream_url`` moves onto
individual stations in the multi-station format).

Secrets come from the environment only:
``HOTLINE_TELEGRAM_TOKEN``, ``HOTLINE_CHAT_ID``, ``HOTLINE_X_BEARER``,
``HOTLINE_IG_TOKEN``, ``HOTLINE_SUMMARY_API_KEY``.
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


@dataclass(frozen=True)
class Station:
    """A single radio station to watch for giveaways.

    Attributes:
        name: Human-readable station name (e.g. ``"987FM"``).
        slug: Short identifier used for the ``--station`` filter and for
            tagging items so dedupe distinguishes stations (e.g. ``"987fm"``).
        language: Detection/transcription language hint — ``"en"``, ``"zh"``,
            or ``"bilingual"``. Maps to a Whisper language in the audio path
            (``bilingual``/unknown auto-detects).
        stream_url: Live audio stream URL, or ``None`` when no verified stream
            is available for this station.
        contest_urls: Public contest/giveaway web pages to poll for this
            station.
        sitemap_url: Optional sitemap URL to discover giveaway pages.
        feed_url: Optional RSS/Atom/JSON feed URL to poll.
        audio_enabled: Whether the event-driven audio path may run for this
            station (requires a ``stream_url``).
    """

    name: str
    slug: str
    language: str
    stream_url: str | None = None
    contest_urls: list[str] = field(default_factory=list)
    sitemap_url: str | None = None
    feed_url: str | None = None
    audio_enabled: bool = False


#: The 8 Singapore stations watched by default (mainly Chinese + English).
#: Only 987FM carries the verified melisten contest page + sitemap by default;
#: the four Mediacorp stations carry verified streamtheworld stream URLs and
#: the other four leave ``stream_url`` as ``None`` until the user supplies one.
DEFAULT_STATIONS: tuple[Station, ...] = (
    Station(
        name="CLASS 95",
        slug="class95",
        language="en",
        stream_url="https://22903.live.streamtheworld.com/CLASS95_PREM.aac",
        audio_enabled=True,
    ),
    Station(
        name="987FM",
        slug="987fm",
        language="en",
        stream_url="https://22903.live.streamtheworld.com/987FM_PREM.aac",
        contest_urls=["https://www.melisten.sg/radio/987"],
        sitemap_url="https://www.melisten.sg/sitemap.xml",
        audio_enabled=True,
    ),
    Station(
        name="GOLD 905",
        slug="gold905",
        language="en",
        stream_url="https://22903.live.streamtheworld.com/GOLD905_PREM.aac",
        audio_enabled=True,
    ),
    Station(
        name="Kiss92",
        slug="kiss92",
        language="en",
        stream_url=None,
        audio_enabled=False,
    ),
    Station(
        name="ONE FM 91.3",
        slug="onefm",
        language="en",
        stream_url=None,
        audio_enabled=False,
    ),
    Station(
        name="YES 933",
        slug="yes933",
        language="zh",
        stream_url="https://22903.live.streamtheworld.com/YES933_PREM.aac",
        audio_enabled=True,
    ),
    Station(
        name="LOVE 972",
        slug="love972",
        language="zh",
        stream_url=None,
        audio_enabled=False,
    ),
    Station(
        name="88.3JIA",
        slug="jia883",
        language="bilingual",
        stream_url=None,
        audio_enabled=False,
    ),
)


@dataclass
class Config:
    """Typed runtime configuration for hotline.

    Non-secret fields come from the TOML file (or defaults); secret fields
    (``telegram_token``, ``chat_id``, ``x_bearer``, ``ig_token``,
    ``summary_api_key``) come only from environment variables.
    """

    contest_urls: list[str] = field(default_factory=list)
    feed_url: str | None = None
    sitemap_url: str | None = None
    poll_interval: int = DEFAULT_POLL_INTERVAL
    user_agent: str = DEFAULT_USER_AGENT
    audio_stream_url: str | None = None
    audio_enabled: bool = False
    audio_model_size: str = "base"
    audio_compute_type: str = "int8"
    audio_clip_seconds: int = 45
    audio_mode: str = "event"
    audio_capture_format: str = "opus"
    audio_gate_enabled: bool = True
    audio_gate_min_confidence: float = 0.6
    audio_gate_backend: str = "builtin"
    summary_mode: str = "rules"
    summary_api_base: str | None = None
    summary_model: str | None = None
    x_bearer: str | None = None
    ig_token: str | None = None
    telegram_token: str | None = None
    chat_id: str | None = None
    summary_api_key: str | None = None
    stations: list[Station] = field(default_factory=list)


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a simple ``.env`` file into a dict (stdlib only).

    Supports ``KEY=value`` lines, ``#`` comments, blank lines, an optional
    ``export`` prefix, and surrounding single/double quotes on the value. Not a
    full shell parser — no interpolation or multiline values. Returns an empty
    dict when the file is absent or unreadable.
    """
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def load_config(
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    dotenv_path: str | Path | None = None,
) -> Config:
    """Load configuration from TOML plus environment secrets.

    Args:
        path: Path to a TOML config file. Defaults to ``config.toml``. A missing
            file yields a :class:`Config` with all defaults (no error).
        env: Mapping used for secret lookups. Defaults to :data:`os.environ`
            layered over a ``.env`` file (real env vars take precedence);
            injectable for tests, in which case no ``.env`` is read.
        dotenv_path: Path to a ``.env`` file. Defaults to ``.env`` in the
            current directory. Only consulted when ``env`` is not injected.

    Returns:
        A populated :class:`Config`.
    """
    if env is None:
        # Layer a .env file UNDER the real environment so an actually-exported
        # variable always wins, but values present only in .env are picked up.
        dotenv_file = Path(dotenv_path) if dotenv_path is not None else Path(".env")
        merged = _parse_dotenv(dotenv_file)
        merged.update(os.environ)
        env = merged

    config_path = Path(path) if path is not None else Path(DEFAULT_CONFIG_PATH)

    data: dict[str, object] = {}
    if config_path.is_file():
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)

    source = _as_table(data.get("source"))
    poll = _as_table(data.get("poll"))
    audio = _as_table(data.get("audio"))
    summary = _as_table(data.get("summary"))

    station_tables = data.get("station")
    stations = _parse_stations(station_tables)

    if stations:
        # Multi-station: mirror the first station's source/audio targeting into
        # the flat fields so the single-station audio pipeline and the fixtures
        # demo keep working unchanged.
        first = stations[0]
        contest_urls = list(first.contest_urls)
        feed_url = first.feed_url
        sitemap_url = first.sitemap_url
        flat_stream_url: str | None = first.stream_url
        flat_audio_enabled: bool = first.audio_enabled
    else:
        contest_urls_raw = source.get("contest_urls", [])
        contest_urls = (
            [str(url) for url in contest_urls_raw] if isinstance(contest_urls_raw, list) else []
        )
        feed_url = source.get("feed_url")
        sitemap_url = source.get("sitemap_url")
        flat_stream_url = audio.get("stream_url")
        flat_audio_enabled = audio.get("enabled", False)

    user_agent = source.get("user_agent", DEFAULT_USER_AGENT)

    poll_interval = poll.get("interval", DEFAULT_POLL_INTERVAL)

    audio_enabled = flat_audio_enabled
    audio_stream_url = flat_stream_url
    audio_model_size = audio.get("model_size", "base")
    audio_compute_type = audio.get("compute_type", "int8")
    audio_clip_seconds = audio.get("clip_seconds", 45)
    audio_mode = audio.get("mode", "event")
    audio_capture_format = audio.get("capture_format", "opus")
    audio_gate_enabled = audio.get("gate_enabled", True)
    audio_gate_min_confidence = audio.get("gate_min_confidence", 0.6)
    audio_gate_backend = audio.get("gate_backend", "builtin")

    summary_mode = summary.get("mode", "rules")
    summary_api_base = summary.get("api_base")
    summary_model = summary.get("model")

    if not stations:
        if source or audio:
            # Legacy single-station TOML: synthesize one 987FM station from the
            # flat [source]/[audio] fields.
            stations = [
                Station(
                    name="987FM",
                    slug="987fm",
                    language="en",
                    stream_url=str(flat_stream_url) if flat_stream_url is not None else None,
                    contest_urls=list(contest_urls),
                    sitemap_url=str(sitemap_url) if sitemap_url is not None else None,
                    feed_url=str(feed_url) if feed_url is not None else None,
                    audio_enabled=bool(flat_audio_enabled),
                )
            ]
        else:
            # No config at all: watch the 8 default Singapore stations.
            stations = list(DEFAULT_STATIONS)

    return Config(
        contest_urls=contest_urls,
        feed_url=str(feed_url) if feed_url is not None else None,
        sitemap_url=str(sitemap_url) if sitemap_url is not None else None,
        poll_interval=int(poll_interval),
        user_agent=str(user_agent),
        audio_stream_url=str(audio_stream_url) if audio_stream_url is not None else None,
        audio_enabled=bool(audio_enabled),
        audio_model_size=str(audio_model_size),
        audio_compute_type=str(audio_compute_type),
        audio_clip_seconds=int(audio_clip_seconds),
        audio_mode=str(audio_mode),
        audio_capture_format=str(audio_capture_format),
        audio_gate_enabled=bool(audio_gate_enabled),
        audio_gate_min_confidence=float(audio_gate_min_confidence),
        audio_gate_backend=str(audio_gate_backend),
        summary_mode=str(summary_mode),
        summary_api_base=str(summary_api_base) if summary_api_base is not None else None,
        summary_model=str(summary_model) if summary_model is not None else None,
        x_bearer=env.get("HOTLINE_X_BEARER"),
        ig_token=env.get("HOTLINE_IG_TOKEN"),
        telegram_token=env.get("HOTLINE_TELEGRAM_TOKEN"),
        chat_id=env.get("HOTLINE_CHAT_ID"),
        summary_api_key=env.get("HOTLINE_SUMMARY_API_KEY"),
        stations=stations,
    )


def _as_table(value: object) -> Mapping[str, object]:
    """Return ``value`` if it is a mapping, else an empty mapping."""
    if isinstance(value, Mapping):
        return value
    return {}


def _derive_slug(name: str) -> str:
    """Derive a URL-safe slug from a station ``name``.

    Lowercases, keeps alphanumerics, and drops everything else (spaces,
    punctuation) so ``"ONE FM 91.3"`` becomes ``"onefm913"``.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _parse_stations(value: object) -> list[Station]:
    """Build a list of :class:`Station` from ``[[station]]`` array-of-tables.

    Secrets are never read here (stations carry no secret fields). A missing or
    non-list ``value`` yields an empty list, signalling the caller to fall back
    to the legacy or default station synthesis.
    """
    if not isinstance(value, list):
        return []

    stations: list[Station] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", "")).strip()
        slug = str(entry.get("slug", "")).strip() or _derive_slug(name)
        language = str(entry.get("language", "en")).strip() or "en"

        stream_url = entry.get("stream_url")
        stream_url = str(stream_url) if stream_url else None

        contest_urls_raw = entry.get("contest_urls", [])
        contest_urls = (
            [str(url) for url in contest_urls_raw] if isinstance(contest_urls_raw, list) else []
        )

        sitemap_url = entry.get("sitemap_url")
        sitemap_url = str(sitemap_url) if sitemap_url else None

        feed_url = entry.get("feed_url")
        feed_url = str(feed_url) if feed_url else None

        stations.append(
            Station(
                name=name,
                slug=slug,
                language=language,
                stream_url=stream_url,
                contest_urls=contest_urls,
                sitemap_url=sitemap_url,
                feed_url=feed_url,
                audio_enabled=bool(entry.get("audio_enabled", False)),
            )
        )
    return stations
