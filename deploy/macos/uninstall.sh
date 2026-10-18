#!/bin/bash
# Uninstaller for the hotline macOS LaunchAgent.
#
# Stops and unloads the agent and removes the plist from ~/Library/LaunchAgents.
# Config and logs are LEFT in place unless you pass --purge.
#
#   bash deploy/macos/uninstall.sh            # stop + remove the agent
#   bash deploy/macos/uninstall.sh --purge    # also delete config + logs
set -euo pipefail

USER_UID="$(id -u)"
PLIST_LABEL="com.hotline.watch"
PLIST_DEST="${HOME}/Library/LaunchAgents/${PLIST_LABEL}.plist"
CONFIG_DIR="${HOME}/.config/hotline"
LOG_DIR="${HOME}/Library/Logs/hotline"

PURGE=0
if [ "${1:-}" = "--purge" ]; then
    PURGE=1
fi

echo "==> stopping ${PLIST_LABEL}"
launchctl bootout "gui/${USER_UID}/${PLIST_LABEL}" 2>/dev/null \
    || launchctl unload -w "${PLIST_DEST}" 2>/dev/null \
    || true

if [ -f "${PLIST_DEST}" ]; then
    rm -f "${PLIST_DEST}"
    echo "==> removed ${PLIST_DEST}"
else
    echo "==> no plist at ${PLIST_DEST}"
fi

if [ "${PURGE}" -eq 1 ]; then
    if [ -d "${CONFIG_DIR}" ]; then
        rm -rf "${CONFIG_DIR}"
        echo "==> purged ${CONFIG_DIR}"
    fi
    if [ -d "${LOG_DIR}" ]; then
        rm -rf "${LOG_DIR}"
        echo "==> purged ${LOG_DIR}"
    fi
else
    echo "==> left config at ${CONFIG_DIR} and logs at ${LOG_DIR}"
    echo "    (pass --purge to remove them too)"
fi
