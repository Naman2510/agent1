import shutil
import tempfile
import time
import unittest
from pathlib import Path

from storage_sim.block_device import SimulatedBlockDevice, create_single_raid_partition
from storage_sim.exceptions import InvalidOperationError
from storage_sim.manager import ArrayManager
from storage_sim.raid1 import RAID1Array
from storage_sim.tests.helpers import pad_block


class TestArrayManagerCreation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="manager_test_"))
        self.mgr = ArrayManager(self.tmpdir)

    def tearDown(self):
        self.mgr.close_all()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_array_is_clean_and_writable(self):
        arr = self.mgr.create_array("tank", num_blocks=16, block_size=32)
        self.assertEqual(arr.status()["state"], "clean")
        self.mgr.write_block("tank", 0, pad_block("hello"))
        self.assertEqual(self.mgr.read_block("tank", 0), pad_block("hello"))

    def test_duplicate_name_rejected(self):
        self.mgr.create_array("tank", num_blocks=16, block_size=32)
        with self.assertRaises(InvalidOperationError):
            self.mgr.create_array("tank", num_blocks=16, block_size=32)

    def test_list_arrays_reports_status(self):
        self.mgr.create_array("tank", num_blocks=16, block_size=32)
        arrays = self.mgr.list_arrays()
        self.assertEqual(len(arrays), 1)
        self.assertEqual(arrays[0]["name"], "tank")
        self.assertEqual(arrays[0]["state"], "clean")

    def test_write_bumps_event_count_on_reachable_members(self):
        self.mgr.create_array("tank", num_blocks=16, block_size=32)
        self.mgr.write_block("tank", 0, pad_block("x"))
        rec = self.mgr._record_for("tank")
        for dev in rec.raw_devices.values():
            self.assertEqual(dev.read_superblock().event_count, 1)


class TestArrayManagerFailReplaceRebuild(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="manager_test_"))
        self.mgr = ArrayManager(self.tmpdir)
        self.mgr.create_array("tank", num_blocks=16, block_size=32)
        for i in range(16):
            self.mgr.write_block("tank", i, pad_block(f"v{i}"))

    def tearDown(self):
        self.mgr.close_all()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_fail_remove_add_rebuild_cycle(self):
        self.mgr.fail("tank", "tank-0")
        self.assertEqual(self.mgr.get("tank").status()["state"], "degraded")

        self.mgr.remove("tank", "tank-0")
        self.mgr.add("tank", "tank-0", delay_per_block=0.0)
        self.mgr.get("tank").wait_for_rebuild(timeout=5)

        status = self.mgr.get("tank").status()
        self.assertEqual(status["state"], "clean")
        for i in range(16):
            self.assertEqual(self.mgr.read_block("tank", i), pad_block(f"v{i}"))

    def test_corrupt_and_scrub_via_manager(self):
        self.mgr.inject_corruption("tank", "tank-1", 4)
        result = self.mgr.scrub("tank", repair=True)
        self.assertEqual(len(result["mismatches"]), 1)
        self.assertEqual(self.mgr.read_block("tank", 4), pad_block("v4"))

    def test_hardware_failure_via_manager_degrades_array(self):
        self.mgr.simulate_hardware_failure("tank", "tank-0")
        # The array doesn't know yet until an I/O actually hits that
        # member and raises — same as a real disk that's still "present"
        # to mdadm until the next command touches it.
        self.mgr.read_block("tank", 0)
        self.assertEqual(self.mgr.get("tank").status()["state"], "degraded")


