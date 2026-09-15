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

Implementation: `phase1-host-provisioning/scripts/` (the real, destructive
shell scripts above — hardware/VM-only, `SIMULATE=1`-dry-run-tested so
far) and `phase1-host-provisioning/storage_sim/` (a from-scratch, 50-test
software model of the RAID1 mirror itself — see its own README for the
architecture and the full mapping onto the real `mdadm` concepts above).

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
feed (fed by telemetryd's webhook), Redfish OOB control buttons, and a
Storage Simulation panel driving the Phase 1 RAID1 model live — including
watching a background rebuild's progress bar advance in real time via
polling, a capability the CLI architecturally cannot offer (see
`storage_sim/README.md`'s "known limitations"). Implementation: `frontend/`.

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

Three distinct tiers of "not real hardware" appear below, and they are not
equivalent — see CLAUDE.md's Virtualization section:

- **Simulation-tested**: exercised against a from-scratch software model
  (`storage_sim`, `policy_sim`) with no real or virtual block device or
  network interface involved at all — the "hardware" being modeled never
  existed anywhere in the test.
- **Mock-tested**: exercised against a real, running process that stands
  in for real hardware/firmware (a Redfish HTTP server, a webhook
  receiver), over a real socket/subprocess — the transport and code path
  are real, only the thing on the other end is a stand-in.
- **VM/hardware-tested**: exercised against the user's actual VirtualBox
  VM or real physical hardware. **Nothing in this project has reached
  this tier yet.**

Every row below is additionally tagged with one of the four required
classification labels (`IMPLEMENTED + TESTED`, `IMPLEMENTED + SIMULATION
TESTED`, `IMPLEMENTED + NOT YET VALIDATED`, `NOT IMPLEMENTED`). Per
CLAUDE.md's Honesty section and this session's explicit instruction,
`IMPLEMENTED + TESTED` is reserved for something exercised against the
*real* target it claims to work with (a real BMC, a real block device, a
real kernel network stack) — mock- and simulation-tested code is always
labeled `IMPLEMENTED + SIMULATION TESTED` here, never plain `TESTED`,
even though every test asserting it actually ran and passed in this
sandbox.

| Feature | Classification | What has been genuinely tested, and where |
| --- | --- | --- |
| Phase 1 — real provisioning scripts (`00`–`06-*.sh`) | IMPLEMENTED + SIMULATION TESTED (shell logic only) | `phase1-host-provisioning/scripts/*.sh` — `SIMULATE=1` dry runs only, in a cloud sandbox with **no real block devices**. Zero real `mdadm`/`sgdisk`/`grub-install` execution has occurred anywhere. |
| Phase 1 — `storage_sim` RAID1 logic | IMPLEMENTED + SIMULATION TESTED (real, executed code) | `phase1-host-provisioning/storage_sim/` — 74 automated tests plus a scripted, asserting demo, all actually run: normal read/write, degraded mode, member fail/remove/add, background rebuild (including one interrupted by a second failure and one by a clean shutdown), silent-corruption detection + self-heal (including the double-corruption/unrecoverable case), `scrub`, cross-process reassembly (stale-event-count exclusion, untrusted-role-state exclusion, corrupted-superblock skip), and a cooperative rebuild-stop race fix verified by a 15-iteration stress test. This validates the *logic*; it is a software model, not mdadm, and says so throughout its own README. |
| Phase 1 — `RealBlockDevice` adapter | IMPLEMENTED + NOT YET VALIDATED (against a real device; SIMULATION TESTED against a stand-in) | `phase1-host-provisioning/storage_sim/tests/test_real_block_device.py` — 15 tests, all against a plain temp file standing in for a device, including `RAID1Array` running unmodified over two `RealBlockDevice` instances. Proves the safety-gating (dry-run default, three independent opt-ins required, hardcoded boot-disk denylist) and the I/O code path. Has **never** opened a real `/dev/sdX` — see `storage_sim/README.md`'s dedicated section. |
| Phase 1 — `plan_from_lsblk.py` safe real-disk planner | IMPLEMENTED + TESTED (against synthetic `lsblk -J` fixtures — not a real disk enumeration) | `phase1-host-provisioning/scripts/tests/test_plan_from_lsblk.py` — 17 tests against hand-built JSON fixtures covering in-use detection (mountpoint/fstype/RO/partition anywhere in a disk's subtree) and the blank-count gate. Never run against this sandbox's own real `lsblk` output (no block devices to enumerate here); will be exercised for real only once the user supplies real `lsblk -J` output per this project's hard safety boundary. |
| Phase 2 — `nftables.conf` (real config) | IMPLEMENTED + SIMULATION TESTED (syntax only) | Syntax-validated against a real `nft -c` binary (`make lint`). The ruleset has never been loaded (`nft -f`) or exercised against real traffic — loading it into this sandbox's own network namespace was attempted once and blocked by the harness's own security policy, so `policy_sim/` (below) was built instead of attempting a workaround. |
| Phase 2 — `policy_sim` firewall decision logic | IMPLEMENTED + SIMULATION TESTED | `phase2-networking/policy_sim/` — 34 automated tests against a from-scratch Python model of the INPUT/FORWARD/OUTPUT chains and the token-bucket rate limiter, including a literal-text consistency check against `nftables.conf` itself so the two can't silently drift apart. No packet has ever actually traversed a real or virtual NIC under this ruleset. |
| Phase 2 — VLAN/netns/diagnostic shell scripts | IMPLEMENTED + SIMULATION TESTED (shell logic only) | `SIMULATE=1` dry-run only — no real interface, VLAN, or network namespace was ever created. |
| Phase 3 — `telemetryd.py` daemon | IMPLEMENTED + SIMULATION TESTED (automated suite: 29 tests) | `phase3-telemetry/telemetryd/tests/` — SlidingWindow math, Prometheus textfile output, WebhookSink dispatch (including a genuine unreachable-endpoint failure path), a full TelemetryDaemon integration run, `load_config()`/`parse_args()`/`main()` end-to-end (including clean Ctrl-C shutdown), all as real automated tests. Two tests exercise code paths the *original* manual verification never reached: the real (non-mock) sysfs-thermal-glob path (via a configurable `base` added to `ThermalCollector` specifically to make this testable) and the real (non-mock) `/dev/kmsg`-tailing fault-detection path (against a real temp file standing in for kmsg). Real `smartctl`/real `/dev/kmsg`/real sysfs on an actual machine have still never been exercised (not installed/available in this sandbox). |
| Phase 4 — `oob_control.py` Redfish CLI | IMPLEMENTED + SIMULATION TESTED (mock-tested; automated suite: 22 tests) | `phase4-oob-lifecycle/tests/test_oob_control.py` — every RedfishClient action and CLI command path against `redfish_mock_server.py` running in-process, a consistency check that `RESET_TYPE_MAP` and the mock server's own reset-type table can't silently drift apart, CLI argument-validation (including missing `--base-url`/subcommand, env-var defaults, explicit-flag overrides), a genuine unreachable-endpoint error-handling path, and — by capturing the real `Authorization` header the mock server received — proof that HTTP Basic Auth is actually sent, not just parsed. No real BMC or OpenBMC/QEMU instance has ever been used. |
| Phase 4 — `fault_drill.sh` fault-injection drill | IMPLEMENTED + SIMULATION TESTED (shell logic; automated suite: 7 tests) | `phase4-oob-lifecycle/tests/test_fault_drill.py` — runs the real script as a subprocess under `SIMULATE=1` and asserts the exact expected `mdadm`/`set-led` command sequence, in order, with every mdadm-looking line confirmed marked `(simulated)`, plus a parameterized run proving no hardcoded device-name fallback exists. The script's real-mode branch (actual `mdadm --fail` etc. against a real array) has never been exercised, and won't be without real/VM hardware. |
| Phase 5 — Physical/DR | IMPLEMENTED + SIMULATION TESTED (shell logic) + docs | A `SIMULATE=1`-only thermal/power profiling script and written documentation (`docs/runbook.md`, `docs/cabling.md`, `docs/network-topology.md`). No physical cabling, thermal, or power measurement has been performed — there is no physical hardware. |
| Frontend (`frontend/`) dashboard | IMPLEMENTED + SIMULATION TESTED (mock-tested; automated suite: 15 tests, real HTTP) | `frontend/tests/` — a real dashboard server and a real mock Redfish server, both on random ports, hit over actual HTTP (not direct handler calls): static serving + path-traversal check, every OOB action, the simulate-forced drill endpoint, an alerts ingest/list roundtrip, and a full `/api/simstorage/*` lifecycle including polling real HTTP responses until a background rebuild finishes. |
| Real `mdadm`/`sgdisk`/GRUB integration on the user's VM | NOT IMPLEMENTED | Blocked on the user supplying real `lsblk -J` output after adding a third disk, per this project's hard safety boundary — no destructive storage command has been run, or will be run, against a guessed device name. |
| Real OpenBMC/QEMU or physical BMC integration | NOT IMPLEMENTED | No OpenBMC/QEMU virtual BMC has been stood up in this sandbox; all Redfish testing to date is against the hand-written mock server, not a spec-compliant BMC implementation. |

**Total automated tests, all actually run in this sandbox as of this
session:** 198 (`make unit-test`) — storage_sim 74, plan_from_lsblk 17,
policy_sim 34, telemetryd 29, oob_control+fault_drill 29, frontend 15.

**Nothing above constitutes real hardware or real-VM validation.** The
next real milestone is Phase 1 on the user's actual VirtualBox VM, which
requires a third disk (see above) before it's safe to run.
`storage_sim`'s value is narrowing that step: the RAID *logic* (mirroring,
degraded mode, rebuild, corruption/staleness handling) is already
implemented, tested, and documented — what remains for real-hardware
validation is integration with actual `/dev/sdX` devices via
`phase1-host-provisioning/scripts/`, not designing the logic itself.
