# Phase 5 — Physical Infrastructure, Cabling & Disaster Recovery

The non-software layer: cabling standards, physical isolation, thermal/power
profiling, and the operational runbook everything else in this repo is
built to make boring.

## Contents

| Path | Purpose |
| --- | --- |
| `../docs/cabling.md` | T568B pinout, EMI separation, Velcro-not-zip-ties, certification steps |
| `../docs/network-topology.md` | Static MAC-to-IP bindings, subnet allocations, VLAN tags |
| `../docs/runbook.md` | Field SOP: degraded-array diagnosis, hot-swap, EFI restore, host-unresponsive escalation |
| `scripts/thermal_power_profile.sh` | Idle-vs-peak thermal/power capture using `stress-ng`, `sensors`, `turbostat` |

## Running the thermal/power profile

```
sudo STRESS_DURATION=600 ./scripts/thermal_power_profile.sh
```

Captures `sensors`, `turbostat`, and sysfs thermal-zone snapshots at idle,
during a 600s `stress-ng --cpu 0 --io 4 --vm 2 --vm-bytes 2G` run, and
during cooldown, so idle-vs-peak dissipation can be compared directly.
Supports `SIMULATE=1` for a dry run without actually loading the CPU.

## Hardware requirements

**Bare-metal (recommended):**
- Any x86-64 machine (old PC, OptiPlex/EliteDesk, or a real server).
- Two identical disks (SATA SSD/HDD or NVMe) for the RAID 1 mirror.
- At least one Gigabit NIC; dual NICs or an Intel I350 make VLAN testing
  more realistic.
- Cat6 bulk cable, RJ-45 connectors, crimper, and a continuity tester —
  see `../docs/cabling.md`.

**Virtualized (zero hardware cost):**
- Proxmox VE / VMware / VirtualBox VM with 2 virtual disks, 2 virtual NICs
  (one bridged, one host-only), Debian 12 or Ubuntu Server 24.04 guest.
- Every script and config in this repo runs unmodified against virtual
  block devices and NICs — only the physical-layer content in
  `../docs/cabling.md` doesn't apply to a fully virtualized build.
