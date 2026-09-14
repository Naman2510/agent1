"""Automated test suite for the dashboard backend (frontend/server.py).

Until this suite, the dashboard was only ever verified with one-off
manual `curl` runs during the build (see PROJECT_SPEC.md's testing
ledger). This runs the *real* dashboard server, the *real* mock Redfish
server, and a *real* storage_sim ArrayManager together — over actual
HTTP, not by calling handler methods directly — so it exercises exactly
what a browser or curl would hit.
"""

import http.client
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRONTEND_DIR))
sys.path.insert(0, str(FRONTEND_DIR.parent / "phase4-oob-lifecycle" / "redfish-mockup"))

import server as dash  # noqa: E402
import redfish_mock_server  # noqa: E402


class DashboardTestCase(unittest.TestCase):
    """Boots a real redfish_mock_server + a real dashboard server on
    random ports, both backed by fresh temp state, for every test."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="dashboard_test_"))

        redfish_mock_server.STATE = redfish_mock_server.RedfishState()
        self.redfish_server = ThreadingHTTPServer(("127.0.0.1", 0), redfish_mock_server.Handler)
        self.redfish_port = self.redfish_server.server_address[1]
        self.redfish_thread = threading.Thread(target=self.redfish_server.serve_forever, daemon=True)
        self.redfish_thread.start()

        dash.Handler.cfg = {
            "textfile_collector_path": str(self.tmpdir / "hardware.prom"),
            "redfish_base_url": f"http://127.0.0.1:{self.redfish_port}",
            "redfish_user": None,
            "redfish_password": None,
            "redfish_insecure": True,
            "redfish_system": "System.Embedded.1",
            "redfish_chassis": "System.Embedded.1",
            "fault_drill_script": str(dash.REPO_ROOT / "phase4-oob-lifecycle" / "fault_drill.sh"),
            "max_alerts": 200,
            "storage_sim_data_dir": str(self.tmpdir / "storage_sim_data"),
        }
        dash.Handler.alerts = dash.AlertStore(200)
        dash.Handler.storage_sim_mgr = dash.ArrayManager(dash.Handler.cfg["storage_sim_data_dir"])

        self.dash_server = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
        self.dash_port = self.dash_server.server_address[1]
        self.dash_thread = threading.Thread(target=self.dash_server.serve_forever, daemon=True)
        self.dash_thread.start()

    def tearDown(self):
        self.dash_server.shutdown()
        self.dash_server.server_close()
        self.dash_thread.join(timeout=2)
        self.redfish_server.shutdown()
        self.redfish_server.server_close()
        self.redfish_thread.join(timeout=2)
        dash.Handler.storage_sim_mgr.close_all()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # -- HTTP helpers -----------------------------------------------------

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.dash_port, timeout=5)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        return resp.status, raw

    def get(self, path):
        return self.request("GET", path)

    def post_json(self, path, body):
        status, raw = self.request("POST", path, body)
        return status, json.loads(raw) if raw else {}

    def get_json(self, path):
        status, raw = self.request("GET", path)
        return status, json.loads(raw) if raw else {}


class TestStaticServing(DashboardTestCase):
    def test_root_serves_index_html(self):
        status, raw = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Edge Server Dashboard</title>", raw)

    def test_static_css_and_js_served(self):
        status, raw = self.get("/static/style.css")
        self.assertEqual(status, 200)
        self.assertIn(b"--bg", raw)

        status, raw = self.get("/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"refreshSimStorage", raw)

    def test_path_traversal_is_blocked(self):
        status, _raw = self.request("GET", "/static/../server.py")
        self.assertEqual(status, 403)

    def test_unknown_api_route_is_404(self):
        status, _body = self.get_json("/api/does-not-exist")
        self.assertEqual(status, 404)


class TestCoreEndpoints(DashboardTestCase):
    def test_overview_reflects_real_mock_power_state(self):
        status, body = self.get_json("/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(body["power_state"], "On")
        self.assertIsNone(body["power_error"])

    def test_storage_and_telemetry_gracefully_report_unavailable(self):
        # No telemetryd has run against this temp textfile path — must
        # report cleanly, not error.
        status, body = self.get_json("/api/telemetry")
        self.assertEqual(status, 200)
        self.assertFalse(body["available"])

    def test_network_falls_back_to_static_config(self):
        status, body = self.get_json("/api/network")
        self.assertEqual(status, 200)
        self.assertIn("note", body)

    def test_alerts_ingest_and_list_roundtrip(self):
        status, _body = self.post_json("/api/alerts/ingest", {"type": "test", "message": "hello"})
        self.assertEqual(status, 200)
        status, body = self.get_json("/api/alerts")
        self.assertEqual(len(body["alerts"]), 1)
        self.assertEqual(body["alerts"][0]["message"], "hello")


class TestOobEndpoints(DashboardTestCase):
    def test_power_cycle_actually_flips_mock_state(self):
        status, body = self.post_json("/api/oob/power-cycle", {"reset_type": "off"})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["PowerState"], "Off")

        status, body = self.get_json("/api/oob/power-status")
        self.assertEqual(body["power_state"], "Off")

    def test_boot_override_persists(self):
        status, body = self.post_json("/api/oob/boot-override", {"target": "pxe"})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["Boot"]["BootSourceOverrideTarget"], "Pxe")

    def test_set_led_persists(self):
        status, body = self.post_json("/api/oob/set-led", {"drive": "1", "state": "Blinking"})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["IndicatorLED"], "Blinking")

    def test_drill_run_is_forced_to_simulate(self):
        status, body = self.post_json("/api/drill/run", {"failed_part": "/dev/sdb1", "drive_id": "2"})
        self.assertEqual(status, 200)
        self.assertIn("SIMULATE=1", body["note"])
        self.assertIn("simulated", body["output"])


class TestSimStorageEndpoints(DashboardTestCase):
    def test_full_lifecycle_over_http(self):
        status, body = self.post_json(
            "/api/simstorage/create", {"name": "tank", "num_blocks": 16, "block_size": 32}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "clean")

        status, body = self.get_json("/api/simstorage/list")
        self.assertEqual(len(body["arrays"]), 1)

        status, body = self.post_json(
            "/api/simstorage/write", {"name": "tank", "block_index": 0, "data": "over http"}
        )
        self.assertEqual(status, 200)
        status, body = self.get_json("/api/simstorage/read?name=tank&block_index=0")
        self.assertEqual(body["data"], "over http")

        status, body = self.post_json("/api/simstorage/fail", {"name": "tank", "label": "tank-0"})
        self.assertEqual(body["state"], "degraded")

        status, body = self.post_json("/api/simstorage/remove", {"name": "tank", "label": "tank-0"})
        self.assertEqual(status, 200)

        status, body = self.post_json(
            "/api/simstorage/add", {"name": "tank", "label": "tank-0", "delay_per_block": 0.02}
        )
        self.assertEqual(status, 200)

        # Poll status over real HTTP until the rebuild finishes — this is
        # exactly the live-progress behavior the CLI cannot do (see
        # storage_sim/README.md) and the dashboard exists to provide.
        deadline = time.time() + 5
        saw_in_progress = False
        final_state = None
        while time.time() < deadline:
            status, body = self.get_json("/api/simstorage/status?name=tank")
            if body.get("rebuild") and not body["rebuild"]["finished"]:
                saw_in_progress = True
            if body["state"] == "clean" and body.get("rebuild", {}).get("finished"):
                final_state = body["state"]
                break
            time.sleep(0.05)
        self.assertTrue(saw_in_progress, "expected to observe the rebuild in progress via polling")
        self.assertEqual(final_state, "clean")

        status, body = self.post_json("/api/simstorage/corrupt", {"name": "tank", "label": "tank-1", "block_index": 3})
        self.assertEqual(status, 200)
        status, body = self.post_json("/api/simstorage/scrub", {"name": "tank", "repair": True})
        self.assertEqual(len(body["mismatches"]), 1)

        status, body = self.post_json("/api/simstorage/hardware-fail", {"name": "tank", "label": "tank-1"})
        self.assertEqual(status, 200)

    def test_missing_required_field_is_400_not_500(self):
        status, body = self.post_json("/api/simstorage/create", {"num_blocks": 16})  # no "name"
        self.assertEqual(status, 400)
        self.assertIn("name", body["error"])

    def test_unknown_array_is_400_not_500(self):
        status, body = self.get_json("/api/simstorage/status?name=does-not-exist")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
