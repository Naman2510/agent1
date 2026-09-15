"""Automated test suite for telemetryd.py.

telemetryd.py was, until this suite, only ever verified with one-off
manual runs during the original build (documented honestly in
PROJECT_SPEC.md's testing ledger as "mock-tested", not "automated-test-
covered"). This closes that gap: every collector, sink, and the sliding-
window anomaly detector are exercised here for real, including two real
code paths the manual runs never actually reached — see
`TestThermalCollectorReal` and `TestKmsgCollectorReal` below, both of
which only ever ran their *mock* branch before because this sandbox has
no real thermal zones or /dev/kmsg.
"""

import asyncio
import http.server
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import telemetryd  # noqa: E402


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestSlidingWindow(unittest.TestCase):
    def test_average_of_samples_in_window(self):
        w = telemetryd.SlidingWindow(window_seconds=10)
        now = 1000.0
        w.add(10.0, now=now)
        w.add(20.0, now=now + 1)
        w.add(30.0, now=now + 2)
        # average of the three samples currently in the window
        self.assertAlmostEqual(sum(x[1] for x in w.samples) / len(w.samples), 20.0)

    def test_old_samples_evicted_outside_window(self):
        w = telemetryd.SlidingWindow(window_seconds=5)
        w.add(100.0, now=0.0)
        w.add(0.0, now=10.0)  # 10s later — the first sample is now outside a 5s window
        self.assertEqual(len(w.samples), 1)
        self.assertEqual(w.samples[0][1], 0.0)

    def test_drift_relative_to_first_seen_baseline(self):
        w = telemetryd.SlidingWindow(window_seconds=300)
        w.add(50.0, now=0.0)
        self.assertEqual(w.baseline, 50.0)
        w.add(65.0, now=1.0)
        # average of [50, 65] = 57.5, drift from baseline 50 = 7.5
        self.assertAlmostEqual(w.drift(), 7.5)

    def test_drift_zero_with_no_samples(self):
        w = telemetryd.SlidingWindow(window_seconds=300)
        self.assertEqual(w.drift(), 0.0)


