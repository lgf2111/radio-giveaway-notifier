#!/bin/bash
# Idempotent installer for the hotline macOS LaunchAgent.
#
# Safe to re-run: it never overwrites an existing config or env file, and
# re-bootstrapping the agent just reloads it. It:
#   1. checks brew + ffmpeg + uv,
#   2. creates ~/Library/Logs/hotline and ~/.config/hotline,
#   3. seeds config.toml / hotline.env from the examples (only if absent),
#   4. substitutes the plist placeholders and installs the LaunchAgent,
#   5. loads it with launchctl and prints next steps.
#
# It does NOT write any secrets -- you edit ~/.config/hotline/hotline.env after.
set -euo pipefail

# Absolute path to the cloned repo (this script lives in deploy/macos/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

USER_NAME="$(id -u -n)"
USER_UID="$(id -u)"

CONFIG_DIR="${HOME}/.config/hotline"
LOG_DIR="${HOME}/Library/Logs/hotline"
CONFIG_PATH="${CONFIG_DIR}/config.toml"
ENV_PATH="${CONFIG_DIR}/hotline.env"
AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_LABEL="com.hotline.watch"
PLIST_DEST="${AGENTS_DIR}/${PLIST_LABEL}.plist"
PLIST_SRC="${SCRIPT_DIR}/${PLIST_LABEL}.plist"

echo "==> hotline macOS install"
echo "    repo:   ${INSTALL_DIR}"
echo "    user:   ${USER_NAME} (uid ${USER_UID})"

# --- 1. system dependencies ------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
    echo "error: Homebrew not found. Install it from https://brew.sh then re-run." >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg is required for the audio pipeline but was not found on PATH."
    if [ -t 0 ]; then
        read -r -p "Run 'brew install ffmpeg' now? [y/N] " reply
        case "${reply}" in
            [yY]*) brew install ffmpeg ;;
            *) echo "Skipping. Install it later with: brew install ffmpeg" ;;
        esac
    else
        echo "Non-interactive shell; install it with: brew install ffmpeg" >&2
    fi
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv not found. Install it with:" >&2
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

# --- 2. directories --------------------------------------------------------
mkdir -p "${LOG_DIR}" "${CONFIG_DIR}"

# --- 3. seed config + secrets (never overwrite) ----------------------------
if [ -f "${CONFIG_PATH}" ]; then
    echo "==> keeping existing ${CONFIG_PATH}"
else
    cp "${INSTALL_DIR}/config.example.toml" "${CONFIG_PATH}"
    echo "==> created ${CONFIG_PATH} (edit it: set [audio] enabled = true)"
fi

if [ -f "${ENV_PATH}" ]; then
    echo "==> keeping existing ${ENV_PATH}"
else
    cp "${SCRIPT_DIR}/hotline.env.example" "${ENV_PATH}"
    chmod 600 "${ENV_PATH}"
    echo "==> created ${ENV_PATH} (chmod 600; add your real token + chat id)"
fi

# --- 4. install the LaunchAgent plist --------------------------------------
mkdir -p "${AGENTS_DIR}"
tmp_plist="$(mktemp)"
trap 'rm -f "${tmp_plist}"' EXIT
sed \
    -e "s#__INSTALL_DIR__#${INSTALL_DIR}#g" \
    -e "s#__USER__#${USER_NAME}#g" \
    -e "s#__HOME__#${HOME}#g" \
    "${PLIST_SRC}" > "${tmp_plist}"
cp "${tmp_plist}" "${PLIST_DEST}"
echo "==> installed ${PLIST_DEST}"

# --- 5. load the agent -----------------------------------------------------
# Reload cleanly if it is already loaded (idempotent).
launchctl bootout "gui/${USER_UID}/${PLIST_LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${USER_UID}" "${PLIST_DEST}"
# Older macOS equivalent (pre-bootstrap):
#   launchctl load -w "${PLIST_DEST}"
echo "==> loaded ${PLIST_LABEL} into gui/${USER_UID}"

cat <<EOF

Next steps:
  1. Edit ${CONFIG_PATH} -> set [audio] enabled = true (stream_url is already
     the 987FM URL). Enable the English/Chinese stations you want.
  2. Put your real Telegram token + chat id in ${ENV_PATH} (chmod 600).
  3. Verify it is running:
       launchctl print gui/${USER_UID}/${PLIST_LABEL}
       tail -f ${LOG_DIR}/hotline.err.log
  4. After editing the env/config, reload with:
       launchctl kickstart -k gui/${USER_UID}/${PLIST_LABEL}
  5. Uninstall any time with:
       bash "${SCRIPT_DIR}/uninstall.sh"
EOF
