#!/usr/bin/env bash
# Phase 1 / Step 4 — install GRUB independently on BOTH physical disks so the
# host is bootable even after total silicon failure of the primary drive.
#
# Usage:
#   DISK1=/dev/sda DISK2=/dev/sdb ./04-bootloader-mirror.sh
#
# Assumes UEFI boot with an ESP (EFI System Partition) already present on
# DISK1 (created by the OS installer) and mirrors it onto DISK2.

source "$(dirname "${BASH_SOURCE[0]}")/../../lib/common.sh"

DISK1="${DISK1:?set DISK1 (currently has the ESP)}"
DISK2="${DISK2:?set DISK2 (secondary boot target)}"
ESP_PART="${ESP_PART:-1}"          # partition number of the ESP on DISK1
ESP_MOUNT="${ESP_MOUNT:-/boot/efi}"
ESP2_LABEL="${ESP2_LABEL:-EFI2}"

require_root
require_cmd sgdisk mkfs.vfat rsync grub-install efibootmgr update-grub

part_of() {
    case "$1" in
        *nvme*|*mmcblk*) echo "${1}p${2}" ;;
        *) echo "${1}${2}" ;;
    esac
}

DISK2_ESP="$(part_of "${DISK2}" "${ESP_PART}")"

log "Creating mirrored ESP partition ${DISK2_ESP} on ${DISK2} (if not already present from Step 1's data partition, this uses a dedicated small EFI partition instead)"
run sgdisk -n "${ESP_PART}:1MiB:+512MiB" -t "${ESP_PART}:ef00" -c "${ESP_PART}:${ESP2_LABEL}" "${DISK2}"
run mkfs.vfat -F32 -n "${ESP2_LABEL}" "${DISK2_ESP}"

TMP_MNT="/mnt/esp2-mirror"
run mkdir -p "${TMP_MNT}"
run mount "${DISK2_ESP}" "${TMP_MNT}"

log "Syncing ESP contents from ${ESP_MOUNT} to ${DISK2_ESP}"
run rsync -a --delete "${ESP_MOUNT}/" "${TMP_MNT}/"

log "Installing GRUB on ${DISK1} (primary)"
run grub-install --target=x86_64-efi --efi-directory="${ESP_MOUNT}" --bootloader-id=debian --recheck "${DISK1}"

log "Installing GRUB on ${DISK2} (secondary, independent boot path)"
run grub-install --target=x86_64-efi --efi-directory="${TMP_MNT}" --bootloader-id=debian-secondary --recheck "${DISK2}"

run umount "${TMP_MNT}"

log "Regenerating grub.cfg"
run update-grub

log "Current EFI boot entries:"
if [[ "${SIMULATE}" != "1" ]]; then
    efibootmgr -v
fi

log "Both disks are now independently bootable. Next: 05-harden-ssh.sh"
