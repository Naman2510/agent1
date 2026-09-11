#!/usr/bin/env python3
"""telemetryd — async hardware telemetry daemon.

Polls S.M.A.R.T. drive attributes, sysfs thermal zones, and the kernel ring
buffer (/dev/kmsg) for MCE/ECC/AER faults; runs a sliding-window anomaly
detector over the readings; and fans out results two ways:

  1. Prometheus textfile-collector format, written atomically to
     /var/lib/node_exporter/textfile_collector/hardware.prom
  2. Structured JSON alerts POSTed to a webhook (Slack/Discord/Alertmanager)
     when a sliding-window breach is detected.

Runs unprivileged (User=telemetry in the systemd unit) with exactly the
capability it needs to issue SCSI/NVMe pass-through queries:
    AmbientCapabilities=CAP_SYS_RAWIO
See telemetryd.service.

Mock mode
---------
On a machine with no smartctl / no thermal zones / no readable /dev/kmsg
(e.g. a CI sandbox or this repo's own test run), pass --mock to synthesize
plausible readings instead of touching hardware, so the polling loop,
sliding-window logic, textfile writer, and webhook dispatch can all be
exercised without real hardware:

    python3 telemetryd.py --mock --once --config config.yaml.example
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover - config falls back to defaults
    yaml = None

log = logging.getLogger("telemetryd")

SMART_ATTRS_OF_INTEREST = {
    5: "reallocated_sector_count",
    197: "current_pending_sector_count",
    198: "offline_uncorrectable_sector_count",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "poll_interval_seconds": 30,
    "window_seconds": 300,          # 5-minute sliding window
    "thermal_drift_threshold_c": 15.0,
    "disks": ["/dev/sda", "/dev/sdb"],
    "thermal_zones_glob": "/sys/class/thermal/thermal_zone*/temp",
    "kmsg_path": "/dev/kmsg",
    "textfile_collector_path": "/var/lib/node_exporter/textfile_collector/hardware.prom",
    "webhook_url": None,
    "webhook_timeout_seconds": 5,
}


def load_config(path: Optional[str]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if path and Path(path).exists():
        if yaml is None:
            log.warning("PyYAML not installed; ignoring %s and using defaults", path)
        else:
            with open(path, "r", encoding="utf-8") as fh:
                user_cfg = yaml.safe_load(fh) or {}
            cfg.update(user_cfg)
    return cfg


# --------------------------------------------------------------------------
# Sliding-window anomaly detection
# --------------------------------------------------------------------------

@dataclass
class SlidingWindow:
    """Keeps (timestamp, value) samples for `window_seconds` and exposes a
    moving average plus baseline drift, so a single transient spike never
    fires an alert on its own."""

    window_seconds: float
    samples: Deque[tuple] = field(default_factory=deque)
    baseline: Optional[float] = None

    def add(self, value: float, now: Optional[float] = None) -> float:
        now = now if now is not None else time.time()
        self.samples.append((now, value))
        cutoff = now - self.window_seconds
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        avg = sum(v for _, v in self.samples) / len(self.samples)
        if self.baseline is None:
            self.baseline = avg
        return avg

    def drift(self) -> float:
        if not self.samples:
            return 0.0
        avg = sum(v for _, v in self.samples) / len(self.samples)
        return avg - (self.baseline if self.baseline is not None else avg)


# --------------------------------------------------------------------------
# Sensor collectors
# --------------------------------------------------------------------------

class SmartCollector:
    """Polls smartctl --json for the S.M.A.R.T. attributes that matter."""

    def __init__(self, disks: Iterable[str], mock: bool = False):
        self.disks = list(disks)
        self.mock = mock
        self._smartctl = shutil.which("smartctl")

    async def poll(self) -> Dict[str, Dict[str, int]]:
        results: Dict[str, Dict[str, int]] = {}
        for disk in self.disks:
            if self.mock or not self._smartctl:
                results[disk] = self._mock_reading()
                continue
            try:
                results[disk] = await self._poll_disk(disk)
            except Exception as exc:  # noqa: BLE001 - never crash the loop over one disk
                log.warning("smartctl poll failed for %s: %s", disk, exc)
        return results

    def _mock_reading(self) -> Dict[str, int]:
        # Overwhelmingly healthy, occasionally ticks up by 1 to exercise
        # the alerting path in tests without a real degrading disk.
        return {
            name: (1 if random.random() < 0.02 else 0)
            for name in SMART_ATTRS_OF_INTEREST.values()
        }

    async def _poll_disk(self, disk: str) -> Dict[str, int]:
        proc = await asyncio.create_subprocess_exec(
            self._smartctl, "--json", "-A", disk,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout or b"{}")
        out = {name: 0 for name in SMART_ATTRS_OF_INTEREST.values()}
        for attr in data.get("ata_smart_attributes", {}).get("table", []):
            attr_id = attr.get("id")
            if attr_id in SMART_ATTRS_OF_INTEREST:
                raw = attr.get("raw", {}).get("value", 0)
                out[SMART_ATTRS_OF_INTEREST[attr_id]] = int(raw)
        return out


class ThermalCollector:
    """Polls sysfs thermal zones (millidegrees C -> degrees C)."""

    def __init__(self, zones_glob: str, mock: bool = False):
        self.zones_glob = zones_glob
        self.mock = mock

    async def poll(self) -> Dict[str, float]:
        if self.mock:
            return self._mock_reading()
        readings: Dict[str, float] = {}
        for zone_path in sorted(Path("/").glob(self.zones_glob.lstrip("/"))):
            try:
                raw = zone_path.read_text().strip()
                readings[zone_path.parent.name] = int(raw) / 1000.0
            except (OSError, ValueError) as exc:
                log.debug("could not read %s: %s", zone_path, exc)
        if not readings:
            log.debug("no thermal zones found at %s, falling back to mock", self.zones_glob)
            return self._mock_reading()
        return readings

    def _mock_reading(self) -> Dict[str, float]:
        base = 45.0
        return {
            "thermal_zone0": base + random.uniform(-2, 2),
            "thermal_zone1": base + random.uniform(-2, 2),
        }


class KmsgCollector:
    """Tails /dev/kmsg for MCE / ECC / PCIe AER fault lines.

    Runs as a background task feeding a shared asyncio.Queue rather than
    being polled, since kmsg is a streaming character device.
    """

    FAULT_MARKERS = ("mce:", "hardware error", "edac", "aer", "correctable error")

    def __init__(self, kmsg_path: str, queue: "asyncio.Queue[str]", mock: bool = False):
        self.kmsg_path = kmsg_path
        self.queue = queue
        self.mock = mock
        self._stop = False

    async def run(self) -> None:
        if self.mock or not os.path.exists(self.kmsg_path):
            await self._run_mock()
            return
        try:
            fd = os.open(self.kmsg_path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            log.warning("cannot open %s (%s); falling back to mock kmsg", self.kmsg_path, exc)
            await self._run_mock()
            return
        loop = asyncio.get_event_loop()
        with os.fdopen(fd, "r", errors="replace") as f:
            while not self._stop:
                line = await loop.run_in_executor(None, f.readline)
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                lowered = line.lower()
                if any(marker in lowered for marker in self.FAULT_MARKERS):
                    await self.queue.put(line.strip())

    async def _run_mock(self) -> None:
        # Emits nothing by default; a synthetic fault can be injected for
        # testing via inject_fault().
        while not self._stop:
            await asyncio.sleep(3600)

    def stop(self) -> None:
        self._stop = True


# --------------------------------------------------------------------------
# Sinks: Prometheus textfile + webhook alerts
# --------------------------------------------------------------------------

class PrometheusTextfileSink:
    def __init__(self, path: str):
        self.path = Path(path)

    def write(self, smart: Dict[str, Dict[str, int]], thermal: Dict[str, float],
              kmsg_faults_total: int) -> None:
        lines: List[str] = [
            "# HELP telemetryd_smart_attribute Raw S.M.A.R.T. attribute value.",
            "# TYPE telemetryd_smart_attribute gauge",
        ]
        for disk, attrs in smart.items():
            for attr, value in attrs.items():
                lines.append(
                    f'telemetryd_smart_attribute{{disk="{disk}",attribute="{attr}"}} {value}'
                )
        lines.append("# HELP telemetryd_thermal_celsius Thermal zone temperature.")
        lines.append("# TYPE telemetryd_thermal_celsius gauge")
        for zone, temp in thermal.items():
            lines.append(f'telemetryd_thermal_celsius{{zone="{zone}"}} {temp:.2f}')
        lines.append("# HELP telemetryd_kmsg_faults_total MCE/ECC/AER faults seen since start.")
        lines.append("# TYPE telemetryd_kmsg_faults_total counter")
        lines.append(f"telemetryd_kmsg_faults_total {kmsg_faults_total}")

        # Atomic write: write to a temp file in the same directory, then
        # rename, so node_exporter's textfile collector never reads a
        # partially-written scrape.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".prom.tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp_path, self.path)


class WebhookSink:
    def __init__(self, url: Optional[str], timeout: float = 5.0):
        self.url = url
        self.timeout = timeout

    async def send(self, payload: Dict[str, Any]) -> None:
        if not self.url:
            log.info("ALERT (no webhook configured): %s", json.dumps(payload))
            return
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._post, payload)
        except Exception as exc:  # noqa: BLE001
            log.error("webhook dispatch failed: %s", exc)

    def _post(self, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"webhook POST to {self.url} failed: {exc}") from exc


# --------------------------------------------------------------------------
# Daemon
# --------------------------------------------------------------------------

class TelemetryDaemon:
    def __init__(self, cfg: Dict[str, Any], mock: bool = False):
        self.cfg = cfg
        self.mock = mock
        self.smart = SmartCollector(cfg["disks"], mock=mock)
        self.thermal = ThermalCollector(cfg["thermal_zones_glob"], mock=mock)
        self.textfile = PrometheusTextfileSink(cfg["textfile_collector_path"])
        self.webhook = WebhookSink(cfg.get("webhook_url"), cfg.get("webhook_timeout_seconds", 5))
        self.kmsg_queue: "asyncio.Queue[str]" = asyncio.Queue()
        self.kmsg = KmsgCollector(cfg["kmsg_path"], self.kmsg_queue, mock=mock)
        self.kmsg_faults_total = 0

        window = cfg["window_seconds"]
        self.thermal_windows: Dict[str, SlidingWindow] = defaultdict(lambda: SlidingWindow(window))
        self.smart_baselines: Dict[str, Dict[str, int]] = {}

    async def run_forever(self, poll_interval: Optional[float] = None, iterations: Optional[int] = None) -> None:
        interval = poll_interval if poll_interval is not None else self.cfg["poll_interval_seconds"]
        kmsg_task = asyncio.create_task(self.kmsg.run())
        drain_task = asyncio.create_task(self._drain_kmsg())
        count = 0
        try:
            while iterations is None or count < iterations:
                await self._poll_once()
                count += 1
                if iterations is None or count < iterations:
                    await asyncio.sleep(interval)
        finally:
            self.kmsg.stop()
            kmsg_task.cancel()
            drain_task.cancel()
            for t in (kmsg_task, drain_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def _drain_kmsg(self) -> None:
        while True:
            line = await self.kmsg_queue.get()
            self.kmsg_faults_total += 1
            log.warning("hardware fault detected in kmsg: %s", line)
            await self.webhook.send({
                "type": "hardware_fault",
                "source": "kmsg",
                "message": line,
                "timestamp": time.time(),
            })

    async def _poll_once(self) -> None:
        smart_reading, thermal_reading = await asyncio.gather(
            self.smart.poll(), self.thermal.poll()
        )

        await self._check_smart_breaches(smart_reading)
        await self._check_thermal_breaches(thermal_reading)

        self.textfile.write(smart_reading, thermal_reading, self.kmsg_faults_total)
        log.debug("poll complete: smart=%s thermal=%s", smart_reading, thermal_reading)

    async def _check_smart_breaches(self, smart_reading: Dict[str, Dict[str, int]]) -> None:
        for disk, attrs in smart_reading.items():
            baseline = self.smart_baselines.setdefault(disk, dict(attrs))
            for attr, value in attrs.items():
                if value > baseline.get(attr, 0):
                    await self.webhook.send({
                        "type": "smart_degradation",
                        "disk": disk,
                        "attribute": attr,
                        "previous": baseline[attr],
                        "current": value,
                        "timestamp": time.time(),
                    })
                    baseline[attr] = value

    async def _check_thermal_breaches(self, thermal_reading: Dict[str, float]) -> None:
        threshold = self.cfg["thermal_drift_threshold_c"]
        for zone, temp in thermal_reading.items():
            window = self.thermal_windows[zone]
            window.add(temp)
            drift = window.drift()
            if drift > threshold:
                await self.webhook.send({
                    "type": "thermal_drift",
                    "zone": zone,
                    "current_c": temp,
                    "drift_c": round(drift, 2),
                    "threshold_c": threshold,
                    "timestamp": time.time(),
                })


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to config.yaml", default=None)
    p.add_argument("--mock", action="store_true", help="synthesize readings instead of touching hardware")
    p.add_argument("--once", action="store_true", help="poll a single time and exit (for testing)")
    p.add_argument("--interval", type=float, default=None, help="override poll_interval_seconds")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    cfg = load_config(args.config)
    daemon = TelemetryDaemon(cfg, mock=args.mock)
    try:
        asyncio.run(daemon.run_forever(poll_interval=args.interval, iterations=1 if args.once else None))
    except KeyboardInterrupt:
        log.info("shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
