"""Tests for plan_from_lsblk.py, against synthetic (not real) lsblk -J
fixtures modeled on real lsblk's actual JSON shape. These are
IMPLEMENTED + TESTED against synthetic data — genuinely validating this
script's parsing/heuristic logic — but NOT validated against the user's
actual VM output, which doesn't exist yet. See PROJECT_SPEC.md's ledger.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plan_from_lsblk as planner  # noqa: E402


def lsblk(*disks) -> dict:
    return {"blockdevices": list(disks)}


def disk(name, size="20G", children=None, mountpoint=None, fstype=None, ro=False):
    d = {"name": name, "size": size, "type": "disk", "mountpoint": mountpoint, "fstype": fstype, "ro": ro}
    if children is not None:
        d["children"] = children
    return d


def part(name, size="20G", mountpoint=None, fstype=None):
    return {"name": name, "size": size, "type": "part", "mountpoint": mountpoint, "fstype": fstype}


class TestAssess(unittest.TestCase):
    def test_blank_disk_is_a_candidate(self):
        data = lsblk(disk("sdb"))
        results = planner.assess(data)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].in_use)
        self.assertEqual(results[0].path, "/dev/sdb")

    def test_os_disk_with_root_partition_is_in_use(self):
        os_disk = disk(
            "sda",
            children=[
                part("sda1", size="512M", mountpoint="/boot/efi", fstype="vfat"),
                part("sda2", size="49.5G", mountpoint="/", fstype="ext4"),
            ],
        )
        results = planner.assess(lsblk(os_disk))
        self.assertTrue(results[0].in_use)
        self.assertTrue(any("mounted at '/'" in r for r in results[0].reasons))

    def test_disk_with_filesystem_but_unmounted_is_still_in_use(self):
        # A disk that was used before and has a leftover filesystem but
        # isn't currently mounted must still be excluded — this is the
        # conservative direction to err in.
        stale_disk = disk("sdc", children=[part("sdc1", fstype="ext4", mountpoint=None)])
        results = planner.assess(lsblk(stale_disk))
        self.assertTrue(results[0].in_use)

    def test_disk_with_partitions_but_no_fs_or_mount_still_in_use(self):
        # Partitioned (even if we can't identify why) is never "blank."
        partitioned = disk("sdd", children=[part("sdd1")])
        results = planner.assess(lsblk(partitioned))
        self.assertTrue(results[0].in_use)

    def test_readonly_disk_is_in_use(self):
        ro_disk = disk("sde", ro=True)
        results = planner.assess(lsblk(ro_disk))
        self.assertTrue(results[0].in_use)

    def test_non_disk_types_are_ignored(self):
        data = {
            "blockdevices": [
                disk("sdb"),
                {"name": "loop0", "size": "1G", "type": "loop", "mountpoint": None, "fstype": None},
                {"name": "sr0", "size": "1G", "type": "rom", "mountpoint": None, "fstype": None},
            ]
        }
        results = planner.assess(data)
        self.assertEqual([r.name for r in results], ["sdb"])

    def test_realistic_three_disk_scenario(self):
        # 1 OS disk (partitioned, mounted) + 2 genuinely blank disks —
        # the exact target scenario this project is waiting for.
        os_disk = disk(
            "sda",
            size="50G",
            children=[
                part("sda1", size="512M", mountpoint="/boot/efi", fstype="vfat"),
                part("sda2", size="49.5G", mountpoint="/", fstype="ext4"),
            ],
        )
        results = planner.assess(lsblk(os_disk, disk("sdb", size="20G"), disk("sdc", size="20G")))
        in_use = [r for r in results if r.in_use]
        candidates = [r for r in results if not r.in_use]
        self.assertEqual([r.name for r in in_use], ["sda"])
        self.assertEqual([r.name for r in candidates], ["sdb", "sdc"])


class TestReport(unittest.TestCase):
    def test_report_warns_on_fewer_than_three_disks(self):
        report = planner.render_report(planner.assess(lsblk(disk("sda", children=[part("sda1", mountpoint="/")]), disk("sdb"))))
        self.assertIn("only 2 disk(s) total", report)

    def test_report_refuses_with_zero_candidates(self):
        os_only = disk("sda", children=[part("sda1", mountpoint="/")])
        report = planner.render_report(planner.assess(lsblk(os_only)))
        self.assertIn("REFUSING", report)
        self.assertIn("0 blank candidate", report)

    def test_report_refuses_with_one_candidate(self):
        os_disk = disk("sda", children=[part("sda1", mountpoint="/")])
        report = planner.render_report(planner.assess(lsblk(os_disk, disk("sdb"))))
        self.assertIn("REFUSING", report)
        self.assertIn("only 1 blank candidate", report)

    def test_report_refuses_with_three_or_more_candidates_as_ambiguous(self):
        report = planner.render_report(planner.assess(lsblk(disk("sdb"), disk("sdc"), disk("sdd"))))
        self.assertIn("REFUSING", report)
        self.assertIn("3 blank candidates", report)

    def test_report_does_not_refuse_with_exactly_two_candidates(self):
        os_disk = disk("sda", children=[part("sda1", mountpoint="/")])
        report = planner.render_report(planner.assess(lsblk(os_disk, disk("sdb"), disk("sdc"))))
        self.assertNotIn("REFUSING", report)


class TestCommandPlan(unittest.TestCase):
    def test_plan_uses_the_exact_candidate_paths(self):
        candidates = [planner.DiskAssessment("sdb", "/dev/sdb", "20G", False), planner.DiskAssessment("sdc", "/dev/sdc", "20G", False)]
        plan = planner.render_command_plan(candidates)
        self.assertIn("DISK1=/dev/sdb DISK2=/dev/sdc", plan)
        self.assertIn("PART1=/dev/sdb1 PART2=/dev/sdc1", plan)
        self.assertIn("SIMULATE=1", plan)


class TestMainCli(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp(prefix="plan_lsblk_test_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, data) -> str:
        path = self.tmpdir / "lsblk.json"
        path.write_text(json.dumps(data))
        return str(path)

    def test_cli_without_confirmation_flag_shows_report_only(self, capsys=None):
        import io
        import contextlib

        os_disk = disk("sda", children=[part("sda1", mountpoint="/")])
        path = self._write(lsblk(os_disk, disk("sdb"), disk("sdc")))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = planner.main([path])
        self.assertEqual(rc, 0)
        self.assertNotIn("Command plan", out.getvalue())
        self.assertIn("pass --i-confirm-these-are-blank-disks", out.getvalue())

    def test_cli_with_confirmation_flag_shows_command_plan(self):
        import io
        import contextlib

        os_disk = disk("sda", children=[part("sda1", mountpoint="/")])
        path = self._write(lsblk(os_disk, disk("sdb"), disk("sdc")))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = planner.main([path, "--i-confirm-these-are-blank-disks"])
        self.assertEqual(rc, 0)
        self.assertIn("Command plan", out.getvalue())
        self.assertIn("DISK1=/dev/sdb DISK2=/dev/sdc", out.getvalue())

    def test_cli_rejects_invalid_json(self):
        path = self.tmpdir / "bad.json"
        path.write_text("not json")
        import io
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = planner.main([str(path)])
        self.assertEqual(rc, 1)
        self.assertIn("not valid JSON", err.getvalue())

    def test_cli_reads_stdin_when_dash(self):
        import io
        import contextlib

        os_disk = disk("sda", children=[part("sda1", mountpoint="/")])
        data = lsblk(os_disk, disk("sdb"), disk("sdc"))
        out = io.StringIO()
        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO(json.dumps(data))
            with contextlib.redirect_stdout(out):
                rc = planner.main(["-"])
        finally:
            sys.stdin = old_stdin
        self.assertEqual(rc, 0)
        self.assertIn("Blank candidates: 2", out.getvalue())


if __name__ == "__main__":
    unittest.main()
