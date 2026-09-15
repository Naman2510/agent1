import shutil
import tempfile
import unittest
from pathlib import Path

from storage_sim.block_device import (
    SimulatedBlockDevice,
    create_single_raid_partition,
)
from storage_sim.exceptions import ChecksumMismatchError, DeviceFailedError
from storage_sim.exceptions import SuperblockError
from storage_sim.superblock import Superblock


class TestSimulatedBlockDevice(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="storage_sim_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_then_open_roundtrip(self):
        path = self.tmpdir / "disk0.img"
        dev = SimulatedBlockDevice.create(path, num_blocks=8, block_size=512)
        self.assertEqual(dev.num_blocks, 8)
        self.assertEqual(dev.block_size, 512)
        dev.close()

        reopened = SimulatedBlockDevice(path)
        self.assertEqual(reopened.num_blocks, 8)
        self.assertEqual(reopened.block_size, 512)
        reopened.close()

    def test_create_refuses_to_overwrite(self):
        path = self.tmpdir / "disk0.img"
        SimulatedBlockDevice.create(path, num_blocks=4, block_size=512).close()
        with self.assertRaises(FileExistsError):
            SimulatedBlockDevice.create(path, num_blocks=4, block_size=512)

    def test_write_then_read_returns_same_bytes(self):
        dev = SimulatedBlockDevice.create(self.tmpdir / "disk0.img", num_blocks=4, block_size=16)
        payload = b"A" * 16
        dev.write_block(2, payload)
        self.assertEqual(dev.read_block(2), payload)
        dev.close()

    def test_unwritten_block_reads_as_zeros_with_valid_checksum(self):
        # A freshly created disk image is zero-filled; a block that was
        # never explicitly written must still read back cleanly (zeros),
        # matching a real blank disk rather than raising spuriously.
        dev = SimulatedBlockDevice.create(self.tmpdir / "disk0.img", num_blocks=4, block_size=16)
        self.assertEqual(dev.read_block(0), b"\0" * 16)
        self.assertEqual(dev.read_block(3), b"\0" * 16)  # last block too, not just the first
        dev.close()

    def test_write_wrong_size_rejected(self):
        dev = SimulatedBlockDevice.create(self.tmpdir / "disk0.img", num_blocks=4, block_size=16)
        with self.assertRaises(ValueError):
            dev.write_block(0, b"too short")
        dev.close()

    def test_out_of_range_index_rejected(self):
        dev = SimulatedBlockDevice.create(self.tmpdir / "disk0.img", num_blocks=4, block_size=16)
        with self.assertRaises(IndexError):
            dev.read_block(4)
        with self.assertRaises(IndexError):
            dev.write_block(-1, b"x" * 16)
        dev.close()

    def test_hardware_failure_blocks_all_io(self):
        dev = SimulatedBlockDevice.create(self.tmpdir / "disk0.img", num_blocks=4, block_size=16)
        dev.write_block(0, b"x" * 16)
        dev.simulate_hardware_failure()
        with self.assertRaises(DeviceFailedError):
            dev.read_block(0)
        with self.assertRaises(DeviceFailedError):
            dev.write_block(0, b"y" * 16)
        dev.close()

    def test_silent_corruption_detected_on_read(self):
        dev = SimulatedBlockDevice.create(self.tmpdir / "disk0.img", num_blocks=4, block_size=16)
        dev.write_block(1, b"good data.......")
        dev.inject_silent_corruption(1)
        with self.assertRaises(ChecksumMismatchError):
            dev.read_block(1)
        # Other blocks are unaffected.
        dev.write_block(2, b"still fine......")
        self.assertEqual(dev.read_block(2), b"still fine......")
        dev.close()

    def test_superblock_roundtrip_and_update(self):
        path = self.tmpdir / "disk0.img"
        dev = SimulatedBlockDevice.create(path, num_blocks=4, block_size=16, role=0)
        sb = dev.read_superblock()
        self.assertEqual(sb.role, 0)
        self.assertEqual(sb.event_count, 0)

        sb.event_count += 1
        sb.state = "active"
        dev.write_superblock(sb)

        reread = dev.read_superblock()
        self.assertEqual(reread.event_count, 1)
        self.assertEqual(reread.state, "active")
        dev.close()

    def test_partition_view_bounds_and_offset(self):
        dev = SimulatedBlockDevice.create(self.tmpdir / "disk0.img", num_blocks=10, block_size=16)
        part = create_single_raid_partition(dev)
        self.assertEqual(part.num_blocks, 10)
        self.assertEqual(part.entry.type_code, "fd00")

        part.write_block(0, b"partition-block0")
        self.assertEqual(dev.read_block(0), b"partition-block0")  # full-span partition -> same offset as raw disk

        with self.assertRaises(IndexError):
            part.read_block(10)
        dev.close()

    def test_corrupt_superblock_does_not_leak_the_file_handle(self):
        # Regression test for a real bug this suite caught: when the
        # constructor's own read_superblock() call raised (invalid
        # magic bytes), the file handle already opened a few lines
        # earlier was never closed — the object never finished
        # constructing, so nothing was ever assigned that could later
        # be close()d. Confirmed by capturing ResourceWarning directly
        # rather than just asserting the expected exception, since the
        # exception alone doesn't prove the fd was cleaned up.
        import gc
        import warnings

        path = self.tmpdir / "corrupt.img"
        with open(path, "wb") as fh:
            fh.write(b"\xff" * 4096 + b"\x00" * 4096)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with self.assertRaises(SuperblockError):
                SimulatedBlockDevice(path)
            gc.collect()  # force any leaked file object's __del__ to run now, not whenever

        leaks = [w for w in caught if issubclass(w.category, ResourceWarning)]
        self.assertEqual(leaks, [], f"file handle leaked on constructor failure: {leaks}")


if __name__ == "__main__":
    unittest.main()
