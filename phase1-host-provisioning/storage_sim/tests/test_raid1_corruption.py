import unittest

from storage_sim.exceptions import ArrayFailedError, ChecksumMismatchError
from storage_sim.raid1 import RAID1Array
from storage_sim.tests.helpers import StorageSimTestCase, pad_block

NUM_BLOCKS = 8
BLOCK_SIZE = 32


class TestRAID1Corruption(StorageSimTestCase):
    def _array_with_data(self):
        d0, d1 = self.make_mirror_pair(num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE)
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        for i in range(NUM_BLOCKS):
            arr.write_block(i, pad_block(f"data-{i}"))
        return arr, d0, d1

    def test_read_self_heals_corrupted_mirror_from_good_copy(self):
        arr, d0, d1 = self._array_with_data()
        d0.inject_silent_corruption(3)

        # d0's block 3 is corrupt at the raw level right now.
        with self.assertRaises(ChecksumMismatchError):
            d0.read_block(3)

        # The array must still return the correct value (from d1)...
        self.assertEqual(arr.read_block(3), pad_block("data-3"))

        # ...and must have healed d0 in the process — this is the
        # self-healing read path, not just failover.
        self.assertEqual(d0.read_block(3), pad_block("data-3"))

    def test_scrub_detects_and_repairs_mismatch(self):
        arr, d0, d1 = self._array_with_data()
        d1.inject_silent_corruption(5)

        result = arr.scrub(repair=True)

        self.assertEqual(result["blocks_scanned"], NUM_BLOCKS)
        self.assertEqual(len(result["mismatches"]), 1)
        self.assertEqual(result["mismatches"][0]["block"], 5)
        self.assertIn("disk1", result["mismatches"][0]["bad_members"])

        # Repaired: reading d1 directly (raw, bypassing the array) must
        # now succeed and match the good data.
        self.assertEqual(d1.read_block(5), pad_block("data-5"))

    def test_scrub_without_repair_leaves_corruption_in_place(self):
        arr, d0, d1 = self._array_with_data()
        d1.inject_silent_corruption(2)

        result = arr.scrub(repair=False)

        self.assertEqual(len(result["mismatches"]), 1)
        # Not repaired — the raw device must still be corrupt.
        with self.assertRaises(ChecksumMismatchError):
            d1.read_block(2)

    def test_scrub_reports_no_mismatches_on_healthy_array(self):
        arr, d0, d1 = self._array_with_data()
        result = arr.scrub(repair=True)
        self.assertEqual(result["mismatches"], [])

    def test_corruption_on_lone_surviving_member_is_unrecoverable(self):
        arr, d0, d1 = self._array_with_data()
        arr.fail_member("disk0")          # only disk1 remains
        d1.inject_silent_corruption(4)     # and now it's corrupt too

        with self.assertRaises(ArrayFailedError):
            arr.read_block(4)

        # Other blocks on the same lone survivor are still fine — this
        # is a single unrecoverable block, not a whole-array wipeout.
        self.assertEqual(arr.read_block(0), pad_block("data-0"))


if __name__ == "__main__":
    unittest.main()
