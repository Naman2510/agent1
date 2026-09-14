import unittest

from storage_sim.block_device import SimulatedBlockDevice
from storage_sim.raid1 import ArrayState, RAID1Array
from storage_sim.tests.helpers import StorageSimTestCase, pad_block


class TestRAID1Normal(StorageSimTestCase):
    def test_requires_exactly_two_members(self):
        d0, _d1 = self.make_mirror_pair()
        with self.assertRaises(Exception):
            RAID1Array([d0])

    def test_rejects_mismatched_geometry(self):
        d0 = self.make_disk("disk0.img", num_blocks=8, block_size=32)
        d1 = self.make_disk("disk1.img", num_blocks=16, block_size=32)
        with self.assertRaises(Exception):
            RAID1Array([d0, d1])

    def test_fresh_array_is_clean(self):
        d0, d1 = self.make_mirror_pair()
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        self.assertEqual(arr.state(), ArrayState.CLEAN)
        status = arr.status()
        self.assertEqual(status["state"], "clean")
        self.assertEqual([m["state"] for m in status["members"]], ["active", "active"])

    def test_write_mirrors_to_both_members(self):
        d0, d1 = self.make_mirror_pair()
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        payload = pad_block("hello raid1 world!!")
        arr.write_block(3, payload)
        # Verify independently at the raw device level, not just through
        # the array's own read path — this proves the mirror actually
        # happened on disk, not just in the array's bookkeeping.
        self.assertEqual(d0.read_block(3), payload)
        self.assertEqual(d1.read_block(3), payload)

    def test_read_returns_written_data(self):
        d0, d1 = self.make_mirror_pair()
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        for i in range(8):
            arr.write_block(i, pad_block(f"block-{i:02d}"))
        for i in range(8):
            self.assertEqual(arr.read_block(i), pad_block(f"block-{i:02d}"))

    def test_write_wrong_size_rejected(self):
        d0, d1 = self.make_mirror_pair()
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        with self.assertRaises(ValueError):
            arr.write_block(0, b"too short")


if __name__ == "__main__":
    unittest.main()
