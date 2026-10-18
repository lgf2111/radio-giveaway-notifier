# Implementation Plan — hotline (987FM radio giveaway notifier)

Greenfield Python 3.13 CLI built directly on `main`. Stdlib-first (urllib, sqlite3,
tomllib, html.parser, urllib.robotparser). Optional `faster-whisper` extra for audio,
imported lazily. Dev tooling: pytest + ruff. No network in tests; all I/O injectable.

## Design decisions (made here, grounded in the spec)

- **Shared types location.** `Item` lives in `hotline/sources/__init__.py` (produced by all
  sources); `Detection` lives in `hotline/detect.py`. Rationale: keeps producers and consumers
  importing from their natural owner and avoids a circular import between sources and detect.
- **HTML parsing.** Use `html.parser.HTMLParser` subclasses (stdlib) over regex for robustness,
  one small extractor that pulls title + visible text blocks. Rationale: stdlib-only, no deps,
  deterministic on the self-contained fixtures.
- **Injection style.** Each source/notify takes an optional callable (`fetch`, `robots_checker`,
  `transcriber`, `sender`) defaulting to the real stdlib implementation; tests pass fakes.
  Rationale: satisfies "no network in tests" without a mocking framework.
- **Scoring model.** Weighted sum of matched positive terms, normalized; any negation term zeros
  the score. Rationale: spec wants negation to suppress; zeroing is the simplest correct behavior.
- **Dedupe hash.** `sha256(normalized_title + "\n" + url + "\n" + normalized_text)` where normalize
  = `strip().lower()` collapsed whitespace. Rationale: stable across re-polls, spec-mandated fields.
- **Offline dry-run.** `once --dry-run` with no reachable config loads bundled `fixtures/*.html`
  + `fixtures/transcript.txt` directly via the web/audio parsers with a file-reading fetcher.
  Rationale: spec requires zero-setup offline detections.

## Tooling: uv is the project/dependency manager (required)

- Manage the venv with `uv venv` (not raw `python -m venv` / `pip install -e .`).
- Declare ALL deps in pyproject.toml: core runtime = stdlib only; `optional-dependencies`
  `audio = ["faster-whisper"]`; dev deps `dev = ["pytest","ruff"]` (exposed so `uv sync` installs them).
- Generate and COMMIT `uv.lock` via `uv lock`.
- Run everything through uv (see commands below).
- uv 0.12.16 confirmed installed at `~/.local/bin/uv`. If absent elsewhere, install via
  `curl -LsSf https://astral.sh/uv/install.sh | sh` or `pip install uv`.
- Plain pip/venv remains a documented fallback in the README, but uv is the primary path.

## Verification commands (project-real, via uv)

- Dev env setup: `uv venv && uv sync --extra audio` (or `uv sync` for core+dev without audio)
- Lockfile: `uv lock` (commit `uv.lock`)
- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Tests: `uv run pytest`
- Offline demo: `uv run python -m hotline once --dry-run`

---

# Items

- [ ] 1. Create `pyproject.toml` with project metadata, extras, scripts, and tool config.
      `[project]` name=`hotline`, `requires-python=">=3.13"`, version, description, MIT license,
      readme. `[project.optional-dependencies]` `audio=["faster-whisper"]`, `dev=["pytest","ruff"]`.
      `[project.scripts] hotline="hotline.cli:main"`. `[tool.ruff]` line-length=100 with sensible
      rule selection (E,F,I,UP,B) and docstring-friendly settings. `[tool.pytest.ini_options]`
      `testpaths=["tests"]`. Build backend `setuptools` with package discovery for `hotline`.
      Also run `uv lock` to generate and commit `uv.lock`.
      Files: pyproject.toml, uv.lock
      Verify: `python3 -c "import tomllib,pathlib; tomllib.loads(pathlib.Path('pyproject.toml').read_text())"` parses; `uv venv && uv sync` succeeds; `uv lock` writes `uv.lock`; `uv run ruff check pyproject.toml` runs clean.

- [ ] 2. Create the package skeleton and shared `Item` type.
      `hotline/__init__.py` (package docstring + `__version__`), `hotline/__main__.py`
      (`from hotline.cli import main; raise SystemExit(main())`), `hotline/sources/__init__.py`
      defining `@dataclass(frozen=True) class Item(title: str, url: str, text: str,
      published: str | None, source: str)` with module + class docstrings.
      Files: hotline/__init__.py, hotline/__main__.py, hotline/sources/__init__.py
      Verify: `python3 -c "from hotline.sources import Item; print(Item('t','u','x',None,'web'))"` prints an Item.

