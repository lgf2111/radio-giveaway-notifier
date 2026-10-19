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

# Isolate the service's environment from the dev `.venv`. `uv run` syncs the
# project environment to match the requested extras on every invocation, so the
# service (--extra audio) and a dev shell (--extra dev) sharing one `.venv`
# would repeatedly tear out each other's extra-only packages -- causing the
# intermittent "can't find pytest" when running tests while the service is up.
# Pointing the service at its own venv keeps the two from fighting: the service
# owns this one (always has faster-whisper) and dev keeps the repo `.venv`.
export UV_PROJECT_ENVIRONMENT="${HOME}/.config/hotline/service-venv"

# Run Whisper fully offline. The faster-whisper model is downloaded once (on the
# first run, or ahead of time) into the HF hub cache; after that, HF_HUB_OFFLINE
# stops faster-whisper from issuing a model-revision check to huggingface.co on
# every transcription. This removes a per-cycle network round-trip and keeps the
# 24/7 watcher working through network blips. If you ever need to pull a new
# model size, comment this out for one run so the download can happen.
export HF_HUB_OFFLINE=1

# Run the watcher. --project pins uv to the install dir regardless of cwd.
# --extra audio installs faster-whisper so the live transcription path works;
# without it the audio source degrades to a no-op (text/web alerts only).
# -v emits INFO logs (poll cycles, gate decisions) to the err log so you can
# confirm it's alive; drop it for a quieter log.
# TRUE 24/7: caffeinate -i prevents IDLE sleep while the watcher runs. Scoped to
# this process only (not a global sleep disable). NOTE: lid-close sleep is NOT
# prevented by caffeinate alone -- for lid-closed (clamshell) operation the Mac
# must be on EXTERNAL POWER, and `sudo pmset -c disablesleep 1` must be set so
# closing the lid on AC doesn't sleep. On battery the Mac will still sleep on
# lid-close regardless. See the README "Keeping the watcher alive" section.
exec caffeinate -i uv run --project "${INSTALL_DIR}" --extra audio python -m hotline -v watch \
    --config "${CONFIG_PATH}" \
    --db "${DB_PATH}"

# Previous (idle-sleep-permitting) exec, kept for reference:
# exec uv run --project "${INSTALL_DIR}" --extra audio python -m hotline -v watch \
#     --config "${CONFIG_PATH}" \
#     --db "${DB_PATH}"
