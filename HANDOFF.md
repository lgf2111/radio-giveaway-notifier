# hotline — session handoff

> Written to preserve the full context of the build/setup session before the
> Kiro chat window (and its in-memory context) is closed. The project was moved
> from `~/Documents/Github/radio-giveaway-notifier` to **`~/hotline`** during
> this session (see "Why the repo moved" below). Open `~/hotline` as the Kiro
> workspace from now on — the old path no longer exists.

## What this project is

A Python 3.13 CLI (`hotline`) that watches Singapore radio stations for on-air
giveaways/contests and pushes a **Telegram alert** (summary + "what to do" +
transcript + a **voice note** of the audio) within seconds. It runs 24/7 as a
macOS `launchd` background service on this MacBook.

Pipeline per poll cycle: pull each station's live stream (ffmpeg) → a cheap
local **music-vs-speech gate** (stdlib DSP, skips songs) → transcribe speech
with **faster-whisper** → **detect** giveaway phrases (English + Mandarin) →
dedupe (sqlite, 7-day TTL) → **notify** via Telegram with a voice clip.

- Repo: https://github.com/lgf2111/radio-giveaway-notifier (branch `main`)
- Everything is committed and pushed to `origin/main`. It's a **solo project** —
  commit straight to `main`, no PRs/branches.
- Stack: stdlib-first (urllib, sqlite3, tomllib, xml.etree, concurrent.futures),
  `uv` for env/deps, `pytest` + `ruff`. Only optional 3rd-party dep is
  `faster-whisper` (the `[audio]` extra). `ffmpeg` is a required SYSTEM package.
- Tests: **131 passing**, ruff clean, offline-only (no network/ffmpeg/whisper in
  tests — everything injectable + fixtures).

## Current running state (as of this session)

- The **launchd LaunchAgent** `com.hotline.watch` is INSTALLED and RUNNING.
  - Plist: `~/Library/LaunchAgents/com.hotline.watch.plist`
  - It runs `~/hotline/deploy/macos/hotline-run.sh` which execs
    `uv run --project ~/hotline --extra audio python -m hotline -v watch
    --config ~/.config/hotline/config.toml --db ~/.config/hotline/hotline.db`
  - Logs: `~/Library/Logs/hotline/hotline.out.log` (poll cycles) and
    `hotline.err.log` (gate decisions, transcripts, warnings).
  - Config: `~/.config/hotline/config.toml` (8 stations, audio enabled,
    `mode = "continuous"`, `clip_seconds = 30`, `interval = 60`).
  - Secrets: `~/.config/hotline/hotline.env` (chmod 600).

### ⚠️ THE ONE REMAINING ACTION FOR THE USER

`~/.config/hotline/hotline.env` is still **EMPTY** — so the service captures &
transcribes but **cannot send Telegram alerts yet**. Fill it in:

```bash
# the working token/chat-id are already in ~/hotline/.env (from a verified test)
grep -E '^HOTLINE_(TELEGRAM_TOKEN|CHAT_ID)=' ~/hotline/.env >> ~/.config/hotline/hotline.env
# edit the file so each key appears once with a real value, then:
chmod 600 ~/.config/hotline/hotline.env
launchctl kickstart -k gui/$(id -u)/com.hotline.watch
```

Verify Telegram delivery (text + voice) end-to-end any time:
```bash
cd ~/hotline && uv run --extra audio python scripts/verify_voice_alert.py
```

## The 8 stations (all stream URLs verified live this session)

| Station       | slug     | lang       | stream |
|---------------|----------|------------|--------|
| CLASS 95      | class95  | en         | streamtheworld CLASS95_PREM.aac |
| 987FM         | 987fm    | en         | streamtheworld 987FM_PREM.aac |
| GOLD 905      | gold905  | en         | streamtheworld GOLD905_PREM.aac |
| Kiss92        | kiss92   | en         | streamtheworld KISS_92AAC.aac |
| ONE FM 91.3   | onefm    | en         | streamtheworld ONE_FM_913AAC.aac |
| YES 933       | yes933   | zh         | streamtheworld YES933_PREM.aac |
| LOVE 972      | love972  | zh         | streamtheworld LOVE972FM_PREM.aac |
| 88.3JIA       | jia883   | bilingual  | streamtheworld 883JIA_SC (MP3) |

(Exact URLs are in `~/.config/hotline/config.toml` and `config.example.toml`.)
POWER 98 and Symphony 924 were deliberately EXCLUDED (app-based giveaways /
classical format). Transcription is language-aware: en→"en", zh→"zh",
bilingual→auto-detect. Detection has both English and Mandarin phrase/keyword
rulesets with negation handling.