- [ ] 3. Create `hotline/config.py`: typed `Config` dataclass + TOML/env loader.
      `@dataclass Config` fields: `contest_urls: list[str]`, `feed_url: str | None`,
      `poll_interval: int = 45`, `user_agent: str`, `audio_stream_url: str | None`,
      `audio_enabled: bool = False`, `x_bearer: str | None`, `ig_token: str | None`,
      `telegram_token: str | None`, `chat_id: str | None`. `load_config(path: str | Path | None=None,
      env: Mapping[str,str] | None=None) -> Config` reads TOML via `tomllib` (default `config.toml`,
      missing file -> defaults), merges env secrets (`HOTLINE_TELEGRAM_TOKEN`, `HOTLINE_CHAT_ID`,
      `HOTLINE_X_BEARER`, `HOTLINE_IG_TOKEN`), never reads secrets from TOML. Env injectable for tests.
      Files: hotline/config.py
      Verify: `uv run pytest tests/test_config.py` passes.

- [ ] 4. Create `hotline/detect.py`: scoring ruleset + `Detection`.
      `@dataclass(frozen=True) class Detection(text, score: float, matched_terms: list[str], source)`.
      Positive terms (case-insensitive, phrases matched as phrases): "call now", "call in",
      "first caller", "phone lines", "text in", "whatsapp", "win", "tickets", "giveaway", "contest".
      Negation terms: "closed", "no longer", "ended". `score_text(text) -> tuple[float, list[str]]`
      (weighted matches, normalized to 0..1; any negation term -> 0.0, empty matched list on zero).
      `detect(text, source, threshold=0.5) -> Detection | None` (None below threshold). Module docstring
      documents the scoring table.
      Files: hotline/detect.py
      Verify: `uv run pytest tests/test_detect.py` passes.

- [ ] 5. Create `hotline/store.py`: sqlite dedupe store with 7-day TTL.
      `class Store` opened on a db path (supports `":memory:"`), creates schema on init. Methods:
      `item_hash(item) -> str` (sha256 of normalized title+url+text), `seen(hash) -> bool`,
      `record(hash)` (insert first_seen=now if absent), `mark_notified(hash)`,
      `should_notify(item_or_hash) -> bool` (True only if not seen OR seen-but-not-notified-and-fresh),
      `prune(now=None)` removes rows older than 7 days. Schema below.
      Files: hotline/store.py
      Verify: `uv run pytest tests/test_store.py` passes.

- [ ] 6. Create `hotline/sources/web.py`: robots-aware HTML poller yielding `Item`s.
      `fetch_url(url, user_agent) -> str` (stdlib urllib, polite UA) injectable. `robots_allowed(url,
      user_agent, opener=None) -> bool` via `urllib.robotparser`, injectable. `parse_html(html, url,
      source) -> Item` using an `html.parser.HTMLParser` extractor (title tag + visible text).
      `poll_web(config, fetch=fetch_url, robots_checker=robots_allowed) -> Iterator[Item]` iterates
      `contest_urls` + optional `feed_url`, skips robots-disallowed URLs, parses each into an Item.
      Files: hotline/sources/web.py
      Verify: `uv run pytest tests/test_web.py` passes.

- [ ] 7. Create `hotline/sources/social.py`: token-gated X/Instagram poller, no-op otherwise.
      `poll_social(config, fetch=...) -> Iterator[Item]`: if `x_bearer` set, fetch public X endpoint
      and yield Items; if `ig_token` set, fetch public IG endpoint and yield Items; if neither set,
      yield nothing and never raise. `fetch` callable injectable. Public endpoints behind helper
      functions so tests inject responses.
      Files: hotline/sources/social.py
      Verify: `uv run pytest tests/test_social.py` passes.

- [ ] 8. Create `hotline/sources/audio.py`: feature-flagged lazy transcription windows.
      `iter_windows(samples/stream, window_seconds=10) -> Iterator[window]` pure/testable windowing.
      `transcribe_stream(config, transcriber=None) -> Iterator[Item]`: if `audio_enabled` False ->
      log once, yield nothing. Else lazily `from faster_whisper import WhisperModel` inside the
      function; on `ImportError` log once + yield nothing. With a transcriber (real or injected fake),
      transcribe each 10s window and yield Items (source="audio"). Injected transcriber + a windowing
      function reading `fixtures/transcript.txt` make it unit-testable with no audio/network.
      Files: hotline/sources/audio.py
      Verify: `uv run pytest tests/test_audio.py` passes.

