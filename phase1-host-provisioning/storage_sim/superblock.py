"""On-disk metadata block ("superblock") for a simulated disk.

Real-world mapping
------------------
Real Linux software RAID (mdadm) writes a small metadata block onto each
member device — by default "metadata 1.2", stored near the start of the
device — recording: the array's UUID, this member's role/slot, an event
counter, and the array's geometry. This is what lets
`mdadm --assemble --scan` find and reassemble an array after a reboot by
scanning disks and grouping the ones whose superblocks agree, and it's
what lets mdadm detect a member that went offline and is now stale (its
event counter is behind).

This module is the simulation's equivalent: a small JSON blob written to
a fixed-size region at the start of every simulated disk image. Nothing
here is a byte-for-byte reproduction of the real mdadm 1.2 metadata
format (that's a binary struct we don't need to match) — only the
*concepts* it stores are reproduced: array identity, member role, and an
event counter for stale-member detection.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

# Fixed-size region reserved at the start of every simulated disk image
# for the superblock, regardless of the data block size chosen for that
# device. 4096 bytes is comfortably larger than any superblock we write;
# real mdadm reserves a comparable small fixed region for the same reason
# (so the metadata's location never depends on how the rest of the device
# is laid out).
SUPERBLOCK_SIZE = 4096

_MAGIC = "STORAGESIM-SB-V1"


@dataclass
class Superblock:
    array_uuid: str
    member_uuid: str
    role: Optional[int]           # this member's slot index in the array, or None if unassigned (spare)
    block_size: int
    num_blocks: int
    event_count: int = 0
    state: str = "unknown"        # mirrors this member's own last-known state name, for humans reading a raw dump
    name: Optional[str] = None    # human-friendly array name, so assembly can recover it after a restart
    member_roles: Optional[dict] = None  # {"0": "active", "1": "failed", ...} — the WHOLE array's last-known
                                          # membership picture as seen by whichever member was updated last.
                                          # This is what lets reassembly refuse to silently reactivate a role
                                          # that was explicitly failed/removed, or trust a rebuild that never
                                          # finished — a disk being *present and readable* is not, by itself,
                                          # proof it should rejoin the array. Real mdadm's superblock carries
                                          # the equivalent "device roles" information for the same reason.
    created_at: float = field(default_factory=time.time)
    magic: str = _MAGIC

    def to_bytes(self) -> bytes:
        payload = json.dumps(asdict(self)).encode("utf-8")
        if len(payload) > SUPERBLOCK_SIZE - 1:
            raise ValueError("superblock payload exceeds reserved region — grow SUPERBLOCK_SIZE")
        return payload.ljust(SUPERBLOCK_SIZE, b"\0")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Superblock":
        from .exceptions import SuperblockError

        text = raw.split(b"\0", 1)[0]
        if not text:
            raise SuperblockError("empty superblock region — device was never initialized")
        try:
            data = json.loads(text.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuperblockError(f"superblock is not valid JSON: {exc}") from exc
        if data.get("magic") != _MAGIC:
            raise SuperblockError("superblock magic mismatch — not a storage_sim disk image")
        data.pop("magic", None)
        return cls(**data)

    @staticmethod
    def new_array_uuid() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def new_member_uuid() -> str:
        return str(uuid.uuid4())