class TestArrayManagerAssembly(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="manager_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reassembly_after_simulated_restart_preserves_data(self):
        mgr1 = ArrayManager(self.tmpdir)
        mgr1.create_array("tank", num_blocks=16, block_size=32)
        for i in range(16):
            mgr1.write_block("tank", i, pad_block(f"v{i}"))
        mgr1.close_all()  # simulates the process exiting

        mgr2 = ArrayManager(self.tmpdir)
        reports = mgr2.assemble_all()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].name, "tank")
        self.assertEqual(reports[0].excluded_stale, [])

        arr = mgr2.get("tank")
        self.assertEqual(arr.status()["state"], "clean")
        for i in range(16):
            self.assertEqual(mgr2.read_block("tank", i), pad_block(f"v{i}"))
        mgr2.close_all()

    def test_reassembly_brings_up_degraded_when_one_disk_missing(self):
        mgr1 = ArrayManager(self.tmpdir)
        mgr1.create_array("tank", num_blocks=16, block_size=32)
        mgr1.write_block("tank", 0, pad_block("v0"))
        mgr1.close_all()

        (self.tmpdir / "tank-1.img").unlink()  # simulate a disk that's physically gone

        mgr2 = ArrayManager(self.tmpdir)
        reports = mgr2.assemble_all()
        self.assertEqual(reports[0].included_labels, ["tank-0"])
        self.assertEqual(mgr2.get("tank").status()["state"], "degraded")
        self.assertEqual(mgr2.read_block("tank", 0), pad_block("v0"))
        mgr2.close_all()

    def test_assembly_excludes_stale_member_by_event_count(self):
        # Constructed directly (not via the full fail/add flow) to keep
        # the scenario deterministic: two disk images sharing an
        # array_uuid and declaring roles 0/1, but with role 0's event
        # count behind role 1's — modeling a disk that was offline while
        # the array kept running and accumulating writes.
        probe = SimulatedBlockDevice.create(self.tmpdir / "probe.img", num_blocks=4, block_size=16)
        array_uuid = probe.read_superblock().array_uuid
        probe.close()
        (self.tmpdir / "probe.img").unlink()

        d_stale = SimulatedBlockDevice.create(
            self.tmpdir / "pair-0.img", num_blocks=4, block_size=16, array_uuid=array_uuid, role=0
        )
        sb = d_stale.read_superblock()
        sb.event_count = 1
        sb.name = "pair"
        d_stale.write_superblock(sb)
        d_stale.close()

        d_current = SimulatedBlockDevice.create(
            self.tmpdir / "pair-1.img", num_blocks=4, block_size=16, array_uuid=array_uuid, role=1
        )
        sb = d_current.read_superblock()
        sb.event_count = 5
        sb.name = "pair"
        d_current.write_superblock(sb)
        d_current.close()

        mgr = ArrayManager(self.tmpdir)
        reports = mgr.assemble_all()
        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertEqual(report.included_labels, ["pair-1"])
        self.assertEqual(len(report.excluded_stale), 1)
        self.assertEqual(report.excluded_stale[0]["label"], "pair-0")
        self.assertEqual(report.excluded_stale[0]["event_count"], 1)
        self.assertEqual(mgr.get("pair").status()["state"], "degraded")
        mgr.close_all()

    def test_assembly_skips_a_disk_with_a_corrupted_superblock_without_crashing(self):
        # A superblock is just bytes at the start of a file — corrupt it
        # directly (bypassing the normal write path, modeling real disk
        # corruption of the metadata region itself, not the data region)
        # and confirm assemble_all() skips that file gracefully instead
        # of crashing the whole scan, while a COMPLETELY SEPARATE valid
        # array in the same directory is entirely unaffected.
        mgr1 = ArrayManager(self.tmpdir)
        mgr1.create_array("good", num_blocks=8, block_size=16)
        mgr1.write_block("good", 0, pad_block("still-fine", size=16))
        mgr1.close_all()

        # A file that merely LOOKS like it might be one of ours, but
        # whose superblock region is garbage from byte 0.
        junk_path = self.tmpdir / "junk-0.img"
        with open(junk_path, "wb") as fh:
            fh.write(b"\xff" * 4096 + b"\x00" * (16 + 32) * 8)

        mgr2 = ArrayManager(self.tmpdir)
        reports = mgr2.assemble_all()  # must not raise

        self.assertEqual(len(reports), 1)  # only "good" — junk-0.img contributed nothing
        self.assertEqual(reports[0].name, "good")
        self.assertEqual(mgr2.read_block("good", 0), pad_block("still-fine", size=16))
        mgr2.close_all()

    def test_assembly_skips_array_where_every_member_superblock_is_corrupt(self):
        mgr1 = ArrayManager(self.tmpdir)
        mgr1.create_array("doomed", num_blocks=8, block_size=16)
        mgr1.close_all()

        for name in ("doomed-0.img", "doomed-1.img"):
            path = self.tmpdir / name
            with open(path, "r+b") as fh:
                fh.write(b"\xff" * 4096)  # stomp the superblock region on BOTH members

        mgr2 = ArrayManager(self.tmpdir)
        reports = mgr2.assemble_all()  # must not raise
        self.assertEqual(reports, [])  # nothing readable -> nothing to report, not a crash
        mgr2.close_all()