- [ ] 9. Create `hotline/notify.py`: Telegram sendMessage with dry-run + injectable POST.
      `format_alert(detection, item) -> str` (title, url, matched terms, score). `send_telegram(text,
      token, chat_id, post=...) -> dict` builds Bot API URL/payload with urllib. `notify(detection,
      item, config, dry_run=False, post=...) -> str`: when `dry_run` format+print+return WITHOUT
      calling `post`; else call injectable `post` with correct URL/payload. Depends on detect.Detection
      (item 4) and sources.Item (item 2).
      Files: hotline/notify.py
      Verify: `uv run pytest tests/test_notify.py` passes.

- [ ] 10. Create `hotline/cli.py`: argparse subcommands wiring all modules.
      `build_parser()`, `cmd_once(args, config)`, `cmd_watch(args, config)`, `cmd_test_alert(args,
      config)`, `main(argv=None) -> int`. Subcommands: `once` (flags `--dry-run`, `--source`
      repeatable choice {web,social,audio}, `--config`), `watch` (adds `--interval` default 45),
      `test-alert` (respects `--dry-run`). `once`/`watch`: poll selected sources -> detect -> dedupe
      via Store -> notify. `once --dry-run` with no reachable config loads bundled `fixtures/` directly
      and prints detections. Depends on items 2–9.
      Files: hotline/cli.py
      Verify: `uv run pytest tests/test_cli.py` passes AND `uv run python -m hotline once --dry-run` exits 0 and prints detections.

- [ ] 11. Create the 4 fixtures (self-contained, no external assets).
      `fixtures/contest_page.html` (active: "call now", "first caller", "win tickets"),
      `fixtures/giveaway_page.html` ("text in", "whatsapp", "giveaway", "contest"),
      `fixtures/closed_page.html` (negation: "closed", "no longer", "ended"),
      `fixtures/transcript.txt` (~10s callout: "call now to win tickets, phone lines are open").
      Files: fixtures/contest_page.html, fixtures/giveaway_page.html, fixtures/closed_page.html, fixtures/transcript.txt
      Verify: `uv run pytest tests/test_web.py tests/test_cli.py` (which parse these) pass.

- [ ] 12. Create the test suite + `tests/conftest.py` shared helpers.
      `conftest.py`: `fixtures_dir()` path helper, `read_fixture(name)`, fake fetcher/robots/sender/
      transcriber factories. Test modules enumerated in "Test cases" below. No network anywhere.
      Files: tests/__init__.py, tests/conftest.py, tests/test_config.py, tests/test_detect.py, tests/test_store.py, tests/test_web.py, tests/test_social.py, tests/test_audio.py, tests/test_notify.py, tests/test_cli.py
      Verify: `uv run pytest` — entire suite passes.

- [ ] 13. Create docs + meta files (uv-first).
      `config.example.toml` (documented: real 987FM URLs as example comments + how to use fixtures;
      interval, user_agent, audio flag/stream url, feed url; NO secrets). `.env.example` (four
      `HOTLINE_` vars empty + comments). `README.md` (overview; **uv-first setup**: install uv,
      `uv venv`, `uv sync --extra audio` for optional audio, and the `uv run ...` commands as the
      primary workflow, with a brief note that plain `pip install -e ".[audio]"` / venv still works;
      env+TOML config; all three subcommands; offline `uv run python -m hotline once --dry-run` demo;
      prominent LEGAL/ToS/ETHICS section covering robots.txt, Mediacorp/987FM + X/IG ToS, audio
      capture/transcription copyright opt-in, rate-limit guidance 45s default/back off, personal use;
      rate limits + polite User-Agent). `Makefile` targets shell out to uv:
      `install: uv venv && uv sync --extra audio`, `test: uv run pytest`, `lint: uv run ruff check .`,
      `fmt: uv run ruff format .`, `run: uv run python -m hotline once --dry-run`, `lock: uv lock`,
      `clean` (remove .venv, caches, *.db). `.github/workflows/ci.yml` (push/PR, Python 3.13,
      `astral-sh/setup-uv` action, `uv sync`, then `uv run ruff check .` + `uv run ruff format --check .`
      + `uv run pytest`; audio extra NOT required for CI).
      Files: config.example.toml, .env.example, README.md, Makefile, .github/workflows/ci.yml
      Verify: `python3 -c "import tomllib,pathlib; tomllib.loads(pathlib.Path('config.example.toml').read_text())"` parses; `make run` prints detections.

