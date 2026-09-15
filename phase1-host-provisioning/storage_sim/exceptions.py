"""Exception hierarchy for the storage simulation.

Each exception here maps onto a real, named failure mode a Linux storage
stack actually produces — see the docstring on each for the real-world
analog. Keeping these distinct (instead of one generic StorageSimError
everywhere) is what lets the RAID1 layer react differently to different
failures, exactly as mdadm/the kernel block layer do.
"""


class StorageSimError(Exception):
    """Base class for every error this package raises."""


class DeviceIOError(StorageSimError):
    """A simulated block device failed to service a read/write.

    Real-world analog: the kernel block layer returning EIO from a disk
    that is dying, disconnected, or wedged. mdadm reacts to a member
    returning EIO by failing that member out of the array.
    """


class DeviceFailedError(DeviceIOError):
    """The device has been marked hardware-failed and refuses all I/O.

    Real-world analog: a drive that has dropped off the SATA/NVMe bus
    entirely — every subsequent command times out or is rejected.
    """


class ChecksumMismatchError(StorageSimError):
    """A block's stored checksum does not match its data.

    Real-world analog: silent data corruption ("bit rot") — the medium
    returned data without an I/O error, but the bytes are wrong. Stock
    ext4-on-mdadm has no way to detect this on its own; see
    storage_sim/README.md's "Honesty note on checksums" for why this
    simulation adds a checksum layer that stock mdadm does not have.
    """


class SuperblockError(StorageSimError):
    """A device's on-disk superblock is missing, corrupt, or invalid.

    Real-world analog: mdadm failing to assemble an array because a
    member's superblock (metadata) can't be read or doesn't match the
    rest of the array (wrong UUID, incompatible geometry, etc.).
    """


class StaleMemberError(SuperblockError):
    """A member's event count is behind the rest of the array.

    Real-world analog: a disk that was offline while the array kept
    running now has stale data. mdadm will not silently reintegrate it —
    it must be re-added and fully resynced, exactly like a replacement.
    """


class ArrayDegradedError(StorageSimError):
    """Informational: the array is running with fewer than full
    redundancy but can still service I/O. Not necessarily fatal — the
    RAID1 layer raises this only where the caller needs to know
    (e.g. so a caller doesn't assume full redundancy exists)."""


class ArrayFailedError(StorageSimError):
    """No remaining healthy member can service reads or writes.

    Real-world analog: both disks in a RAID1 mirror are gone — this is
    unrecoverable data loss, not just degraded operation.
    """


class RebuildError(StorageSimError):
    """A rebuild could not proceed or was aborted by a second failure.

    Real-world analog: the classic "second disk fails during rebuild"
    scenario that is the textbook argument against RAID1 (or RAID5) as a
    sole backup strategy — rebuild reads put extra load on the one
    surviving, possibly already-marginal, disk.
    """


class InvalidOperationError(StorageSimError):
    """The requested operation is not valid in the array's current state
    (e.g. removing a member that hasn't been failed first, or adding a
    member when there is no degraded slot to fill).

    Real-world analog: mdadm refusing `--remove` on a member that is
    still active ("mdadm: hot remove failed for sdb1: Device or resource
    busy") — you must `--fail` it first.
    """
