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

# __INSTALL_DIR__ is substituted by install.sh with the absolute repo path.
INSTALL_DIR="__INSTALL_DIR__"
CONFIG_PATH="${HOME}/.config/hotline/config.toml"
ENV_FILE="${HOME}/.config/hotline/hotline.env"
DB_PATH="${HOME}/.config/hotline/hotline.db"

# Make sure Homebrew (and its ffmpeg/uv) resolve even under launchd's bare env.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"

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

# Run the watcher. --project pins uv to the install dir regardless of cwd.
# --extra audio installs faster-whisper so the live transcription path works;
# without it the audio source degrades to a no-op (text/web alerts only).
exec uv run --project "${INSTALL_DIR}" --extra audio python -m hotline watch \
    --config "${CONFIG_PATH}" \
    --db "${DB_PATH}"

# Opt-in TRUE 24/7: prevent idle sleep while the watcher runs by wrapping the
# command in caffeinate. Comment out the exec above and uncomment the line
# below. Do NOT also disable sleep globally -- caffeinate -i is scoped to this
# process only. See the README "Keeping the watcher alive" section.
# exec caffeinate -i uv run --project "${INSTALL_DIR}" --extra audio \
#     python -m hotline watch --config "${CONFIG_PATH}" --db "${DB_PATH}"
