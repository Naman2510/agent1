#!/usr/bin/env python3
"""Dashboard backend for the Bare-Metal Edge Server & Reliability Platform.

Serves the static UI in static/ and a small JSON API that aggregates data
already produced elsewhere in this repo:

  - Storage:   /proc/mdstat (RAID array state) + telemetryd's Prometheus
               textfile (S.M.A.R.T. attributes)
  - Telemetry: the same textfile — thermal zones, kmsg fault counter
  - Network:   `ip -j`/`ss -tulpn`/`nft -j list ruleset` when available,
               falling back to the repo's static config files otherwise
  - OOB:       proxies to a Redfish endpoint using the exact RedfishClient
               from phase4-oob-lifecycle/oob_control.py (imported directly,
               not reimplemented)
  - Alerts:    an in-memory feed fed by telemetryd's webhook — point
               telemetryd's `webhook_url` at this server's
               /api/alerts/ingest and alerts appear on the dashboard live

Every data source degrades gracefully: on hardware without mdadm, live
`ip`/`ss`/`nft`, or a populated textfile (i.e. this sandbox, or any host
that hasn't finished Phase 1-3 yet), the API returns a clearly-labeled
"unavailable"/"static config" response instead of failing — the dashboard
is meant to be usable from day one of a deployment, not just at the end.

Usage:
    python3 server.py --port 8080 --config config.yaml.example
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

DEFAULT_CONFIG: Dict[str, Any] = {
    "port": 8080,
    "textfile_collector_path": str(
        REPO_ROOT / "phase3-telemetry" / "telemetryd" / "_dashboard_demo_hardware.prom"
    ),
    "redfish_base_url": "http://127.0.0.1:8443",
    "redfish_user": None,
    "redfish_password": None,
    "redfish_insecure": True,
    "redfish_system": "System.Embedded.1",
    "redfish_chassis": "System.Embedded.1",
    "fault_drill_script": str(REPO_ROOT / "phase4-oob-lifecycle" / "fault_drill.sh"),
    "max_alerts": 200,
}


def load_config(path: Optional[str]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if path and Path(path).exists() and yaml is not None:
        with open(path, "r", encoding="utf-8") as fh:
            cfg.update(yaml.safe_load(fh) or {})
    # A relative fault_drill_script is resolved against the repo root, not
    # the process's CWD — otherwise the same config.yaml behaves
    # differently depending on whether it's launched via `make dashboard`
    # (CWD = repo root) or manually from inside frontend/ (CWD = frontend/).
    script = cfg.get("fault_drill_script")
    if script and not Path(script).is_absolute():
        cfg["fault_drill_script"] = str((REPO_ROOT / script).resolve())
    return cfg


# --------------------------------------------------------------------------
# Reuse oob_control.py's RedfishClient rather than reimplementing it.
# --------------------------------------------------------------------------

def _load_oob_control():
    oob_path = REPO_ROOT / "phase4-oob-lifecycle" / "oob_control.py"
    spec = importlib.util.spec_from_file_location("oob_control", oob_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


oob_control = _load_oob_control()


# --------------------------------------------------------------------------
# Data collectors
# --------------------------------------------------------------------------

def read_mdstat() -> Dict[str, Any]:
    path = Path("/proc/mdstat")
    if not path.exists():
        return {"available": False, "reason": "no /proc/mdstat on this host (not Linux, or no md arrays)"}
    text = path.read_text()
    arrays = []
    for block in re.split(r"\n(?=md\d+ ?:)", text):
        m = re.match(r"(md\d+)\s*:\s*(\w+)\s+(\S+)\s+(.*)", block)
        if not m:
            continue
        name, state, level, members = m.groups()
        status_line = re.search(r"\[(U_+|_+U|U+)\]", block)
        recovery = re.search(r"recovery\s*=\s*([\d.]+%)", block)
        arrays.append({
            "device": f"/dev/{name}",
            "state": state,
            "level": level,
            "members_raw": members.strip(),
            "sync_status": status_line.group(1) if status_line else None,
            "recovery_progress": recovery.group(1) if recovery else None,
            "degraded": bool(status_line and "_" in status_line.group(1)),
        })
    return {"available": True, "arrays": arrays, "raw": text}


PROM_LINE_RE = re.compile(r'^(?P<name>\w+)(\{(?P<labels>[^}]*)\})?\s+(?P<value>[-0-9.eE]+)\s*$')
LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_prom_textfile(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"available": False, "reason": f"textfile not found at {path} (telemetryd not run yet, or path differs)"}
    metrics: Dict[str, List[Dict[str, Any]]] = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = PROM_LINE_RE.match(line)
        if not m:
            continue
        labels = dict(LABEL_RE.findall(m.group("labels") or ""))
        try:
            value = float(m.group("value"))
        except ValueError:
            continue
        metrics.setdefault(m.group("name"), []).append({"labels": labels, "value": value})
    return {"available": True, "mtime": p.stat().st_mtime, "metrics": metrics}


def read_network_state() -> Dict[str, Any]:
    result: Dict[str, Any] = {"live": False}
    try:
        addr = subprocess.run(["ip", "-j", "addr", "show"], capture_output=True, text=True, timeout=3)
        sockets = subprocess.run(["ss", "-tulpnH"], capture_output=True, text=True, timeout=3)
        if addr.returncode == 0:
            result["live"] = True
            result["interfaces"] = json.loads(addr.stdout or "[]")
            result["listening_sockets"] = sockets.stdout.splitlines() if sockets.returncode == 0 else []
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    try:
        ruleset = subprocess.run(["nft", "-j", "list", "ruleset"], capture_output=True, text=True, timeout=3)
        if ruleset.returncode == 0:
            result["nftables_live"] = True
            result["ruleset"] = json.loads(ruleset.stdout or "{}")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        result["nftables_live"] = False

    if not result["live"]:
        # Fall back to the repo's declarative config so the dashboard is
        # still informative before/without live host access.
        netplan = REPO_ROOT / "phase2-networking" / "netplan" / "01-netcfg.yaml"
        result["static_config"] = netplan.read_text() if netplan.exists() else None
        result["note"] = "no live `ip`/`ss` on this host — showing the checked-in static config instead"

    return result


class AlertStore:
    def __init__(self, max_alerts: int):
        self.max_alerts = max_alerts
        self.lock = threading.Lock()
        self.alerts: List[Dict[str, Any]] = []

    def add(self, payload: Dict[str, Any]) -> None:
        with self.lock:
            payload = dict(payload)
            payload.setdefault("received_at", time.time())
            self.alerts.insert(0, payload)
            del self.alerts[self.max_alerts:]

    def list(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.alerts)


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "EdgeDashboard/1.0"
    cfg: Dict[str, Any] = {}
    alerts: AlertStore = AlertStore(200)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[dashboard] " + (fmt % args) + "\n")

    # -- helpers ------------------------------------------------------

    def _json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
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

    def _redfish_client(self):
        c = self.cfg
        return oob_control.RedfishClient(
            c["redfish_base_url"], c.get("redfish_user"), c.get("redfish_password"),
            verify=not c.get("redfish_insecure", True), timeout=5.0,
        )

    def _serve_static(self, rel_path: str) -> None:
        if rel_path in ("", "/"):
            rel_path = "index.html"
        rel_path = rel_path.lstrip("/")
        if rel_path.startswith("static/"):
            rel_path = rel_path[len("static/"):]
        target = (STATIC_DIR / rel_path).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            self._json(403, {"error": "forbidden"})
            return
        if not target.exists() or not target.is_file():
            self._json(404, {"error": "not found"})
            return
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }
        ctype = content_types.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routing --------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/overview":
                self._json(200, self._overview())
            elif path == "/api/storage":
                self._json(200, {"mdstat": read_mdstat(), "smart": self._smart_summary()})
            elif path == "/api/telemetry":
                self._json(200, parse_prom_textfile(self.cfg["textfile_collector_path"]))
            elif path == "/api/network":
                self._json(200, read_network_state())
            elif path == "/api/alerts":
                self._json(200, {"alerts": self.alerts.list()})
            elif path == "/api/oob/power-status":
                self._oob_power_status()
            elif path.startswith("/api/"):
                self._json(404, {"error": "unknown endpoint", "path": path})
            else:
                self._serve_static(path)
        except Exception as exc:  # noqa: BLE001 - never let a bad request kill the server
            self._json(500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json_body()
            if path == "/api/alerts/ingest":
                self.alerts.add(body)
                self._json(200, {"status": "recorded"})
            elif path == "/api/oob/power-cycle":
                self._oob_power_cycle(body)
            elif path == "/api/oob/boot-override":
                self._oob_boot_override(body)
            elif path == "/api/oob/set-led":
                self._oob_set_led(body)
            elif path == "/api/drill/run":
                self._run_drill(body)
            else:
                self._json(404, {"error": "unknown endpoint", "path": path})
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON body"})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})

    # -- endpoint implementations ----------------------------------------

    def _overview(self) -> Dict[str, Any]:
        mdstat = read_mdstat()
        telemetry = parse_prom_textfile(self.cfg["textfile_collector_path"])
        power_state = None
        power_error = None
        try:
            client = self._redfish_client()
            data = client.get(f"/redfish/v1/Systems/{self.cfg['redfish_system']}")
            power_state = data.get("PowerState")
        except Exception as exc:  # noqa: BLE001
            power_error = str(exc)

        degraded_arrays = [a for a in mdstat.get("arrays", []) if a.get("degraded")]
        fault_total = 0
        if telemetry.get("available"):
            faults = telemetry["metrics"].get("telemetryd_kmsg_faults_total", [])
            fault_total = int(faults[0]["value"]) if faults else 0

        return {
            "power_state": power_state,
            "power_error": power_error,
            "raid_available": mdstat.get("available", False),
            "raid_degraded_count": len(degraded_arrays),
            "telemetry_available": telemetry.get("available", False),
            "hardware_faults_total": fault_total,
            "recent_alerts": self.alerts.list()[:5],
        }

    def _smart_summary(self) -> Dict[str, Any]:
        telemetry = parse_prom_textfile(self.cfg["textfile_collector_path"])
        if not telemetry.get("available"):
            return telemetry
        by_disk: Dict[str, Dict[str, float]] = {}
        for sample in telemetry["metrics"].get("telemetryd_smart_attribute", []):
            disk = sample["labels"].get("disk", "unknown")
            attr = sample["labels"].get("attribute", "unknown")
            by_disk.setdefault(disk, {})[attr] = sample["value"]
        return {"available": True, "disks": by_disk}

    def _oob_power_status(self) -> None:
        try:
            client = self._redfish_client()
            data = client.get(f"/redfish/v1/Systems/{self.cfg['redfish_system']}")
            self._json(200, {
                "power_state": data.get("PowerState"),
                "serial_number": data.get("SerialNumber"),
                "status": data.get("Status", {}),
                "boot": data.get("Boot", {}),
            })
        except urllib.error.URLError as exc:
            self._json(502, {"error": f"Redfish endpoint unreachable: {exc}"})
        except Exception as exc:  # noqa: BLE001 - includes requests.exceptions.*
            self._json(502, {"error": str(exc)})

    def _oob_power_cycle(self, body: Dict[str, Any]) -> None:
        reset_type = body.get("reset_type", "cycle")
        if reset_type not in oob_control.RESET_TYPE_MAP:
            self._json(400, {"error": f"invalid reset_type, must be one of {sorted(oob_control.RESET_TYPE_MAP)}"})
            return
        client = self._redfish_client()
        path = f"/redfish/v1/Systems/{self.cfg['redfish_system']}/Actions/ComputerSystem.Reset"
        try:
            result = client.post(path, {"ResetType": oob_control.RESET_TYPE_MAP[reset_type]})
            self._json(200, {"reset_type": reset_type, "result": result})
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"error": str(exc)})

    def _oob_boot_override(self, body: Dict[str, Any]) -> None:
        target = body.get("target", "pxe")
        if target not in oob_control.BOOT_TARGET_MAP:
            self._json(400, {"error": f"invalid target, must be one of {sorted(oob_control.BOOT_TARGET_MAP)}"})
            return
        client = self._redfish_client()
        payload = {
            "Boot": {
                "BootSourceOverrideEnabled": "Continuous" if body.get("persistent") else "Once",
                "BootSourceOverrideTarget": oob_control.BOOT_TARGET_MAP[target],
            }
        }
        try:
            result = client.patch(f"/redfish/v1/Systems/{self.cfg['redfish_system']}", payload)
            self._json(200, {"target": target, "result": result})
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"error": str(exc)})

    def _oob_set_led(self, body: Dict[str, Any]) -> None:
        drive = body.get("drive")
        state = body.get("state")
        if not drive or state not in ("Lit", "Blinking", "Off"):
            self._json(400, {"error": "body must include drive and state in {Lit, Blinking, Off}"})
            return
        client = self._redfish_client()
        path = f"/redfish/v1/Chassis/{self.cfg['redfish_chassis']}/Drives/{drive}"
        try:
            result = client.patch(path, {"IndicatorLED": state})
            self._json(200, {"drive": drive, "state": state, "result": result})
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"error": str(exc)})

    def _run_drill(self, body: Dict[str, Any]) -> None:
        # Always forced to SIMULATE=1 from the web UI — a real fault drill
        # (mdadm --fail against a live array) is a CLI-only, deliberate
        # action; see phase4-oob-lifecycle/README.md.
        script = self.cfg["fault_drill_script"]
        if not Path(script).exists():
            self._json(404, {"error": f"fault_drill.sh not found at {script}"})
            return
        env = dict(os.environ)
        env.update({
            "SIMULATE": "1",
            "FAILED_PART": body.get("failed_part", "/dev/sdb1"),
            "DRIVE_ID": str(body.get("drive_id", "2")),
            "REDFISH_URL": self.cfg["redfish_base_url"],
            "CONFIRM": "yes",
        })
        try:
            proc = subprocess.run([script], env=env, capture_output=True, text=True, timeout=30)
            self._json(200, {
                "returncode": proc.returncode,
                "output": proc.stdout + proc.stderr,
                "note": "ran with SIMULATE=1 — no real mdadm/Redfish state was touched",
            })
        except subprocess.TimeoutExpired:
            self._json(504, {"error": "drill script timed out"})


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.port:
        cfg["port"] = args.port

    Handler.cfg = cfg
    Handler.alerts = AlertStore(cfg.get("max_alerts", 200))

    server = ThreadingHTTPServer((args.host, cfg["port"]), Handler)
    print(f"Edge server dashboard listening on http://{args.host}:{cfg['port']}")
    print(f"  Redfish target:    {cfg['redfish_base_url']}")
    print(f"  Telemetry textfile: {cfg['textfile_collector_path']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
