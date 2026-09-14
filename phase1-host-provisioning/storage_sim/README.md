# Storage Simulation — RAID1 over simulated block devices

A from-scratch, testable software model of a two-disk RAID1 mirror,
built so the RAID logic itself never touches a real block device and
can later be pointed at one with minimal changes. Built and tested
entirely in a sandbox with **no real disks available** — see "What has
and hasn't been validated" at the bottom, and `PROJECT_SPEC.md`'s
testing ledger, before treating anything here as hardware-proven.

## Architecture

```
   CLI (cli.py) / Dashboard (frontend/server.py)
                    |
              ArrayManager (manager.py)
         creation, assembly, superblock persistence
                    |
              RAID1Array (raid1.py)
     mirrored writes, degraded reads, fail/remove/add,
        background rebuild, scrub — the actual RAID logic
                    |
          BlockDevice interface (block_device.py)
           /                          \\
  SimulatedBlockDevice          <future: RealBlockDevice
   (a regular file)               wrapping /dev/sdX>
```

`raid1.py` only ever calls `read_block()` / `write_block()` / `flush()`
on whatever it's handed. It has zero knowledge of files, paths, or
VirtualBox. That's the whole point: swapping in a `RealBlockDevice` that
wraps an actual `/dev/sdX1` (opened with `O_DIRECT`, ioctl'd for its real
size, etc.) should require **no changes to raid1.py at all** — only a new
class satisfying the same interface, and a manager-level choice of which
backend to instantiate.

## Mapping onto real Linux / mdadm concepts

| This simulation | Real Linux equivalent |
| --- | --- |
| `SimulatedBlockDevice` (a file) | `/dev/sdX` — a raw disk |
| `create_single_raid_partition()` | `sgdisk -n 1:0:0 -t 1:fd00 /dev/sdX` |
| `PartitionView` | `/dev/sdX1` — what mdadm actually operates on |
| `Superblock` (JSON blob, offset 0) | mdadm metadata 1.2 superblock |
| `Superblock.event_count` | mdadm's per-member event counter |
| `Superblock.member_roles` | mdadm's device-roles metadata (see below) |
| `RAID1Array.fail_member()` | `mdadm --fail /dev/mdX /dev/sdYn` |
| `RAID1Array.remove_member()` | `mdadm --remove /dev/mdX /dev/sdYn` |
| `RAID1Array.add_member()` | `mdadm --add /dev/mdX /dev/sdYn` |
| `RAID1Array._run_rebuild()` progress | `/proc/mdstat`'s `recovery = NN%` |
| `RAID1Array.scrub()` | `echo check\|repair > /sys/block/mdX/md/sync_action` |
| `ArrayManager.assemble_all()` | `mdadm --assemble --scan` |
| per-block checksum in `block_device.py` | **not** stock mdadm — see below |

## Design decisions worth defending in an interview

### Why exactly 2 members, not N-way mirroring
Real mdadm RAID1 supports N-way mirrors. This project only ever needs 2
(matching the two physical disks in the actual VM/hardware target), and
hard-coding 2 keeps the state machine (`ArrayState`: CLEAN / DEGRADED /
REBUILDING / FAILED) simple enough to exhaustively test — every state
transition in `raid1.py` has a direct test in `tests/test_raid1_*.py`.
Generalizing to N members is a mechanical extension (loop over all
members instead of assuming 2) but was left out deliberately: it would
add surface area without adding anything this project's learning
objective — or its actual 2-disk VM target — needs.

### Why a checksum layer that stock mdadm doesn't have
Stock Linux `mdadm` + ext4 has **no way to know which mirror copy is
correct** if the two disagree. `check` just counts mismatches;
`repair` blindly copies the first device over the rest — it is not
"smart" about which one is actually right. This is a well-known real
limitation of RAID1 (as opposed to ZFS/Btrfs, which checksum every block
at the filesystem layer specifically to solve this).

