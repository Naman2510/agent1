"""Block-device abstraction and its simulated (file-backed) implementation.

Architecture
------------
    Application / CLI / Dashboard
                |
            RAID1 layer            (raid1.py)
                |
     BlockDevice interface         (this module: the abstract contract)
           /          \\
   SimulatedBlockDevice  <future: RealBlockDevice over /dev/sdX>

`BlockDevice` is the seam. `raid1.RAID1Array` only ever calls
`read_block`/`write_block`/`flush` on whatever it's given — it has no
idea whether that's a file on disk (this module, tonight) or a real
`/dev/sdX` opened with O_DIRECT (a future `RealBlockDevice`, once the VM
has a third disk). That is the whole point of the abstraction: replacing
the simulated backend with a real one should not require touching
raid1.py at all.

On-disk layout of a SimulatedBlockDevice's backing file
--------------------------------------------------------
    [ Superblock region: SUPERBLOCK_SIZE bytes, see superblock.py ]
    [ block 0: block_size bytes of data | 32-byte SHA-256 checksum ]
    [ block 1: block_size bytes of data | 32-byte SHA-256 checksum ]
    ...

Storing a checksum alongside every block models what real storage
hardware/firmware increasingly does at the physical layer — e.g. T10
DIF/DIX (SCSI "protection information") or what ZFS/Btrfs do at the
filesystem layer — to let a layer above (here, RAID1) detect silent
corruption on read rather than trusting the medium blindly. See
storage_sim/README.md for the explicit, honest caveat that stock mdadm
+ ext4 does *not* have this by default; this is a deliberate simulation
enhancement, not a claim about real mdadm's actual behavior.
"""

from __future__ import annotations

import hashlib
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .exceptions import ChecksumMismatchError, DeviceFailedError, DeviceIOError
from .superblock import SUPERBLOCK_SIZE, Superblock

CHECKSUM_SIZE = 32  # SHA-256 digest length in bytes


class BlockDevice(ABC):
    """The contract every RAID1 member must satisfy. Nothing in raid1.py
    is allowed to reach past this interface into implementation details
    (no `._file`, no path manipulation) — that discipline is what keeps
    the RAID logic hardware-agnostic."""

    block_size: int

    @property
    @abstractmethod
    def num_blocks(self) -> int: ...

    @abstractmethod
    def read_block(self, index: int) -> bytes:
        """Return exactly `block_size` bytes. Raises DeviceIOError if the
        device can't service the read, ChecksumMismatchError if the data
        it returned doesn't match its stored checksum."""

    @abstractmethod
    def write_block(self, index: int, data: bytes) -> None:
        """`data` must be exactly `block_size` bytes. Raises
        DeviceIOError if the device can't service the write."""

    @abstractmethod
    def flush(self) -> None:
        """Ensure all writes are durable (models fsync)."""

    def _bounds_check(self, index: int) -> None:
        if not (0 <= index < self.num_blocks):
            raise IndexError(f"block index {index} out of range [0, {self.num_blocks})")


