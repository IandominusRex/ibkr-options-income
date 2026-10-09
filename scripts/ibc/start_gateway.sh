#!/bin/bash
# Launches IB Gateway via IBC (https://github.com/IbcAlpha/IBC) — automates the login
# screen and the daily restart so Gateway doesn't sit disconnected for hours whenever
# nobody is around to click through it by hand. See SETUP.md "Automating Gateway login
# with IBC" for the full setup (including the one-time GUI step and what this can and
# can't automate around IBKR Mobile push 2FA).
#
# Credentials are read from .env, never written to disk anywhere else. IBC's own
# gatewaystartmacos.sh unconditionally blanks TWSUSERID/TWSPASSWORD at the top of the
# file (it's designed to be hand-edited there), which would clobber anything exported
# before calling it — so this script calls IBC's displaybannerandlaunch.sh directly and
# never touches IBC's vendored files.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: $ENV_FILE not found. Copy .env.example to .env first." >&2
    exit 1
fi

env_var() {
    grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d'=' -f2- || true
}

IBKR_LOGIN_ID="$(env_var IBKR_LOGIN_ID)"
IBKR_LOGIN_PASSWORD="$(env_var IBKR_LOGIN_PASSWORD)"
LIVE_TRADING="$(env_var LIVE_TRADING)"

if [[ -z "$IBKR_LOGIN_ID" || -z "$IBKR_LOGIN_PASSWORD" ]]; then
    echo "Error: IBKR_LOGIN_ID / IBKR_LOGIN_PASSWORD are not set in $ENV_FILE." >&2
    echo "Add them (see .env.example), then re-run." >&2
    exit 1
fi

# Single source of truth for paper vs live: reuse the same switch the trading app
# itself is gated on, so Gateway's trading mode can never drift out of sync with it.
if [[ "$LIVE_TRADING" == "true" ]]; then
    TRADING_MODE=live
else
    TRADING_MODE=paper
fi

# IBC / Gateway install locations — override via env if you installed elsewhere.
IBC_PATH="${IBC_PATH:-$HOME/Applications/ibc}"
TWS_PATH="${TWS_PATH:-$HOME/Applications}"
# IBC finds Gateway by its versioned install folder ("IB Gateway 10.51"). Unless
# TWS_MAJOR_VRSN is exported, use the newest one installed, so an upgrade is just "run the
# new installer, restart Gateway" — the old folder can stay as a rollback until removed.
if [[ -z "${TWS_MAJOR_VRSN:-}" ]]; then
    TWS_MAJOR_VRSN="$(find "$TWS_PATH" -maxdepth 1 -type d -name 'IB Gateway [0-9]*.[0-9]*' \
        | sed -E 's/.*IB Gateway //' | sort -t. -k1,1n -k2,2n | tail -1)"
fi
if [[ -z "$TWS_MAJOR_VRSN" || ! -d "${TWS_PATH}/IB Gateway ${TWS_MAJOR_VRSN}" ]]; then
    echo "Error: no IB Gateway install found in ${TWS_PATH} (looked for 'IB Gateway <version>')." >&2
    exit 1
fi
echo "Using IB Gateway ${TWS_MAJOR_VRSN} from ${TWS_PATH}"

if [[ ! -x "${IBC_PATH}/scripts/displaybannerandlaunch.sh" ]]; then
    echo "Error: IBC not found at ${IBC_PATH}. Set IBC_PATH or re-check the install." >&2
    exit 1
fi

IBC_INI="${IBC_PATH}/config.ini"

# Same duplicate-instance guard IBC's own gatewaystartmacos.sh does — we skip that
# script entirely (see header comment), so we re-implement its check here. Matters
# once this runs under launchd's KeepAlive: without it, a launchd relaunch racing a
# manual run (or a stuck old process) could start two Gateway/IBC instances at once.
if [[ -n $(/usr/bin/pgrep -f "java.*${IBC_INI}") ]]; then
    echo "IBC/Gateway is already running for ${IBC_INI} — not starting a duplicate." >&2
    exit 0
fi

export IBC_INI
export TRADING_MODE
export TWOFA_TIMEOUT_ACTION=restart
export IBC_PATH
export TWS_PATH
export TWS_SETTINGS_PATH=
export LOG_PATH="${IBC_PATH}/logs"
export TWSUSERID="$IBKR_LOGIN_ID"
export TWSPASSWORD="$IBKR_LOGIN_PASSWORD"
export FIXUSERID=
export FIXPASSWORD=
export JAVA_PATH=
export TWS_MAJOR_VRSN
export APP=GATEWAY

exec "${IBC_PATH}/scripts/displaybannerandlaunch.sh"
