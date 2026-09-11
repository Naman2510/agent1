#!/usr/bin/env bash
# Phase 1 / Step 3 — format the mirror ext4 and mount it persistently by UUID.
#
# Usage:
#   ./03-format-mount.sh                       # uses /dev/md0 -> /srv/data
#   MD_DEVICE=/dev/md0 MOUNT_POINT=/srv/data ./03-format-mount.sh

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

MD_DEVICE="${MD_DEVICE:-/dev/md0}"
MOUNT_POINT="${MOUNT_POINT:-/srv/data}"

require_root
require_cmd mkfs.ext4 blkid

log "Formatting ${MD_DEVICE} as ext4 with 1% reserved blocks (down from default 5%)"
run mkfs.ext4 -m 1 -L data "${MD_DEVICE}"

run mkdir -p "${MOUNT_POINT}"

if [[ "${SIMULATE}" == "1" ]]; then
    UUID="00000000-0000-0000-0000-000000000000"
    warn "SIMULATE=1: using placeholder UUID ${UUID}"
else
    UUID="$(blkid -s UUID -o value "${MD_DEVICE}")"
    [[ -n "${UUID}" ]] || die "could not read UUID for ${MD_DEVICE}"
fi

FSTAB_LINE="UUID=${UUID}  ${MOUNT_POINT}  ext4  defaults,noatime,nodev,nosuid  0  2"

if [[ "${SIMULATE}" == "1" ]]; then
    echo "+ (simulated) append to /etc/fstab: ${FSTAB_LINE}"
else
    if grep -qF "${UUID}" /etc/fstab 2>/dev/null; then
        warn "fstab already has an entry for UUID ${UUID}, not duplicating"
    else
        echo "${FSTAB_LINE}" >> /etc/fstab
        log "Appended to /etc/fstab: ${FSTAB_LINE}"
    fi
    run mount -a
fi

log "Mounted ${MD_DEVICE} at ${MOUNT_POINT} (UUID=${UUID})"
log "Next: 04-bootloader-mirror.sh"
