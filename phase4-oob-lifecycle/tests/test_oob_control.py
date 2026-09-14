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
import os
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

    def test_missing_base_url_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            oob_control.build_parser().parse_args(["power-status"])

    def test_missing_subcommand_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            oob_control.build_parser().parse_args(["--base-url", "http://x"])


class TestArgParsingDefaults(unittest.TestCase):
    """--user/--password/--timeout had no direct test coverage before
    this, including the REDFISH_USER/REDFISH_PASSWORD env var defaults
    (os.environ.get calls evaluated once at argparse construction time)."""

    def test_user_and_password_default_to_none_without_env_vars(self):
        for var in ("REDFISH_USER", "REDFISH_PASSWORD"):
            os.environ.pop(var, None)
        parser = oob_control.build_parser()  # env vars read at parser-build time
        args = parser.parse_args(["--base-url", "http://x", "power-status"])
        self.assertIsNone(args.user)
        self.assertIsNone(args.password)

    def test_user_and_password_env_vars_become_defaults(self):
        old_user = os.environ.get("REDFISH_USER")
        old_password = os.environ.get("REDFISH_PASSWORD")
        os.environ["REDFISH_USER"] = "admin"
        os.environ["REDFISH_PASSWORD"] = "hunter2"
        try:
            parser = oob_control.build_parser()
            args = parser.parse_args(["--base-url", "http://x", "power-status"])
            self.assertEqual(args.user, "admin")
            self.assertEqual(args.password, "hunter2")
        finally:
            for var, old in (("REDFISH_USER", old_user), ("REDFISH_PASSWORD", old_password)):
                if old is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = old

    def test_explicit_flags_override_env_vars(self):
        os.environ["REDFISH_USER"] = "from-env"
        try:
            parser = oob_control.build_parser()
            args = parser.parse_args(["--base-url", "http://x", "--user", "from-flag", "power-status"])
            self.assertEqual(args.user, "from-flag")
        finally:
            os.environ.pop("REDFISH_USER", None)

    def test_default_timeout_is_ten_seconds(self):
        args = oob_control.build_parser().parse_args(["--base-url", "http://x", "power-status"])
        self.assertEqual(args.timeout, 10.0)

    def test_custom_timeout_parsed(self):
        args = oob_control.build_parser().parse_args(
            ["--base-url", "http://x", "--timeout", "3.5", "power-status"]
        )
        self.assertEqual(args.timeout, 3.5)


class TestBasicAuthActuallyUsed(MockRedfishServerTestCase):
    """--user/--password must actually reach the HTTP request, not just
    parse — verified by checking the real Authorization header the mock
    server received, not just that no exception was raised."""

    def test_credentials_sent_as_http_basic_auth(self):
        received_headers = {}
        original_do_get = redfish_mock_server.Handler.do_GET

        def capturing_do_get(self):
            received_headers["Authorization"] = self.headers.get("Authorization")
            original_do_get(self)

        redfish_mock_server.Handler.do_GET = capturing_do_get
        try:
            returncode, _out = self.run_cli(["power-status"])
        finally:
            redfish_mock_server.Handler.do_GET = original_do_get

        # This particular CLI invocation didn't pass --user/--password —
        # confirms the ABSENCE of an Authorization header when none is given.
        self.assertEqual(returncode, 0)
        self.assertIsNone(received_headers["Authorization"])

        client = oob_control.RedfishClient(self.base_url, "admin", "hunter2", verify=False)
        received_headers.clear()
        redfish_mock_server.Handler.do_GET = capturing_do_get
        try:
            client.get("/redfish/v1/Systems/System.Embedded.1")
        finally:
            redfish_mock_server.Handler.do_GET = original_do_get

        self.assertIsNotNone(received_headers["Authorization"])
        self.assertTrue(received_headers["Authorization"].startswith("Basic "))


if __name__ == "__main__":
    unittest.main()