## Why the repo moved (important)

macOS TCC (privacy) blocks a launchd background agent from executing scripts in
`~/Documents`. Running the service there failed with "Operation not permitted".
Fix: the whole repo was moved to **`~/hotline`** (outside the protected dir).
Git history, remote, and the venv all came along intact. **Update any editor
tabs/aliases/bookmarks** that still point at the old `~/Documents/...` path.

## Performance tuning done (for 24/7 on a laptop)

- Station captures run **concurrently** (ThreadPoolExecutor); transcription
  stays **sequential/gated** so Whisper never runs in parallel. This cut a full
  8-station pass from ~294s (serial) to ~40s (concurrent) — measured.
- `clip_seconds = 30`, `interval = 60` → a brief concurrent burst then idle,
  with Whisper only firing on speech clips. Config knob
  `audio_max_parallel_captures` (default 8) caps capture concurrency.
- The music gate skips songs at confidence ≥ `audio_gate_min_confidence` (0.6);
  it is SPEECH-BIASED and fails open (transcribes if unsure / if ffmpeg can't
  decode) so a real callout is never skipped.

## Bugs found & fixed during live testing (all on main)

1. `--audio` didn't force capture without a prior web detection — fixed.
2. **Transcription crashed** on every real clip: faster-whisper called
   `av.open(..., metadata_errors=...)` but PyAV 19 removed that kwarg
   (`TypeError`). Fixed by decoding clips to PCM via ffmpeg and passing a numpy
   array to Whisper, bypassing PyAV entirely (`hotline/sources/audio.py`).
3. `.env` wasn't auto-loaded — `load_config` now reads a `.env` file (stdlib
   parser) layered UNDER real env vars.
4. launchd deploy gotchas: TCC (moved repo), `uv` not on PATH (added
   `~/.local/bin`), unsubstituted `__INSTALL_DIR__` (wrapper is now
   self-locating), buffered logs (`PYTHONUNBUFFERED=1` + `-v`).
5. `watch` ignored `config.poll_interval` (argparse default won) — fixed so
   config's interval is honored.

## Known follow-ups / not yet done (candidates for next session)

- **Service vs dev share one `.venv`** and fight over it: the running service
  does `uv run --extra audio` which re-syncs the venv, so `uv run pytest` in a
  dev shell intermittently can't find pytest. Recommend isolating the service's
  environment (e.g. a dedicated venv or `uv run` cache) from dev. Workaround for
  now: run tests with `uv run --extra dev python -m pytest -q`, ideally while the
  service is stopped (`launchctl bootout gui/$(id -u)/com.hotline.watch`).
- **No real giveaway has fired yet** — the full detect→alert path on real
  Mandarin/English on-air callouts is only proven via fixtures + a forced-alert
  test. Real accuracy + the gate threshold should be reviewed after some live
  airtime. If it ever skips a callout, lower the gate skip threshold.
- Per-station **contest WEB page URLs** beyond 987FM are placeholders (only the
  audio path is wired for the other 7). Fill in if you want web/sitemap
  detection per station.
- Oracle Cloud deploy assets exist under `deploy/` as a documented ALTERNATIVE;
  macOS launchd is the chosen primary.

## Useful commands (run from ~/hotline)

```bash
# one offline demo (no network/ffmpeg): prints 3 fixture detections
uv run python -m hotline once --dry-run
# one real audio capture of a station with verbose logs
uv run --extra audio python -m hotline -vv once --audio --station 987fm
# tests / lint
uv run --extra dev python -m pytest -q
uv run ruff check . && uv run ruff format --check .
# service control
launchctl print gui/$(id -u)/com.hotline.watch        # status
launchctl kickstart -k gui/$(id -u)/com.hotline.watch # restart
launchctl bootout   gui/$(id -u)/com.hotline.watch    # stop
bash deploy/macos/uninstall.sh                         # full uninstall
tail -f ~/Library/Logs/hotline/hotline.err.log         # watch it work
```

## How to continue in a fresh Kiro session

1. In Kiro, open the folder **`~/hotline`** as the workspace (File → Open Folder,
   or "Open Folder" from the welcome screen). The old
   `~/Documents/Github/radio-giveaway-notifier` path is gone.
2. Point the new chat at this file (`#HANDOFF.md`) so the agent picks up where
   this session left off.
3. First thing to check: is `~/.config/hotline/hotline.env` populated and is the
   agent sending alerts? (See "THE ONE REMAINING ACTION" above.)
