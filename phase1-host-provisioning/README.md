# Phase 1 — Host Provisioning, Storage Fabric & Security Baseline

Turns raw hardware into an isolated, resilient foundation where no single
drive failure crashes the host or leaves it unbootable.

## Run order

```
sudo DISK1=/dev/sda DISK2=/dev/sdb ./scripts/00-wipe-disks.sh
sudo DISK1=/dev/sda DISK2=/dev/sdb ./scripts/01-partition-raid.sh
sudo PART1=/dev/sda1 PART2=/dev/sdb1 ./scripts/02-assemble-raid.sh
sudo ./scripts/03-format-mount.sh
sudo DISK1=/dev/sda DISK2=/dev/sdb ./scripts/04-bootloader-mirror.sh
sudo ./scripts/05-harden-ssh.sh
sudo ./scripts/06-sudoers-audit.sh
```

Every script accepts `SIMULATE=1` to print exactly what it would run
without touching disks, bootloaders, sshd, or sudoers — use this to review
the plan on a machine that doesn't have the target hardware yet:

```
SIMULATE=1 DISK1=/dev/sda DISK2=/dev/sdb ./scripts/00-wipe-disks.sh
```

## What each step does

| Script | Action |
| --- | --- |
| `00-wipe-disks.sh` | `wipefs --all` + `sgdisk --zap-all` on both members |
| `01-partition-raid.sh` | Full-disk GPT partition, typecode `fd00` (Linux RAID) |
| `02-assemble-raid.sh` | `mdadm --create` RAID 1, metadata 1.2, persists to `mdadm.conf`, rebuilds initramfs |
| `03-format-mount.sh` | `mkfs.ext4 -m 1` (1% reserved blocks), UUID-mounted at `/srv/data` |
| `04-bootloader-mirror.sh` | Mirrors the ESP and runs `grub-install` against **both** disks independently |
| `05-harden-ssh.sh` | Installs `config/sshd_config.d/99-hardening.conf`, reloads sshd |
| `06-sudoers-audit.sh` | Installs `config/sudoers.d/99-sysadmin` with `visudo -c` validation, sets up `/var/log/sudo_audit.log` |

## Safety notes

- **Order matters.** Wipe → partition → assemble → format → mirror boot →
  harden SSH → harden sudo. Hardening SSH before you've confirmed key-based
  access works will lock you out.
- `04-bootloader-mirror.sh` and `06-sudoers-audit.sh` are the two steps most
  capable of bricking remote access — always keep an out-of-band console
  (see `phase4-oob-lifecycle/`) or physical access available while running
  them for the first time.
- `systemd/hardened.service.template` is the sandboxing profile referenced
  by every service unit elsewhere in this repo (`phase3-telemetry/telemetryd`,
  node_exporter, etc.) — copy and fill in the `<REPLACE: ...>` fields per service.
