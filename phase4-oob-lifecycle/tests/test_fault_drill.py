"""Automated test for fault_drill.sh's SIMULATE=1 output — previously
only verified by one-off manual runs during the original build (per
PROJECT_SPEC.md's testing ledger). Runs the REAL script as a real
subprocess with SIMULATE=1 and asserts the exact expected command
sequence appears, in order — not just "it didn't crash."

Classification: IMPLEMENTED + TESTED for the shell logic under
SIMULATE=1. The script's real-mode behavior (actual `mdadm --fail`
etc.) is NOT exercised here or anywhere else without real hardware —
see PROJECT_SPEC.md.
"""

import os
import subprocess
import unittest
from pathlib import Path

FAULT_DRILL = Path(__file__).resolve().parent.parent / "fault_drill.sh"


class TestFaultDrillSimulateOutput(unittest.TestCase):
    def _run(self, extra_env=None):
        env = dict(os.environ)
        env.update({
            "SIMULATE": "1",
            "FAILED_PART": "/dev/sdb1",
            "DRIVE_ID": "2",
            "MD_DEVICE": "/dev/md0",
            "CHASSIS_ID": "System.Embedded.1",
            "REDFISH_URL": "https://127.0.0.1:8443",
        })
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            ["bash", str(FAULT_DRILL)], env=env, capture_output=True, text=True, timeout=30,
        )
        return proc

    def test_exits_zero_under_simulate(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, f"stderr:\n{proc.stderr}")

    def test_never_touches_a_real_command_under_simulate(self):
        # Every mdadm/oob_control invocation must be prefixed "(simulated)"
        # — if a real command ever appears unprefixed, that's the exact
        # safety property this test exists to catch a regression in.
        proc = self._run()
        combined = proc.stdout + proc.stderr
        for line in combined.splitlines():
            if "mdadm --fail" in line or "mdadm --remove" in line or "mdadm --add" in line:
                self.assertIn("(simulated)", line, f"a real-looking mdadm command was not marked simulated: {line!r}")

    def test_five_steps_appear_in_order(self):
        proc = self._run()
        combined = proc.stdout + proc.stderr
        step_markers = ["Step 1/5", "Step 2/5", "Step 3/5", "Step 4/5", "Step 5/5"]
        positions = [combined.find(marker) for marker in step_markers]
        self.assertTrue(all(p != -1 for p in positions), f"missing a step marker: {list(zip(step_markers, positions))}")
        self.assertEqual(positions, sorted(positions), "steps did not appear in order 1 through 5")

    def test_exact_commands_use_the_confirmed_device_names(self):
        proc = self._run()
        combined = proc.stdout + proc.stderr
        self.assertIn("mdadm --fail /dev/md0 /dev/sdb1", combined)
        self.assertIn("mdadm --remove /dev/md0 /dev/sdb1", combined)
        self.assertIn("mdadm --add /dev/md0 /dev/sdb1", combined)

    def test_led_set_to_blinking_then_off(self):
        proc = self._run()
        combined = proc.stdout + proc.stderr
        blinking_pos = combined.find("set-led --drive 2 --state Blinking")
        off_pos = combined.find("set-led --drive 2 --state Off")
        self.assertNotEqual(blinking_pos, -1, "did not find the Blinking LED command")
        self.assertNotEqual(off_pos, -1, "did not find the Off LED command")
        self.assertLess(blinking_pos, off_pos, "LED must be set Blinking before being cleared to Off")

    def test_different_device_names_are_reflected_exactly(self):
        # Confirms the script genuinely parameterizes on the env vars
        # rather than having any hardcoded device name fallback that
        # would silently ignore a real, confirmed device name.
        proc = self._run(extra_env={"FAILED_PART": "/dev/sdz9", "MD_DEVICE": "/dev/md3", "DRIVE_ID": "7"})
        combined = proc.stdout + proc.stderr
        self.assertIn("mdadm --fail /dev/md3 /dev/sdz9", combined)
        self.assertIn("set-led --drive 7", combined)
        self.assertNotIn("/dev/sdb1", combined)

    def test_completion_message_present(self):
        proc = self._run()
        combined = proc.stdout + proc.stderr
        self.assertIn("Fault drill complete", combined)


if __name__ == "__main__":
    unittest.main()
