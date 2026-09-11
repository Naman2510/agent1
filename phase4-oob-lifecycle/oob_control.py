#!/usr/bin/env python3
"""oob_control — Redfish-based out-of-band lifecycle control CLI.

Talks to a service processor's Redfish API (a real BMC, an OpenBMC QEMU
instance, or the Redfish Mockup Server in redfish-mockup/) to read power
state and drive chassis actions that would otherwise require physical
presence: power-cycling a hung host, or forcing the next boot to PXE for
remote OS recovery.

Usage:
    oob_control.py power-status   --base-url https://bmc.local:8443 --system System.Embedded.1
    oob_control.py power-cycle    --base-url https://bmc.local:8443 --system System.Embedded.1
    oob_control.py boot-override  --base-url https://bmc.local:8443 --system System.Embedded.1 --target pxe
    oob_control.py set-led        --base-url https://bmc.local:8443 --drive 1 --state Blinking

Authentication: HTTP basic auth via --user/--password (or REDFISH_USER /
REDFISH_PASSWORD env vars). --insecure skips TLS verification, which is
expected against a self-signed BMC cert or the mockup server — never pass
it against a production endpoint you haven't pinned a CA for.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

import requests
from requests.auth import HTTPBasicAuth

# Redfish's controlled vocabulary for ResetType and BootSourceOverrideTarget.
RESET_TYPES = {"cycle", "on", "off", "graceful-shutdown", "force-restart"}
RESET_TYPE_MAP = {
    "cycle": "PowerCycle",
    "on": "On",
    "off": "ForceOff",
    "graceful-shutdown": "GracefulShutdown",
    "force-restart": "ForceRestart",
}
BOOT_TARGETS = {"pxe", "hdd", "cd", "usb", "bios-setup", "none"}
BOOT_TARGET_MAP = {
    "pxe": "Pxe",
    "hdd": "Hdd",
    "cd": "Cd",
    "usb": "Usb",
    "bios-setup": "BiosSetup",
    "none": "None",
}


class RedfishClient:
    def __init__(self, base_url: str, user: Optional[str], password: Optional[str],
                 verify: bool = True, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.auth = HTTPBasicAuth(user, password) if user else None
        self.verify = verify
        self.timeout = timeout
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get(self, path: str) -> Dict[str, Any]:
        resp = self.session.get(
            self._url(path), auth=self.auth, verify=self.verify, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.post(
            self._url(path), auth=self.auth, verify=self.verify, timeout=self.timeout,
            headers={"Content-Type": "application/json"}, json=payload,
        )
        resp.raise_for_status()
        if resp.content:
            try:
                return resp.json()
            except ValueError:
                return {"status": resp.status_code}
        return {"status": resp.status_code}

    def patch(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.patch(
            self._url(path), auth=self.auth, verify=self.verify, timeout=self.timeout,
            headers={"Content-Type": "application/json"}, json=payload,
        )
        resp.raise_for_status()
        if resp.content:
            try:
                return resp.json()
            except ValueError:
                return {"status": resp.status_code}
        return {"status": resp.status_code}


def cmd_power_status(client: RedfishClient, args: argparse.Namespace) -> int:
    data = client.get(f"/redfish/v1/Systems/{args.system}")
    result = {
        "power_state": data.get("PowerState"),
        "system": args.system,
        "serial_number": data.get("SerialNumber"),
        "status": data.get("Status", {}),
    }
    print(json.dumps(result, indent=2))
    return 0


def cmd_power_cycle(client: RedfishClient, args: argparse.Namespace) -> int:
    reset_type = RESET_TYPE_MAP[args.reset_type]
    path = f"/redfish/v1/Systems/{args.system}/Actions/ComputerSystem.Reset"
    result = client.post(path, {"ResetType": reset_type})
    print(json.dumps({"action": "reset", "reset_type": reset_type, "result": result}, indent=2))
    return 0


def cmd_boot_override(client: RedfishClient, args: argparse.Namespace) -> int:
    target = BOOT_TARGET_MAP[args.target]
    path = f"/redfish/v1/Systems/{args.system}"
    payload = {
        "Boot": {
            "BootSourceOverrideEnabled": "Once" if not args.persistent else "Continuous",
            "BootSourceOverrideTarget": target,
        }
    }
    result = client.patch(path, payload)
    print(json.dumps({"action": "boot-override", "target": target, "result": result}, indent=2))
    return 0


def cmd_set_led(client: RedfishClient, args: argparse.Namespace) -> int:
    # Drive fault-indicator LED, used by fault_drill.sh to visually flag a
    # failed member of the RAID mirror during a simulated disk swap.
    path = f"/redfish/v1/Chassis/{args.chassis}/Drives/{args.drive}"
    payload = {"IndicatorLED": args.state}
    result = client.patch(path, payload)
    print(json.dumps({"action": "set-led", "drive": args.drive, "state": args.state, "result": result}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True, help="e.g. https://bmc.local:8443")
    p.add_argument("--system", default="System.Embedded.1", help="Redfish ComputerSystem id")
    p.add_argument("--chassis", default="System.Embedded.1", help="Redfish Chassis id (for set-led)")
    p.add_argument("--user", default=os.environ.get("REDFISH_USER"))
    p.add_argument("--password", default=os.environ.get("REDFISH_PASSWORD"))
    p.add_argument("--insecure", action="store_true", help="skip TLS verification (self-signed BMC/mockup cert)")
    p.add_argument("--timeout", type=float, default=10.0)

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("power-status", help="read chassis power state")

    pc = sub.add_parser("power-cycle", help="send a power action to the service processor")
    pc.add_argument("--reset-type", choices=sorted(RESET_TYPES), default="cycle")

    bo = sub.add_parser("boot-override", help="change the next boot target")
    bo.add_argument("--target", choices=sorted(BOOT_TARGETS), required=True)
    bo.add_argument("--persistent", action="store_true", help="apply to every boot, not just the next one")

    sl = sub.add_parser("set-led", help="set a drive's fault-indicator LED")
    sl.add_argument("--drive", required=True, help="Redfish drive id, e.g. '1'")
    sl.add_argument("--state", choices=["Lit", "Blinking", "Off"], required=True)

    return p


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    client = RedfishClient(
        args.base_url, args.user, args.password,
        verify=not args.insecure, timeout=args.timeout,
    )
    handlers = {
        "power-status": cmd_power_status,
        "power-cycle": cmd_power_cycle,
        "boot-override": cmd_boot_override,
        "set-led": cmd_set_led,
    }
    try:
        return handlers[args.command](client, args)
    except requests.exceptions.RequestException as exc:
        print(f"error: Redfish request failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
