#!/usr/bin/env python3
"""redfish_mock_server — minimal stateful Redfish emulator for local testing.

The DMTF Redfish-Mockup-Server (referenced in README.md as the production
choice) replays a *static* JSON tree and does not meaningfully execute
POST/PATCH actions. For actually exercising oob_control.py end-to-end —
power-cycling changes PowerState, a boot-override PATCH sticks, an LED PATCH
sticks — this tiny stdlib-only server keeps real mutable state in memory
and implements exactly the endpoints oob_control.py calls. Use the real
Redfish-Mockup-Server or an OpenBMC QEMU instance for wider API-surface
compatibility testing; use this one for CI / fast local iteration.

Usage:
    python3 redfish_mock_server.py --port 8443
    python3 ../oob_control.py --insecure --base-url http://127.0.0.1:8443 power-status
"""

from __future__ import annotations

import argparse
import http.server
import json
import re
import threading
from typing import Any, Dict


class RedfishState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.systems: Dict[str, Dict[str, Any]] = {
            "System.Embedded.1": {
                "@odata.id": "/redfish/v1/Systems/System.Embedded.1",
                "Id": "System.Embedded.1",
                "Name": "Edge Server",
                "SerialNumber": "MOCK-SN-0001",
                "PowerState": "On",
                "Status": {"State": "Enabled", "Health": "OK"},
                "Boot": {
                    "BootSourceOverrideEnabled": "Disabled",
                    "BootSourceOverrideTarget": "None",
                },
            }
        }
        self.chassis_drives: Dict[str, Dict[str, Dict[str, Any]]] = {
            "System.Embedded.1": {
                "1": {"@odata.id": "/redfish/v1/Chassis/System.Embedded.1/Drives/1",
                      "Id": "1", "IndicatorLED": "Off"},
                "2": {"@odata.id": "/redfish/v1/Chassis/System.Embedded.1/Drives/2",
                      "Id": "2", "IndicatorLED": "Off"},
            }
        }


STATE = RedfishState()

SYSTEM_RE = re.compile(r"^/redfish/v1/Systems/([^/]+)$")
RESET_RE = re.compile(r"^/redfish/v1/Systems/([^/]+)/Actions/ComputerSystem\.Reset$")
DRIVE_RE = re.compile(r"^/redfish/v1/Chassis/([^/]+)/Drives/([^/]+)$")

RESET_TO_POWER_STATE = {
    "On": "On",
    "ForceOff": "Off",
    "GracefulShutdown": "Off",
    "ForceRestart": "On",
    "PowerCycle": "On",
}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "RedfishMock/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter test output
        pass

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        m = SYSTEM_RE.match(self.path)
        if m:
            with STATE.lock:
                sysid = m.group(1)
                if sysid not in STATE.systems:
                    self._send_json(404, {"error": f"unknown system {sysid}"})
                    return
                self._send_json(200, STATE.systems[sysid])
            return
        self._send_json(404, {"error": "not found", "path": self.path})

    def do_POST(self) -> None:
        m = RESET_RE.match(self.path)
        if m:
            sysid = m.group(1)
            body = self._read_json_body()
            reset_type = body.get("ResetType")
            with STATE.lock:
                if sysid not in STATE.systems:
                    self._send_json(404, {"error": f"unknown system {sysid}"})
                    return
                new_state = RESET_TO_POWER_STATE.get(reset_type)
                if new_state is None:
                    self._send_json(400, {"error": f"unsupported ResetType {reset_type}"})
                    return
                STATE.systems[sysid]["PowerState"] = new_state
            self._send_json(200, {"ResetType": reset_type, "PowerState": new_state})
            return
        self._send_json(404, {"error": "not found", "path": self.path})

    def do_PATCH(self) -> None:
        m = SYSTEM_RE.match(self.path)
        if m:
            sysid = m.group(1)
            body = self._read_json_body()
            with STATE.lock:
                if sysid not in STATE.systems:
                    self._send_json(404, {"error": f"unknown system {sysid}"})
                    return
                boot_patch = body.get("Boot", {})
                STATE.systems[sysid].setdefault("Boot", {}).update(boot_patch)
                self._send_json(200, STATE.systems[sysid])
            return

        m = DRIVE_RE.match(self.path)
        if m:
            chassis_id, drive_id = m.group(1), m.group(2)
            body = self._read_json_body()
            with STATE.lock:
                drives = STATE.chassis_drives.get(chassis_id, {})
                if drive_id not in drives:
                    self._send_json(404, {"error": f"unknown drive {drive_id}"})
                    return
                drives[drive_id]["IndicatorLED"] = body.get("IndicatorLED", drives[drive_id]["IndicatorLED"])
                self._send_json(200, drives[drive_id])
            return

        self._send_json(404, {"error": "not found", "path": self.path})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8443)
    args = p.parse_args()

    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"redfish_mock_server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
