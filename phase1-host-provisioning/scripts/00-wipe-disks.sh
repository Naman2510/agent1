#!/usr/bin/env bash
# Phase 1 / Step 0 — scrub legacy signatures off the two RAID member disks.
#
# Usage:
#   DISK1=/dev/sda DISK2=/dev/sdb ./00-wipe-disks.sh
#   SIMULATE=1 DISK1=/dev/sda DISK2=/dev/sdb ./00-wipe-disks.sh   # dry run
#
# DESTRUCTIVE: this destroys all partition tables and filesystem signatures
# on both disks. Requires the operator to type "yes" unless SIMULATE=1 or
# CONFIRM=yes is set.

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

DISK1="${DISK1:?set DISK1, e.g. /dev/sda or /dev/nvme0n1}"
DISK2="${DISK2:?set DISK2, e.g. /dev/sdb or /dev/nvme1n1}"

require_root
require_cmd wipefs sgdisk blockdev

for d in "${DISK1}" "${DISK2}"; do
    [[ -b "${d}" || "${SIMULATE}" == "1" ]] || die "${d} is not a block device"
done

log "About to irreversibly wipe: ${DISK1} and ${DISK2}"
confirm "This will DESTROY ALL DATA on ${DISK1} and ${DISK2}"

for d in "${DISK1}" "${DISK2}"; do
    log "Wiping filesystem/RAID signatures on ${d}"
    run wipefs --all --force "${d}"
    log "Zapping GPT/MBR structures on ${d}"
    run sgdisk --zap-all "${d}"
    run blockdev --rereadpt "${d}" || true
done

log "Disks wiped clean. Next: 01-partition-raid.sh"
