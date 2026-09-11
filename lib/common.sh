#!/usr/bin/env bash
# lib/common.sh — shared helpers for every provisioning/automation script in this repo.
#
# Source this from any script:
#   source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
#
# Provides:
#   - log/warn/die           structured stderr logging
#   - require_root           refuse to continue without EUID 0 (unless SIMULATE=1)
#   - require_cmd            fail fast with a clear message if a binary is missing
#   - run                    execute (or, under SIMULATE=1, just print) a command
#   - confirm                interactive "type yes to continue" gate for destructive ops
#
# SIMULATE=1 is the load-bearing convention across this repo: every destructive
# script (disk wiping, RAID assembly, mdadm fault injection, firewall reload,
# power-cycling) must be runnable end-to-end with SIMULATE=1 on a machine with
# no matching hardware, printing exactly what it *would* execute. This is what
# lets the automation be exercised in CI / a sandbox before it ever touches a
# real chassis.

set -euo pipefail

SIMULATE="${SIMULATE:-0}"

_ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

log()  { printf '[%s] [INFO ] %s\n'  "$(_ts)" "$*" >&2; }
warn() { printf '[%s] [WARN ] %s\n'  "$(_ts)" "$*" >&2; }
die()  { printf '[%s] [FATAL] %s\n'  "$(_ts)" "$*" >&2; exit 1; }

require_root() {
    if [[ "${SIMULATE}" == "1" ]]; then
        warn "SIMULATE=1: skipping root check (would require EUID 0)"
        return 0
    fi
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        die "this script must be run as root (or with SIMULATE=1 for a dry run)"
    fi
}

require_cmd() {
    local missing=()
    for c in "$@"; do
        command -v "$c" >/dev/null 2>&1 || missing+=("$c")
    done
    if [[ "${#missing[@]}" -gt 0 ]]; then
        if [[ "${SIMULATE}" == "1" ]]; then
            warn "SIMULATE=1: missing tool(s) [${missing[*]}] — continuing anyway"
        else
            die "required tool(s) not found: ${missing[*]}"
        fi
    fi
}

# run <cmd...>: executes the command, or under SIMULATE=1 prints "+ cmd" and
# returns success without touching the system. Use this for every command
# that writes to disk, partitions, networking, or hardware state.
run() {
    if [[ "${SIMULATE}" == "1" ]]; then
        printf '+ (simulated) %s\n' "$*"
    else
        printf '+ %s\n' "$*" >&2
        "$@"
    fi
}

# confirm <prompt>: in interactive+destructive scripts, require the operator
# to type the literal word "yes". Always short-circuits true under SIMULATE=1
# or CONFIRM=yes (for scripted/CI use).
confirm() {
    local prompt="$1"
    if [[ "${SIMULATE}" == "1" || "${CONFIRM:-}" == "yes" ]]; then
        return 0
    fi
    local reply
    read -r -p "${prompt} [type 'yes' to continue]: " reply
    [[ "${reply}" == "yes" ]] || die "aborted by operator"
}
