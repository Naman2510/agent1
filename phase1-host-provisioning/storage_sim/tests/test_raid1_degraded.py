import unittest

from storage_sim.exceptions import ArrayFailedError, InvalidOperationError
from storage_sim.raid1 import ArrayState, MemberState, RAID1Array
from storage_sim.tests.helpers import StorageSimTestCase, pad_block


class TestRAID1Degraded(StorageSimTestCase):
    def _clean_array(self):
        d0, d1 = self.make_mirror_pair()
        arr = RAID1Array([d0, d1], labels=["disk0", "disk1"])
        return arr, d0, d1

    def test_fail_member_marks_degraded(self):
        arr, d0, d1 = self._clean_array()
        arr.fail_member("disk0")
        self.assertEqual(arr.state(), ArrayState.DEGRADED)
        status = arr.status()
        states = {m["label"]: m["state"] for m in status["members"]}
        self.assertEqual(states["disk0"], "failed")
        self.assertEqual(states["disk1"], "active")

    def test_write_continues_on_surviving_member_only(self):
        arr, d0, d1 = self._clean_array()
        arr.fail_member("disk0")
        payload = pad_block("still writable")
        arr.write_block(0, payload)
        self.assertEqual(d1.read_block(0), payload)
        # The failed member must NOT have received the write — it's
        # disconnected from the array's mirror path entirely.
        self.assertEqual(d0.read_block(0), b"\0" * d0.block_size)

    def test_read_still_works_from_surviving_member(self):
        arr, d0, d1 = self._clean_array()
        arr.write_block(1, pad_block("before failure"))
        arr.fail_member("disk0")
        self.assertEqual(arr.read_block(1), pad_block("before failure"))

    def test_both_members_failed_is_array_failed(self):
        arr, d0, d1 = self._clean_array()
        arr.fail_member("disk0")
        arr.fail_member("disk1")
        self.assertEqual(arr.state(), ArrayState.FAILED)
        with self.assertRaises(ArrayFailedError):
            arr.read_block(0)
        with self.assertRaises(ArrayFailedError):
            arr.write_block(0, pad_block("x"))

    def test_failing_already_failed_member_raises(self):
        arr, d0, d1 = self._clean_array()
        arr.fail_member("disk0")
        with self.assertRaises(InvalidOperationError):
            arr.fail_member("disk0")

    def test_failing_unknown_label_raises(self):
        arr, d0, d1 = self._clean_array()
        with self.assertRaises(InvalidOperationError):
            arr.fail_member("does-not-exist")

    def test_cannot_remove_active_member(self):
        arr, d0, d1 = self._clean_array()
        with self.assertRaises(InvalidOperationError):
            arr.remove_member("disk1")  # still active — must be failed first

    def test_can_construct_array_already_missing_a_member(self):
        # Models `mdadm --assemble` finding only one of two expected
        # disks and bringing the array up degraded rather than refusing.
        d0, _d1 = self.make_mirror_pair()
        arr = RAID1Array([d0, None], labels=["disk0", "disk1"])
        self.assertEqual(arr.state(), ArrayState.DEGRADED)
        self.assertEqual(arr.read_block(0), b"\0" * d0.block_size)

    def test_remove_after_fail_empties_slot(self):
        arr, d0, d1 = self._clean_array()
        arr.fail_member("disk0")
        arr.remove_member("disk0")
        status = arr.status()
        states = {m["label"]: m["state"] for m in status["members"]}
        self.assertEqual(states["disk0"], "removed")
        # State is still reported as degraded (not clean) — a removed
        # slot is not redundancy restored.
        self.assertEqual(arr.state(), ArrayState.DEGRADED)


if __name__ == "__main__":
    unittest.main()
