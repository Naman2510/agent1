#!/usr/bin/env bash
# Phase 1 / Step 1 — create aligned, RAID-typed partitions on both disks.
#
# Creates one partition spanning the disk on each member, typecode fd00
# ("Linux RAID"), 1MiB-aligned (sgdisk default alignment already respects
# this on modern disks).
#
# Usage:
#   DISK1=/dev/sda DISK2=/dev/sdb ./01-partition-raid.sh

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

DISK1="${DISK1:?set DISK1}"
DISK2="${DISK2:?set DISK2}"

require_root
require_cmd sgdisk partprobe

part_suffix() {
    # /dev/sda -> 1 ; /dev/nvme0n1 -> p1
    case "$1" in
        *nvme*|*mmcblk*) echo "p1" ;;
        *) echo "1" ;;
    esac
}

for d in "${DISK1}" "${DISK2}"; do
    log "Creating full-disk RAID partition on ${d}"
    # -n 1:0:0  -> partition 1, default start, use full remaining disk
    # -t 1:fd00 -> typecode fd00 = "Linux RAID"
    # -c 1:raid-member -> partition label for clarity
    run sgdisk -n 1:0:0 -t 1:fd00 -c "1:raid-member-$(basename "${d}")" "${d}"
    run partprobe "${d}"
done

log "Partitions created:"
for d in "${DISK1}" "${DISK2}"; do
    echo "  ${d}$(part_suffix "${d}")"
done
log "Next: 02-assemble-raid.sh"
