#!/usr/bin/env bash
# Phase 4 — automated fault injection & rebuild drill.
#
# Simulates a silicon disk failure on one RAID 1 member, sets the chassis
# drive-slot fault LED via Redfish, logically removes the failed member,
# simulates a physical swap, re-adds it, and monitors the mdadm rebuild to
# completion.
#
# Usage:
#   MD_DEVICE=/dev/md0 FAILED_PART=/dev/sdb1 DRIVE_ID=2 \
#     REDFISH_URL=https://bmc.local:8443 \
#     ./fault_drill.sh
#
#   SIMULATE=1 ./fault_drill.sh   # dry run, no mdadm/Redfish calls made

source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"

MD_DEVICE="${MD_DEVICE:-/dev/md0}"
FAILED_PART="${FAILED_PART:?set FAILED_PART, e.g. /dev/sdb1}"
CHASSIS_ID="${CHASSIS_ID:-System.Embedded.1}"
DRIVE_ID="${DRIVE_ID:?set DRIVE_ID, the Redfish drive slot id, e.g. 2}"
REDFISH_URL="${REDFISH_URL:-https://127.0.0.1:8443}"
REDFISH_ARGS=(--insecure --base-url "${REDFISH_URL}" --chassis "${CHASSIS_ID}")
OOB_CLI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/oob_control.py"
POLL_SECONDS="${POLL_SECONDS:-5}"

require_root
require_cmd mdadm python3

log "=== Fault drill: ${MD_DEVICE} member ${FAILED_PART} (drive slot ${DRIVE_ID}) ==="

log "Step 1/5: injecting simulated silicon failure"
run mdadm --fail "${MD_DEVICE}" "${FAILED_PART}"

log "Step 2/5: setting chassis drive fault LED to Blinking Amber via Redfish"
run python3 "${OOB_CLI}" "${REDFISH_ARGS[@]}" set-led --drive "${DRIVE_ID}" --state Blinking

log "Step 3/5: logically removing the failed member from the array"
run mdadm --remove "${MD_DEVICE}" "${FAILED_PART}"

log "Step 4/5: simulating physical drive replacement"
warn "In a real drill: physically swap the drive now, then re-partition it"
warn "identically to its mirror (see phase1-host-provisioning/scripts/01-partition-raid.sh)."
if [[ "${SIMULATE}" != "1" ]]; then
    confirm "Replacement drive is in place at ${FAILED_PART} and partitioned — continue?"
fi

log "Step 5/5: re-adding the replacement and monitoring rebuild"
run mdadm --add "${MD_DEVICE}" "${FAILED_PART}"
run python3 "${OOB_CLI}" "${REDFISH_ARGS[@]}" set-led --drive "${DRIVE_ID}" --state Off

if [[ "${SIMULATE}" == "1" ]]; then
    log "(simulated) would now poll /proc/mdstat until rebuild completes"
else
    log "Monitoring rebuild progress (polling every ${POLL_SECONDS}s)..."
    while true; do
        line="$(grep -A1 "^${MD_DEVICE#/dev/}" /proc/mdstat | grep -oE '\[=*>?\.*\] +recovery = [0-9.]+%.*' || true)"
        if [[ -z "${line}" ]]; then
            if grep -q "^${MD_DEVICE#/dev/}.*\[UU\]" /proc/mdstat 2>/dev/null; then
                log "Rebuild complete — array is fully synced ([UU])"
                break
            fi
        else
            log "Rebuild progress: ${line}"
        fi
        sleep "${POLL_SECONDS}"
    done
fi

log "=== Fault drill complete ==="