class TestArrayManagerCrossProcessLifecycle(unittest.TestCase):
    """Regression coverage for a real bug caught while building this:
    without persisting *which member is failed/removed/mid-rebuild* (not
    just which disk images exist), a fresh process would silently
    reactivate a failed-but-still-readable disk, because nothing on disk
    recorded that it had been kicked out. Every test here simulates a
    process restart between steps by constructing a brand-new
    ArrayManager over the same data_dir, exactly like separate CLI
    invocations do."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="manager_lifecycle_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fail_remove_add_rebuild_survive_process_restarts_between_every_step(self):
        mgr = ArrayManager(self.tmpdir)
        mgr.create_array("tank", num_blocks=16, block_size=32)
        for i in range(16):
            mgr.write_block("tank", i, pad_block(f"v{i}"))
        mgr.close_all()

        mgr = ArrayManager(self.tmpdir)
        mgr.assemble_all()
        mgr.fail("tank", "tank-0")
        self.assertEqual(mgr.get("tank").status()["state"], "degraded")
        mgr.close_all()

        # This is the exact scenario that used to fail: a fresh process
        # reassembling must NOT silently reactivate tank-0 just because
        # its file is still present and readable.
        mgr = ArrayManager(self.tmpdir)
        reports = mgr.assemble_all()
        self.assertEqual(
            [u["label"] for u in reports[0].untrusted_by_state], ["tank-0"],
            "a failed member must not be silently reactivated across a process restart",
        )
        self.assertEqual(mgr.get("tank").status()["state"], "degraded")
        mgr.remove("tank", "tank-0")  # must succeed without error even though this process never saw the `fail`
        mgr.close_all()

        mgr = ArrayManager(self.tmpdir)
        mgr.assemble_all()
        mgr.add("tank", "tank-0", delay_per_block=0.0)
        progress = mgr.get("tank").wait_for_rebuild(timeout=5)
        self.assertTrue(progress.finished)
        self.assertEqual(mgr.get("tank").status()["state"], "clean")
        mgr.close_all()

        mgr = ArrayManager(self.tmpdir)
        mgr.assemble_all()
        for i in range(16):
            self.assertEqual(mgr.read_block("tank", i), pad_block(f"v{i}"))
        self.assertEqual(mgr.get("tank").status()["state"], "clean")
        mgr.close_all()

    def test_interrupted_rebuild_is_not_trusted_after_restart(self):
        mgr = ArrayManager(self.tmpdir)
        mgr.create_array("tank", num_blocks=32, block_size=32)
        for i in range(32):
            mgr.write_block("tank", i, pad_block(f"v{i}"))
        mgr.fail("tank", "tank-0")
        mgr.remove("tank", "tank-0")
        # Start a slow rebuild, then simulate a crash (process exit)
        # before it finishes — never call wait_for_rebuild.
        mgr.add("tank", "tank-0", delay_per_block=0.05)
        time.sleep(0.15)  # rebuild is now partway through, definitely not finished
        mgr.close_all()

        mgr = ArrayManager(self.tmpdir)
        reports = mgr.assemble_all()
        labels = [u["label"] for u in reports[0].untrusted_by_state]
        self.assertIn(
            "tank-0", labels,
            "a rebuild interrupted by a restart must not be silently trusted as complete",
        )
        self.assertEqual(mgr.get("tank").status()["state"], "degraded")
        # Recovery path: a fresh add (full re-copy) still works.
        mgr.add("tank", "tank-0", delay_per_block=0.0)
        progress = mgr.get("tank").wait_for_rebuild(timeout=5)
        self.assertTrue(progress.finished)
        for i in range(32):
            self.assertEqual(mgr.read_block("tank", i), pad_block(f"v{i}"))
        mgr.close_all()

    def test_close_all_during_active_rebuild_never_races(self):
        # Direct regression test for the exact bug this suite caught:
        # ArrayManager.close_all() used to close device file handles
        # while a background rebuild thread was still actively using
        # them, which could leave one member's superblock updated and
        # the other's not, producing an inconsistent event-count state
        # that made the NEXT assemble_all() exclude every member and
        # crash instead of correctly reporting a degraded/failed array.
        # Run several times in one test, since a race — even a fixed
        # one — deserves more than a single lucky pass as evidence.
        for _ in range(15):
            mgr = ArrayManager(self.tmpdir / f"run_{_}")
            mgr.create_array("tank", num_blocks=32, block_size=32)
            for i in range(32):
                mgr.write_block("tank", i, pad_block(f"v{i}"))
            mgr.fail("tank", "tank-0")
            mgr.remove("tank", "tank-0")
            mgr.add("tank", "tank-0", delay_per_block=0.02)
            time.sleep(0.05)  # rebuild is definitely still in flight here
            mgr.close_all()  # must never raise, and must leave consistent metadata

            mgr2 = ArrayManager(self.tmpdir / f"run_{_}")
            reports = mgr2.assemble_all()  # must never raise "zero available members"
            self.assertEqual(len(reports), 1)
            self.assertIn(mgr2.get("tank").status()["state"], ("degraded", "failed"))
            mgr2.close_all()

    def test_five_generations_with_a_process_restart_between_every_step(self):
        # The strongest durability test available: five full fail/
        # remove/add/rebuild generations, with a brand-new ArrayManager
        # (a simulated process restart) between EVERY single step, not
        # just between generations. If event-count bookkeeping or
        # member_roles persistence had any subtle bug that only shows up
        # after repeated cycles, this is what would catch it.
        mgr = ArrayManager(self.tmpdir)
        mgr.create_array("tank", num_blocks=16, block_size=32)
        for i in range(16):
            mgr.write_block("tank", i, pad_block(f"v{i}"))
        mgr.close_all()

        for generation in range(5):
            target = "tank-0" if generation % 2 == 0 else "tank-1"

            mgr = ArrayManager(self.tmpdir)
            mgr.assemble_all()
            mgr.fail("tank", target)
            mgr.close_all()

            mgr = ArrayManager(self.tmpdir)
            mgr.assemble_all()
            mgr.remove("tank", target)
            mgr.close_all()

            mgr = ArrayManager(self.tmpdir)
            mgr.assemble_all()
            mgr.add("tank", target, delay_per_block=0.0)
            mgr.get("tank").wait_for_rebuild(timeout=5)
            mgr.close_all()

            mgr = ArrayManager(self.tmpdir)
            mgr.assemble_all()
            self.assertEqual(
                mgr.get("tank").status()["state"], "clean",
                f"generation {generation} did not end clean",
            )
            for i in range(16):
                self.assertEqual(mgr.read_block("tank", i), pad_block(f"v{i}"))
            mgr.close_all()


if __name__ == "__main__":
    unittest.main()
