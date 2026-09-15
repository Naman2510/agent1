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

    def test_corrupted_source_block_aborts_rebuild_not_just_that_block(self):
        # The rebuild source (disk1, the only remaining original member)
        # has a silently corrupted block. When the rebuild cursor
        # reaches it, this must be treated exactly like a hardware read
        # failure on the source — the textbook "second failure during
        # recovery" scenario — not skipped over or silently propagated
        # as corrupt data onto the replacement.
        arr, old_d0, d1 = self._degraded_array_with_data()
        d1.inject_silent_corruption(10)
        replacement = self.make_disk(
            "disk0_replacement.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=0
        )
        arr.add_member("disk0", replacement, delay_per_block=0.0)
        progress = arr.wait_for_rebuild(timeout=5)

        self.assertFalse(progress.finished)
        self.assertIsNotNone(progress.aborted_reason)
        self.assertIn("10", progress.aborted_reason)
        self.assertEqual(arr.state(), ArrayState.FAILED)

    def test_repeated_fail_remove_add_cycles_preserve_data_integrity(self):
        # Five full lifecycle generations in a row on the same array
        # instance — a stress test for accumulated state corruption
        # (stale in-memory references, event-count drift, etc.) that a
        # single cycle wouldn't reveal.
        d0, d1 = self.make_mirror_pair(num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE)
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        for i in range(NUM_BLOCKS):
            arr.write_block(i, pad_block(f"gen0-{i:03d}"))

        current_devices = {"disk0": d0, "disk1": d1}
        for generation in range(1, 6):
            target_label = "disk0" if generation % 2 else "disk1"
            arr.fail_member(target_label)
            arr.remove_member(target_label)
            replacement = self.make_disk(
                f"{target_label}_gen{generation}.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=None
            )
            arr.add_member(target_label, replacement, delay_per_block=0.0)
            progress = arr.wait_for_rebuild(timeout=5)
            self.assertTrue(progress.finished, f"generation {generation} rebuild did not finish: {progress.aborted_reason}")
            current_devices[target_label] = replacement

            for i in range(NUM_BLOCKS):
                arr.write_block(i, pad_block(f"gen{generation}-{i:03d}"))

            self.assertEqual(arr.state(), ArrayState.CLEAN)
            for i in range(NUM_BLOCKS):
                expected = pad_block(f"gen{generation}-{i:03d}")
                self.assertEqual(arr.read_block(i), expected)
                # Verify both underlying devices directly too — not just
                # through the array's own (potentially self-healing) read path.
                self.assertEqual(current_devices["disk0"].read_block(i), expected)
                self.assertEqual(current_devices["disk1"].read_block(i), expected)

    def test_concurrent_writes_during_rebuild_stress(self):
        # Multiple threads hammering different blocks with writes while
        # a rebuild runs in the background — a genuine concurrency
        # stress test beyond the single deterministic write already
        # covered by test_writes_during_rebuild_land_on_both_source_and_target.
        import threading

        arr, old_d0, d1 = self._degraded_array_with_data()
        replacement = self.make_disk(
            "disk0_replacement.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=0
        )
        arr.add_member("disk0", replacement, delay_per_block=0.005)

        errors = []
        final_values = {}
        final_values_lock = threading.Lock()

        def writer(thread_id):
            try:
                for round_num in range(20):
                    block = (thread_id * 7 + round_num) % NUM_BLOCKS
                    value = pad_block(f"t{thread_id}-r{round_num}")
                    arr.write_block(block, value)
                    with final_values_lock:
                        final_values[block] = value
            except Exception as exc:  # noqa: BLE001 — captured for the assertion below, not swallowed
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"writer thread(s) raised during concurrent rebuild: {errors}")
        arr.wait_for_rebuild(timeout=10)
        self.assertEqual(arr.state(), ArrayState.CLEAN)

        # Whatever each block's LAST recorded write was, both members —
        # including the freshly rebuilt one — must agree on it.
        for block, expected in final_values.items():
            self.assertEqual(d1.read_block(block), expected)
            self.assertEqual(replacement.read_block(block), expected)

    def test_request_rebuild_stop_and_join_stops_cleanly(self):
        # Regression test for a real race caught while building this:
        # closing a device's file handle while a rebuild thread is still
        # actively reading/writing it (e.g. from ArrayManager.close_all())
        # could leave members with inconsistent metadata. The fix is a
        # cooperative stop the rebuild thread checks BEFORE touching any
        # device each iteration — this test proves the stop is clean
        # (no exception, no FAILED state, thread genuinely exited) rather
        # than just asserting the race doesn't happen (which, being a
        # race, wouldn't reliably prove anything on its own).
        arr, old_d0, d1 = self._degraded_array_with_data()
        replacement = self.make_disk(
            "disk0_replacement.img", num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE, role=0
        )
        arr.add_member("disk0", replacement, delay_per_block=0.05)

        arr.request_rebuild_stop_and_join(timeout=5)

        status = arr.status()
        self.assertEqual(status["state"], "rebuilding")  # not failed — a clean stop, not a fault
        self.assertFalse(status["rebuild"]["finished"])
        self.assertIn("stopped", status["rebuild"]["aborted_reason"])
        self.assertLess(status["rebuild"]["blocks_done"], NUM_BLOCKS)  # genuinely interrupted, not raced to completion

        # The devices must now be safe to close without any exception —
        # the thread has actually exited, not just been asked to.
        old_d0.close()
        d1.close()
        replacement.close()


if __name__ == "__main__":
    unittest.main()
