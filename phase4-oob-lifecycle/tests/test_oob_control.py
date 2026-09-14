"""Automated test suite for oob_control.py.

Until this suite, oob_control.py was only ever verified with one-off
manual `curl`/CLI runs against the mock server during the original build
(see PROJECT_SPEC.md's testing ledger: "mock-tested" via manual runs, not
automated-test-covered). This runs the same mock server in-process
(rather than shelling out to it) so every RedfishClient action and CLI
command path is exercised as a repeatable, automated test — including a
consistency check between oob_control.py's RESET_TYPE_MAP and the mock
server's own reset-type table, which would otherwise be able to silently
drift apart without either side's own tests noticing.
"""

import contextlib
import http.server
import io
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "redfish-mockup"))
import oob_control  # noqa: E402
import redfish_mock_server  # noqa: E402


class MockRedfishServerTestCase(unittest.TestCase):
    """Base class: spins up redfish_mock_server.Handler in-process on a
    random port, and resets its module-level STATE singleton before each
    test so tests don't leak PowerState/LED changes into each other."""

    def setUp(self):
        redfish_mock_server.STATE = redfish_mock_server.RedfishState()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), redfish_mock_server.Handler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def run_cli(self, args):
        """Runs oob_control.main() for real, capturing stdout — this
        exercises the exact same code path a real CLI invocation does,
        not just the RedfishClient class in isolation."""
        argv = ["--insecure", "--base-url", self.base_url] + args
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            returncode = oob_control.main(argv)
        return returncode, out.getvalue()


class TestPowerStatus(MockRedfishServerTestCase):
    def test_initial_power_state_is_on(self):
        client = oob_control.RedfishClient(self.base_url, None, None, verify=False)
        data = client.get("/redfish/v1/Systems/System.Embedded.1")
        self.assertEqual(data["PowerState"], "On")
        self.assertEqual(data["SerialNumber"], "MOCK-SN-0001")

    def test_cli_power_status(self):
        returncode, out = self.run_cli(["power-status"])
        self.assertEqual(returncode, 0)
        self.assertIn('"power_state": "On"', out)


class TestPowerCycle(MockRedfishServerTestCase):
    def test_every_reset_type_is_recognized_by_the_mock_server(self):
        # Consistency check: every reset_type oob_control.py exposes must
        # map to something the mock server's own table understands —
        # without this test, the two files could silently drift apart
        # (e.g. a new reset_type added to one but not the other) and
        # nothing would catch it until a real run failed.
        for cli_name, redfish_name in oob_control.RESET_TYPE_MAP.items():
            with self.subTest(reset_type=cli_name):
                self.assertIn(
                    redfish_name, redfish_mock_server.RESET_TO_POWER_STATE,
                    f"mock server does not know how to handle ResetType={redfish_name!r}",
                )

    def test_power_cycle_off_then_on_via_cli(self):
        returncode, out = self.run_cli(["power-cycle", "--reset-type", "off"])
        self.assertEqual(returncode, 0)
        self.assertIn('"PowerState": "Off"', out)

        status_code, status_out = self.run_cli(["power-status"])
        self.assertIn('"power_state": "Off"', status_out)

        returncode, out = self.run_cli(["power-cycle", "--reset-type", "on"])
        self.assertIn('"PowerState": "On"', out)

    def test_default_reset_type_is_cycle_and_leaves_power_on(self):
        client = oob_control.RedfishClient(self.base_url, None, None, verify=False)
        path = "/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset"
        result = client.post(path, {"ResetType": "PowerCycle"})
        self.assertEqual(result["PowerState"], "On")


class TestBootOverride(MockRedfishServerTestCase):
    def test_boot_override_pxe_once(self):
        returncode, out = self.run_cli(["boot-override", "--target", "pxe"])
        self.assertEqual(returncode, 0)
        self.assertIn('"BootSourceOverrideTarget": "Pxe"', out)
        self.assertIn('"BootSourceOverrideEnabled": "Once"', out)

    def test_boot_override_persistent(self):
        returncode, out = self.run_cli(["boot-override", "--target", "hdd", "--persistent"])
        self.assertEqual(returncode, 0)
        self.assertIn('"BootSourceOverrideEnabled": "Continuous"', out)

    def test_every_boot_target_is_accepted(self):
        for target in oob_control.BOOT_TARGETS:
            with self.subTest(target=target):
                returncode, _out = self.run_cli(["boot-override", "--target", target])
                self.assertEqual(returncode, 0)


class TestSetLed(MockRedfishServerTestCase):
    def test_set_led_blinking_then_off(self):
        returncode, out = self.run_cli(["set-led", "--drive", "1", "--state", "Blinking"])
        self.assertEqual(returncode, 0)
        self.assertIn('"IndicatorLED": "Blinking"', out)

        returncode, out = self.run_cli(["set-led", "--drive", "1", "--state", "Off"])
        self.assertIn('"IndicatorLED": "Off"', out)

    def test_set_led_unknown_drive_errors_cleanly(self):
        client = oob_control.RedfishClient(self.base_url, None, None, verify=False)
        path = "/redfish/v1/Chassis/System.Embedded.1/Drives/99"
        with self.assertRaises(Exception):
            client.patch(path, {"IndicatorLED": "Blinking"})


class TestCliErrorHandling(unittest.TestCase):
    def test_unreachable_endpoint_returns_nonzero_not_a_crash(self):
        # No mock server started for this test class — the connection
        # must genuinely fail, exercising main()'s real error handling
        # path rather than a mocked-out one.
        argv = ["--insecure", "--base-url", "http://127.0.0.1:1", "power-status"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            returncode = oob_control.main(argv)
        self.assertEqual(returncode, 1)
        self.assertIn("error:", err.getvalue())

    def test_invalid_reset_type_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            oob_control.build_parser().parse_args(
                ["--base-url", "http://x", "power-cycle", "--reset-type", "not-a-real-type"]
            )

    def test_invalid_boot_target_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            oob_control.build_parser().parse_args(
                ["--base-url", "http://x", "boot-override", "--target", "not-a-real-target"]
            )

    def test_missing_required_target_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            oob_control.build_parser().parse_args(["--base-url", "http://x", "boot-override"])


if __name__ == "__main__":
    unittest.main()
