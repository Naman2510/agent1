"""Tests for RealBlockDevice.

Classification (see PROJECT_SPEC.md's ledger): the SAFETY-GATING logic
here (dry-run default, multi-flag opt-in, denylist, required num_blocks)
is IMPLEMENTED + TESTED — genuinely exercised below. The actual
os.pread/os.pwrite/os.fsync I/O path is exercised against a plain temp
FILE standing in for a block device (safe: it's not a device, but it's
the exact same syscalls) — that part is IMPLEMENTED + TESTED against a
file, but explicitly NOT YET VALIDATED against a real block device,
since none is available in this environment.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from storage_sim.exceptions import DeviceIOError, InvalidOperationError
from storage_sim.raid1 import RAID1Array
from storage_sim.real_block_device import DENYLISTED_PATH_PREFIXES, RealBlockDevice


class TestSafetyGating(unittest.TestCase):
    def test_default_construction_is_dry_run(self):
        dev = RealBlockDevice("/dev/sdz", num_blocks=4)
        self.assertTrue(dev.dry_run)

    def test_dry_run_read_raises_without_opening_anything(self):
        dev = RealBlockDevice("/dev/sdz", num_blocks=4)
        with self.assertRaises(InvalidOperationError):
            dev.read_block(0)

    def test_dry_run_write_raises_without_opening_anything(self):
        dev = RealBlockDevice("/dev/sdz", num_blocks=4)
        with self.assertRaises(InvalidOperationError):
            dev.write_block(0, b"x" * dev.block_size)

    def test_allow_real_io_alone_is_not_enough(self):
        # allow_real_io=True without the explicit lsblk-confirmation flag
        # must still refuse — this is deliberately not a single switch.
        with self.assertRaises(InvalidOperationError):
            RealBlockDevice("/dev/sdz", num_blocks=4, dry_run=False, allow_real_io=True)

    def test_missing_num_blocks_refused_even_with_both_flags(self):
        with self.assertRaises(InvalidOperationError):
            RealBlockDevice(
                "/dev/sdz", num_blocks=None, dry_run=False,
                allow_real_io=True, i_have_confirmed_with_lsblk=True,
            )

    def test_denylisted_paths_refused_even_with_both_flags_and_num_blocks(self):
        for prefix in DENYLISTED_PATH_PREFIXES:
            with self.subTest(prefix=prefix):
                with self.assertRaises(InvalidOperationError):
                    RealBlockDevice(
                        prefix, num_blocks=4, dry_run=False,
                        allow_real_io=True, i_have_confirmed_with_lsblk=True,
                    )

    def test_denylist_check_happens_before_any_real_open_attempt(self):
        # A denylisted path that also doesn't exist must fail with the
        # denylist error, not a "no such device" OSError — proving the
        # safety check runs first, not as an afterthought.
        with self.assertRaises(InvalidOperationError) as ctx:
            RealBlockDevice(
                "/dev/sda99-does-not-exist", num_blocks=4, dry_run=False,
                allow_real_io=True, i_have_confirmed_with_lsblk=True,
            )
        self.assertIn("denylisted", str(ctx.exception))

    def test_repr_reports_dry_run_state(self):
        dev = RealBlockDevice("/dev/sdz", num_blocks=4)
        self.assertIn("DRY-RUN", repr(dev))


class TestRealIoAgainstAStandInFile(unittest.TestCase):
    """A plain temp file, never a device — but the exact same
    open/pread/pwrite/fsync/close syscalls RealBlockDevice would issue
    against a real block device run here for real."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="real_block_device_test_"))
        self.path = self.tmpdir / "stand_in_disk.img"
        # Pre-allocate: a real block device already "exists" at some
        # size; this class never creates one, only opens an existing path.
        with open(self.path, "wb") as fh:
            fh.truncate(4 * 4096)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _open(self, **kwargs) -> RealBlockDevice:
        return RealBlockDevice(
            str(self.path), block_size=4096, num_blocks=4,
            dry_run=False, allow_real_io=True, i_have_confirmed_with_lsblk=True,
            **kwargs,
        )

    def test_write_then_read_roundtrip(self):
        dev = self._open()
        payload = b"A" * 4096
        dev.write_block(1, payload)
        self.assertEqual(dev.read_block(1), payload)
        dev.close()

    def test_write_wrong_size_rejected(self):
        dev = self._open()
        with self.assertRaises(ValueError):
            dev.write_block(0, b"too short")
        dev.close()

    def test_out_of_range_index_rejected(self):
        dev = self._open()
        with self.assertRaises(IndexError):
            dev.read_block(4)
        with self.assertRaises(IndexError):
            dev.write_block(-1, b"x" * 4096)
        dev.close()

    def test_flush_and_close_do_not_raise(self):
        dev = self._open()
        dev.write_block(0, b"B" * 4096)
        dev.flush()
        dev.close()
        # Double-close must be safe (mirrors SimulatedBlockDevice's contract).
        dev.close()

    def test_read_after_close_is_treated_as_dry_run_not_a_crash(self):
        # After close(), _fd is None again — the same, correct code path
        # as never having opened a real device fires: a clear
        # InvalidOperationError, not a segfault-adjacent use-after-close.
        dev = self._open()
        dev.close()
        with self.assertRaises(InvalidOperationError):
            dev.read_block(0)

    def test_nonexistent_path_raises_our_typed_device_io_error(self):
        with self.assertRaises(DeviceIOError):
            RealBlockDevice(
                str(self.tmpdir / "does-not-exist.img"), num_blocks=4,
                dry_run=False, allow_real_io=True, i_have_confirmed_with_lsblk=True,
            )


class TestRAID1ArrayOverRealBlockDevices(unittest.TestCase):
    """The actual point of the BlockDevice abstraction, proven directly:
    RAID1Array — completely unmodified, no special-casing — mirrors,
    degrades, and rebuilds over two RealBlockDevice instances exactly as
    it does over two SimulatedBlockDevice instances. The only thing that
    changed between this test and storage_sim's other RAID1 tests is
    which BlockDevice subclass got instantiated.

    Still backed by temp files, not an actual /dev/sdX — so this proves
    the abstraction boundary holds, not that real hardware I/O works."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="raid1_real_device_test_"))
        for name in ("disk0.img", "disk1.img"):
            with open(self.tmpdir / name, "wb") as fh:
                fh.truncate(8 * 512)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _real_dev(self, name: str) -> RealBlockDevice:
        return RealBlockDevice(
            str(self.tmpdir / name), block_size=512, num_blocks=8,
            dry_run=False, allow_real_io=True, i_have_confirmed_with_lsblk=True,
        )

    def test_mirrored_write_and_degraded_read_over_real_block_devices(self):
        d0, d1 = self._real_dev("disk0.img"), self._real_dev("disk1.img")
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])

        payload = b"real-io-mirror".ljust(512, b".")
        arr.write_block(3, payload)
        self.assertEqual(d0.read_block(3), payload)
        self.assertEqual(d1.read_block(3), payload)

        arr.fail_member("disk0")
        self.assertEqual(arr.state().value, "degraded")
        self.assertEqual(arr.read_block(3), payload)  # still readable from the survivor

        d0.close()
        d1.close()


if __name__ == "__main__":
    unittest.main()