This simulation adds a per-block SHA-256 checksum at the *block device*
layer (see `block_device.py`'s module docstring) so `scrub()` and
`read_block()`'s self-heal path can actually identify and correct silent
corruption. **This is a deliberate simulation enhancement, not a claim
about real mdadm's behavior.** It's modeled on real prior art that
*does* exist at the physical/firmware layer (T10 DIF/DIX "protection
information") — the honest framing is "this simulation adds a
capability comparable to T10 DIF, layered under a RAID1 that otherwise
behaves like mdadm," not "this is what mdadm does out of the box."

### Why `member_roles` exists (a real bug this caught)
Early in building this, `ArrayManager` persisted *which disk images
exist* (via `array_uuid` + `role` + `event_count`) but not *which member
is currently failed/removed/mid-rebuild*. Consequence: a member that was
merely **administratively** failed (`mdadm --fail`-equivalent — not a
simulated hardware fault, so the underlying file was still perfectly
readable) would be **silently reactivated** by the very next process
invocation's `assemble_all()`, since nothing on disk recorded that it
had been kicked out.

The fix: a surviving member's superblock also carries a `member_roles`
snapshot — the whole array's last-known membership picture, refreshed on
every membership-changing operation. On reassembly, a role is only
trusted if the most up-to-date snapshot says it's `"active"`. This is a
close analog of what real mdadm superblocks actually carry (device role
metadata replicated across surviving members) for exactly this reason —
a real degraded array doesn't silently re-admit a pulled-and-reinserted
disk either; it stays out until you `mdadm --add` it back, with a
resync forced from scratch (or resumed from a bitmap, on hardware that
has one).

Full regression coverage:
`tests/test_manager.py::TestArrayManagerCrossProcessLifecycle`.

### Why the block-level test surface, not a filesystem
This simulation tests at the block-device/RAID layer — the layer real
`mdadm` actually operates at — rather than implementing a toy filesystem
on top. The learning objective (mirroring, degraded mode, rebuild,
corruption detection, event-count staleness) lives entirely below the
filesystem layer; a real deployment runs ext4 on top of `/dev/md0`
exactly as `phase1-host-provisioning/scripts/03-format-mount.sh` already
does. Reimplementing even a minimal filesystem here would be unnecessary
complexity for no additional learning value — see CLAUDE.md's "challenge
unnecessary complexity" principle.

### Why not a full GPT partition table parser
Every disk in this project only ever gets **one** partition spanning the
whole device (`sgdisk -n 1:0:0 -t 1:fd00`, matching
`phase1-host-provisioning/scripts/01-partition-raid.sh` exactly). A
general multi-partition GPT reader/writer would be real complexity spent
on a case this project never actually needs — `create_single_raid_partition()`
models exactly the one layout that matters, and no more.

## Known, documented limitations

- **Rebuilds do not resume across a restart.** Real mdadm can resume a
  partially-completed resync using a write-intent bitmap. This
  simulation does not implement one: an interrupted rebuild is reported
  as untrusted on reassembly (`AssemblyReport.untrusted_by_state`) and
  must be `add`ed again from scratch. Documented, not silently wrong —
  see `tests/test_manager.py::test_interrupted_rebuild_is_not_trusted_after_restart`.
- **The CLI's `add` command blocks until the rebuild finishes.** A CLI
  invocation is a fresh process every time (mirroring mdadm's own
  stateless-per-invocation nature); there is no persistent daemon here
  for a *later, separate* `raidsim` command to poll a rebuild an
  *earlier* invocation started. Real mdadm doesn't have this limitation
  because the kernel's md driver runs the resync independent of any
  userspace process. **The dashboard** (`frontend/`), which keeps one
  `ArrayManager` alive for its whole run, is where a rebuild is actually
  watchable live via polling — see `frontend/README.md`.
- **Single-process-at-a-time ownership is assumed**, same as a real
  array should only be assembled on one host at a time. Nothing here
  guards against two processes pointed at the same `data_dir`
  simultaneously; real mdadm's `homehost` mechanism exists to catch
  exactly that scenario, and is out of scope here.
- **Checksums are a simulation-only addition** — see "Why a checksum
  layer" above. Don't cite this project's corruption-recovery behavior
  as representative of stock mdadm.

## Running it

```bash
cd phase1-host-provisioning
python3 -m unittest discover -s storage_sim/tests -v   # 48 tests as of this writing
python3 -m storage_sim.cli demo                          # scripted, narrated, asserting walkthrough
python3 -m storage_sim.cli create tank --num-blocks 4096 --block-size 4096
python3 -m storage_sim.cli status tank
```

See `cli.py`'s module docstring for the full command reference.

## What has and hasn't been validated

**Genuinely tested, right now, in this sandbox:** every code path above
— normal read/write, degraded-mode read/write, member failure, removal,
replacement, background rebuild (including one interrupted by a second
failure), silent-corruption detection and self-heal, `scrub`, and
cross-process persistence/reassembly (including the stale-event-count
and untrusted-role-state cases) — via 48 real automated tests plus a
scripted demo, all actually executed, not just asserted to work.

**Not tested, and cannot be, without real hardware:** real `mdadm`,
real `/dev/sdX` block devices, real disk failure timing/latency
characteristics, real GRUB/EFI interaction, real filesystem behavior on
top of the array. This simulation is a model of the *logic*, built to
make the eventual real-hardware integration (see
`phase1-host-provisioning/scripts/`) a smaller, better-understood step —
it is not a substitute for actually running that integration on the VM.
