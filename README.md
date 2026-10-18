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
- **Rich audio alerts:** when enabled, a detection triggers a short stream clip
  that is transcribed on-device, summarised into a headline + the action to
  take, and delivered to Telegram as a text message plus a voice note.

> **System dependency:** the audio pipeline shells out to **ffmpeg** to pull
> and clip the stream. ffmpeg is a *system* package (install it with your OS
> package manager — `brew install ffmpeg` on macOS, `apt install ffmpeg` on
> Debian/Ubuntu), **not** a pip dependency. Without ffmpeg on `PATH` the audio
> source degrades to a no-op and text alerts keep working.

> **Where it runs:** hotline is cross-platform. The recommended deploy is an
> always-on **macOS** machine via a launchd LaunchAgent (see
> [Run 24/7 on macOS](#run-247-on-macos-recommended)); running on an Oracle
> Cloud Always Free Linux VM is documented as an alternative.

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

### Audio pipeline options (`[audio]` / `[summary]`)

The optional audio pipeline is **off by default**. When enabled, a web/sitemap
detection triggers a short clip capture → on-device transcription → summary →
rich Telegram alert. Configure it in `config.toml` (see `config.example.toml`
for the shipped defaults). Requires the `audio` extra (`uv sync --extra audio`)
and **ffmpeg** on `PATH`.

`[audio]` table:

| Key            | Default                                               | Meaning                                                               |
|----------------|-------------------------------------------------------|-----------------------------------------------------------------------|
| `enabled`      | `false`                                               | Master switch. `--audio` on the CLI force-enables it for one run.     |
| `stream_url`   | `https://22903.live.streamtheworld.com/987FM_PREM.aac`| Verified live 987FM stream (streamtheworld AAC+, HTTP 200).           |
| `mode`         | `event`                                               | `event` clips only when a web/sitemap detection fires; else `continuous`. |
| `model_size`   | `base`                                                | faster-whisper model (`tiny`, `base`, `small`, …). `base` suits a free-tier CPU. |
| `compute_type` | `int8`                                                | faster-whisper compute type. `int8` keeps CPU/memory low.             |
| `clip_seconds` | `45`                                                  | Seconds of audio captured per clip (transcribed + sent as the voice note). |
| `gate_enabled` | `true`                                                | Run the music-vs-speech gate before transcription (skip confident music). |
| `gate_min_confidence` | `0.6`                                          | Only SKIP transcription when the gate is at least this confident it is music. |
| `gate_backend` | `builtin`                                             | Classifier backend. `builtin` is the stdlib DSP gate; `silero` is reserved/not implemented (falls back to builtin). |

#### Music vs. speech gate

Transcription is the one expensive step, so a cheap local gate runs on every
captured clip **before** Whisper and skips transcribing songs. The classifier is
pure Python stdlib (short-time RMS energy, zero-crossing rate, and spectral
flatness computed over a small pure-Python radix-2 FFT) — **no numpy, no extra
pip deps**. ffmpeg is used only to decode the clip to PCM and is injectable.

The gate is the main lever keeping Whisper cost low, and it is deliberately
conservative:

- **Speech-biased.** It returns *music* only when the evidence is strong and
  steady; anything ambiguous classifies as speech, so a giveaway callout is
  never skipped.
- **Fails open.** If ffmpeg is missing or decoding fails, the clip is treated as
  speech and transcribed anyway.

Transcription is skipped only when the gate decides *music* **and** its
confidence meets `gate_min_confidence`. Configure it with `gate_enabled` and
`gate_min_confidence` in `[audio]`. The `gate_backend` key is reserved: `silero`
is not implemented and falls back to the builtin gate with a logged warning,
adding no dependency.

`[summary]` table:

| Key                       | Default   | Meaning                                                                         |
|---------------------------|-----------|---------------------------------------------------------------------------------|
| `mode`                    | `rules`   | `rules` builds the summary locally (no network/API key); `llm` calls an API.    |
| `api_base`                | *(unset)* | OpenAI-compatible base URL, used only when `mode = "llm"`.                       |
| `model`                   | *(unset)* | Chat model name, used only when `mode = "llm"`.                                  |
| `HOTLINE_SUMMARY_API_KEY` | *(unset)* | API key for `mode = "llm"`. **Env var only** (never in TOML). Falls back to rules on any error. |

## Usage

```bash
# Poll every source once, detect, dedupe, and notify:
uv run python -m hotline once --config config.toml

# Dry run: print detections instead of sending Telegram messages:
uv run python -m hotline once --dry-run

# Restrict to specific sources (repeatable: web, sitemap, social, audio):
uv run python -m hotline once --source web --source sitemap

# Force the audio pipeline on for this run (even if [audio] enabled = false).
# With --dry-run this demonstrates a rich alert fully OFFLINE from the bundled
# fixtures (no ffmpeg, no whisper, no network): it prints the summary headline,
# the suggested action, the transcript, and "would attach <clip>".
uv run python -m hotline once --dry-run --audio

# Watch continuously, polling on an interval (default 45s):
uv run python -m hotline watch --interval 45 --config config.toml

# Use a specific dedupe database (default: hotline.db):
uv run python -m hotline once --config config.toml --db hotline.db

# Send (or dry-run) a sample alert to verify Telegram delivery:
uv run python -m hotline test-alert
uv run python -m hotline test-alert --dry-run
```

Exit code is `0` on success and non-zero on bad usage.

### Dedupe and the `--db` flag

Both `once` and `watch` accept `--db PATH` (default `hotline.db`) to choose the
SQLite database that backs the 7-day dedupe. Because a contest is only alerted
once, a second run against the same on-disk database prints
`0 detection(s)` — the dedupe has already seen everything. Re-demo from scratch
with a throwaway database:

```bash
uv run python -m hotline once --dry-run --db /tmp/demo.db   # prints 3 detections
uv run python -m hotline once --dry-run --db /tmp/demo.db   # prints 0 (deduped)
```

Plain `--dry-run` with **no** `--db` uses an in-memory store instead, so the
zero-setup offline demo stays repeatable and prints 3 detections every time:

```bash
uv run python -m hotline once --dry-run   # always prints 3 detections
```

## Target: 987FM

These are the verified research findings behind the shipped defaults in
`config.example.toml`:

- **Contest/giveaway pages** live at
  `https://www.melisten.sg/radio/<station>/<slug>-<id>`. The verified example
  `https://www.melisten.sg/radio/class95/class-95-giveaway-pickle-beats-3485961`
  returns HTTP 200 and is server-rendered (the giveaway text is in the HTML, no
  JavaScript needed).
- **Sitemap discovery.** `https://www.melisten.sg/sitemap.xml` is
  robots-allowed and lists 681 URLs, 14 of them under `/radio/987/`. The
  `sitemap` source fetches it and keeps `<loc>` entries whose path is under
  `/radio/987/` and whose slug matches `giveaway|contest|win|prize|promo`
  (case-insensitive), then fetches and detects those pages.
- **The 987FM station page** `https://www.melisten.sg/radio/987` is the shipped
  default in `contest_urls`.

### ⚠️ robots.txt and the audio source

melisten's `robots.txt` disallows `/api/`, `/liveradio/`, `/user/`, and
`/login`. The live stream endpoint `https://live.melisten.sg/liveradio/987`
sits under a disallowed path, so the audio source **must not** point at it. The
audio source stays disabled unless you supply a stream you are explicitly
permitted to capture (see the LEGAL / ToS / ETHICS section).

### Smoke test

The verified state after this revision:

- `uv run pytest` → **87 passed**.
- `uv run ruff check .` → clean.
- `uv run ruff format --check .` → clean.
- `uv run python -m hotline once --dry-run` → 3 fixture detections offline.
- `uv run python -m hotline once --dry-run --audio` → the same 3 detections
  plus a rich audio alert built from the bundled fixtures (no ffmpeg/network).
- `make install` uses `uv sync --extra dev` and does **not** install
  `faster-whisper`/`torch` (that is the opt-in `make install-audio` target).
- The 987FM station page returned HTTP 200 with ~98,619 bytes on a live fetch
  (the user's reported finding; the test suite itself never touches the
  network).

## Run 24/7 on macOS (recommended)

The simplest way to run hotline forever is on a Mac that is always on — a
launchd **LaunchAgent** starts `hotline watch` at login and keeps it alive.
Ready-made assets live in [`deploy/macos/`](deploy/macos/): the LaunchAgent
plist (`com.hotline.watch.plist`), a wrapper script (`hotline-run.sh`), a
macOS env template (`hotline.env.example`), and `install.sh` / `uninstall.sh`.

> A **LaunchAgent** (loaded into `gui/$(id -u)`) is used, **not** a root
> LaunchDaemon, because the watcher needs the logged-in user's network/audio
> context and Homebrew (`/opt/homebrew`) on `PATH`. A LaunchDaemon runs
> pre-login with a bare environment and does not fit. For a headless,
> always-on Mac this means the machine must stay **logged into your user
> session** (enable automatic login).

### Quick path (install script)

From the cloned repo:

```bash
brew install ffmpeg          # system dependency for audio (if not already)
uv sync --extra audio        # install core + the audio extra
bash deploy/macos/install.sh # idempotent: safe to re-run
```

`install.sh` checks `brew`/`ffmpeg`/`uv`, creates `~/Library/Logs/hotline` and
`~/.config/hotline`, seeds `config.toml` + `hotline.env` from the examples
(only if they do not already exist — it never overwrites your settings),
substitutes the real repo path/user into the plist, copies it to
`~/Library/LaunchAgents/com.hotline.watch.plist`, and loads it with
`launchctl`. Then edit the two seeded files (below) and reload.

### Manual path

```bash
# 1. System dependency + Python deps.
brew install ffmpeg
uv sync --extra audio

# 2. Non-secret config: enable audio, keep the 987FM stream url.
mkdir -p ~/.config/hotline ~/Library/Logs/hotline
cp config.example.toml ~/.config/hotline/config.toml
#   edit ~/.config/hotline/config.toml:
#     [audio]
#     enabled = true
#     stream_url = "https://22903.live.streamtheworld.com/987FM_PREM.aac"

# 3. Secrets: real token + chat id, locked down.
cp deploy/macos/hotline.env.example ~/.config/hotline/hotline.env
chmod 600 ~/.config/hotline/hotline.env
#   edit ~/.config/hotline/hotline.env: set HOTLINE_TELEGRAM_TOKEN + HOTLINE_CHAT_ID

# 4. Install the LaunchAgent. Substitute the two placeholders first:
#      __INSTALL_DIR__ -> the absolute path to this repo
#      __USER__        -> your short username ($(id -u -n))
sed -e "s#__INSTALL_DIR__#$(pwd)#g" -e "s#__USER__#$(id -u -n)#g" \
    deploy/macos/com.hotline.watch.plist \
    > ~/Library/LaunchAgents/com.hotline.watch.plist

# 5. Load it (RunAtLoad starts it immediately).
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hotline.watch.plist
#   Older macOS equivalent: launchctl load -w ~/Library/LaunchAgents/com.hotline.watch.plist
```

### Verify and operate

```bash
# Confirm the agent is loaded and see its state/last exit code:
launchctl print gui/$(id -u)/com.hotline.watch

# Follow the logs (stdout + stderr land under ~/Library/Logs/hotline/):
tail -f ~/Library/Logs/hotline/hotline.err.log

# After editing config/env, restart the agent to pick up changes:
launchctl kickstart -k gui/$(id -u)/com.hotline.watch

# Uninstall (stops + removes the agent; keeps config/logs, --purge to delete):
bash deploy/macos/uninstall.sh
```

The wrapper (`hotline-run.sh`) sources `~/.config/hotline/hotline.env` so
secrets never touch the plist, puts Homebrew on `PATH`, then execs
`uv run --project <repo> python -m hotline watch`. If the env file is missing
it warns and continues, but text/audio alerts need the Telegram token + chat
id to be set.

### Keeping the watcher alive (sleep/standby)

You have two choices; pick based on how aggressively your Mac sleeps:

- **(a) Default low-impact path — launchd `KeepAlive` + wake-resume.** The
  plist sets `KeepAlive = { Crashed = true, SuccessfulExit = false }`, so the
  watcher restarts if it crashes but stays down on a clean exit or manual
  unload. `ProcessType = Background` tells macOS this is a long-running service
  and mitigates **App Nap** throttling. When the Mac sleeps the process pauses
  and simply resumes on wake — fine if the Mac is awake most of the time (for
  example, an always-on machine running other agents). No global settings
  change.
- **(b) True 24/7 — opt in to staying awake.** If the Mac sleeps on idle and
  you want the watcher polling through it, pick one:
  - Uncomment the `caffeinate -i` line in `deploy/macos/hotline-run.sh` so the
    watcher asserts "no idle sleep" only while it runs (scoped to this process).
  - System Settings → **Battery / Energy** → enable **"Prevent automatic
    sleeping when the display is off"** (on desktops / when plugged in).
  - `pmset` can adjust sleep timers (e.g. `sudo pmset -c sleep 0` on AC).

Do **not** force-disable sleep globally as a default — keep `caffeinate`
opt-in and prefer the scoped options above so you are not changing
system-wide power behaviour just to run one watcher.

## Alternative: Oracle Cloud Always Free

If you would rather not keep a Mac on, hotline is also light enough to run
forever on an **Oracle Cloud Infrastructure (OCI) Always Free** Ampere A1
(ARM64) VM — the audio pipeline included. Ready-made deploy artifacts live in
[`deploy/`](deploy/): a `Dockerfile`, a systemd unit (`hotline.service`), and
an env template (`hotline.env.example`).

### 1. Create an Always-Free Ampere A1 (ARM64) VM

- In the OCI console create a Compute instance using the **Ampere A1 (Arm)**
  shape (`VM.Standard.A1.Flex`), image **Ubuntu** or **Oracle Linux**.
- **Free-tier sizing (important):** beginning **2026-06-15**, Oracle reduced the
  Always-Free Ampere A1 allowance to **2 OCPU / 12 GB of memory total across the
  whole tenancy**, down from the old 4 OCPU / 24 GB. ([OCI Free Tier docs](https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm)).
  hotline fits comfortably inside this: run the default **event** mode with the
  small **`base`** whisper model (`compute_type = "int8"`), and keep the whole
  A1 footprint under 2 OCPU / 12 GB so the instance is not disabled. A single
  1 OCPU / 4–6 GB A1 VM is plenty.
- *Content was rephrased for compliance with licensing restrictions.*

### 2. Networking: outbound-only, no ingress

hotline is **outbound-only** — it polls the melisten web pages, pulls the audio
stream, and calls the Telegram Bot API. It never listens for inbound
connections. So you do **not** need to open any ports: leave the default
locked-down security list / Network Security Group in place (no ingress rules
beyond SSH if you want remote admin). This keeps the attack surface minimal.

### 3. Install the system dependencies

ffmpeg is a required system package. Install it plus either uv or Docker:

```bash
# Ubuntu
sudo apt-get update && sudo apt-get install -y ffmpeg

# uv (for the systemd option)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 4. Run it — pick systemd OR Docker

**Option A — systemd (recommended for a bare VM):**

```bash
# Put the project at /opt/hotline and install core + audio.
sudo git clone https://github.com/lgf2111/radio-giveaway-notifier /opt/hotline
cd /opt/hotline && uv sync --extra audio

# Dedicated user + config/secret locations the unit expects.
sudo useradd --system --home-dir /opt/hotline --shell /usr/sbin/nologin hotline
sudo install -d -o hotline -g hotline /etc/hotline /var/lib/hotline
sudo cp config.example.toml /etc/hotline/config.toml        # edit: set [audio] enabled = true
sudo cp deploy/hotline.env.example /etc/hotline/hotline.env # edit: real token + chat id
sudo chown hotline:hotline /etc/hotline/hotline.env && sudo chmod 600 /etc/hotline/hotline.env
sudo chown -R hotline:hotline /opt/hotline

# Install and start the service (Restart=always, starts on boot).
sudo cp deploy/hotline.service /etc/systemd/system/hotline.service
sudo systemctl daemon-reload && sudo systemctl enable --now hotline
journalctl -u hotline -f
```

The unit runs `hotline watch` as the `hotline` user, loads secrets from
`EnvironmentFile=/etc/hotline/hotline.env`, reads `/etc/hotline/config.toml`,
persists the dedupe db at `/var/lib/hotline/hotline.db`, and restarts on any
exit. See the comments in [`deploy/hotline.service`](deploy/hotline.service).

**Option B — Docker:**

```bash
# ARM64 image with ffmpeg + the [audio] extra baked in.
docker build -t hotline -f deploy/Dockerfile .

docker run -d --name hotline --restart unless-stopped \
  --env-file /etc/hotline/hotline.env \
  -v /etc/hotline/config.toml:/etc/hotline/config.toml:ro \
  -v hotline-data:/data \
  hotline watch --config /etc/hotline/config.toml --db /data/hotline.db
```

### 5. Keep the free instance from being reclaimed

Oracle may reclaim **idle** Always-Free compute, and it now **disables** A1
instances that exceed the 2 OCPU / 12 GB tenancy cap. To stay safe: keep your
total A1 usage under the cap, keep the instance genuinely busy (hotline's `watch`
loop and periodic stream pulls help), check the console for reclamation/limit
notices, and consider upgrading to a **Pay As You Go** account (you still keep
the Always-Free resources, and they are not reclaimed for inactivity).

### 6. Legal / ToS note

This deployment is for **personal use**. Respect the audio stream provider's
Terms of Service, and record only short clips for your own personal
transcription — do not redistribute captured audio. The streamtheworld URL
(`https://22903.live.streamtheworld.com/987FM_PREM.aac`) is the allowed stream
the audio source uses. melisten's `robots.txt` disallows `/api/`,
`/liveradio/`, `/user/`, and `/login`, so the audio source must **not** point at
`https://live.melisten.sg/liveradio/987`. See the full
[LEGAL / ToS / ETHICS](#️-legal--tos--ethics) section below.

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
