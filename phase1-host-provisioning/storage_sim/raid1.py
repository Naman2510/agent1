"""RAID1 (mirroring) logic over the BlockDevice abstraction.

This is the layer that actually implements RAID1 semantics — mirrored
writes, degraded-mode reads, member failure/removal/addition, background
rebuild, and scrubbing — independent of what a "member" physically is.
Everything here would work unmodified if PartitionView were swapped for
a `RealBlockDevice` wrapping an actual `/dev/sdX1`.

State machine
-------------
    CLEAN       both/all members active and in sync
    DEGRADED    at least one member missing/failed, but >=1 healthy member remains
    REBUILDING  a replacement member is being resynced from a healthy source
    FAILED      no healthy member remains — unrecoverable

Real-world mapping: these states correspond to what you'd read out of
`mdadm --detail /dev/md0` (`State : clean`, `State : clean, degraded`,
`State : clean, degraded, recovering`) or `/proc/mdstat`'s `[UU]` / `[U_]`
/ `[_U]` sync-status markers and `recovery = NN%` line.
"""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .block_device import BlockDevice
from .exceptions import (
    ArrayFailedError,
    ChecksumMismatchError,
    DeviceIOError,
    InvalidOperationError,
    RebuildError,
)


class MemberState(str, enum.Enum):
    ACTIVE = "active"          # in sync, serving I/O normally
    FAILED = "failed"          # marked failed, no longer receiving I/O
    REMOVED = "removed"        # logically pulled from the array (slot empty)
    REBUILDING = "rebuilding"  # a replacement is being resynced into this slot
    SPARE = "spare"            # attached but not yet an active member (pre-rebuild)


class ArrayState(str, enum.Enum):
    CLEAN = "clean"
    DEGRADED = "degraded"
    REBUILDING = "rebuilding"
    FAILED = "failed"


@dataclass
class Member:
    device: Optional[BlockDevice]
    state: MemberState
    label: str  # e.g. "disk0" — for human-readable status output only


@dataclass
class RebuildProgress:
    target_label: str
    blocks_total: int
    blocks_done: int = 0
    started_at: float = field(default_factory=time.time)
    finished: bool = False
    aborted_reason: Optional[str] = None

    @property
    def percent(self) -> float:
        if self.blocks_total == 0:
            return 100.0
        return round(100.0 * self.blocks_done / self.blocks_total, 1)


