# Bare-Metal Edge Server & Reliability Platform — Project Specification

Full architecture reference for the platform implemented in this repository.
See `README.md` for the repo layout and quick-start commands, and
`CLAUDE.md` for how this project is developed and reviewed.

---

## Architecture & Topology

```
+---------------------------------------------------------------------------------------------------+
|                                  PHYSICAL & OUT-OF-BAND LAYER                                      |
|  - ANSI/TIA-568-B Cat6 Termination    - AC / Low-Voltage Physical Separation                       |
|  - OpenBMC / Redfish REST API Emulator (Virtual BMC on QEMU / isolated container on veth)           |
+---------------------------------------------------------------------------------------------------+
                                                  |
+-------------------------------------------------v-------------------------------------------------+
|                                     LINUX KERNEL & HARDWARE                                         |
|  - Dual Block Devices (/dev/nvme0n1 + /dev/nvme1n1 or /dev/sda + /dev/sdb)                          |
|  - Thermal Junctions (/sys/class/thermal/)  - Kernel Ring Buffer (/dev/kmsg, MCE/ECC)               |
+---------------------------------------------------------------------------------------------------+
                                                  |
+-------------------------------------------------v-------------------------------------------------+
|                                         STORAGE FABRIC                                              |
|  - mdadm RAID 1 (Metadata 1.2, 1% root reserved blocks)                                             |
|  - Dual-disk EFI / GRUB Bootloader Mirroring                                                         |
|  - Systemd sandboxed units (ProtectSystem=strict, PrivateTmp=yes, CapabilityBoundingSet=)            |
+---------------------------------------------------------------------------------------------------+
                                                  |
+-------------------------------------------------v-------------------------------------------------+
|                                        NETWORKING FABRIC                                             |
|  - Netplan / systemd-networkd (Static IP, MTU 1500/9000, 802.1Q VLAN sub-interfaces)                |
|  - Linux Network Namespaces (netns: 'diag-ns' isolated for diagnostic traffic)                       |
|  - nftables (Atomic ruleset, stateful conntrack, SYN rate-limiting, egress NAT)                      |
+---------------------------------------------------------------------------------------------------+
                                                  |
+-------------------------------------------------v-------------------------------------------------+
|                                 TELEMETRY & OBSERVABILITY PIPELINE                                   |
|  - Async Python 3 Daemon (telemetryd.py with CAP_SYS_RAWIO)                                          |
|  - smartmontools (smartctl S.M.A.R.T. polling: Raw attributes 5, 197, 198)                           |
|  - Prometheus Node Exporter (Textfile Collector) + Grafana Visualization                             |
|  - Alertmanager / HTTP Webhook Dispatcher (JSON payloads to Slack/Discord/PagerDuty)                 |
+---------------------------------------------------------------------------------------------------+
```

---

## Technology Stack Matrix

| Layer | Primary Technology | Supporting Tools / Libraries | Function |
| --- | --- | --- | --- |
| Base OS | Debian 12 (Bookworm) or Ubuntu Server 24.04 LTS (Minimal) | Linux Kernel 6.x, OpenSSH Server | Headless operating system with minimal attack surface |
| Storage Fabric | `mdadm` (Linux Software RAID) | `sgdisk`, `wipefs`, `e2fsprogs` (`mkfs.ext4`) | Block-level mirroring (RAID 1), partition alignment |
| Bootloader | GRUB 2 (EFI / MBR dual-install) | `efibootmgr`, `parted` | Independent bootability from either physical drive |
| Process Sandboxing | `systemd` Security Directives | Linux Namespaces, cgroups v2, Capabilities | Service sandboxing (`ProtectSystem`, `NoNewPrivileges`) |
| Network Configuration | Netplan + `systemd-networkd` | `iproute2` (`ip link`, `ip route`, `ip rule`) | Declarative IP configuration and VLAN tagging (802.1Q) |
| Network Isolation | Linux Network Namespaces (`netns`) | Virtual Ethernet (`veth`) pairs | Complete network stack isolation for diagnostics |
| Packet Filtering & NAT | `nftables` | `conntrack`, `ethtool` | Atomic firewall rules, stateful inspection, and NAT |
| Diagnostics & Auditing | `iperf3`, `tcpdump`, `ss` | `ethtool`, `ip -s link` | Throughput validation, packet captures, socket auditing |
| Hardware Telemetry | Python 3 (`asyncio`) | `smartmontools` (`smartctl`), `sysfs`, `/dev/kmsg` | Reading drive health, core thermals, and bus faults |
| Observability | Prometheus (Textfile Collector) | Grafana, Alertmanager | Metric scraping, real-time dashboards, threshold alerting |
| Out-of-Band Emulation | OpenBMC (in QEMU) or Redfish-Mockup-Server | Docker/Podman, Python `requests` | Emulating chassis controls (IPMI/Redfish) over REST |
| Physical Layer | ANSI/TIA-568-B Cat6 UTP | RJ-45 Crimp Tools, Cable Continuity Tester | 1/10 Gbps physical network cabling |
| Load Testing | `stress-ng` | `powertop`, `turbostat` | Synthetic load generation for thermal/power profiling |

