"""Shared test scaffolding for storage_sim's test suite."""

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import List, Tuple

from storage_sim.block_device import SimulatedBlockDevice


def pad_block(text: str, size: int = 32) -> bytes:
    """Pad/truncate a string to exactly `size` bytes — every write in
    this test suite must be exactly the array's block_size, same as a
    real block device demands."""
    return text.encode().ljust(size, b".")[:size]


class StorageSimTestCase(unittest.TestCase):
    """Base class that gives every test a scratch directory and tracks
    every SimulatedBlockDevice it creates so tearDown can close them all
    (avoiding ResourceWarning noise from dangling open file handles)."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="storage_sim_test_"))
        self._devices: List[SimulatedBlockDevice] = []

    def tearDown(self):
        for dev in self._devices:
            try:
                dev.close()
            except Exception:
                pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_disk(self, name: str, num_blocks: int, block_size: int, role=None, array_uuid=None) -> SimulatedBlockDevice:
        dev = SimulatedBlockDevice.create(
            self.tmpdir / name, num_blocks=num_blocks, block_size=block_size, role=role, array_uuid=array_uuid
        )
        self._devices.append(dev)
        return dev

    def make_mirror_pair(self, num_blocks=8, block_size=32) -> Tuple[SimulatedBlockDevice, SimulatedBlockDevice]:
        d0 = self.make_disk("disk0.img", num_blocks, block_size, role=0)
        array_uuid = d0.read_superblock().array_uuid
        d1 = self.make_disk("disk1.img", num_blocks, block_size, role=1, array_uuid=array_uuid)
        return d0, d1
