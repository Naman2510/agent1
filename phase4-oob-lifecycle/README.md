# Phase 4 — Out-of-Band (OOB) Control & Server Lifecycle Automation

Emulates enterprise remote management (IPMI/Redfish) to power-cycle,
recover, and observe the server even when the main OS is hung or the
production network is down.

## Components

| Path | Purpose |
| --- | --- |
| `oob_control.py` | Redfish CLI: `power-status`, `power-cycle`, `boot-override`, `set-led` |
| `tests/` | Automated test suite (29 tests) — see "Testing" below |
| `fault_drill.sh` | End-to-end fault injection & rebuild drill (mdadm + Redfish LED) |
| `redfish-mockup/` | Three ways to stand up a BMC to test against — see its README |

## Quick start

```
pip install -r requirements.txt
python3 redfish-mockup/redfish_mock_server.py --port 8443 &

python3 oob_control.py --insecure --base-url http://127.0.0.1:8443 power-status
python3 oob_control.py --insecure --base-url http://127.0.0.1:8443 power-cycle --reset-type cycle
python3 oob_control.py --insecure --base-url http://127.0.0.1:8443 boot-override --target pxe
```

Against a real BMC, drop `--insecure` once you've pinned its CA, and set
`--user`/`--password` or `REDFISH_USER`/`REDFISH_PASSWORD`.

This exact sequence (power-status → power-cycle → verify state flipped →
boot-override → set-led) has been run in this repo's own build/test pass
against `redfish_mock_server.py` and confirmed working: `PowerState`
actually transitions, the boot override persists, and the drive LED state
persists.

### Testing

Beyond the manual sequence above, there's a real automated test suite:

```
python3 -m unittest discover -s tests -v   # 29 tests
```

`test_oob_control.py` (22 tests) runs the mock server in-process (not a
subprocess) and exercises every CLI command path, every reset type and
boot target, argparse's own validation of bad input (including missing
`--base-url`/subcommand), the `--user`/`--password`/`--timeout` argparse
defaults and their `REDFISH_USER`/`REDFISH_PASSWORD` env-var fallbacks,
a genuine unreachable-endpoint failure path, and — by monkeypatching the
mock server's request handler to capture the real `Authorization`
header — that HTTP Basic Auth credentials are actually sent on the wire,
not just accepted by argparse. It also checks that `RESET_TYPE_MAP` here
and `RESET_TO_POWER_STATE` in `redfish-mockup/redfish_mock_server.py`
can't silently drift apart — without that check, adding a reset type to
one file but not the other would go unnoticed until a real run failed.

`test_fault_drill.py` (7 tests) runs the real `fault_drill.sh` script as
a subprocess with `SIMULATE=1` and asserts the exact expected command
sequence appears, in the right order: all 5 numbered steps, the precise
`mdadm --fail/--remove/--add` command lines built from `MD_DEVICE`/
`FAILED_PART`, the drive LED going Blinking before Off, the completion
message, and — critically — that every real-looking `mdadm` invocation
is actually prefixed `(simulated)` (never a real, unmarked command) and
that a second run with different device names produces exactly those
new device names with no leftover trace of the defaults. This exercises
the shell logic genuinely, not just "the script didn't crash" — but it
is still exclusively `SIMULATE=1` shell-logic coverage: the real-mode
branch (actual `mdadm --fail` etc. against a real array) is NOT
exercised here or anywhere else in this repo without real hardware.

## Fault drill

```
sudo MD_DEVICE=/dev/md0 FAILED_PART=/dev/sdb1 DRIVE_ID=2 \
    REDFISH_URL=https://127.0.0.1:8443 \
    ./fault_drill.sh
```

Sequence: `mdadm --fail` → set fault LED (Redfish, Blinking Amber) →
`mdadm --remove` → (operator swaps the physical drive) → `mdadm --add` →
clear the LED → poll `/proc/mdstat` until the rebuild completes.

`SIMULATE=1` runs the entire sequence without touching `mdadm` or issuing
real Redfish calls — validated in this repo as part of the build.

## Why Redfish over IPMI

IPMI (port 623) is included in the architecture diagram for completeness —
real BMCs still expose it — but all automation here targets Redfish (REST
over HTTPS, port 8443): it's structured JSON instead of a binary protocol,
trivially testable with `curl`/`requests`, and is what OpenBMC and every
modern BMC vendor treat as the primary interface going forward.
