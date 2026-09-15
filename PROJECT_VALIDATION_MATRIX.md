# Project Validation Matrix

Requirement-by-requirement comparison of this repository against
`PROJECT_SPEC.md`, as of this audit. This supersedes the phase-level
table in `PROJECT_SPEC.md`'s "Testing Status" section for detail (that
table still stands as the phase-level summary); this document is the
feature-level breakdown behind it.

## Legend

| Code | Meaning |
| --- | --- |
| 🟢 GREEN | IMPLEMENTED + TESTED — exercised against its real target with no stand-in (real OS/file behavior, real algorithm, real socket) |
| 🟡 YELLOW | IMPLEMENTED + SIMULATION TESTED — exercised only via a software model, a mock service, a dry run, or synthetic fixtures standing in for the real hardware/OS/network the requirement targets |
| 🟠 ORANGE | IMPLEMENTED + NOT YET VALIDATED — the code/config/doc exists but has no automated test and no dry-run/syntax check has been run against it, or its central claim remains completely unverified |
| 🔴 RED | NOT IMPLEMENTED — no file, script, or integration exists for this requirement |

**Ground rule applied throughout:** GREEN is never used for a claim about
real hardware, a real kernel network stack, a real BMC, or real SMART/
sysfs data — nothing in this repository has reached that tier yet (see
`PROJECT_SPEC.md`). GREEN appears only for pure-software components
(math, file-format writers, CLI argument parsing) whose entire contract
is software behavior with no hardware/OS/network claim to hedge on. A
passing mock or simulation test is always labeled YELLOW, never GREEN. A
`SIMULATE=1` dry run is always labeled YELLOW (it proves the shell logic
runs and prints the right thing) and is never treated as real execution.

**Sandbox tool inventory** (checked directly while writing this matrix —
explains why several rows below say "never even attempted," not just
"attempted and not fully validated"): `mdadm`, `sgdisk`, `ip`, `ss`,
`tcpdump`, `iperf3`, `grub-install`, `efibootmgr`, `smartctl`, `sensors`,
`turbostat`, `stress-ng`, and `sshd` are **not installed** in this
sandbox. `wipefs`, `mkfs.ext4`, `visudo`, `systemctl`, `nft`, and `docker`
**are** installed, but none of them has been pointed at real project
state (no real disk was wiped/formatted, no real ruleset was loaded, no
`docker compose up` was ever run for this project).

**Supporting evidence for every YELLOW/GREEN row below:** `make lint`,
`make unit-test` (198 tests), `make sim-test`, and `make simulate` were
all run clean, and `make unit-test`/`make lint` were additionally
repeated 5 consecutive times with identical results, immediately before
this audit (see the preceding turn in this conversation). Per-row test
file/class references below are what those 198 tests break down into.

---

## Phase 1 — Host Provisioning, Storage Fabric & Security Baseline

