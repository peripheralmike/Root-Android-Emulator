#!/usr/bin/env bash
#
# Install weirdfinder on macOS and schedule it with launchd.
#
#   ./install/install.sh              # install, schedule daily at 09:00
#   ./install/install.sh --hour 7     # ...at 07:00 instead
#   ./install/install.sh --no-schedule
#   ./install/install.sh --uninstall
#
set -euo pipefail

LABEL="com.weirdfinder.run"
PREFIX="${HOME}/.local/share/weirdfinder"
VENV="${PREFIX}/venv"
BIN="${VENV}/bin/weirdfinder"
LOG="${HOME}/Library/Logs/weirdfinder.log"
CONFIG="${HOME}/.config/weirdfinder/config.toml"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
HOUR=9
MINUTE=0
SCHEDULE=1

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hour) HOUR="$2"; shift 2 ;;
        --minute) MINUTE="$2"; shift 2 ;;
        --no-schedule) SCHEDULE=0; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

unload_agent() {
    # bootout is the modern spelling; both are noisy when nothing is loaded.
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
    launchctl unload "${PLIST}" 2>/dev/null || true
}

if [[ "${UNINSTALL:-0}" == "1" ]]; then
    echo "==> removing the schedule"
    unload_agent
    rm -f "${PLIST}"
    echo "==> removing ${VENV}"
    rm -rf "${VENV}"
    echo
    echo "Left in place (delete by hand if you want them gone):"
    echo "  config  ${CONFIG}"
    echo "  state   ${HOME}/.local/state/weirdfinder/"
    echo "  log     ${LOG}"
    exit 0
fi

# --- python ------------------------------------------------------------------
# macOS ships 3.9, which has no tomllib. Find a real 3.11+ before doing anything.
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "${candidate}" >/dev/null 2>&1 && \
       "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PYTHON="$(command -v "${candidate}")"
        break
    fi
done

if [[ -z "${PYTHON}" ]]; then
    echo "error: need Python 3.11 or newer (macOS ships 3.9)." >&2
    echo "       install one with:  brew install python@3.12" >&2
    exit 1
fi
echo "==> using ${PYTHON} ($("${PYTHON}" --version))"

# --- install -----------------------------------------------------------------
echo "==> creating venv at ${VENV}"
mkdir -p "${PREFIX}"
"${PYTHON}" -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --upgrade pip
echo "==> installing weirdfinder from ${REPO}"
"${VENV}/bin/pip" install --quiet "${REPO}"

mkdir -p "$(dirname "${CONFIG}")" "$(dirname "${LOG}")"
if [[ ! -f "${CONFIG}" ]]; then
    "${BIN}" --config "${CONFIG}" init >/dev/null
    echo "==> wrote a starter config to ${CONFIG}"
else
    echo "==> keeping your existing config at ${CONFIG}"
fi

# --- schedule ----------------------------------------------------------------
if [[ "${SCHEDULE}" == "1" ]]; then
    echo "==> scheduling daily at $(printf '%02d:%02d' "${HOUR}" "${MINUTE}")"
    mkdir -p "$(dirname "${PLIST}")"
    sed -e "s|@LABEL@|${LABEL}|g" \
        -e "s|@BIN@|${BIN}|g" \
        -e "s|@LOG@|${LOG}|g" \
        -e "s|@CONFIG@|${CONFIG}|g" \
        -e "s|@HOUR@|${HOUR}|g" \
        -e "s|@MINUTE@|${MINUTE}|g" \
        "${REPO}/install/com.weirdfinder.run.plist.template" > "${PLIST}"

    unload_agent
    launchctl bootstrap "gui/$(id -u)" "${PLIST}"
    echo "==> loaded ${LABEL}"
fi

cat <<EOF

Installed. Two things left, both on the Google side:

  1. Make a service account and download its JSON key:
       console.cloud.google.com -> new project -> enable "Google Sheets API"
       -> Credentials -> Create credentials -> Service account -> Keys -> JSON
     Save it as: ${HOME}/.config/weirdfinder/service-account.json

  2. Open that JSON, copy the "client_email" value, and share your
     spreadsheet with that address as an Editor. Then put the spreadsheet id
     (the long string in its URL) into sheet.spreadsheet_id in:
       ${CONFIG}

Then:
  ${BIN} check              # verify config, auth and connectivity
  ${BIN} run --dry-run      # see what it would add, without writing
  ${BIN} run                # for real

Schedule:
  launchctl print gui/$(id -u)/${LABEL}   # is it loaded?
  launchctl kickstart -k gui/$(id -u)/${LABEL}   # run it right now
  tail -f ${LOG}
EOF