class TestPrometheusTextfileSink(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="telemetryd_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_produces_valid_exposition_format(self):
        path = self.tmpdir / "hardware.prom"
        sink = telemetryd.PrometheusTextfileSink(str(path))
        smart = {"/dev/sda": {"reallocated_sector_count": 0, "current_pending_sector_count": 1}}
        thermal = {"thermal_zone0": 42.5}
        sink.write(smart, thermal, kmsg_faults_total=3)

        text = path.read_text()
        self.assertIn('telemetryd_smart_attribute{disk="/dev/sda",attribute="reallocated_sector_count"} 0', text)
        self.assertIn('telemetryd_smart_attribute{disk="/dev/sda",attribute="current_pending_sector_count"} 1', text)
        self.assertIn('telemetryd_thermal_celsius{zone="thermal_zone0"} 42.50', text)
        self.assertIn("telemetryd_kmsg_faults_total 3", text)
        # No leftover temp file from the atomic-write rename.
        self.assertFalse(path.with_suffix(".prom.tmp").exists())

    def test_write_creates_parent_directories(self):
        path = self.tmpdir / "nested" / "dir" / "hardware.prom"
        sink = telemetryd.PrometheusTextfileSink(str(path))
        sink.write({}, {}, 0)
        self.assertTrue(path.exists())


class _CapturingWebhookHandler(http.server.BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        self.__class__.received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class TestWebhookSink(unittest.TestCase):
    def setUp(self):
        _CapturingWebhookHandler.received = []
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _CapturingWebhookHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_send_posts_json_payload(self):
        sink = telemetryd.WebhookSink(f"http://127.0.0.1:{self.port}/hook", timeout=5)
        run_async(sink.send({"type": "test_alert", "value": 42}))
        self.assertEqual(len(_CapturingWebhookHandler.received), 1)
        self.assertEqual(_CapturingWebhookHandler.received[0], {"type": "test_alert", "value": 42})

    def test_send_with_no_url_does_not_raise(self):
        sink = telemetryd.WebhookSink(None)
        run_async(sink.send({"type": "test_alert"}))  # must not raise
        self.assertEqual(_CapturingWebhookHandler.received, [])

    def test_send_to_unreachable_url_does_not_raise(self):
        # Port 1 is reserved and nothing should be listening on it — this
        # exercises the actual network-failure path, not just the happy path.
        sink = telemetryd.WebhookSink("http://127.0.0.1:1/hook", timeout=1)
        run_async(sink.send({"type": "test_alert"}))  # must not raise


class TestSmartCollector(unittest.TestCase):
    def test_mock_mode_returns_all_configured_disks(self):
        collector = telemetryd.SmartCollector(["/dev/sda", "/dev/sdb"], mock=True)
        result = run_async(collector.poll())
        self.assertEqual(set(result.keys()), {"/dev/sda", "/dev/sdb"})
        for attrs in result.values():
            self.assertEqual(set(attrs.keys()), set(telemetryd.SMART_ATTRS_OF_INTEREST.values()))

    def test_real_mode_without_smartctl_falls_back_gracefully(self):
        # This sandbox genuinely has no smartctl installed (verified
        # during the original build) — this exercises the real
        # "smartctl missing" fallback path, not a simulated one.
        self.assertIsNone(shutil.which("smartctl"), "this test assumes smartctl is not installed")
        collector = telemetryd.SmartCollector(["/dev/sda"], mock=False)
        result = run_async(collector.poll())
        self.assertIn("/dev/sda", result)


class TestThermalCollectorMock(unittest.TestCase):
    def test_mock_mode_returns_plausible_values(self):
        collector = telemetryd.ThermalCollector("/sys/class/thermal/thermal_zone*/temp", mock=True)
        result = run_async(collector.poll())
        self.assertTrue(result)
        for temp in result.values():
            self.assertTrue(20 < temp < 80)


class TestThermalCollectorReal(unittest.TestCase):
    """Exercises the REAL (non-mock) sysfs-glob code path — never reached
    by the original manual verification, since this sandbox has no real
    /sys/class/thermal. Made possible by threading a configurable `base`
    through ThermalCollector (see telemetryd.py) instead of hardcoding
    the real filesystem root."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="telemetryd_thermal_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_fake_sysfs(self, zone_temps_millidegrees: dict):
        base = self.tmpdir / "sys" / "class" / "thermal"
        for zone, millidegrees in zone_temps_millidegrees.items():
            zone_dir = base / zone
            zone_dir.mkdir(parents=True, exist_ok=True)
            (zone_dir / "temp").write_text(str(millidegrees))
        return self.tmpdir

    def test_reads_real_sysfs_style_files(self):
        base = self._make_fake_sysfs({"thermal_zone0": 45000, "thermal_zone1": 52500})
        collector = telemetryd.ThermalCollector(
            "/sys/class/thermal/thermal_zone*/temp", mock=False, base=base
        )
        result = run_async(collector.poll())
        self.assertEqual(result, {"thermal_zone0": 45.0, "thermal_zone1": 52.5})

    def test_falls_back_to_mock_when_no_zones_found(self):
        empty_base = self.tmpdir  # no sys/class/thermal tree created at all
        collector = telemetryd.ThermalCollector(
            "/sys/class/thermal/thermal_zone*/temp", mock=False, base=empty_base
        )
        result = run_async(collector.poll())
        self.assertTrue(result)  # mock fallback still returns plausible data, not an empty dict

    def test_ignores_unreadable_zone_without_crashing(self):
        base = self._make_fake_sysfs({"thermal_zone0": 45000})
        # A zone file with non-numeric content models a real sysfs read
        # racing a sensor error — must be skipped, not raise.
        bad_zone = base / "sys" / "class" / "thermal" / "thermal_zone1"
        bad_zone.mkdir(parents=True)
        (bad_zone / "temp").write_text("not-a-number")
        collector = telemetryd.ThermalCollector(
            "/sys/class/thermal/thermal_zone*/temp", mock=False, base=base
        )
        result = run_async(collector.poll())
        self.assertEqual(result, {"thermal_zone0": 45.0})


class TestKmsgCollectorReal(unittest.TestCase):
    """Exercises the REAL (non-mock) kmsg-tailing code path against a
    real file on disk — never reached by the original manual runs, since
    kmsg_path defaulted to /dev/kmsg, which doesn't exist in this
    sandbox, so it always silently fell back to the mock branch."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="telemetryd_kmsg_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fault_marker_line_is_queued(self):
        kmsg_path = self.tmpdir / "fake_kmsg"
        kmsg_path.write_text(
            "6,100,0,-;normal boot message\n"
            "3,101,0,-;mce: [Hardware Error]: CPU 0: Machine Check Exception\n"
            "6,102,0,-;another normal line\n"
        )
        queue: "asyncio.Queue[str]" = asyncio.Queue()
        collector = telemetryd.KmsgCollector(str(kmsg_path), queue, mock=False)

        async def run_briefly():
            task = asyncio.create_task(collector.run())
            try:
                line = await asyncio.wait_for(queue.get(), timeout=2)
                return line
            finally:
                collector.stop()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        line = run_async(run_briefly())
        self.assertIn("mce:", line.lower())
        self.assertTrue(queue.empty(), "the normal-boot-message lines must NOT be queued")

    def test_falls_back_to_mock_when_path_does_not_exist(self):
        queue: "asyncio.Queue[str]" = asyncio.Queue()
        collector = telemetryd.KmsgCollector("/nonexistent/path/kmsg", queue, mock=False)

        async def run_briefly():
            task = asyncio.create_task(collector.run())
            await asyncio.sleep(0.1)
            collector.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        run_async(run_briefly())  # must not raise, and must not hang


class TestTelemetryDaemonIntegration(unittest.TestCase):
    """End-to-end: a real TelemetryDaemon, in --mock mode, actually
    polling, writing the textfile, and firing a real webhook alert on a
    forced sliding-window breach — the same scenario manually verified
    once during the original build, now automated and repeatable."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="telemetryd_daemon_"))
        _CapturingWebhookHandler.received = []
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _CapturingWebhookHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_thermal_drift_breach_fires_webhook_and_writes_textfile(self):
        cfg = dict(telemetryd.DEFAULT_CONFIG)
        cfg.update({
            "poll_interval_seconds": 0.01,
            "window_seconds": 5,
            "thermal_drift_threshold_c": -100.0,  # guaranteed to breach on the very first poll
            "disks": ["/dev/fake0"],
            "textfile_collector_path": str(self.tmpdir / "hardware.prom"),
            "webhook_url": f"http://127.0.0.1:{self.port}/hook",
        })
        daemon = telemetryd.TelemetryDaemon(cfg, mock=True)
        run_async(daemon.run_forever(iterations=1))

        self.assertTrue((self.tmpdir / "hardware.prom").exists())
        text = (self.tmpdir / "hardware.prom").read_text()
        self.assertIn("telemetryd_thermal_celsius", text)

        thermal_alerts = [a for a in _CapturingWebhookHandler.received if a.get("type") == "thermal_drift"]
        self.assertTrue(thermal_alerts, "expected at least one thermal_drift alert to have fired")

    def test_smart_degradation_fires_webhook_on_increase(self):
        cfg = dict(telemetryd.DEFAULT_CONFIG)
        cfg.update({
            "disks": ["/dev/fake0"],
            "textfile_collector_path": str(self.tmpdir / "hardware.prom"),
            "webhook_url": f"http://127.0.0.1:{self.port}/hook",
        })
        daemon = telemetryd.TelemetryDaemon(cfg, mock=True)

        # First poll establishes the baseline (deterministic, not mock-random).
        run_async(daemon._check_smart_breaches({"/dev/fake0": {"reallocated_sector_count": 0}}))
        self.assertEqual(_CapturingWebhookHandler.received, [])

        # A real increase must fire exactly one alert.
        run_async(daemon._check_smart_breaches({"/dev/fake0": {"reallocated_sector_count": 1}}))
        smart_alerts = [a for a in _CapturingWebhookHandler.received if a.get("type") == "smart_degradation"]
        self.assertEqual(len(smart_alerts), 1)
        self.assertEqual(smart_alerts[0]["previous"], 0)
        self.assertEqual(smart_alerts[0]["current"], 1)

        # A steady value must NOT fire again.
        run_async(daemon._check_smart_breaches({"/dev/fake0": {"reallocated_sector_count": 1}}))
        self.assertEqual(len(_CapturingWebhookHandler.received), 1)


class TestLoadConfig(unittest.TestCase):
    """load_config() had zero test coverage before this — every branch
    (no path, missing file, valid YAML, empty YAML, PyYAML unavailable)
    is exercised below."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="telemetryd_config_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_path_returns_defaults(self):
        self.assertEqual(telemetryd.load_config(None), telemetryd.DEFAULT_CONFIG)

    def test_nonexistent_path_returns_defaults(self):
        cfg = telemetryd.load_config(str(self.tmpdir / "does-not-exist.yaml"))
        self.assertEqual(cfg, telemetryd.DEFAULT_CONFIG)

    def test_valid_yaml_overrides_defaults_but_keeps_unspecified_keys(self):
        path = self.tmpdir / "config.yaml"
        path.write_text("poll_interval_seconds: 5\ndisks:\n  - /dev/testdisk\n")
        cfg = telemetryd.load_config(str(path))
        self.assertEqual(cfg["poll_interval_seconds"], 5)
        self.assertEqual(cfg["disks"], ["/dev/testdisk"])
        self.assertEqual(cfg["window_seconds"], telemetryd.DEFAULT_CONFIG["window_seconds"])

    def test_empty_yaml_file_returns_defaults(self):
        path = self.tmpdir / "empty.yaml"
        path.write_text("")
        self.assertEqual(telemetryd.load_config(str(path)), telemetryd.DEFAULT_CONFIG)

    def test_missing_pyyaml_falls_back_to_defaults_with_a_warning(self):
        # Monkeypatches the module's own `yaml` global rather than
        # actually uninstalling PyYAML — this exercises the real
        # `if yaml is None:` branch in load_config(), not a re-implementation.
        path = self.tmpdir / "config.yaml"
        path.write_text("poll_interval_seconds: 999\n")
        original_yaml = telemetryd.yaml
        telemetryd.yaml = None
        try:
            cfg = telemetryd.load_config(str(path))
        finally:
            telemetryd.yaml = original_yaml
        self.assertEqual(cfg, telemetryd.DEFAULT_CONFIG)  # file ignored entirely, not partially applied


class TestParseArgs(unittest.TestCase):
    def test_defaults(self):
        args = telemetryd.parse_args([])
        self.assertIsNone(args.config)
        self.assertFalse(args.mock)
        self.assertFalse(args.once)
        self.assertIsNone(args.interval)
        self.assertFalse(args.verbose)

    def test_all_flags_parsed(self):
        args = telemetryd.parse_args(
            ["--config", "/tmp/x.yaml", "--mock", "--once", "--interval", "2.5", "-v"]
        )
        self.assertEqual(args.config, "/tmp/x.yaml")
        self.assertTrue(args.mock)
        self.assertTrue(args.once)
        self.assertEqual(args.interval, 2.5)
        self.assertTrue(args.verbose)


class TestMainEntryPoint(unittest.TestCase):
    """main() — the actual `python3 telemetryd.py ...` entry point — had
    zero direct test coverage before this; only its constituent pieces
    were tested individually. This runs it exactly as a real invocation
    would, argv and all."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="telemetryd_main_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_config(self, textfile: Path) -> Path:
        config_path = self.tmpdir / "config.yaml"
        config_path.write_text(f"textfile_collector_path: {textfile}\ndisks: [/dev/fake0]\n")
        return config_path

    def test_main_mock_once_writes_textfile_and_returns_zero(self):
        textfile = self.tmpdir / "hardware.prom"
        config_path = self._write_config(textfile)
        rc = telemetryd.main(["--mock", "--once", "--config", str(config_path)])
        self.assertEqual(rc, 0)
        self.assertTrue(textfile.exists())
        self.assertIn("telemetryd_thermal_celsius", textfile.read_text())

    def test_main_with_interval_override_and_verbose_completes_quickly(self):
        textfile = self.tmpdir / "hardware.prom"
        config_path = self._write_config(textfile)
        start = time.time()
        rc = telemetryd.main(
            ["--mock", "--once", "--interval", "0.01", "--config", str(config_path), "-v"]
        )
        elapsed = time.time() - start
        self.assertEqual(rc, 0)
        self.assertLess(elapsed, 5, "a single --once iteration should never take this long")

    def test_main_handles_keyboard_interrupt_gracefully(self):
        # Simulates Ctrl-C landing inside asyncio.run() — main() must
        # catch it and return 0, not propagate a traceback to the shell.
        import unittest.mock as mock

        def _raise_keyboard_interrupt(coro):
            # asyncio.run(coro) is mocked out entirely, so the real
            # coroutine it would have awaited is never awaited by
            # anyone — close it explicitly, or Python emits a spurious
            # "coroutine was never awaited" RuntimeWarning (observed
            # landing on a LATER, unrelated test's output, since garbage
            # collection timing is non-deterministic — a real, if minor,
            # test-hygiene bug this fixed rather than ignored).
            coro.close()
            raise KeyboardInterrupt

        config_path = self._write_config(self.tmpdir / "hardware.prom")
        with mock.patch("telemetryd.asyncio.run", side_effect=_raise_keyboard_interrupt):
            rc = telemetryd.main(["--mock", "--config", str(config_path)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