- [ ] 14. Full integration pass: lint, format, tests, offline demo all green.
      Files: (none — verification only)
      Verify: `uv run ruff check .` clean; `uv run ruff format --check .` clean; `uv run pytest` all pass; `uv run python -m hotline once --dry-run` exits 0 with detections printed.

---

## sqlite schema (item 5)

```sql
CREATE TABLE IF NOT EXISTS seen_items (
    hash        TEXT PRIMARY KEY,
    first_seen  REAL NOT NULL,   -- epoch seconds
    notified    INTEGER NOT NULL DEFAULT 0  -- 0/1 flag
);
CREATE INDEX IF NOT EXISTS idx_seen_items_first_seen ON seen_items(first_seen);
```
TTL = 7 days (604800 s). `prune(now)` deletes rows where `first_seen < now - 604800`.
`should_notify`: returns True when hash absent, or present with `notified=0` and not expired.

## Scoring ruleset (item 4)

| term           | weight | kind     |
|----------------|--------|----------|
| call now       | 3      | phrase   |
| first caller   | 3      | phrase   |
| phone lines    | 2      | phrase   |
| call in        | 2      | phrase   |
| text in        | 2      | phrase   |
| whatsapp       | 1      | keyword  |
| giveaway       | 2      | keyword  |
| contest        | 2      | keyword  |
| win            | 1      | keyword  |
| tickets        | 1      | keyword  |

- Matching is case-insensitive; multi-word entries match as contiguous phrases.
- Negation terms ("closed", "no longer", "ended") present anywhere -> score forced to `0.0`,
  `matched_terms = []`.
- `score_text` normalizes raw weight sum by a cap (e.g. `min(1.0, raw / 6.0)`) so a single strong
  phrase like "call now" clears the default threshold 0.5; `detect` returns None below threshold.

## Fixture content requirements (item 11)

- `contest_page.html`: `<title>` + body containing "call now", "first caller", "win tickets" ->
  high score, detection fires.
- `giveaway_page.html`: contains "text in", "whatsapp", "giveaway", "contest" -> detection fires.
- `closed_page.html`: active-looking terms PLUS "closed"/"no longer"/"ended" -> negation zeros score.
- `transcript.txt`: ~10s line "call now to win tickets, phone lines are open" -> audio detection fires.

## Test cases (item 12)

- **test_detect**: positive text scores above threshold; negation suppresses to 0/None;
  `matched_terms` exact for a known string; case-insensitivity ("CALL NOW"); phrase vs keyword.
- **test_web**: `parse_html` on each of the 3 fixtures yields a correct `Item`; `poll_web` with an
  injected fetcher returns Items for all allowed URLs; an injected robots checker that disallows one
  URL causes that URL to be skipped.
- **test_store**: seen/record/mark_notified/should_notify flow; same hash not notified twice;
  TTL prune removes an entry with a back-dated `first_seen`; `:memory:` db works.
- **test_notify**: dry-run returns formatted text and does NOT call injected sender; real path calls
  injected sender once with correct URL (contains token) + payload (chat_id, text).
- **test_config**: defaults when no TOML; TOML values loaded; env secrets merged; secrets never from
  TOML; interval default 45.
- **test_social**: no tokens -> `poll_social` yields nothing, no exception; with injected fetch +
  token -> yields Items.
- **test_audio**: windowing splits a transcript into 10s windows; fake transcriber yields Items;
  `audio_enabled=False` -> yields nothing; simulated `ImportError` on faster_whisper -> graceful
  no-op (no raise).
- **test_cli**: `main(["once","--dry-run"])` returns 0 and produces detections against fixtures;
  `--source web` restricts sources; unknown subcommand returns non-zero.
- **conftest**: `fixtures_dir`, `read_fixture`, fake fetcher/robots/sender/transcriber factories.

## Deferred / assumptions

- Exact raw-weight normalization constant chosen by implementer so default threshold 0.5 behaves per
  the fixture expectations above; documented in `detect.py`.
- Real 987FM URLs are placeholders/example comments only (ToS/robots respected); no live calls shipped.