---

## Phase 1 — Host Provisioning, Storage Fabric & Security Baseline

**Objective:** turn raw hardware into an isolated, resilient foundation
where no single drive failure crashes the host or leaves it unbootable.

- **Hardened access:** root SSH login disabled, password auth disabled,
  ed25519-only host/client keys, ciphers restricted to
  `chacha20-poly1305@openssh.com` / `aes256-gcm@openssh.com`, sudo isolated
  in `/etc/sudoers.d/99-sysadmin` with command logging to
  `/var/log/sudo_audit.log`.
- **Storage layer:** two member disks wiped clean (`wipefs`, `sgdisk
  --zap-all`), aligned RAID partitions (typecode `fd00`), `mdadm` RAID 1
  (`/dev/md0`, metadata 1.2), `ext4` with reserved blocks dropped from 5%
  to 1% (`mkfs.ext4 -m 1`), array persisted to `/etc/mdadm/mdadm.conf` and
  baked into initramfs, mounted at `/srv/data` by UUID with
  `noatime,nodev,nosuid`.
- **Bootloader redundancy:** the ESP is synced and `grub-install` is run
  against **both** physical disks independently, so total silicon failure
  of the primary drive doesn't halt the boot process.
- **Process sandboxing:** services run under `systemd` profiles
  (`ProtectSystem=strict`, `PrivateTmp=yes`, `NoNewPrivileges=true`,
  `MemoryDenyWriteExecute=true`).

Implementation: `phase1-host-provisioning/`.

## Phase 2 — Deterministic Networking & Traffic Control

**Objective:** replace dynamic/unpredictable network configuration with
deterministic routing, segmented traffic paths, and a stateful firewall.

- Static IPv4 via Netplan/`systemd-networkd`, explicit MTU, 802.1Q tagged
  VLAN sub-interface.
- Isolated `diag-ns` network namespace (veth pair) so diagnostic traffic
  never touches production routing.
- `nftables`: default-deny input/forward/output, `ct state
  established,related accept`, SYN-flood rate limiting, explicit egress
  allow-list (DNS/NTP/HTTP/HTTPS).
- Validation via `iperf3` (throughput), `tcpdump` with BPF filters
  (cross-VLAN leak checks), `ss -tulpn` (socket exposure).

Implementation: `phase2-networking/`.

## Phase 3 — Hardware Telemetry Daemon & Alert Pipeline

**Objective:** poll low-level physical sensors, flag degradation before
catastrophe, stream metrics to a dashboard.

- `telemetryd.py`: async Python 3 daemon, runs as unprivileged
  `telemetry` user with `CAP_SYS_RAWIO`.
- Polls: S.M.A.R.T. via `smartctl --json` (attributes 5, 197, 198),
  `/sys/class/thermal/thermal_zone*/temp`, `/dev/kmsg` (MCE/ECC/AER).
- 5-minute sliding-window anomaly detection (moving average + drift from
  baseline) rather than firing on a single transient spike.
- Output: Prometheus textfile collector format; alert dispatch via HTTP
  webhook (Slack/Discord/Alertmanager).

Implementation: `phase3-telemetry/`.

## Phase 4 — Out-of-Band (OOB) Control & Server Lifecycle Automation