class RAID1Array:
    """A 2-member RAID1 mirror. Generalizing beyond 2 members is possible
    (real mdadm RAID1 supports N-way mirrors) but 2 is what this project
    needs and keeps the state machine easy to reason about and verify —
    see storage_sim/README.md, "Why exactly 2 members"."""

    def __init__(self, members: List[Optional[BlockDevice]], labels: Optional[List[str]] = None):
        """`members` normally holds 2 BlockDevices. A slot may instead be
        `None`, meaning "this array is being constructed already missing
        a member" — the equivalent of `mdadm --assemble` only finding
        one of two expected disks and bringing the array up degraded
        rather than refusing to start."""
        if len(members) != 2:
            raise InvalidOperationError("RAID1Array in this project always has exactly 2 member slots")
        present = [m for m in members if m is not None]
        if not present:
            raise InvalidOperationError("cannot construct a RAID1Array with zero available members")
        sizes = {(m.block_size, m.num_blocks) for m in present}
        if len(sizes) != 1:
            raise InvalidOperationError(
                f"member geometry mismatch: {sizes} — real mdadm refuses to create an "
                "array from members of different size/block_size too"
            )
        block_size, num_blocks = next(iter(sizes))
        self.block_size = block_size
        self.num_blocks = num_blocks
        labels = labels or [f"disk{i}" for i in range(len(members))]
        self._members: List[Member] = [
            Member(device=m, state=MemberState.ACTIVE if m is not None else MemberState.REMOVED, label=label)
            for m, label in zip(members, labels)
        ]
        self._lock = threading.RLock()
        self._rebuild_thread: Optional[threading.Thread] = None
        self._rebuild_progress: Optional[RebuildProgress] = None
        self.on_state_change: Optional[Callable[[str], None]] = None  # optional hook for the dashboard/CLI

    # -- status -------------------------------------------------------------

    def _active_members(self) -> List[Member]:
        return [m for m in self._members if m.state in (MemberState.ACTIVE, MemberState.REBUILDING) and m.device]

    def state(self) -> ArrayState:
        with self._lock:
            if any(m.state == MemberState.REBUILDING for m in self._members):
                return ArrayState.REBUILDING
            active = sum(1 for m in self._members if m.state == MemberState.ACTIVE)
            if active == len(self._members):
                return ArrayState.CLEAN
            if active == 0:
                return ArrayState.FAILED
            return ArrayState.DEGRADED

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self.state().value,
                "block_size": self.block_size,
                "num_blocks": self.num_blocks,
                "members": [
                    {"label": m.label, "state": m.state.value} for m in self._members
                ],
                "rebuild": (
                    {
                        "target": self._rebuild_progress.target_label,
                        "percent": self._rebuild_progress.percent,
                        "blocks_done": self._rebuild_progress.blocks_done,
                        "blocks_total": self._rebuild_progress.blocks_total,
                        "finished": self._rebuild_progress.finished,
                        "aborted_reason": self._rebuild_progress.aborted_reason,
                    }
                    if self._rebuild_progress
                    else None
                ),
            }

    def _notify(self) -> None:
        if self.on_state_change:
            self.on_state_change(self.state().value)

    # -- I/O ------------------------------------------------------------------

    def write_block(self, index: int, data: bytes) -> None:
        """Mirror a write to every ACTIVE and REBUILDING member. A
        member still being resynced gets the write too — exactly like
        real mdadm, which keeps the array live during recovery: any
        write that lands ahead of the resync cursor is simply already
        correct by the time the cursor reaches it."""
        with self._lock:
            targets = [m for m in self._members if m.state in (MemberState.ACTIVE, MemberState.REBUILDING)]
            if not targets:
                raise ArrayFailedError("no healthy member available to write to — array has failed")
            last_error = None
            wrote_to_any = False
            for m in targets:
                try:
                    m.device.write_block(index, data)
                    wrote_to_any = True
                except DeviceIOError as exc:
                    last_error = exc
                    self._fail_member_locked(m, reason=str(exc))
            if not wrote_to_any:
                raise ArrayFailedError(f"write failed on every member: {last_error}")

    def read_block(self, index: int) -> bytes:
        """Read from the first available member; on a checksum mismatch
        or I/O error, fail that member over to the mirror and, if the
        mirror's copy is good, self-heal the bad copy by rewriting it —
        the same "read one, if bad try the other, and if the other is
        good repair the bad one" behavior a `check`/`repair` scrub cycle
        (or a smart RAID1 read path) provides on real mdadm.

        Correctness note: a REBUILDING member is only a valid read
        source for blocks its resync cursor has already passed
        (`index < blocks_done`). Blocks ahead of the cursor still hold
        old placeholder data with a *valid* checksum on that member (see
        block_device.py — a never-written block reads back as
        zero-with-correct-checksum, not an error), so naively treating a
        recovering member as equally trustworthy would silently return
        stale/zero data instead of the real value. This is exactly why
        real Linux md RAID1 tracks a resync bitmap and never serves a
        not-yet-recovered region from the recovering disk."""
        with self._lock:
            candidates = []
            for m in self._members:
                if m.state == MemberState.ACTIVE and m.device:
                    candidates.append(m)
                elif (
                    m.state == MemberState.REBUILDING
                    and m.device
                    and self._rebuild_progress
                    and index < self._rebuild_progress.blocks_done
                ):
                    candidates.append(m)
            if not candidates:
                raise ArrayFailedError("no healthy, in-sync member available to read from — array has failed")

            errors = []
            for i, m in enumerate(candidates):
                try:
                    data = m.device.read_block(index)
                    # Self-heal: if an earlier candidate in this loop was
                    # bad, propagate the good data back to it now.
                    for bad_label, bad_member in errors:
                        try:
                            bad_member.device.write_block(index, data)
                        except DeviceIOError:
                            pass  # bad member may be genuinely failed now; read still succeeded
                    return data
                except ChecksumMismatchError as exc:
                    errors.append((m.label, m))
                    continue
                except DeviceIOError as exc:
                    self._fail_member_locked(m, reason=str(exc))
                    errors.append((m.label, m))
                    continue
            raise ArrayFailedError(
                f"block {index} unreadable on every remaining member: {[e[0] for e in errors]}"
            )

    # -- membership changes ----------------------------------------------------

    def fail_member(self, label: str) -> None:
        """Administrative equivalent of `mdadm --fail /dev/mdX /dev/sdYn`."""
        with self._lock:
            m = self._find(label)
            if m.state not in (MemberState.ACTIVE, MemberState.REBUILDING):
                raise InvalidOperationError(f"{label} is not active/rebuilding (state={m.state.value})")
            self._fail_member_locked(m, reason="administratively failed")

    def _fail_member_locked(self, m: Member, reason: str) -> None:
        if m.state == MemberState.FAILED:
            return
        was_rebuilding = m.state == MemberState.REBUILDING
        m.state = MemberState.FAILED
        if was_rebuilding and self._rebuild_progress and self._rebuild_progress.target_label == m.label:
            self._rebuild_progress.aborted_reason = reason
        self._notify()

    def remove_member(self, label: str) -> None:
        """Equivalent of `mdadm --remove /dev/mdX /dev/sdYn` — logically
        pull a failed member's slot so a replacement can be `add`ed."""
        with self._lock:
            m = self._find(label)
            if m.state != MemberState.FAILED:
                raise InvalidOperationError(
                    f"{label} must be failed before it can be removed (state={m.state.value}); "
                    "real mdadm refuses `--remove` on an active member too"
                )
            m.device = None
            m.state = MemberState.REMOVED
            self._notify()

    def add_member(self, label: str, device: BlockDevice, delay_per_block: float = 0.0) -> None:
        """Equivalent of `mdadm --add /dev/mdX /dev/sdYn` — attach a
        blank replacement and kick off a background rebuild. Returns
        immediately; poll `status()['rebuild']` for progress, exactly
        like polling `/proc/mdstat`'s `recovery = NN%` line."""
        with self._lock:
            if self.state() == ArrayState.FAILED:
                raise InvalidOperationError("cannot add a member to a failed array — no healthy source to rebuild from")
            m = self._find(label)
            if m.state != MemberState.REMOVED:
                raise InvalidOperationError(f"{label} slot must be REMOVED before add (state={m.state.value})")
            if device.block_size != self.block_size or device.num_blocks != self.num_blocks:
                raise InvalidOperationError("replacement device geometry does not match the array")
            source = self._pick_rebuild_source()
            if source is None:
                raise InvalidOperationError("no healthy member available as a rebuild source")

            m.device = device
            m.state = MemberState.REBUILDING
            self._rebuild_progress = RebuildProgress(target_label=label, blocks_total=self.num_blocks)
            self._notify()

        self._rebuild_thread = threading.Thread(
            target=self._run_rebuild, args=(label, source.label, delay_per_block), daemon=True
        )
        self._rebuild_thread.start()

    def _pick_rebuild_source(self) -> Optional[Member]:
        for m in self._members:
            if m.state == MemberState.ACTIVE:
                return m
        return None

    def _run_rebuild(self, target_label: str, source_label: str, delay_per_block: float) -> None:
        progress = self._rebuild_progress
        for i in range(self.num_blocks):
            with self._lock:
                target = self._find(target_label)
                source = self._find(source_label)
                if target.state != MemberState.REBUILDING:
                    return  # aborted (e.g. target failed mid-rebuild) — _fail_member_locked already recorded why
                if source.state not in (MemberState.ACTIVE, MemberState.REBUILDING):
                    progress.aborted_reason = f"rebuild source {source_label} failed mid-rebuild — data loss"
                    self._fail_member_locked(target, reason=progress.aborted_reason)
                    return
                try:
                    data = source.device.read_block(i)
                except Exception as exc:  # noqa: BLE001 — see note below
                    # Caught broadly, not just DeviceIOError/ChecksumMismatchError:
                    # this background thread must never die with an unhandled
                    # exception and leave `progress`/member state inconsistent —
                    # e.g. the owning process closing every file handle out
                    # from under an in-flight rebuild (simulating a crash)
                    # raises a plain ValueError from the stdlib file object,
                    # not one of our own typed exceptions, and must still be
                    # treated as "the source became unusable," the textbook
                    # "second failure during recovery" scenario.
                    progress.aborted_reason = f"rebuild source {source_label} failed at block {i}: {exc}"
                    self._fail_member_locked(source, reason=str(exc))
                    self._fail_member_locked(target, reason="rebuild aborted: no healthy source remained")
                    return
                try:
                    target.device.write_block(i, data)
                except Exception as exc:  # noqa: BLE001 — same reasoning as the read above
                    progress.aborted_reason = f"rebuild target {target_label} failed at block {i}: {exc}"
                    self._fail_member_locked(target, reason=str(exc))
                    return
                progress.blocks_done = i + 1
            if delay_per_block:
                time.sleep(delay_per_block)

        with self._lock:
            target = self._find(target_label)
            if target.state == MemberState.REBUILDING:
                target.state = MemberState.ACTIVE
                progress.finished = True
                self._notify()

    def wait_for_rebuild(self, timeout: Optional[float] = None) -> RebuildProgress:
        """Test/CLI helper: block until the current rebuild thread exits."""
        if self._rebuild_thread:
            self._rebuild_thread.join(timeout=timeout)
        if self._rebuild_progress is None:
            raise RebuildError("no rebuild is or was in progress")
        return self._rebuild_progress

    # -- integrity ------------------------------------------------------------

    def scrub(self, repair: bool = True) -> dict:
        """Read every block from every active member and compare them.
        Real-world analog: `echo check > /sys/block/mdX/md/sync_action`
        (or `repair` instead of `check`). Honesty note: stock mdadm's
        `check`/`repair` has no checksum to know which mirror is
        *correct* on a mismatch — `repair` just blindly copies the first
        member's data over the rest. Because our simulated devices carry
        a per-block checksum (see block_device.py's module docstring),
        this scrub can actually identify which copy is corrupt and heal
        from the verified-good one — a capability real mdadm alone does
        not have. See storage_sim/README.md for the full explanation."""
        mismatches = []
        with self._lock:
            active = [m for m in self._members if m.state == MemberState.ACTIVE]
            if len(active) < 1:
                raise ArrayFailedError("no active members to scrub")
            for i in range(self.num_blocks):
                good_data = None
                bad_members = []
                for m in active:
                    try:
                        data = m.device.read_block(i)
                        if good_data is None:
                            good_data = data
                        elif data != good_data:
                            bad_members.append(m)
                    except ChecksumMismatchError:
                        bad_members.append(m)
                if bad_members and good_data is not None:
                    mismatches.append({"block": i, "bad_members": [m.label for m in bad_members]})
                    if repair:
                        for m in bad_members:
                            try:
                                m.device.write_block(i, good_data)
                            except DeviceIOError:
                                self._fail_member_locked(m, reason="I/O error during scrub repair")
        return {"blocks_scanned": self.num_blocks, "mismatches": mismatches, "repaired": repair}

    # -- helpers ----------------------------------------------------------

    def _find(self, label: str) -> Member:
        for m in self._members:
            if m.label == label:
                return m
        raise InvalidOperationError(f"no such member: {label}")
