# Round 2 review — hotline (from the build supervisor)

Verified against the round-1 output: 46 tests pass, `ruff check` and
`ruff format --check` are clean, `once --dry-run` prints 3 detections on a fresh
database (and 0 on a second run — dedupe works), and a live fetch of
`https://www.melisten.sg/radio/987` succeeds (HTTP 200, 98,619 bytes, robots
allows it).

Fix the following, then re-verify.

## 1. `make install` must not pull torch

`install:` runs `uv venv && uv sync --extra audio`, which downloads
faster-whisper and its torch dependency (gigabytes) for every contributor.
Change it to `uv venv && uv sync --extra dev` and add a separate
`install-audio:` target that uses `--extra audio`.

## 2. Ship a working 987FM source by default

`config.example.toml` has every URL commented out, so out of the box the tool
polls nothing. Ship a working default and document the research:

- Contest/giveaway pages live at `https://www.melisten.sg/radio/<station>/<slug>-<id>`,
  e.g. `https://www.melisten.sg/radio/class95/class-95-giveaway-pickle-beats-3485961`
  (HTTP 200, server-rendered, contains "CLASS 95 Giveaway").
- `https://www.melisten.sg/sitemap.xml` lists 681 URLs and is robots-allowed.
  It contains 14 `/radio/987/` entries today.
- `robots.txt` for melisten: `Disallow: /api/`, `/liveradio/`, `/user/`,
  `/login`. So the live stream at `https://live.melisten.sg/liveradio/987` is
  **not** permitted — the audio source needs a stream you are explicitly allowed
  to capture, or it stays disabled.

Add a `sitemap_url` config option and a `sources/sitemap.py` poller that fetches
the sitemap, filters `<loc>` entries under `/radio/987/` whose slug matches
`giveaway|contest|win|prize|promo`, then fetches and detects those pages. Keep
it robots-aware and polite. Default `config.example.toml` should enable the
sitemap source plus the station page `https://www.melisten.sg/radio/987`.

## 3. One bad URL must not kill `watch`

`poll_web` lets `URLError`/`HTTPError`/timeouts/SSL failures propagate, so a
single 404 stops the whole poll and `hotline watch` dies. Wrap each fetch (and
each social call) in `try/except`, print one warning line to stderr, and
continue. Add tests: inject a fetch that raises, assert the remaining URLs are
still yielded and that `watch` survives.

## 4. Commit `.python-version`

Add a tracked `.python-version` containing `3.13`, and change CI to
`uv sync --python 3.13 --extra dev` instead of running `uv python pin 3.13`
inside CI — that rewrites a tracked file on every run.

## 5. Make the demo re-runnable

Add `--db PATH` to `once` and `watch` (default `hotline.db`). Document in the
README that a second `--dry-run` prints `0 detection(s)` because of the SQLite
dedupe, with the exact command that re-demos from scratch:

    uv run python -m hotline once --dry-run --db /tmp/demo.db

## 6. README additions

A "Target: 987FM" section with the two verified URLs and the robots finding
above; the verified smoke-test output (46 tests, ruff clean, 3 detections from
fixtures, live fetch 200/98 KB); and the uv-only setup path.

## Acceptance

- `uv run pytest` passes including the new resilience tests
- `uv run ruff check .` and `uv run ruff format --check .` clean
- `make install` does not install torch
- `uv run python -m hotline once --dry-run --db /tmp/demo.db` prints 3 detections
  on a fresh file, then 0 on the second run
- Sitemap source is exercised by a test with an injected sitemap document
- Report the diff and the command output