| # | Requirement | Class | Implementation file(s) | Test(s) covering it | Current validation method | Remaining validation needed | VM required? | Physical HW required? |
|---|---|---|---|---|---|---|---|---|
| 1 | Wipe both RAID member disks (`wipefs`, `sgdisk --zap-all`) | 🟡 | `phase1-host-provisioning/scripts/00-wipe-disks.sh` | None (no unittest for this script) | `bash -n` syntax check (`make lint`); `SIMULATE=1` dry run (`make simulate`) — every command printed as `+ (simulated) ...`, never executed; `wipefs` itself is installed here but was never invoked against a real device | Run for real against a disk `plan_from_lsblk.py` confirmed blank, from real `lsblk -J` output | Yes | No |
| 2 | Create aligned, RAID-typed partitions (`sgdisk`, typecode `fd00`) on both disks | 🟡 | `phase1-host-provisioning/scripts/01-partition-raid.sh` | None | `bash -n` + `SIMULATE=1` dry run only; `sgdisk` is **not installed** in this sandbox, so even a syntax/no-op invocation of the real binary has never happened here | Run for real on the VM (has `sgdisk`); confirm `fd00` typecode and alignment with `sgdisk -p` after | Yes | No |
| 3 | Assemble `mdadm` RAID 1 (metadata 1.2), persist to `/etc/mdadm/mdadm.conf` + initramfs | 🟡 | `phase1-host-provisioning/scripts/02-assemble-raid.sh`, `phase1-host-provisioning/config/mdadm.conf.example` | None (real script); RAID1 *logic* is covered by `storage_sim` — see rows 9–13, a separate software model, not this script | `bash -n` + `SIMULATE=1` dry run; `mdadm` is **not installed** in this sandbox | Run for real on the VM; confirm `cat /proc/mdstat` shows `[UU]` and array survives a reboot via `mdadm.conf`+initramfs | Yes | No |
| 4 | Format `ext4` with 1% reserved blocks, mount by UUID with `noatime,nodev,nosuid` | 🟡 | `phase1-host-provisioning/scripts/03-format-mount.sh`, `phase1-host-provisioning/config/fstab.snippet` | None | `bash -n` + `SIMULATE=1` dry run; `mkfs.ext4` **is** installed here but was never run against any real block device — only ever printed as `(simulated)` | Run for real against `/dev/md0` on the VM; confirm `tune2fs -l` reserved-block % and `mount` options | Yes | No |
| 5 | Install GRUB independently on **both** disks (boot survives total loss of the primary drive) | 🟡 | `phase1-host-provisioning/scripts/04-bootloader-mirror.sh` | None | `bash -n` + `SIMULATE=1` dry run; `grub-install`/`efibootmgr` are **not installed** in this sandbox | Run for real on the VM, then the actual proof of this requirement: detach/disable the primary virtual disk and confirm the VM still boots from the secondary | Yes | No (a VM can fully prove this — pulling a *virtual* disk is a legitimate test of "boots from either disk") |
| 6 | SSH hardening: no root/password login, ed25519-only, restricted ciphers/MACs/KEX | 🟡 | `phase1-host-provisioning/scripts/05-harden-ssh.sh`, `phase1-host-provisioning/config/sshd_config.d/99-hardening.conf` | None | `bash -n` + `SIMULATE=1` dry run — note this script's own internal `sshd -t` syntax check is *itself* skipped under `SIMULATE=1` (wrapped in the shared `run()` helper), and `sshd` is **not installed** in this sandbox, so the config's syntax has never been checked by a real `sshd` at all | Install on the VM, run real `sshd -t`, reload, then confirm from a second terminal: password auth rejected, ed25519 key accepted, `AuthenticationMethods publickey` enforced | Yes | No |
| 7 | Sudoers isolation (`/etc/sudoers.d/99-sysadmin`) with full command audit logging | 🟡 | `phase1-host-provisioning/scripts/06-sudoers-audit.sh`, `phase1-host-provisioning/config/sudoers.d/99-sysadmin` | None | `bash -n` + `SIMULATE=1` dry run of the script (the script's own internal `visudo -c -f` check is itself skipped under `SIMULATE=1`). Separately, during this audit, `visudo -c -f` **was** run directly against the real config file with the real installed `visudo` binary — `parsed OK`, exit 0 — so the sudoers syntax itself is genuinely validated; the file has still never been installed to `/etc/sudoers.d/`, and no audit-log behavior has ever been observed | Install on the VM, confirm `sudo` command auditing actually appears in `/var/log/sudo_audit.log`, confirm the `telemetry` user's narrow `NOPASSWD` grant works and nothing broader does | Yes | No |
| 8 | `systemd` sandboxing profile (`ProtectSystem=strict`, `NoNewPrivileges`, `MemoryDenyWriteExecute`, etc.) | 🟠 | `phase1-host-provisioning/systemd/hardened.service.template`, `phase3-telemetry/telemetryd/telemetryd.service` | None | **None at all** — unlike every script above, this isn't even dry-run-tested: there is no `systemd-analyze verify` step in `make lint`/`make simulate`, and it is a static reference template, never rendered or loaded by a real `systemd` in this sandbox | Run `systemd-analyze verify` against both units on the VM; then `systemctl start` a real unit built from the template and confirm it stays up under the full directive set (some combinations, e.g. `ProtectKernelModules=true` + a service that legitimately needs a kernel module, can be self-defeating and this has never been checked) | Yes | No |
| 9 | RAID1 mirrored read/write logic (normal mode) | 🟡 | `phase1-host-provisioning/storage_sim/raid1.py`, `block_device.py`, `manager.py` | `storage_sim/tests/test_raid1_normal.py` (`TestRAID1Normal`, 6 tests) | Real, executed Python code, real assertions — but against a from-scratch **software model** of RAID1, not `mdadm` or any block device. `mdadm` is not installed in this sandbox and has never been invoked | Cross-check: after real `mdadm` RAID1 is assembled on the VM (row 3), manually confirm its observed behavior (mirrored writes, `/proc/mdstat` states) matches what this model predicts — this model does not itself become "tested against mdadm" by that, but it validates the mental model the real scripts were built from | No (the model itself needs no VM) | No |
| 10 | RAID1 degraded-mode read/write | 🟡 | `storage_sim/raid1.py` | `storage_sim/tests/test_raid1_degraded.py` (`TestRAID1Degraded`, 9 tests) | Same as row 9 — software model only | Same as row 9 | No | No |
| 11 | Member fail/remove/add + background rebuild with live progress | 🟡 | `storage_sim/raid1.py`, `manager.py` | `storage_sim/tests/test_raid1_rebuild.py` (`TestRAID1Rebuild`, 10 tests) | Software model only, including a race-condition fix (cooperative rebuild-stop) verified by a 15-iteration internal stress loop in `test_close_all_during_active_rebuild_never_races` | Real `mdadm --fail`/`--remove`/`--add` + `watch /proc/mdstat` on the VM (this is exactly what `fault_drill.sh`, row 33, automates) | Yes (for the real-mdadm comparison) | No |
| 12 | Silent-corruption detection, self-heal, and `scrub` | 🟡 | `storage_sim/block_device.py` (per-block SHA-256 checksum — an explicit simulation addition, not a stock `mdadm` behavior), `raid1.py` | `storage_sim/tests/test_raid1_corruption.py` (`TestRAID1Corruption`, 7 tests) | Software model only. `storage_sim/README.md` is explicit that stock `mdadm` RAID1 has **no** block-level checksum of its own — this simulation adds one deliberately and documents that it is not claiming to replicate real `mdadm` here | None applicable to real `mdadm` (this specific capability is a documented simulation enhancement, not a gap to close against real hardware) | No | No |
| 13 | Cross-process array persistence/reassembly (superblock, event counts, member roles) | 🟡 | `storage_sim/superblock.py`, `manager.py` | `storage_sim/tests/test_manager.py` (`TestArrayManagerCreation`, `TestArrayManagerFailReplaceRebuild`, `TestArrayManagerAssembly`, `TestArrayManagerCrossProcessLifecycle`; 16 tests) | Software model only | Real `mdadm --assemble --scan` after a real reboot on the VM, to confirm real superblock persistence behaves as this model assumes | Yes | No |
| 14 | Safety-gated adapter letting the RAID1 logic run against a real block-device path | 🟠 | `phase1-host-provisioning/storage_sim/real_block_device.py` | `storage_sim/tests/test_real_block_device.py` (`TestSafetyGating`, `TestRealIoAgainstAStandInFile`, `TestRAID1ArrayOverRealBlockDevices`; 15 tests) | All 15 tests run against a plain temp file, **not a device** — proves the safety gating (dry-run default; `allow_real_io` alone is insufficient; `i_have_confirmed_with_lsblk` required; hardcoded boot-disk-prefix denylist) and the `os.pread`/`os.pwrite` code path. Has never opened `/dev/sdX`, never seen real alignment/`O_DIRECT`/latency/concurrent-access behavior | Construct one instance with `allow_real_io=True, i_have_confirmed_with_lsblk=True` against a disk `plan_from_lsblk.py` confirmed blank, run a small read/write/checksum smoke test before trusting it further | Yes | No |
| 15 | Safe planner that classifies real disks from `lsblk -J` before any destructive command runs | 🟡 | `phase1-host-provisioning/scripts/plan_from_lsblk.py` | `phase1-host-provisioning/scripts/tests/test_plan_from_lsblk.py` (17 tests) | 17 tests against **hand-built JSON fixtures** shaped like real `lsblk -J` output (mountpoint/fstype/RO/partition-anywhere-in-subtree detection, the exactly-2-blank-disks gate). Never run against this sandbox's own `lsblk` (no block devices exist here to enumerate) | Run against the VM's real `lsblk -J` output once the third disk is added — this is literally the next required step per this project's hard safety boundary, and per `CLAUDE.md`, blocks all further real-device work until it happens | Yes | No |

---

## Phase 2 — Deterministic Networking & Traffic Control

| # | Requirement | Class | Implementation file(s) | Test(s) covering it | Current validation method | Remaining validation needed | VM required? | Physical HW required? |
|---|---|---|---|---|---|---|---|---|
| 16 | Static IPv4 + 802.1Q tagged VLAN sub-interface via Netplan/`systemd-networkd` | 🟠 | `phase2-networking/netplan/01-netcfg.yaml` | None | Generic `yaml.safe_load()` syntax check only (`make lint`'s config-validation step) — confirms the file is valid YAML, nothing about whether netplan's own schema accepts it or whether `systemd-networkd` would render it correctly. `ip`/`netplan` are not installed here | Run `netplan generate && netplan apply` for real on the VM; confirm `ip -d link show vlan100` shows the tag and `10.10.100.10/24` is bound | Yes | No |
| 17 | Isolated `diag-ns` network namespace + veth pair, so diagnostics never touch production routing | 🟡 | `phase2-networking/scripts/setup-diag-netns.sh` | None | `bash -n` + `SIMULATE=1` dry run; `ip` is not installed here, so even `ip netns add` has never been attempted for real | Run for real on the VM; confirm `ip netns exec diag-ns ip addr` shows only the link-local `/30` and that egress is NATed per `nftables.conf`, never routed to the production LAN | Yes | No |
| 18 | Imperative 802.1Q VLAN sub-interface script (ad-hoc alternative to Netplan) | 🟡 | `phase2-networking/scripts/setup-vlan.sh` | None | `bash -n` + `SIMULATE=1` dry run only | Run for real on the VM; confirm with `ip -d link show` that the VLAN tag and IP match `VLAN_ID`/`VLAN_IP` | Yes | No |
| 19 | `nftables`: default-deny input/forward/output, stateful conntrack, SYN-flood rate limiting, explicit egress allow-list, NAT for `diag-ns` | 🟡 | `phase2-networking/nftables/nftables.conf` | `phase2-networking/policy_sim/tests/test_firewall.py` (34 tests) exercises the **decision logic model**, not this file directly | `nft -c -f nftables.conf` — a **real** `nftables` binary (`nftables v1.0.9`, confirmed installed and run during this audit) parses the full ruleset as real nftables grammar, exit 0. This is genuine syntax validation, not a no-op. It has **never** been loaded (`nft -f`) or seen a single real packet — an attempt to load it into this sandbox's own network namespace was previously blocked by the harness's own security policy, which is why `policy_sim/` (row 20) exists as a separate decision-logic model instead | Load for real on the VM (`nft -f /etc/nftables.conf`); confirm with real traffic: SSH accepted only from the management VLAN, SYN flood past 20/s dropped, egress blocked on a port not in the allow-list, `diag-ns` NAT egress works and cannot reach the production LAN | Yes | No |
| 20 | Firewall decision-logic model, cross-checked against the literal ruleset text | 🟡 | `phase2-networking/policy_sim/firewall.py` | `phase2-networking/policy_sim/tests/test_firewall.py` (34 tests, including `TestConsistencyWithRealConfigFile`) | Real, executed Python model of the INPUT/FORWARD/OUTPUT chains and the token-bucket rate limiter, with a literal-text consistency check against `nftables.conf` so the two can't silently drift apart. No packet has ever traversed a real or virtual NIC under this logic | Same as row 19 — this model is validated by design, not by more testing of itself; what remains is confirming the real ruleset it's modeled on actually behaves this way | No | No |
| 21 | Network diagnostics: `iperf3` throughput, `tcpdump` cross-VLAN leak check, `ss` socket audit | 🟡 | `phase2-networking/scripts/network-diagnostics.sh` | None | `bash -n` + `SIMULATE=1` dry run; `iperf3`, `tcpdump`, and `ss` are **all absent** from this sandbox, so none of the three checks this script performs has ever run for real anywhere in this project | Run for real on the VM with `IPERF_TARGET` set; visually confirm the `tcpdump` capture shows zero cross-VLAN leakage and `ss -tulpn` matches the intended exposed-socket list | Yes | No |

---

## Phase 3 — Hardware Telemetry Daemon & Alert Pipeline

| # | Requirement | Class | Implementation file(s) | Test(s) covering it | Current validation method | Remaining validation needed | VM required? | Physical HW required? |
|---|---|---|---|---|---|---|---|---|
| 22 | Async daemon core, runs as unprivileged `telemetry` user with `CAP_SYS_RAWIO` | 🟡 | `phase3-telemetry/telemetryd/telemetryd.py` (`TelemetryDaemon`), `telemetryd.service` | `phase3-telemetry/telemetryd/tests/test_telemetryd.py` — daemon integration tests | The daemon's control flow (poll loop, per-source dispatch, shutdown) is exercised for real in `--mock` mode. The **user/capability** part of this requirement — actually running as `telemetry` with `CAP_SYS_RAWIO` and *not* root — has never been done; the daemon has always run as whatever user this sandbox's shell is | Deploy the systemd unit on the VM as the real `telemetry` user with `setcap`/`CAP_SYS_RAWIO`, confirm `smartctl` access works **without** root | Yes | No |
| 23 | S.M.A.R.T. polling via `smartctl --json` (attributes 5, 197, 198) | 🟡 | `telemetryd.py` (`SmartCollector`) | `test_telemetryd.py` | `smartctl` is **not installed** in this sandbox. All testing is against `--mock` synthesized values; `SmartCollector`'s real, non-mock code path (building the `smartctl` command, parsing real JSON output) has never executed once | Run non-mock on the VM against a real virtual disk; confirm attributes 5/197/198 parse correctly from genuine `smartctl --json` output (virtual disks may report these attributes differently or not at all — a genuine open question this sandbox cannot answer) | Yes | Only for validating against a real physical drive's real wear data — a VM's virtual SMART passthrough (if the hypervisor provides any) is a partial substitute at best |
| 24 | Thermal polling via `/sys/class/thermal/thermal_zone*/temp` | 🟡 | `telemetryd.py` (`ThermalCollector`) | `test_telemetryd.py` | The real (non-mock) sysfs-glob code path **is** exercised — against fake files standing in for `/sys/class/thermal` (via a configurable `base` path added specifically to make this testable), not this sandbox's real thermal zones (there may be none, or their layout may differ) | Run non-mock on the VM/real hardware and confirm real thermal zone files parse and produce sane values | Yes (to see whatever the VM's virtual thermal exposure looks like, if any) | Yes, for a real temperature reading — a VM's virtualized thermal zones (if present at all) don't reflect real silicon temperature |
| 25 | Kernel ring buffer fault detection (`/dev/kmsg`: MCE/ECC/AER) | 🟡 | `telemetryd.py` (`KmsgCollector`) | `test_telemetryd.py` | The real (non-mock) `/dev/kmsg`-tailing code path **is** exercised — against a real temporary file standing in for `/dev/kmsg`, not the genuine kernel ring buffer | Run non-mock on the VM against the real `/dev/kmsg`; this also requires *injecting* a real or realistic MCE/EDAC/AER log line to prove the regex actually matches genuine kernel output, which has never been done | Yes | Yes, for a real MCE/ECC/AER event — a VM will rarely if ever produce a genuine one; testing the detection logic against a real fault needs physical hardware with ECC RAM (or a fault injector) |
| 26 | 5-minute sliding-window anomaly detection (moving average + baseline drift) | 🟢 | `telemetryd.py` (`SlidingWindow`) | `test_telemetryd.py` | Pure math/data-structure component with no hardware or OS dependency — genuinely, fully tested with real inputs and real assertions against real target behavior (there is no "real" version of this beyond the algorithm itself) | None outstanding for the algorithm itself; only relevant once fed real sensor data (rows 23–25) | No | No |
| 27 | Prometheus textfile collector output | 🟢 | `telemetryd.py` (`PrometheusTextfileSink`) | `test_telemetryd.py` | Writes a real file to a real path and reads it back, asserting genuine Prometheus text-exposition-format output — no external system needed to validate this format, and none was stood in for | Confirm a real `node_exporter --collector.textfile.directory=...` actually scrapes the file without error (a formatting edge case node_exporter is stricter about than this test might be) | Yes (or any Linux host with node_exporter) | No |
| 28 | HTTP webhook alert dispatch (Slack/Discord/Alertmanager JSON payloads) | 🟡 | `telemetryd.py` (`WebhookSink`) | `test_telemetryd.py` | Real HTTP POST code path exercised against a real local test HTTP server (including a genuine unreachable-endpoint failure test) — never sent to an actual Slack/Discord/PagerDuty/Alertmanager endpoint | Point `webhook_url` at a real Alertmanager or Slack incoming-webhook URL and confirm a real alert arrives correctly formatted | No (any network-reachable host works — a VM is convenient but not required) | No |
| 29 | CLI/config: `load_config()`, `parse_args()`, `main()` (incl. `--mock`, `--once`, clean Ctrl-C shutdown) | 🟢 | `telemetryd.py` | `test_telemetryd.py` (`TestLoadConfig`, `TestParseArgs`, `TestMainEntryPoint`) | Real argv, real config files (including the no-path/missing-file/empty-YAML/PyYAML-unavailable branches), real `main()` execution end-to-end, including a real `KeyboardInterrupt` shutdown path — this is the daemon's own control-flow plumbing, fully exercised for real; it does not itself validate the hardware-facing collectors it calls (rows 23–25) | None outstanding for this layer itself | No | No |
| 30 | Observability wiring: Prometheus scrape config, alert rules, Alertmanager routing, Grafana dashboard | 🟠 | `phase3-telemetry/prometheus/prometheus.yml.example`, `alert.rules.yml`, `alertmanager/alertmanager.yml.example`, `grafana/dashboard.json` | None | Generic syntax validation only (`yaml.safe_load()` for the `.yml` files, `json.load()` for the dashboard) via `make lint` — confirms the files parse, says nothing about whether Prometheus/Alertmanager/Grafana actually accept and apply them correctly | Load all four into a real (or containerized) Prometheus + Alertmanager + Grafana stack; confirm the alert rules actually fire off real `telemetryd` metrics and the dashboard renders | No (any Docker host works — `docker` **is** installed in this sandbox, so this specific row could be closed without a VM, but it hasn't been) | No |

---

## Phase 4 — Out-of-Band (OOB) Control & Server Lifecycle Automation

| # | Requirement | Class | Implementation file(s) | Test(s) covering it | Current validation method | Remaining validation needed | VM required? | Physical HW required? |
|---|---|---|---|---|---|---|---|---|
| 31 | Redfish REST CLI: `power-status`, `power-cycle`, `boot-override --target pxe`, `set-led` | 🟡 | `phase4-oob-lifecycle/oob_control.py` | `phase4-oob-lifecycle/tests/test_oob_control.py` (22 tests) | Every command and every reset-type/boot-target exercised over real HTTP against this repo's own mock Redfish server (real sockets, real JSON, real HTTP Basic Auth header verified on the wire) — **no real BMC or OpenBMC/QEMU instance has ever received one of these requests** | Point `--base-url` at a real BMC (physical iDRAC/iLO, or OpenBMC-in-QEMU) and confirm each command actually does the real thing (this is the single largest remaining gap in the whole project — every other subsystem has at least a plausible non-hardware path to close, this one architecturally needs *some* BMC, real or virtualized) | Yes (OpenBMC-in-QEMU can satisfy this without physical hardware) | No (OpenBMC-in-QEMU is spec's own explicitly-sanctioned substitute) — only for testing against a **specific vendor's real** BMC firmware would physical hardware be needed |
| 32 | Stateful mock BMC standing in for real Redfish hardware during development | 🟡 | `phase4-oob-lifecycle/redfish-mockup/redfish_mock_server.py` | `test_oob_control.py` (all 22 tests exercise it) | Real HTTP server, real mutable state (`PowerState`/`BootSourceOverride`/`IndicatorLED` genuinely persist across requests) — but it is, by design, the simulated stand-in itself, not a spec-compliant Redfish implementation (it only knows the 4 endpoints `oob_control.py` calls) | N/A for its own purpose (it's a test fixture, not a production component); the requirement it's meant to unblock (row 31) still needs a real/virtualized BMC behind it | No | No |
| 33 | `fault_drill.sh`: `mdadm --fail` → set fault LED → `mdadm --remove` → (swap) → `mdadm --add` → monitor `/proc/mdstat` to completion | 🟡 | `phase4-oob-lifecycle/fault_drill.sh` | `phase4-oob-lifecycle/tests/test_fault_drill.py` (7 tests) | Runs the **real script** as a real subprocess under `SIMULATE=1`, asserting the exact command sequence and order, every `mdadm`-looking line confirmed marked `(simulated)`, and a parameterized run proving no hardcoded device-name fallback exists. `mdadm` is not installed in this sandbox — the real-mode branch (`SIMULATE` unset) has never executed a single real command | Run non-`SIMULATE` on the VM against a real degraded array and a real (or OpenBMC) BMC; watch a genuine `/proc/mdstat` recovery percentage to completion | Yes | No |
| 34 | BMC emulation option: Docker Compose wrapper around the mock server | 🟠 | `phase4-oob-lifecycle/redfish-mockup/docker-compose.yml` | None | The file exists and wraps the already-tested mock server (row 32), but `docker compose up` has **never been run** in this project — despite `docker` itself being installed in this sandbox | Run `docker compose up -d` and repeat a subset of `test_oob_control.py`'s scenarios against the containerized instance over its published port | No (any Docker host, including this sandbox, could close this row) | No |
| 35 | BMC emulation options: DMTF Redfish-Mockup-Server / OpenBMC-in-QEMU | 🔴 | None — `redfish-mockup/README.md` documents both as `pip install`/QEMU instructions only; no integration code, script, or test exists for either anywhere in this repository | None | Documentation only | Actually stand up one of the two, point `oob_control.py` at it, and run the existing test scenarios (or new ones) against it | Yes, for OpenBMC-in-QEMU | No |

---

## Phase 5 — Physical Infrastructure, Cabling & Disaster Recovery Runbook

| # | Requirement | Class | Implementation file(s) | Test(s) covering it | Current validation method | Remaining validation needed | VM required? | Physical HW required? |
|---|---|---|---|---|---|---|---|---|
| 36 | ANSI/TIA-568-B Cat6 structured cabling, T568B pinout, continuity-tester-certified | 🔴 | `docs/cabling.md` (complete written standard/procedure) | None — not a testable artifact in software | The document itself is complete and accurate as a *reference*; **zero physical cables have been terminated or tested** — there is no cabling to certify | Physically terminate and continuity-test real Cat6 runs against this standard | No | Yes — this is inherently a physical-world action |
| 37 | AC power / low-voltage Ethernet physical separation (EMI), Velcro not zip ties | 🔴 | `docs/cabling.md` | None | Documentation only; no physical rack, cabling, or power run exists to inspect | Physically route and dress cabling per the doc, inspect for AC/low-voltage separation | No | Yes |
| 38 | Idle-vs-peak thermal/power profiling under `stress-ng` load | 🟡 | `phase5-physical-dr/scripts/thermal_power_profile.sh` | None | `bash -n` + `SIMULATE=1` dry run only; `sensors`, `turbostat`, and `stress-ng` are **all absent** from this sandbox, so none of the three measurements this script takes has ever been produced for real, simulated or otherwise | Run for real (needs `stress-ng`/`sensors`/`turbostat` installed); compare idle vs. peak numbers | Partially — a VM can run `stress-ng` and produce *some* numbers, but they describe the hypervisor host's shared silicon, not this VM's dedicated thermal/power envelope | Yes, for a real, meaningful thermal/power profile |
| 39 | DR runbook: degraded-array diagnosis, hot-swap procedure, EFI bootloader restoration, escalation checklist | 🟠 | `docs/runbook.md` | None (procedural document, not code) | The runbook is complete, cross-referenced to the real scripts/commands it describes, and (as of this session) explicitly documents its own unvalidated status in a dedicated "Section 0." No step in it has ever actually been walked through, dry-run or otherwise — it is prose describing real commands, not an automated or automatable artifact itself | Actually perform a hot-swap drill on the VM end-to-end (this is exactly what `fault_drill.sh`, row 33, is for automating the mdadm/LED half of) and confirm every runbook step matches real observed behavior | Yes | For the "physical bay identification" and real hot-swap mechanics specifically, yes |
| 40 | Static network topology reference (MAC-to-IP bindings, subnet allocation, VLAN tags) | 🟠 | `docs/network-topology.md` | None | A structurally complete *template* with explicit `<replace: ...>` placeholders for real MAC addresses — matches the example values in `netplan/01-netcfg.yaml`/`nftables.conf`, but has never been filled in with a real site's actual values | Fill in real MAC addresses and IPs once the VM's real NICs exist | Yes | No |

---

## Frontend — Web Dashboard

| # | Requirement | Class | Implementation file(s) | Test(s) covering it | Current validation method | Remaining validation needed | VM required? | Physical HW required? |
|---|---|---|---|---|---|---|---|---|
| 41 | Single-page dashboard: power/RAID/thermal overview, S.M.A.R.T./thermal detail, alert feed, Redfish OOB buttons, live Storage Simulation panel | 🟡 | `frontend/server.py`, `frontend/static/` | `frontend/tests/test_server.py` (`DashboardTestCase`, `TestStaticServing`, `TestCoreEndpoints`, `TestOobEndpoints`, `TestSimStorageEndpoints`; 15 tests) | Real dashboard server and a real mock Redfish server, both on random ports, hit over **actual HTTP** (not direct handler calls) — static serving + path-traversal check, every OOB action, the alerts ingest/list roundtrip, and a full `/api/simstorage/*` lifecycle polled to completion. Every piece of data displayed ultimately traces back to either the mock BMC (row 32) or `storage_sim` (rows 9–13) — never real hardware or a real telemetryd | Point the dashboard at a non-mock `telemetryd` (row 22) and a real/OpenBMC BMC (row 31) and confirm the same UI panels render correctly with real data | Yes | No |

---

## Summary

**41 requirements audited.**

| Classification | Count | Percentage |
| --- | --- | --- |
| 🟢 GREEN — IMPLEMENTED + TESTED | 3 | 7.3% |
| 🟡 YELLOW — IMPLEMENTED + SIMULATION TESTED | 28 | 68.3% |
| 🟠 ORANGE — IMPLEMENTED + NOT YET VALIDATED | 7 | 17.1% |
| 🔴 RED — NOT IMPLEMENTED | 3 | 7.3% |

(1. 7.3% fully tested — rows 26, 27, 29, and only because they are pure
software with no hardware/OS/network claim at all; 2. 68.3%
simulation-tested; 3. 17.1% implemented but unvalidated; 4. 7.3% not
implemented.)

**Nothing in this project has reached real hardware or real-VM
validation.** That is unchanged from `PROJECT_SPEC.md`'s own honesty
ledger — this document adds the granularity of exactly which 41 pieces
that verdict is made of, not a different verdict.

### 5. Exact list of things to personally validate in the VM

1. Row 15 — run `plan_from_lsblk.py` against real `lsblk -J` output (the
   required, hard-blocking first step per `CLAUDE.md`).
2. Rows 1–4 — real `wipefs`/`sgdisk`/`mdadm --create`/`mkfs.ext4` against
   the two disks `plan_from_lsblk.py` confirms blank.
3. Row 14 — a small `RealBlockDevice` smoke test against the same
   confirmed-blank disks before trusting the scripts alone.
4. Row 5 — dual-disk GRUB install, then detach the primary virtual disk
   and confirm the VM still boots.
5. Rows 6–7 — SSH hardening + sudoers install, verified by an actual
   second-terminal login attempt and a real `sudo_audit.log` entry.
6. Row 8 — `systemd-analyze verify` on both unit files, then run one for
   real under `systemctl`.
7. Row 16 — `netplan apply`, confirm the VLAN sub-interface with `ip`.
8. Rows 17–18 — real `diag-ns` netns/veth creation and the imperative
   VLAN script.
9. Row 19 — real `nft -f` load, then real traffic tests (rate limiting,
   default-deny, egress allow-list, `diag-ns` NAT isolation).
10. Row 21 — real `iperf3`/`tcpdump`/`ss` diagnostics run.
11. Rows 22–25 — `telemetryd.py` run non-mock, with real `smartctl`,
    real `/sys/class/thermal`, and real `/dev/kmsg`.
12. Row 28 — point `WebhookSink` at a real Slack/Alertmanager endpoint.
13. Row 30 — load the Prometheus/Alertmanager/Grafana configs into a
    real (or containerized) stack.
14. Row 31 — stand up OpenBMC-in-QEMU (or another real/virtual BMC) and
    point `oob_control.py` at it.
15. Row 33 — run `fault_drill.sh` for real (SIMULATE unset) end-to-end.
16. Row 34 — `docker compose up` the mock server wrapper.
17. Row 39 — perform an actual hot-swap drill and correct the runbook
    against whatever doesn't match real observed behavior.
18. Row 40 — fill in `docs/network-topology.md` with the VM's real MACs.
19. Row 41 — point the dashboard at real (non-mock) backends end-to-end.

### 6. Exact list of things requiring physical hardware

1. Row 36 — Cat6 T568B termination and continuity-tester certification.
2. Row 37 — physical AC/low-voltage cable-routing separation inspection.
3. Row 38 — a *meaningful* idle-vs-peak thermal/power profile (a VM's
   `stress-ng` numbers describe shared hypervisor silicon, not a
   dedicated thermal/power envelope).
4. Row 23 — real SMART wear data from an actual physical drive (a VM's
   virtual SMART passthrough, if any, is not the same signal).
5. Row 24 — a real temperature reading (VM thermal zones, if they exist
   at all, don't reflect real silicon).
6. Row 25 — a genuine MCE/ECC/AER kernel event (needs real ECC RAM or a
   real fault injector; a VM will essentially never produce one).
7. Row 39 (partially) — the physical bay-identification and real
   drive-swap mechanics half of a hot-swap drill (the mdadm/LED
   automation half is fully VM-testable).
8. Row 31/35 (only if validating against a **specific vendor's real**
   BMC firmware rather than OpenBMC-in-QEMU) — a real iDRAC/iLO/OpenBMC
   chassis.

### 7. Recommended validation order

1. **Unblock storage** — provide real `lsblk -J` output → run
   `plan_from_lsblk.py` (row 15) → confirm the two disks it names.
2. **Phase 1 storage + boot, in script order** — rows 1→2→3→4, then row
   5 with the disk-pull boot test, then rows 6→7. Each step's success is
   the precondition for the next; do not skip ahead.
3. **Cross-check row 14** (`RealBlockDevice`) against the same disks
   while they're already confirmed blank and mounted, since this is the
   cheapest moment to do it.
4. **Phase 2 networking** — row 16 (Netplan) → rows 17–18 (netns/VLAN)
   → row 19 (real `nft -f` load and traffic tests, the highest-value
   remaining validation in Phase 2) → row 21 (diagnostics).
5. **Phase 3 telemetry** — rows 22–25 non-mock on the now-provisioned
   VM, then row 28 (real webhook) and row 30 (real Prometheus/
   Alertmanager/Grafana stack — this one doesn't even need the VM and
   could be done in parallel with step 4 using the sandbox's own
   `docker`).
6. **Phase 4 OOB** — row 34 (`docker compose up`, cheap and unblocks
   nothing else but is nearly free) then row 31/35 (stand up
   OpenBMC-in-QEMU or another real BMC — the single largest remaining
   gap in the project) then row 33 (`fault_drill.sh` for real, which
   depends on both the real array from step 2 and the real BMC here).
7. **Frontend** — row 41, pointing at the now-real telemetryd and BMC
   from steps 5–6.
8. **Phase 5 physical/DR last** — rows 36–38 whenever physical hardware
   is available (independent of everything above), then row 39 (full
   hot-swap rehearsal, which exercises nearly everything already
   validated above in one end-to-end drill) and row 40 (topology doc,
   trivial once real MACs exist from step 4).

This order front-loads the one hard dependency (`lsblk` → blank-disk
confirmation) that blocks the most other work, defers the two purely
physical-hardware phases (which don't block anything software-side) to
last, and puts the single largest remaining gap — a real or virtualized
BMC — in the middle rather than the end, since `fault_drill.sh`'s real
validation (row 33) depends on it.
