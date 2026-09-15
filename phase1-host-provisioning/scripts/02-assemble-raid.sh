#!/usr/bin/env bash
# Phase 1 / Step 2 — assemble the mdadm RAID 1 mirror and persist it.
#
# Usage:
#   PART1=/dev/sda1 PART2=/dev/sdb1 ./02-assemble-raid.sh

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

PART1="${PART1:?set PART1, e.g. /dev/sda1}"
PART2="${PART2:?set PART2, e.g. /dev/sdb1}"
MD_DEVICE="${MD_DEVICE:-/dev/md0}"

require_root
require_cmd mdadm update-initramfs

log "Creating ${MD_DEVICE} as RAID 1 (metadata 1.2) from ${PART1} + ${PART2}"
run mdadm --create "${MD_DEVICE}" \
    --level=1 \
    --raid-devices=2 \
    --metadata=1.2 \
    --homehost=any \
    "${PART1}" "${PART2}"

log "Persisting array definition to /etc/mdadm/mdadm.conf"
run mkdir -p /etc/mdadm
if [[ "${SIMULATE}" == "1" ]]; then
    echo "+ (simulated) mdadm --detail --scan >> /etc/mdadm/mdadm.conf"
else
    mdadm --detail --scan | tee -a /etc/mdadm/mdadm.conf
fi

log "Rebuilding initramfs so the array is assembled at boot"
run update-initramfs -u

log "Array state:"
if [[ "${SIMULATE}" != "1" ]]; then
    cat /proc/mdstat
fi
log "Next: 03-format-mount.sh"
