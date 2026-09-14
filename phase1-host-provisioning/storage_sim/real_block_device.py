"""RealBlockDevice — the adapter that lets RAID1Array eventually operate
on real Linux block devices instead of simulated files.

This is the seam storage_sim/README.md's architecture diagram promises:
`raid1.py` only ever calls `read_block`/`write_block`/`flush` through
the `BlockDevice` interface, so nothing there needs to change to use
this class instead of `SimulatedBlockDevice` — only which class the
caller instantiates.

THIS CLASS HAS NEVER BEEN RUN AGAINST A REAL DEVICE. There is no real
hardware or VM block device available to this session. Everything below
is IMPLEMENTED but explicitly NOT YET VALIDATED for the real-I/O path —
see PROJECT_SPEC.md's testing ledger. What IS tested (in
tests/test_real_block_device.py) is the safety-gating logic itself:
that this class refuses to touch anything without multiple explicit,
deliberate opt-ins, and that its bounds/size checks behave correctly.

Safety model (defense in depth — any ONE of these alone would already
prevent accidental real I/O; there are several on purpose)
-----------------------------------------------------------------------
1. `dry_run=True` is the default. In dry-run mode this class never calls
   `os.open` on a real path at all — reads/writes just raise, loudly.
2. Even with `dry_run=False`, real I/O additionally requires
   `allow_real_io=True` AND `i_have_confirmed_with_lsblk=True` — the
   second flag exists specifically so a human has to affirmatively
   assert they checked `lsblk` output before this constructor will do
   anything, mirroring the exact process this project's own safety rules
   require (see phase1-host-provisioning/scripts/plan_from_lsblk.py).
3. A hard-coded denylist refuses common boot-disk device names outright
   (`/dev/sda`, `/dev/nvme0n1`, `/dev/vda`, `/dev/xvda`) regardless of
   the flags above — a human can still be wrong about which disk is
   which, so this is a backstop, not a substitute for actually checking.
4. `num_blocks` must be explicitly supplied — this class will never
   probe a device's real size via ioctl and "figure it out," which
   removes an entire class of "it silently did something on a
   differently-sized device than intended" mistakes.

None of this makes real I/O SAFE in an absolute sense — a human with
root can always misuse any tool. It makes ACCIDENTAL real I/O require
several independent, deliberate steps instead of one.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .block_device import BlockDevice
from .exceptions import DeviceIOError, InvalidOperationError

# Conventional first/boot-disk device names on common Linux VM/hardware
# platforms. Refusing these by default is a deliberate, conservative
# backstop — NOT a guarantee a boot disk can't have a different name.
# Human confirmation via lsblk remains mandatory regardless.
DENYLISTED_PATH_PREFIXES = ("/dev/sda", "/dev/nvme0n1", "/dev/vda", "/dev/xvda", "/dev/hda")


class RealBlockDevice(BlockDevice):
    def __init__(
        self,
        path: str,
        block_size: int = 4096,
        num_blocks: Optional[int] = None,
        dry_run: bool = True,
        allow_real_io: bool = False,
        i_have_confirmed_with_lsblk: bool = False,
    ):
        self.path = Path(path)
        self.block_size = block_size
        self._num_blocks = num_blocks
        self.dry_run = dry_run or not allow_real_io
        self._fd: Optional[int] = None

        if not self.dry_run:
            if not i_have_confirmed_with_lsblk:
                raise InvalidOperationError(
                    "refusing real I/O: i_have_confirmed_with_lsblk=True was not set. "
                    "Run `lsblk -J -O` on the target machine and confirm this path is genuinely "
                    "a blank, dedicated RAID member before setting this flag — see "
                    "phase1-host-provisioning/scripts/plan_from_lsblk.py."
                )
            self._check_not_denylisted(self.path)
            if num_blocks is None:
                raise InvalidOperationError(
                    "refusing real I/O: num_blocks must be explicitly supplied — this class will "
                    "never probe a real device's size and assume it guessed right."
                )
            try:
                self._fd = os.open(str(self.path), os.O_RDWR)
            except OSError as exc:
                raise DeviceIOError(f"{self.path}: could not open for real I/O: {exc}") from exc

    @staticmethod
    def _check_not_denylisted(path: Path) -> None:
        path_str = str(path)
        for prefix in DENYLISTED_PATH_PREFIXES:
            if path_str.startswith(prefix):
                raise InvalidOperationError(
                    f"refusing to treat {path_str!r} as a RAID member: it matches the "
                    f"denylisted boot-disk-like prefix {prefix!r}. If this really is intended "
                    "to be a RAID member, this is a strong signal something about the device "
                    "identification was wrong — re-check `lsblk` output before proceeding."
                )

    @property
    def num_blocks(self) -> int:
        if self._num_blocks is None:
            raise InvalidOperationError("num_blocks was never confirmed for this device")
        return self._num_blocks

    def read_block(self, index: int) -> bytes:
        self._bounds_check(index)
        if self.dry_run or self._fd is None:
            raise InvalidOperationError(
                "cannot read_block: this RealBlockDevice is in dry-run mode (no real device is "
                "open) — this is expected and correct unless you explicitly intended real I/O"
            )
        offset = index * self.block_size
        try:
            data = os.pread(self._fd, self.block_size, offset)
        except OSError as exc:
            raise DeviceIOError(f"{self.path}: read failed at block {index}: {exc}") from exc
        if len(data) != self.block_size:
            raise DeviceIOError(f"{self.path}: short read at block {index} ({len(data)} of {self.block_size} bytes)")
        return data

    def write_block(self, index: int, data: bytes) -> None:
        self._bounds_check(index)
        if len(data) != self.block_size:
            raise ValueError(f"write_block expects exactly {self.block_size} bytes, got {len(data)}")
        if self.dry_run or self._fd is None:
            raise InvalidOperationError(
                "cannot write_block: this RealBlockDevice is in dry-run mode (no real device is "
                "open) — this is expected and correct unless you explicitly intended real I/O"
            )
        offset = index * self.block_size
        try:
            written = os.pwrite(self._fd, data, offset)
        except OSError as exc:
            raise DeviceIOError(f"{self.path}: write failed at block {index}: {exc}") from exc
        if written != self.block_size:
            raise DeviceIOError(f"{self.path}: short write at block {index} ({written} of {self.block_size} bytes)")

    def flush(self) -> None:
        if self._fd is not None:
            os.fsync(self._fd)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __repr__(self) -> str:
        mode = "DRY-RUN" if self.dry_run else "REAL-IO"
        return f"RealBlockDevice({self.path!s}, {mode}, block_size={self.block_size}, num_blocks={self._num_blocks})"
