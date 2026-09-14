"""ArrayManager — creation and superblock-based assembly of RAID1 arrays.

Real-world mapping
------------------
`create_array()` is this simulation's `mdadm --create`: allocate two
fresh disk images, partition each (typecode fd00), write matching
superblocks, and build a live RAID1Array.

`assemble_all()` is this simulation's `mdadm --assemble --scan`: scan a
directory of disk images, read each one's superblock, group them by
`array_uuid`, and reconstruct a RAID1Array per group.

Two independent reasons a present, readable disk image is still NOT
trusted as an active member on reassembly (mirroring two different real
mdadm protections):

1. **Stale by event count** — its event_count is behind the rest of the
   group, meaning it missed writes while offline. Excluded into
   `AssemblyReport.excluded_stale`.
2. **Untrusted by recorded role state** — a *surviving* member's own
   superblock carries a `member_roles` snapshot of the whole array's
   last-known membership (see superblock.py). If that snapshot says role
   0 was "failed", "removed", or still "rebuilding" when the process
   last ran, a disk claiming to be role 0 is NOT silently reactivated
   just because it's technically present and readable now — it must be
   explicitly `add`ed again. Excluded into
   `AssemblyReport.untrusted_by_state`.

(2) is the fix for a real bug caught while building this: without it, a
disk that was administratively failed (not hardware-failed — still a
perfectly readable file) would be silently treated as healthy again by
the very next process invocation, since nothing else on disk recorded
that it had been kicked out. See storage_sim/README.md, "Why member_roles
exists", for the full writeup.

Known, documented limitation: a rebuild interrupted by a process restart
is NOT resumed — the role is brought back as untrusted, requiring a
fresh `add` and a full re-copy from scratch. Real mdadm can resume a
partial resync via its write-intent bitmap; this simulation does not
implement that, and says so rather than silently claiming otherwise.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .block_device import PartitionView, SimulatedBlockDevice, create_single_raid_partition
from .exceptions import InvalidOperationError, SuperblockError
from .raid1 import RAID1Array
from .superblock import Superblock

DEFAULT_NUM_BLOCKS = 4096
DEFAULT_BLOCK_SIZE = 4096

# Role states a surviving member's recorded member_roles snapshot must
# show before we'll trust a same-role disk found on reassembly.
# "rebuilding" is deliberately NOT trusted here: a rebuild interrupted by
# a restart is incomplete by definition (see module docstring's "Known,
# documented limitation") and must not be silently treated as done.
_TRUSTED_ROLE_STATES = ("active",)


@dataclass
class AssemblyReport:
    array_uuid: str
    name: str
    included_labels: List[str]
    excluded_stale: List[dict] = field(default_factory=list)
    untrusted_by_state: List[dict] = field(default_factory=list)


@dataclass
class _ArrayRecord:
    name: str
    array: RAID1Array
    raw_devices: Dict[str, SimulatedBlockDevice]  # label -> underlying disk image (for superblock writes)
    event_count: int


class ArrayManager:
    """Owns a directory of simulated disk images and every RAID1Array
    assembled from them. One instance per process — the dashboard and
    the CLI each hold exactly one, mirroring how only one running system
    should have a given real array assembled at a time."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._records: Dict[str, _ArrayRecord] = {}  # array_uuid -> record

    # -- creation -------------------------------------------------------------

    def create_array(
        self, name: str, num_blocks: int = DEFAULT_NUM_BLOCKS, block_size: int = DEFAULT_BLOCK_SIZE
    ) -> RAID1Array:
        with self._lock:
            if self._find_uuid_by_name(name) is not None:
                raise InvalidOperationError(f"an array named {name!r} already exists")
            array_uuid = Superblock.new_array_uuid()
            label0, label1 = f"{name}-0", f"{name}-1"
            d0 = SimulatedBlockDevice.create(
                self.data_dir / f"{label0}.img", num_blocks, block_size, array_uuid=array_uuid, role=0
            )
            d1 = SimulatedBlockDevice.create(
                self.data_dir / f"{label1}.img", num_blocks, block_size, array_uuid=array_uuid, role=1
            )
            for dev in (d0, d1):
                sb = dev.read_superblock()
                sb.name = name
                dev.write_superblock(sb)

            arr = RAID1Array(
                [create_single_raid_partition(d0), create_single_raid_partition(d1)], labels=[label0, label1]
            )
            rec = _ArrayRecord(name=name, array=arr, raw_devices={label0: d0, label1: d1}, event_count=0)
            self._records[array_uuid] = rec
            arr.on_state_change = self._make_async_state_hook(array_uuid)
            self._persist_metadata(rec, bump=False)  # write an initial, consistent role snapshot immediately
            return arr

    # -- assembly ---------------------------------------------------------------

    def assemble_all(self) -> List[AssemblyReport]:
        """Scan self.data_dir for *.img files not already assembled in
        this process, group by array_uuid, and reconstruct each group."""
        groups: Dict[str, List[tuple]] = {}
        for path in sorted(self.data_dir.glob("*.img")):
            try:
                dev = SimulatedBlockDevice(path)
                sb = dev.read_superblock()
            except (SuperblockError, FileNotFoundError):
                continue  # not one of ours, or corrupt beyond even reading metadata
            groups.setdefault(sb.array_uuid, []).append((dev, sb))

        reports = []
        with self._lock:
            for array_uuid, entries in groups.items():
                if array_uuid in self._records:
                    for dev, _sb in entries:
                        dev.close()  # already assembled; this is a redundant handle
                    continue
                reports.append(self._assemble_group(array_uuid, entries))
        return reports

    def _assemble_group(self, array_uuid: str, entries: List[tuple]) -> AssemblyReport:
        max_event = max(sb.event_count for _dev, sb in entries)
        included = [(dev, sb) for dev, sb in entries if sb.event_count == max_event]
        excluded_stale = [(dev, sb) for dev, sb in entries if sb.event_count < max_event]

        name = next((sb.name for _dev, sb in entries if sb.name), array_uuid[:8])
        labels = [f"{name}-0", f"{name}-1"]

        # The most up-to-date included entry's member_roles snapshot (if
        # any) is authoritative about which roles are really trustworthy
        # right now. If nothing has one yet (a brand-new array that
        # somehow got scanned before create_array's initial persist —
        # shouldn't happen via the public API, but be defensive), no
        # role is rejected on that basis.
        authoritative_roles: dict = {}
        for _dev, sb in included:
            if sb.member_roles:
                authoritative_roles = sb.member_roles
                break

        slots: List[Optional[PartitionView]] = [None, None]
        raw_devices: Dict[str, SimulatedBlockDevice] = {}
        untrusted_by_state = []

        for dev, sb in included:
            if sb.role not in (0, 1):
                dev.close()
                continue
            label = labels[sb.role]
            recorded_state = authoritative_roles.get(str(sb.role))
            if authoritative_roles and recorded_state not in _TRUSTED_ROLE_STATES:
                reason = (
                    f"array metadata last recorded role {sb.role} as {recorded_state!r} — "
                    "not silently reactivated; use `add` to rejoin it"
                )
                untrusted_by_state.append({"label": label, "reason": reason})
                dev.close()
                continue
            slots[sb.role] = create_single_raid_partition(dev)
            raw_devices[label] = dev

        for dev, _sb in excluded_stale:
            dev.close()

        arr = RAID1Array(slots, labels=labels)
        rec = _ArrayRecord(name=name, array=arr, raw_devices=raw_devices, event_count=max_event)
        self._records[array_uuid] = rec
        arr.on_state_change = self._make_async_state_hook(array_uuid)

        return AssemblyReport(
            array_uuid=array_uuid,
            name=name,
            included_labels=list(raw_devices.keys()),
            excluded_stale=[
                {"label": f"{name}-{sb.role}", "event_count": sb.event_count, "current_event_count": max_event}
                for _dev, sb in excluded_stale
            ],
            untrusted_by_state=untrusted_by_state,
        )

    # -- lookups ------------------------------------------------------------

    def _find_uuid_by_name(self, name: str) -> Optional[str]:
        for uuid, rec in self._records.items():
            if rec.name == name:
                return uuid
        return None

    def get(self, name: str) -> RAID1Array:
        return self._record_for(name).array

    def list_arrays(self) -> List[dict]:
        return [
            {"name": rec.name, "array_uuid": uuid, **rec.array.status()}
            for uuid, rec in self._records.items()
        ]

    # -- administrative operations (persist to superblocks) ----------------------

    def fail(self, name: str, label: str) -> None:
        rec = self._record_for(name)
        rec.array.fail_member(label)
        self._persist_metadata(rec)

    def remove(self, name: str, label: str) -> None:
        rec = self._record_for(name)
        current = self._member_state(rec, label)
        if current != "removed":
            rec.array.remove_member(label)  # raises InvalidOperationError if not actually failed — as intended
        dev = rec.raw_devices.pop(label, None)
        if dev:
            dev.close()
        self._persist_metadata(rec)

    def add(self, name: str, label: str, delay_per_block: float = 0.0) -> None:
        rec = self._record_for(name)
        role = 0 if label.endswith("-0") else 1
        path = self.data_dir / f"{label}.img"
        if path.exists():
            path.unlink()  # a fresh replacement — the old failed image is not reused, same as a real disk swap
        dev = SimulatedBlockDevice.create(
            path, rec.array.num_blocks, rec.array.block_size, array_uuid=self._uuid_for(name), role=role
        )
        sb = dev.read_superblock()
        sb.name = rec.name
        dev.write_superblock(sb)
        rec.raw_devices[label] = dev
        rec.array.add_member(label, create_single_raid_partition(dev), delay_per_block=delay_per_block)
        self._persist_metadata(rec)

    def scrub(self, name: str, repair: bool = True) -> dict:
        return self._record_for(name).array.scrub(repair=repair)

    def inject_corruption(self, name: str, label: str, block_index: int) -> None:
        rec = self._record_for(name)
        dev = rec.raw_devices.get(label)
        if dev is None:
            raise InvalidOperationError(f"{label} has no attached device to corrupt (already removed?)")
        dev.inject_silent_corruption(block_index)

    def simulate_hardware_failure(self, name: str, label: str) -> None:
        rec = self._record_for(name)
        dev = rec.raw_devices.get(label)
        if dev is None:
            raise InvalidOperationError(f"{label} has no attached device to fail (already removed?)")
        dev.simulate_hardware_failure()

    def write_block(self, name: str, index: int, data: bytes) -> None:
        rec = self._record_for(name)
        rec.array.write_block(index, data)
        self._persist_metadata(rec)

    def read_block(self, name: str, index: int) -> bytes:
        return self._record_for(name).array.read_block(index)

    # -- internals ------------------------------------------------------------

    def _record_for(self, name: str) -> _ArrayRecord:
        uuid = self._find_uuid_by_name(name)
        if uuid is None:
            raise InvalidOperationError(f"no such array: {name!r}")
        return self._records[uuid]

    def _uuid_for(self, name: str) -> str:
        uuid = self._find_uuid_by_name(name)
        assert uuid is not None
        return uuid

    @staticmethod
    def _role_from_label(label: str) -> Optional[int]:
        if label.endswith("-0"):
            return 0
        if label.endswith("-1"):
            return 1
        return None

    @staticmethod
    def _member_state(rec: _ArrayRecord, label: str) -> Optional[str]:
        for m in rec.array.status()["members"]:
            if m["label"] == label:
                return m["state"]
        return None

    def _persist_metadata(self, rec: _ArrayRecord, bump: bool = True) -> None:
        """Write the array's current membership picture into every
        currently-reachable member's superblock: this device's own role
        state, the array's event count, and a full role->state snapshot
        for the WHOLE array (so a surviving member's superblock stays
        authoritative about who's really in the array, even when a
        failed/removed disk's own on-disk state can't be trusted)."""
        if bump:
            rec.event_count += 1
        status = rec.array.status()
        role_map = {}
        for m in status["members"]:
            role = self._role_from_label(m["label"])
            if role is not None:
                role_map[str(role)] = m["state"]
        for label, dev in list(rec.raw_devices.items()):
            try:
                sb = dev.read_superblock()
                sb.event_count = rec.event_count
                sb.member_roles = role_map
                role = self._role_from_label(label)
                sb.state = role_map.get(str(role), sb.state)
                dev.write_superblock(sb)
            except Exception:
                pass  # device may itself be hardware-failed; its superblock is unreachable — expected, not fatal

    def _make_async_state_hook(self, array_uuid: str):
        """RAID1Array notifies on internal state transitions that happen
        on a background thread (a rebuild finishing, or a second failure
        aborting one) — this is the only path by which those need to
        reach the on-disk superblocks, since no synchronous manager call
        is what caused them."""

        def _hook(_state: str) -> None:
            rec = self._records.get(array_uuid)
            if rec:
                self._persist_metadata(rec, bump=True)

        return _hook

    def close_all(self) -> None:
        for rec in self._records.values():
            for dev in rec.raw_devices.values():
                try:
                    dev.close()
                except Exception:
                    pass
        self._records.clear()
