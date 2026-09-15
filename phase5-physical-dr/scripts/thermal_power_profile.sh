#!/usr/bin/env bash
# Phase 5 — thermal & power profiling under synthetic load.
#
# Captures sensor/turbostat/powertop snapshots at idle, then again during a
# stress-ng run driving CPU/IO/VM pressure, so idle-vs-peak dissipation and
# draw can be compared.
#
# Usage:
#   OUT_DIR=/var/log/thermal-profile ./thermal_power_profile.sh
#   SIMULATE=1 ./thermal_power_profile.sh

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

OUT_DIR="${OUT_DIR:-./thermal-profile-$(date -u +%Y%m%dT%H%M%SZ)}"
STRESS_DURATION="${STRESS_DURATION:-600}"   # seconds, matches spec's --timeout 600s

require_root
run mkdir -p "${OUT_DIR}"

snapshot() {
    local label="$1"
    local dir="${OUT_DIR}/${label}"
    run mkdir -p "${dir}"

    if [[ "${SIMULATE}" == "1" ]]; then
        echo "(simulated) sensors -> ${dir}/sensors.txt"
        echo "(simulated) turbostat snapshot -> ${dir}/turbostat.txt"
        return
    fi

    command -v sensors >/dev/null 2>&1 && sensors > "${dir}/sensors.txt" 2>&1 || true
    if command -v turbostat >/dev/null 2>&1; then
        timeout 5 turbostat --num_iterations 1 > "${dir}/turbostat.txt" 2>&1 || true
    fi
    for zone in /sys/class/thermal/thermal_zone*/temp; do
        [[ -r "${zone}" ]] || continue
        echo "${zone}: $(($(cat "${zone}")/1000))C" >> "${dir}/sysfs_thermal.txt"
    done
}

log "Capturing idle baseline"
snapshot "idle"

log "Driving peak load for ${STRESS_DURATION}s: stress-ng --cpu 0 --io 4 --vm 2 --vm-bytes 2G"
require_cmd stress-ng
if [[ "${SIMULATE}" == "1" ]]; then
    echo "+ (simulated) stress-ng --cpu 0 --io 4 --vm 2 --vm-bytes 2G --timeout ${STRESS_DURATION}s &"
else
    stress-ng --cpu 0 --io 4 --vm 2 --vm-bytes 2G --timeout "${STRESS_DURATION}s" &
    STRESS_PID=$!
    sleep 30   # let load ramp and thermals stabilize before sampling
fi

log "Capturing peak-load snapshot"
snapshot "peak-load"

if [[ "${SIMULATE}" != "1" ]]; then
    wait "${STRESS_PID}" 2>/dev/null || true
fi

log "Capturing cooldown snapshot"
snapshot "cooldown"

log "Report written to ${OUT_DIR}/{idle,peak-load,cooldown}/"
