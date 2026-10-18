#!/bin/sh
# Wrapper that the launchd LaunchAgent (com.hotline.watch.plist) invokes.
#
# It sources the secrets env file, makes sure Homebrew is on PATH, then execs
# `uv run ... python -m hotline watch`. Keeping uv out of the plist means the
# binary is resolved via PATH here rather than hardcoded in the agent.
#
# `set -u` catches unset variables; we deliberately do NOT `set -e` around the
# optional env-file source so a missing env file degrades to a warning instead
# of aborting the agent.
set -u

# Derive the repo root from this script's own location (it lives at
# <repo>/deploy/macos/hotline-run.sh), so no install-time substitution is
# needed and the wrapper works wherever the repo is checked out.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONFIG_PATH="${HOME}/.config/hotline/config.toml"
ENV_FILE="${HOME}/.config/hotline/hotline.env"
DB_PATH="${HOME}/.config/hotline/hotline.db"

# Make sure Homebrew (ffmpeg) and the uv install dir resolve even under
# launchd's bare env. uv installs to ~/.local/bin via the astral installer;
# Homebrew lives in /opt/homebrew (Apple Silicon) or /usr/local (Intel).
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# Load secrets (HOTLINE_TELEGRAM_TOKEN, HOTLINE_CHAT_ID, optional
# HOTLINE_SUMMARY_API_KEY) from the env file. `set -a` exports everything the
# file defines; `set +a` restores the prior behaviour afterwards.
if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
else
    echo "hotline-run: warning: ${ENV_FILE} not found; text/audio alerts need" \
        "HOTLINE_TELEGRAM_TOKEN and HOTLINE_CHAT_ID to be set" >&2
fi

# Unbuffered stdout/stderr so the launchd log files stream live instead of
# buffering (critical for monitoring a long-running background service).
export PYTHONUNBUFFERED=1

# Run the watcher. --project pins uv to the install dir regardless of cwd.
# --extra audio installs faster-whisper so the live transcription path works;
# without it the audio source degrades to a no-op (text/web alerts only).
# -v emits INFO logs (poll cycles, gate decisions) to the err log so you can
# confirm it's alive; drop it for a quieter log.
exec uv run --project "${INSTALL_DIR}" --extra audio python -m hotline -v watch \
    --config "${CONFIG_PATH}" \
    --db "${DB_PATH}"

# Opt-in TRUE 24/7: prevent idle sleep while the watcher runs by wrapping the
# command in caffeinate. Comment out the exec above and uncomment the line
# below. Do NOT also disable sleep globally -- caffeinate -i is scoped to this
# process only. See the README "Keeping the watcher alive" section.
# exec caffeinate -i uv run --project "${INSTALL_DIR}" --extra audio \
#     python -m hotline watch --config "${CONFIG_PATH}" --db "${DB_PATH}"
