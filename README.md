# hotline

A stdlib-first Python 3.13 CLI that watches **987FM** (Mediacorp, Singapore)
for radio giveaways and pushes a **Telegram** alert within seconds. It catches
"call now / text in" contest segments, dedupes them, and notifies once.

- **Sources:** public contest/giveaway web pages (+ optional feed), optional
  public X / Instagram endpoints (only when tokens are set), and an optional
  feature-flagged audio source that transcribes the live stream locally.
- **Detection:** an explicit phrase + keyword ruleset with negation handling.
- **Dedupe:** SQLite with a 7-day TTL so the same contest never alerts twice.
- **Stdlib-first:** `urllib`, `sqlite3`, `tomllib`, `html.parser`. The only
  optional third-party dependency is `faster-whisper` for audio.

## Quick start (uv)

[uv](https://docs.astral.sh/uv/) is the project and dependency manager.

```bash
# Install uv if you don't have it:
#   curl -LsSf https://astral.sh/uv/install.sh | sh

# Create the venv and install core + dev (+ optional audio) dependencies:
uv venv
uv sync --extra audio      # or `uv sync --extra dev` for core + tooling only

# Try it offline with zero config -- prints detections from bundled fixtures:
uv run python -m hotline once --dry-run
```

The `install` make target wraps the two setup steps: `make install`.

### pip fallback

uv is the primary workflow, but a plain virtualenv works too:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[audio]"   # or ".[dev]" for tooling without audio
python -m hotline once --dry-run
```

## Configuration

Non-secret settings live in a TOML file; secrets come only from environment
variables (never from TOML, so they can't be committed with a config).

1. Copy the examples:

   ```bash
   cp config.example.toml config.toml
   cp .env.example .env
   ```

2. Edit `config.toml` (contest URLs, poll interval, User-Agent, optional feed
   and audio stream).

3. Set secrets in the environment (see `.env.example`):

   | Variable                 | Purpose                                   |
   |--------------------------|-------------------------------------------|
   | `HOTLINE_TELEGRAM_TOKEN` | Telegram bot token (required to send)     |
   | `HOTLINE_CHAT_ID`        | Destination chat id (required to send)    |
   | `HOTLINE_X_BEARER`       | X API bearer (optional; enables X source) |
   | `HOTLINE_IG_TOKEN`       | Instagram token (optional; enables IG)    |

   ```bash
   set -a; source .env; set +a
   ```

## Usage

```bash
# Poll every source once, detect, dedupe, and notify:
uv run python -m hotline once --config config.toml

# Dry run: print detections instead of sending Telegram messages:
uv run python -m hotline once --dry-run

# Restrict to specific sources (repeatable: web, social, audio):
uv run python -m hotline once --source web --source social

# Watch continuously, polling on an interval (default 45s):
uv run python -m hotline watch --interval 45 --config config.toml

# Send (or dry-run) a sample alert to verify Telegram delivery:
uv run python -m hotline test-alert
uv run python -m hotline test-alert --dry-run
```

Exit code is `0` on success and non-zero on bad usage.

## Development

```bash
make lint    # uv run ruff check .
make fmt     # uv run ruff format .
make test    # uv run pytest
make run     # uv run python -m hotline once --dry-run
make lock    # uv lock
make clean   # remove .venv, caches, *.db
```

Tests never touch the network: every fetch/robots/sender/transcriber is an
injectable callable and the suite runs against the `fixtures/` directory.

## Rate limits and the polite User-Agent

- The default poll interval is **45 seconds**. Do not lower it aggressively;
  polling too fast can get you blocked and is unfair to the source.
- Every real HTTP request sends a **configurable, identifiable User-Agent**
  (set `user_agent` in `config.toml`). Include a contact URL so site owners can
  reach you instead of silently blocking you.
- `watch` mode is intended for personal, low-volume use. If you see errors or
  `429`/`503` responses, **back off** (increase the interval).

## ⚠️ LEGAL / ToS / ETHICS

Read this before pointing hotline at any real service. hotline is for
**personal, educational use** and you are responsible for how you use it.

- **robots.txt is respected.** The web source checks `robots.txt` and skips any
  URL it disallows before fetching. Do not work around this.
- **Terms of Service.** Mediacorp / 987FM and X / Instagram each have Terms of
  Service that may restrict automated access, scraping, or redistribution.
  Review and comply with them. The example URLs in `config.example.toml` are
  commented-out placeholders -- nothing is polled until you opt in.
- **Audio capture and transcription.** The audio source is **off by default**
  and gated behind the `audio` extra. Radio streams are copyrighted works.
  Capturing and transcribing a stream may be restricted by copyright and by the
  stream provider's terms. Only enable audio if you have the right to do so;
  enabling it is an explicit opt-in.
- **API tokens.** The social source only runs when you supply your own X /
  Instagram tokens and use them within those platforms' developer terms and
  rate limits.
- **No secrets in the repo.** Tokens and chat ids are read from environment
  variables only; keep them out of `config.toml` and version control.
- **Be a good citizen.** Keep polling gentle, identify yourself via the
  User-Agent, back off on errors, and don't redistribute scraped content.

## License

MIT © 2026 lgf2111. See [LICENSE](LICENSE).
