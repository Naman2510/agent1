# Bare-Metal Edge Server & Reliability Platform
#
#   make simulate   — dry-run every destructive script (SIMULATE=1), compile
#                      every Python entrypoint, syntax-check every shell
#                      script and every YAML/JSON config. Safe on any
#                      machine — never touches real disks/network/hardware.
#   make lint       — syntax/compile checks only (subset of simulate).
#   make telemetry-test — runs telemetryd.py in --mock --once mode.
#   make oob-test   — spins up the local Redfish mock and exercises oob_control.py.
#   make dashboard  — runs the full local stack (Redfish mock + telemetryd
#                      mock + dashboard backend) so http://localhost:8080
#                      is browsable with live mock data. Foreground; Ctrl-C
#                      stops all three.
#   make clean      — removes scratch output from the targets above.

SHELL := /bin/bash
.PHONY: simulate lint telemetry-test oob-test dashboard clean

lint:
	@echo "== bash -n on every script =="
	@find . -name '*.sh' -print0 | xargs -0 -n1 bash -n
	@echo "== python3 -m py_compile on every entrypoint =="
	@python3 -m py_compile phase3-telemetry/telemetryd/telemetryd.py
	@python3 -m py_compile phase4-oob-lifecycle/oob_control.py
	@python3 -m py_compile phase4-oob-lifecycle/redfish-mockup/redfish_mock_server.py
	@python3 -m py_compile frontend/server.py
	@command -v node >/dev/null && node --check frontend/static/app.js || echo "node not installed, skipped JS syntax check"
	@echo "== YAML/JSON config validation =="
	@python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('**/*.yml', recursive=True) + glob.glob('**/*.yaml', recursive=True)]"
	@python3 -c "import json; json.load(open('phase3-telemetry/grafana/dashboard.json'))"
	@command -v nft >/dev/null && nft -c -f phase2-networking/nftables/nftables.conf || echo "nft not installed, skipped ruleset check"
	@echo "lint OK"

simulate: lint
	@echo "== dry-running Phase 1 (SIMULATE=1) =="
	SIMULATE=1 DISK1=/dev/sda DISK2=/dev/sdb ./phase1-host-provisioning/scripts/00-wipe-disks.sh
	SIMULATE=1 DISK1=/dev/sda DISK2=/dev/sdb ./phase1-host-provisioning/scripts/01-partition-raid.sh
	SIMULATE=1 PART1=/dev/sda1 PART2=/dev/sdb1 ./phase1-host-provisioning/scripts/02-assemble-raid.sh
	SIMULATE=1 ./phase1-host-provisioning/scripts/03-format-mount.sh
	SIMULATE=1 DISK1=/dev/sda DISK2=/dev/sdb ./phase1-host-provisioning/scripts/04-bootloader-mirror.sh
	SIMULATE=1 ./phase1-host-provisioning/scripts/05-harden-ssh.sh
	SIMULATE=1 ./phase1-host-provisioning/scripts/06-sudoers-audit.sh
	@echo "== dry-running Phase 2 =="
	SIMULATE=1 VLAN_ID=100 VLAN_IP=10.10.100.10/24 ./phase2-networking/scripts/setup-vlan.sh
	SIMULATE=1 ./phase2-networking/scripts/setup-diag-netns.sh
	SIMULATE=1 ./phase2-networking/scripts/network-diagnostics.sh
	@echo "== dry-running Phase 4 fault drill =="
	SIMULATE=1 FAILED_PART=/dev/sdb1 DRIVE_ID=2 ./phase4-oob-lifecycle/fault_drill.sh
	@echo "== dry-running Phase 5 =="
	SIMULATE=1 ./phase5-physical-dr/scripts/thermal_power_profile.sh
	@rm -rf netcheck-* thermal-profile-*
	@echo "simulate OK — nothing above touched real disks, network, or hardware"

telemetry-test:
	python3 phase3-telemetry/telemetryd/telemetryd.py --mock --once -v \
		--config phase3-telemetry/telemetryd/config.yaml.example

oob-test:
	python3 phase4-oob-lifecycle/redfish-mockup/redfish_mock_server.py --port 8443 & \
	SRV=$$!; sleep 1; \
	python3 phase4-oob-lifecycle/oob_control.py --insecure --base-url http://127.0.0.1:8443 power-status; \
	python3 phase4-oob-lifecycle/oob_control.py --insecure --base-url http://127.0.0.1:8443 power-cycle --reset-type cycle; \
	kill $$SRV

dashboard:
	@echo "Starting Redfish mock (8443), telemetryd --mock, and the dashboard (8080)."
	@echo "Open http://localhost:8080/  —  Ctrl-C stops all three."
	@trap 'kill $$(jobs -p) 2>/dev/null' EXIT; \
	python3 phase4-oob-lifecycle/redfish-mockup/redfish_mock_server.py --port 8443 & \
	python3 phase3-telemetry/telemetryd/telemetryd.py --mock \
		--config phase3-telemetry/telemetryd/config.yaml.example & \
	sleep 1; \
	python3 frontend/server.py --config frontend/config.yaml.example; \
	wait

clean:
	rm -rf netcheck-* thermal-profile-* /var/lib/node_exporter
