# Bare-Metal Edge Server & Reliability Platform

An infrastructure-as-code implementation of a resilient, self-monitoring
bare-metal edge server: mirrored storage and boot, a deterministic and
firewalled network stack, an async hardware-telemetry daemon with alerting,
Redfish-based out-of-band lifecycle control, and the physical/operational
standards to run it in a real rack.

Every script, daemon, and config here is meant to run on **real hardware**
(or a VM standing in for it) — this is not a simulation of the platform,
it's the platform's own automation. What *is* simulate-able, and has been
exercised as part of building this repo, is the logic: every destructive
shell script supports `SIMULATE=1` for a dry run, and the Python daemon/CLI
support `--mock` and a local mock BMC, respectively, so the automation can
be validated before it ever touches a disk, a NIC, or a chassis.

## Architecture

```
+---------------------------------------------------------------------------------------------------+
|                                  PHYSICAL & OUT-OF-BAND LAYER                                      |
|  - ANSI/TIA-568-B Cat6 Termination    - AC / Low-Voltage Physical Separation                      |
|  - Redfish REST API (OpenBMC/QEMU, or this repo's mock server)                                    |
+---------------------------------------------------------------------------------------------------+
                                                  |
+-------------------------------------------------v-------------------------------------------------+
|                                     LINUX KERNEL & HARDWARE                                        |
|  - Dual Block Devices (/dev/sda + /dev/sdb, or NVMe equivalents)                                   |
|  - Thermal Junctions (/sys/class/thermal/)  - Kernel Ring Buffer (/dev/kmsg, MCE/ECC)              |
+---------------------------------------------------------------------------------------------------+
                                                  |
+-------------------------------------------------v-------------------------------------------------+
|                                         STORAGE FABRIC                                             |
|  - mdadm RAID 1 (Metadata 1.2, 1% root reserved blocks)                                            |
|  - Dual-disk EFI / GRUB Bootloader Mirroring                                                        |
|  - Systemd sandboxed units (ProtectSystem=strict, PrivateTmp=yes, CapabilityBoundingSet=)          |
+---------------------------------------------------------------------------------------------------+
                                                  |
+-------------------------------------------------v-------------------------------------------------+
|                                        NETWORKING FABRIC                                            |
|  - Netplan / systemd-networkd (Static IP, MTU, 802.1Q VLAN sub-interfaces)                         |
|  - Linux Network Namespaces (diag-ns, isolated diagnostic traffic)                                 |
|  - nftables (Atomic ruleset, stateful conntrack, SYN rate-limiting, egress NAT)                    |
+---------------------------------------------------------------------------------------------------+
                                                  |
+-------------------------------------------------v-------------------------------------------------+
|                                 TELEMETRY & OBSERVABILITY PIPELINE                                  |
|  - Async Python 3 daemon (telemetryd.py, CAP_SYS_RAWIO, no root)                                   |
|  - smartmontools (S.M.A.R.T. attributes 5, 197, 198) + sysfs thermals + /dev/kmsg                  |
|  - Prometheus (textfile collector) + Grafana + Alertmanager -> Slack/Discord/PagerDuty              |
+---------------------------------------------------------------------------------------------------+
```

## Repository layout

| Path | Phase | Contents |
| --- | --- | --- |
| `phase1-host-provisioning/` | 1 | RAID 1 storage, dual-disk boot mirroring, SSH/sudo hardening, systemd sandboxing profile |
| `phase2-networking/` | 2 | Netplan static/VLAN config, nftables default-deny firewall, diagnostic network namespace |
| `phase3-telemetry/` | 3 | `telemetryd.py` async daemon, Prometheus/Alertmanager/Grafana wiring |
| `phase4-oob-lifecycle/` | 4 | `oob_control.py` Redfish CLI, `fault_drill.sh` fault-injection drill, mock/real BMC options |
| `phase5-physical-dr/` | 5 | Thermal/power profiling script, hardware requirements |
| `docs/` | 5 | Cabling standard, network topology reference, disaster-recovery runbook |
| `lib/common.sh` | — | Shared bash helpers (logging, `SIMULATE=1`, root checks) used by every script |

Each phase directory has its own `README.md` with exact commands. Start
with `phase1-host-provisioning/README.md` and work through in order — later
phases assume earlier ones are in place (e.g. Phase 4's fault drill assumes
Phase 1's RAID array exists).

## Try it without hardware

```
make simulate         # dry-runs every destructive script across all 5 phases
make telemetry-test    # runs telemetryd.py in --mock mode, one poll cycle
make oob-test          # spins up the local Redfish mock, exercises oob_control.py
```

All three have been run against this exact repo as part of building it —
`make simulate` dry-runs cleanly end to end, `telemetry-test` produces valid
Prometheus textfile output and fires a webhook on a sliding-window thermal
breach, and `oob-test` proves `power-cycle` actually flips `PowerState` on
the mock BMC.

## Hardware requirements

See `phase5-physical-dr/README.md` — bare-metal (two disks, one+ NIC, Cat6
tooling) or fully virtualized (2 virtual disks, 2 virtual NICs on any
hypervisor) options, at zero and near-zero cost respectively.

## Technology stack

| Layer | Technology |
| --- | --- |
| Base OS | Debian 12 (Bookworm) or Ubuntu Server 24.04 LTS, minimal |
| Storage | `mdadm` RAID 1, `sgdisk`, `e2fsprogs` |
| Bootloader | GRUB 2 (EFI), `efibootmgr` |
| Process sandboxing | `systemd` (`ProtectSystem`, `NoNewPrivileges`, capabilities, cgroups v2) |
| Networking | Netplan + `systemd-networkd`, `iproute2`, network namespaces |
| Firewall/NAT | `nftables`, `conntrack` |
| Diagnostics | `iperf3`, `tcpdump`, `ss`, `ethtool` |
| Telemetry | Python 3 `asyncio`, `smartmontools`, sysfs, `/dev/kmsg` |
| Observability | Prometheus (textfile collector), Grafana, Alertmanager |
| Out-of-band | Redfish REST (OpenBMC/QEMU or a mockup server), Python `requests` |
| Physical layer | ANSI/TIA-568-B Cat6 |
| Load testing | `stress-ng`, `turbostat`, `powertop` |

## Safety

Nothing in this repo runs automatically. Every script that touches a disk,
the bootloader, sshd, sudoers, or the firewall requires an explicit
environment variable pointing at real device paths, and destructive
operations require typing `yes` to confirm (or `SIMULATE=1`/`CONFIRM=yes`
for a dry run or scripted use). Read each phase's README before running
anything against hardware you care about.