class SimulatedBlockDevice(BlockDevice):
    """A "disk" backed by a single regular file. Not a toy that just
    prints success — every read/write actually goes through a real
    `open()`/`seek()`/`read()`/`write()` against a file on this
    machine's real filesystem, and a corrupted or hardware-failed device
    behaves like one: reads/writes genuinely raise, genuinely return
    wrong bytes when corrupted, etc.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} does not exist — use SimulatedBlockDevice.create() to make a new disk image"
            )
        self._lock = threading.Lock()
        self._fh = open(self.path, "r+b")
        self._hardware_failed = False
        sb = self.read_superblock()
        self.block_size = sb.block_size
        self._num_blocks = sb.num_blocks

    # -- construction -----------------------------------------------------

    @classmethod
    def create(
        cls,
        path: Path,
        num_blocks: int,
        block_size: int = 4096,
        array_uuid: Optional[str] = None,
        role: Optional[int] = None,
    ) -> "SimulatedBlockDevice":
        """Allocate a brand-new, zeroed disk image with a fresh
        superblock. Real-world analog: a blank drive fresh out of the
        box — no partition table, no filesystem, nothing on it yet."""
        path = Path(path)
        if path.exists():
            raise FileExistsError(f"{path} already exists — refusing to overwrite a disk image")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            sb = Superblock(
                array_uuid=array_uuid or Superblock.new_array_uuid(),
                member_uuid=Superblock.new_member_uuid(),
                role=role,
                block_size=block_size,
                num_blocks=num_blocks,
                event_count=0,
                state="spare" if role is None else "active",
            )
            fh.write(sb.to_bytes())
            # Every block is explicitly initialized with real
            # (zero-data, matching-checksum) pairs rather than sparse-
            # truncated. A merely-truncated file would have an all-zero
            # checksum trailer that does NOT match sha256(zero-data),
            # so every never-written block would incorrectly look
            # corrupted on its first read — caught by this package's own
            # tests (test_unwritten_block_reads_as_zeros_with_valid_checksum).
            zero_block = bytes(block_size)
            zero_checksum = hashlib.sha256(zero_block).digest()
            zero_record = zero_block + zero_checksum
            for _ in range(num_blocks):
                fh.write(zero_record)
        return cls(path)

    # -- superblock access --------------------------------------------------

    def read_superblock(self) -> Superblock:
        with self._lock:
            self._fh.seek(0)
            raw = self._fh.read(SUPERBLOCK_SIZE)
        return Superblock.from_bytes(raw)

    def write_superblock(self, sb: Superblock) -> None:
        with self._lock:
            self._fh.seek(0)
            self._fh.write(sb.to_bytes())
            self._fh.flush()
            os.fsync(self._fh.fileno())

    # -- BlockDevice interface --------------------------------------------

    @property
    def num_blocks(self) -> int:
        return self._num_blocks

    def _offset(self, index: int) -> int:
        return SUPERBLOCK_SIZE + index * (self.block_size + CHECKSUM_SIZE)

    def read_block(self, index: int) -> bytes:
        self._bounds_check(index)
        if self._hardware_failed:
            raise DeviceFailedError(f"{self.path.name}: device is hardware-failed, refusing I/O")
        with self._lock:
            self._fh.seek(self._offset(index))
            raw = self._fh.read(self.block_size + CHECKSUM_SIZE)
        if len(raw) != self.block_size + CHECKSUM_SIZE:
            raise DeviceIOError(f"{self.path.name}: short read at block {index} (disk image truncated?)")
        data, checksum = raw[: self.block_size], raw[self.block_size :]
        if hashlib.sha256(data).digest() != checksum:
            raise ChecksumMismatchError(f"{self.path.name}: checksum mismatch at block {index}")
        return data

    def write_block(self, index: int, data: bytes) -> None:
        self._bounds_check(index)
        if len(data) != self.block_size:
            raise ValueError(f"write_block expects exactly {self.block_size} bytes, got {len(data)}")
        if self._hardware_failed:
            raise DeviceFailedError(f"{self.path.name}: device is hardware-failed, refusing I/O")
        checksum = hashlib.sha256(data).digest()
        with self._lock:
            self._fh.seek(self._offset(index))
            self._fh.write(data + checksum)

    def flush(self) -> None:
        if self._hardware_failed:
            raise DeviceFailedError(f"{self.path.name}: device is hardware-failed, refusing I/O")
        with self._lock:
            self._fh.flush()
            os.fsync(self._fh.fileno())

    # -- fault injection (test/demo hooks — never called by raid1.py itself) --

    def simulate_hardware_failure(self) -> None:
        """Model a drive that has dropped off the bus entirely: every
        subsequent I/O raises DeviceFailedError until the process
        restarts against a fresh/replacement image. This is the
        *physical* fault; `RAID1Array.fail_member()` is the
        *administrative* response to seeing I/O errors like this one."""
        self._hardware_failed = True

    def inject_silent_corruption(self, index: int) -> None:
        """Flip bytes in a block's stored *data* without touching its
        checksum trailer — models bit rot / a medium error the drive's
        own firmware didn't catch. The next read_block() on this index
        will raise ChecksumMismatchError, exactly as if the drive
        returned bytes that don't match what was written."""
        self._bounds_check(index)
        with self._lock:
            self._fh.seek(self._offset(index))
            data = bytearray(self._fh.read(self.block_size))
            # Flip every bit in the first byte — guaranteed to change the
            # checksum outcome without needing a random-corruption model.
            data[0] ^= 0xFF
            self._fh.seek(self._offset(index))
            self._fh.write(bytes(data))  # checksum trailer intentionally left untouched

    def close(self) -> None:
        self._fh.close()


@dataclass
class PartitionEntry:
    """A single partition record. Deliberately minimal — this simulation
    only ever creates one full-span partition per disk, exactly matching
    what phase1-host-provisioning/scripts/01-partition-raid.sh actually
    does on a real disk (`sgdisk -n 1:0:0 -t 1:fd00`, i.e. one partition
    spanning the whole device). A general multi-partition GPT parser
    would be complexity this project doesn't need — see storage_sim/README.md,
    "Why not a full partition table"."""

    start_block: int
    num_blocks: int
    type_code: str  # "fd00" == Linux RAID autodetect, matching sgdisk's typecode
    label: str


class PartitionView(BlockDevice):
    """Presents one partition of a parent BlockDevice as its own
    BlockDevice, bounded to that partition's block range. This is the
    layer RAID1Array members actually are — mirroring the real fact that
    mdadm operates on `/dev/sdb1`, not `/dev/sdb`."""

    def __init__(self, parent: BlockDevice, entry: PartitionEntry):
        self._parent = parent
        self.entry = entry
        self.block_size = parent.block_size

    @property
    def num_blocks(self) -> int:
        return self.entry.num_blocks

    def read_block(self, index: int) -> bytes:
        self._bounds_check(index)
        return self._parent.read_block(self.entry.start_block + index)

    def write_block(self, index: int, data: bytes) -> None:
        self._bounds_check(index)
        self._parent.write_block(self.entry.start_block + index, data)

    def flush(self) -> None:
        self._parent.flush()


def create_single_raid_partition(disk: SimulatedBlockDevice) -> PartitionView:
    """Equivalent of `sgdisk -n 1:0:0 -t 1:fd00 <disk>` — one partition
    spanning the entire simulated disk, typed as a RAID member. Real
    disks reserve some space for the partition table itself (GPT header
    + entries); this simulation reserves none, since the superblock
    region already sits outside the block-addressable range and there is
    no real GPT structure to make room for."""
    entry = PartitionEntry(start_block=0, num_blocks=disk.num_blocks, type_code="fd00", label="raid-member")
    return PartitionView(disk, entry)
