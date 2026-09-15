# Disaster Recovery & Field Operations Runbook

Standard Operating Procedure for on-call/field response to the failure
modes this platform is built to survive. Keep a printed copy in the rack —
if the array is degraded badly enough, you may not trust the network to
serve this page.

---

## 0. Before this runbook applies: simulation vs. real hardware

Everything below describes procedure against **real** `/dev/sdX` devices
and a **real** `mdadm` array. As of this writing, none of it has been
executed against real or virtual block devices in this project — see
`PROJECT_SPEC.md`'s testing ledger and `phase1-host-provisioning/
storage_sim/README.md`'s "What has and hasn't been validated" section for
the honest, current status. What *has* been built and tested is:

- **`storage_sim/`** — a from-scratch software model of RAID1 mirroring
  (mirroring, degraded reads/writes, member fail/remove/add, background
  rebuild, corruption detection + self-heal, `scrub`, cross-process
  reassembly). This validates the *logic* this runbook's Section 1–2
  procedures are built around, entirely in software — it never opens a
  real device file. See `storage_sim/README.md`'s "mdadm equivalence
  table" for the exact mapping between simulated operations and the real
  commands in Sections 1–2 below.
- **`storage_sim/real_block_device.py`** (`RealBlockDevice`) — a
  safety-gated adapter that lets the *same* `RAID1Array` logic run against
  a real path instead of the simulation's in-memory/file model. It is
  fully implemented and tested against a stand-in (a plain temp file, not
  a device), but has never opened an actual `/dev/sdX` — see its README
  section for the precise IMPLEMENTED+TESTED / NOT YET VALIDATED split.
  It refuses to do real I/O at all unless three independent things are
  true: `allow_real_io=True`, `i_have_confirmed_with_lsblk=True`, and the
  target path isn't on its hardcoded boot-disk-prefix denylist
  (`/dev/sda`, `/dev/nvme0n1`, `/dev/vda`, `/dev/xvda`, `/dev/hda`).
- **`phase1-host-provisioning/scripts/plan_from_lsblk.py`** — the
  required *first step* of real integration, and the tool that produces
  the human check this runbook assumes happened before Section 1–2 ever
  touch a device. Feed it real `lsblk -J` output; it classifies every
  disk as in-use (has a mountpoint, filesystem, RO flag, or existing
  partition anywhere in its subtree) or blank, and refuses to print a
  concrete wipe/partition/assemble command plan unless **exactly two**
  disks come back unambiguously blank *and* you pass
  `--i-confirm-these-are-blank-disks` yourself:
  ```bash
  lsblk -J | python3 phase1-host-provisioning/scripts/plan_from_lsblk.py - \
      --i-confirm-these-are-blank-disks
  ```
  It never runs a command itself — it only ever prints a plan for a human
  to read and then execute (or not) by hand, using the real
  `phase1-host-provisioning/scripts/*.sh` scripts.

**The integration path, in order:** (1) run `storage_sim`'s test suite and
`raidsim demo` to understand the logic with zero risk — nothing below
requires a device; (2) once real disks exist, capture `lsblk -J` and run
it through `plan_from_lsblk.py` to get an explicit, human-reviewed blank/
in-use classification — never hand-pick a device name by guessing; (3)
only then follow Sections 1–4 below against the disks `plan_from_lsblk.py`
confirmed blank. Skipping step (2) — assuming you know which disk is
blank instead of having a tool confirm it from real `lsblk` output — is
exactly how a hot-swap procedure ends up wiping the OS disk.

## 1. Diagnosing a degraded RAID array

**Symptom:** Alertmanager fires `DiskReallocatedSectorsRising` /
`DiskPendingSectorsCritical` / `DiskUncorrectableSectors`, or a scheduled
check notices `/proc/mdstat` shows `[U_]` instead of `[UU]`.

```bash
cat /proc/mdstat                    # look for [U_] (degraded) vs [UU] (healthy)
mdadm --detail /dev/md0             # State: clean, degraded ?  which device failed?
smartctl -a /dev/sdX                # confirm the failing member's SMART attributes 5/197/198
journalctl -k --since "-1h" | grep -iE 'mce|edac|ata|aer'   # corroborate with kernel faults
```

If `mdadm --detail` shows a member as `faulty` or missing, proceed to
Section 2. If SMART shows rising-but-not-yet-failed counters on a member
mdadm still considers healthy, schedule a proactive replacement during the
next maintenance window rather than waiting for a hard failure.

## 2. Hot-swap procedure (no reboot required)

The mirror is designed to survive this with the host never going down.

1. Confirm which physical bay holds the failed device:
   ```bash
   udevadm info --query=all --name=/dev/sdX | grep ID_PATH
   ```
   Or use `oob_control.py set-led` to light the fault LED for physical
   identification (`phase4-oob-lifecycle/fault_drill.sh` does this
   automatically as part of the drill).
2. Fail and remove the member from the array (skip `--fail` if mdadm
   already marked it faulty):
   ```bash
   mdadm --fail /dev/md0 /dev/sdX1
   mdadm --remove /dev/md0 /dev/sdX1
   ```
3. Physically hot-swap the drive (hardware must support hot-swap bays —
   confirm before pulling a non-hot-swap drive live).
4. Partition the replacement identically to its mirror (typecode `fd00`,
   full-disk):
   ```bash
   sgdisk -n 1:0:0 -t 1:fd00 -c 1:raid-member-sdX /dev/sdX
   ```
   (Same command as `phase1-host-provisioning/scripts/01-partition-raid.sh`.)
5. Re-add and monitor the rebuild:
   ```bash
   mdadm --add /dev/md0 /dev/sdX1
   watch cat /proc/mdstat        # wait for [UU] and 100% recovery
   ```
6. Clear the fault LED (`oob_control.py set-led --state Off`).

For a scripted, repeatable version of steps 2–6 with LED control built in,
use `phase4-oob-lifecycle/fault_drill.sh` (also serves as the drill script
for practicing this procedure before a real failure).

## 3. EFI bootloader restoration on a newly inserted bare drive

If the **boot** drive (not just a data mirror member) was replaced and the
new drive has no ESP yet:

```bash
# Partition a fresh ESP on the replacement (512MiB, typecode ef00):
sgdisk -n 1:1MiB:+512MiB -t 1:ef00 -c 1:EFI2 /dev/sdX
mkfs.vfat -F32 -n EFI2 /dev/sdX1

mount /dev/sdX1 /mnt/esp-restore
rsync -a --delete /boot/efi/ /mnt/esp-restore/
grub-install --target=x86_64-efi --efi-directory=/mnt/esp-restore --bootloader-id=debian-secondary --recheck /dev/sdX
umount /mnt/esp-restore
update-grub
efibootmgr -v   # confirm the new boot entry is present
```

This mirrors `phase1-host-provisioning/scripts/04-bootloader-mirror.sh` —
re-run that script instead of doing it by hand when both DISK1/DISK2 are
known-good and only the ESP needs resyncing.

## 4. Host completely unresponsive (network and console both down)

1. From the management VLAN, reach the BMC directly (never routed through
   the host's own NICs):
   ```bash
   python3 oob_control.py --base-url https://<bmc-ip>:8443 power-status
   ```
2. If `PowerState` shows `On` but the host doesn't respond to SSH/ping,
   attempt a graceful reset first, hard cycle only if that fails:
   ```bash
   python3 oob_control.py --base-url https://<bmc-ip>:8443 power-cycle --reset-type graceful-shutdown
   # wait 30s, then if still unresponsive:
   python3 oob_control.py --base-url https://<bmc-ip>:8443 power-cycle --reset-type cycle
   ```
3. If the host fails to come back up cleanly, force a PXE boot to bring up
   a recovery/rescue image:
   ```bash
   python3 oob_control.py --base-url https://<bmc-ip>:8443 boot-override --target pxe
   python3 oob_control.py --base-url https://<bmc-ip>:8443 power-cycle --reset-type cycle
   ```
4. Once a rescue shell is reachable, re-check `/proc/mdstat`, `dmesg`, and
   `journalctl -b -1` (previous boot) for the root cause before returning
   to production boot (`boot-override --target hdd`).

## 5. Static network topology reference

See `docs/network-topology.md` for the authoritative MAC-to-IP bindings,
subnet allocations, and VLAN tags for this site.

## 6. Escalation checklist

- [ ] Is this a single-member RAID degradation (self-healing via hot-swap,
      no customer impact expected) or a full host outage (page on-call)?
- [ ] Has the fault LED been set so the physical bay is unambiguous to
      whoever swaps the drive?
- [ ] Was a `smartctl`/kernel-log root cause captured **before** the drive
      was pulled? (Evidence is gone once the drive is removed.)
- [ ] After rebuild/recovery: confirm `mdadm --detail /dev/md0` shows
      `State: clean` and `[UU]`, confirm both ESPs re-synced if the boot
      drive was touched, confirm nftables/telemetryd/node_exporter came
      back up (`systemctl status nftables telemetryd node_exporter`).