**Objective:** emulate enterprise remote management (IPMI/Redfish) to
power-cycle, recover, and observe the server without physical presence.

- `oob_control.py`: Redfish REST CLI (`power-status`, `power-cycle`,
  `boot-override --target pxe`, `set-led`).
- BMC emulation options: this repo's stateful mock server, Docker Compose,
  the DMTF Redfish-Mockup-Server, or OpenBMC in QEMU.
- `fault_drill.sh`: automated fault injection & rebuild drill —
  `mdadm --fail` → set fault LED → `mdadm --remove` → (physical/simulated
  swap) → `mdadm --add` → monitor `/proc/mdstat` to completion.

Implementation: `phase4-oob-lifecycle/`.

## Phase 5 — Physical Infrastructure, Cabling & Disaster Recovery Runbook

**Objective:** physical reliability standards (cabling, airflow, power)
and an operational disaster-recovery runbook.

- ANSI/TIA-568-B Cat6, T568B pinout, certified with a continuity tester.
- AC power and low-voltage Ethernet physically separated (EMI); Velcro
  straps only, never zip ties.
- Idle-vs-peak thermal/power profiling under `stress-ng` load.
- Runbook: degraded-array diagnosis, hot-swap procedure, EFI bootloader
  restoration, static network topology reference.

Implementation: `phase5-physical-dr/`, `docs/`.

## Frontend — Web Dashboard

A single-page operations dashboard aggregating the above: power/RAID/
thermal overview, S.M.A.R.T./thermal detail, network state, a live alert
feed (fed by telemetryd's webhook), and Redfish OOB control buttons.
Implementation: `frontend/`.

---

## Hardware Requirements

**Bare-metal:** any x86-64 machine; two identical disks (SATA SSD/HDD or
NVMe) for the RAID 1 mirror; at least one Gigabit NIC.

**Virtualized (this project's actual environment):** a hypervisor VM with
multiple virtual disks and NICs. Every script and config in this repo runs
unmodified against virtual block devices/NICs — only the physical-layer
content in `docs/cabling.md` doesn't apply to a fully virtualized build.

**Disk count note for a 2-disk-total VM (1 OS disk + 1 added disk):**
RAID 1 requires **two disks dedicated to the array**, separate from
whatever disk boots the OS — `phase1-host-provisioning/scripts/
00-wipe-disks.sh` and `01-partition-raid.sh` fully wipe both disks they're
pointed at. Pointing them at your OS disk destroys your running system.
A real, safe RAID 1 test therefore needs **three disks total**: 1 for the
OS, 2 dedicated, blank disks for the mirror.

---

## Testing Status (honesty ledger — see CLAUDE.md's Honesty section)

| Phase | What has been genuinely tested, and where |
| --- | --- |
| 1 — Storage/Boot | Shell logic only, via `SIMULATE=1` dry runs in a cloud sandbox with **no real block devices**. Zero real `mdadm`/`sgdisk`/`grub-install` execution has occurred anywhere yet. |
| 2 — Networking | `nftables.conf` syntax-validated against a real `nft` binary. VLAN/netns/diagnostic scripts are `SIMULATE=1` dry-run only — no real interface was ever created. |
| 3 — Telemetry | `telemetryd.py --mock` actually run end-to-end against a live mock webhook receiver: sliding-window thermal-drift detection fired real alerts, Prometheus textfile output was valid. Real `smartctl`/sysfs/`/dev/kmsg` polling has never been exercised (not installed/available in the sandbox). |
| 4 — OOB/Redfish | `oob_control.py` run for real against a self-written stateful mock Redfish server: `power-cycle` actually flipped mock `PowerState`, `boot-override`/`set-led` actually persisted. No real BMC or OpenBMC/QEMU instance has ever been used. |
| 5 — Physical/DR | Documentation and a `SIMULATE=1`-only profiling script. No physical cabling, thermal, or power measurement has been performed — there is no physical hardware. |
| Frontend | Full local stack (mock Redfish + mock telemetryd + dashboard backend) run together; every API endpoint and OOB button exercised for real against the mocks. |

**Nothing above constitutes real hardware validation.** The next real
milestone is Phase 1 on the user's actual VirtualBox VM, which requires a
third disk (see above) before it's safe to run.
