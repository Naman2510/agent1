import unittest

from storage_sim.exceptions import ArrayFailedError, InvalidOperationError
from storage_sim.raid1 import ArrayState, MemberState, RAID1Array
from storage_sim.tests.helpers import StorageSimTestCase, pad_block

NUM_BLOCKS = 32
BLOCK_SIZE = 32


class TestRAID1Rebuild(StorageSimTestCase):
    def _degraded_array_with_data(self):
        d0, d1 = self.make_mirror_pair(num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE)
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        for i in range(NUM_BLOCKS):
            arr.write_block(i, pad_block(f"data-{i:03d}"))
        arr.fail_member("disk0")
        arr.remove_member("disk0")
        return arr, d0, d1

    def test_add_member_rebuilds_and_returns_to_clean(self):
        arr, old_d0, d1 = self._degraded_array_with_data()
        replacement = self.make_disk(
            "disk0_replacement.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=0
        )
        arr.add_member("disk0", replacement)
        progress = arr.wait_for_rebuild(timeout=5)

        self.assertTrue(progress.finished)
        self.assertIsNone(progress.aborted_reason)
        self.assertEqual(arr.state(), ArrayState.CLEAN)

        # Independently verify at the raw device level that every block
        # was actually copied correctly — not just trusting the array's
        # own bookkeeping.
        for i in range(NUM_BLOCKS):
            self.assertEqual(replacement.read_block(i), pad_block(f"data-{i:03d}"))

    def test_reads_during_rebuild_never_see_stale_unsynced_data(self):
        # Regression test for a real bug caught while building this:
        # a REBUILDING member's not-yet-synced blocks hold zeroed
        # placeholder data with a *valid* checksum, so naively treating
        # it as a readable mirror would silently return wrong data for
        # blocks the resync cursor hasn't reached yet.
        arr, old_d0, d1 = self._degraded_array_with_data()
        replacement = self.make_disk(
            "disk0_replacement.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=0
        )
        arr.add_member("disk0", replacement, delay_per_block=0.02)  # slow enough to read mid-rebuild

        # Immediately (rebuild cursor likely still near 0), read every
        # block through the array and confirm correctness regardless of
        # where the cursor is.
        for i in range(NUM_BLOCKS):
            self.assertEqual(arr.read_block(i), pad_block(f"data-{i:03d}"))

        arr.wait_for_rebuild(timeout=5)
        self.assertEqual(arr.state(), ArrayState.CLEAN)

    def test_writes_during_rebuild_land_on_both_source_and_target(self):
        arr, old_d0, d1 = self._degraded_array_with_data()
        replacement = self.make_disk(
            "disk0_replacement.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=0
        )
        arr.add_member("disk0", replacement, delay_per_block=0.02)

        arr.write_block(5, pad_block("updated-during-rebuild"))
        arr.wait_for_rebuild(timeout=5)

        self.assertEqual(d1.read_block(5), pad_block("updated-during-rebuild"))
        self.assertEqual(replacement.read_block(5), pad_block("updated-during-rebuild"))

    def test_source_failure_mid_rebuild_fails_the_array(self):
        arr, old_d0, d1 = self._degraded_array_with_data()
        replacement = self.make_disk(
            "disk0_replacement.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=0
        )
        arr.add_member("disk0", replacement, delay_per_block=0.03)

        # The only remaining healthy member (d1, the rebuild source)
        # dies mid-rebuild — the textbook "second failure during
        # recovery" scenario. This must be unrecoverable, not silently
        # tolerated.
        d1.simulate_hardware_failure()
        progress = arr.wait_for_rebuild(timeout=5)

        self.assertIsNotNone(progress.aborted_reason)
        self.assertFalse(progress.finished)
        self.assertEqual(arr.state(), ArrayState.FAILED)
        with self.assertRaises(ArrayFailedError):
            arr.read_block(0)

    def test_cannot_add_member_to_non_removed_slot(self):
        d0, d1 = self.make_mirror_pair(num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE)
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        replacement = self.make_disk("spare.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=None)
        with self.assertRaises(InvalidOperationError):
            arr.add_member("disk0", replacement)  # disk0 is still ACTIVE, not REMOVED

    def test_cannot_add_mismatched_geometry_replacement(self):
        arr, old_d0, d1 = self._degraded_array_with_data()
        wrong_size = self.make_disk("wrong.img", num_blocks=NUM_BLOCKS, block_size=64, role=None)
        with self.assertRaises(InvalidOperationError):
            arr.add_member("disk0", wrong_size)


if __name__ == "__main__":
    unittest.main()
