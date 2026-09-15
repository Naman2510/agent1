# Interview Prep — RAID1 Storage Simulation

Structured per CLAUDE.md's Interview Preparation section. This is a
reference document, not a transcript of a quiz — the questions at the
bottom are for you to work through on your own before an interview
(or against a real Data Center Technician-style panel), not something
answered inline here.

## 1. What we built

A from-scratch, testable software model of a two-disk RAID1 mirror:
simulated block devices, GPT-style partitioning, an mdadm-superblock-like
metadata layer, mirrored writes, degraded-mode reads, member fail/
remove/add, a background rebuild with live progress, per-block checksums
enabling self-healing reads and a real `scrub`, and superblock-based
reassembly after a process restart (`mdadm --assemble --scan`'s
equivalent). Wired into a CLI (`raidsim`) and a live dashboard panel.

## 2. Why we built it

The user has one OS disk plus one blank disk in their VM tonight — not
enough for a real RAID1 test (needs two dedicated members), and won't be
until a third disk is added. Rather than wait, the RAID *logic* — the
actual hard part conceptually (mirroring semantics, degraded-mode
correctness, rebuild races, corruption handling, stale-member detection)
— was built and proven correct in software, so the eventual real-VM
integration is "point this at real disks" rather than "design this from
scratch under time pressure."

## 3. How it works

```
CLI / Dashboard -> ArrayManager -> RAID1Array -> BlockDevice interface -> SimulatedBlockDevice (a file)
```

See `README.md`'s architecture diagram and the real-mdadm mapping table
for the full detail. Key mechanism: every simulated disk reserves a
fixed-size region at offset 0 for a JSON superblock (array UUID, this
member's role, an event counter, and — critically — a snapshot of the
*whole array's* last-known membership, `member_roles`). `ArrayManager`
reads these on every process start to decide which disks to trust.

## 4. Key technologies

Pure Python 3 standard library: `dataclasses`, `enum`, `threading`
(the background rebuild thread + an `RLock` guarding array state),
`hashlib` (SHA-256 per-block checksums), `json` (superblock encoding),
`unittest` (the whole test suite — no pytest, no mocking framework, no
new dependency). Deliberately zero-dependency, matching the rest of the
repo's style.

## 5. Design decisions (and why each one is defensible)

- **Exactly 2 members, not N-way.** Matches the actual 2-disk target;
  keeps the state machine (CLEAN/DEGRADED/REBUILDING/FAILED) small
  enough to exhaustively test.
- **A checksum layer stock mdadm doesn't have.** Added deliberately, and
  called out honestly as an enhancement (comparable to T10 DIF, not to
  ext4-on-mdadm) — without it, `scrub`/self-heal would have nothing to
  decide *which* copy is correct on a mismatch, which is a real,
  well-known limitation of plain RAID1.
- **Block-level testing, no toy filesystem.** The learning objective
  lives below the filesystem layer; a real deployment runs ext4 on top
  exactly as `phase1-host-provisioning/scripts/03-format-mount.sh` does.
- **One partition per disk, not a general GPT parser.** The real scripts
  only ever create one full-disk partition (`sgdisk -n 1:0:0`) — matching
  that exactly avoids solving a harder, unneeded problem.
- **`member_roles` in the superblock.** Added *after* a real bug: a
  disk that was administratively failed (not hardware-failed, still a
  perfectly readable file) was silently reactivated by the very next
  process's reassembly, because only *which disks exist* was persisted,
  not *which member is failed*. Fixed by having surviving members carry
  the whole array's membership picture, mirroring what real mdadm
  superblocks actually do and why.

## 6. Failure modes identified and handled

| Failure | Handled how |
| --- | --- |
| One member fails | Array degrades, stays writable/readable on the survivor |
| Both members fail | `ArrayFailedError` — explicit, not silent data corruption |
| Silent corruption (bit rot) on one copy | Detected via checksum mismatch; self-healed on read if that copy is tried first, or found by `scrub` otherwise |
| Second failure during rebuild | The rebuild aborts, the array is marked FAILED — the textbook "RAID1 is not a backup" scenario, made explicit rather than glossed over |
| Rebuild interrupted by a process restart | NOT silently trusted as complete on reassembly — requires a fresh `add`. Real mdadm can resume via a write-intent bitmap; this simulation doesn't implement one, and says so |
| A failed-but-still-readable disk reappearing | Not silently reactivated — see `member_roles` above |
| Reading a not-yet-synced block during rebuild | Resync-cursor-aware: a REBUILDING member is only a valid read source for blocks its cursor has already passed |

## 7. Troubleshooting procedure (for this simulation specifically)

1. `python3 -m storage_sim.cli status <name>` — state, per-member state,
   rebuild progress if any.
2. If a reassembly excluded something unexpectedly, `assemble_all()`'s
   stderr output (`[assemble] ... EXCLUDED ...` / `NOT TRUSTED ...`)
   names the array_uuid and reason — check the offending disk's
   superblock (`SimulatedBlockDevice(path).read_superblock()`).
3. If a rebuild seems stuck, check `status()['rebuild']['aborted_reason']`
   — a non-null value always means the source or target failed mid-copy.
4. Run the test suite (`python3 -m unittest discover -s tests -v`) —
   any regression shows up immediately and names the exact scenario.

## 8. Testing performed

48 automated tests (`tests/`), all genuinely executed, covering every
row in the failure-modes table above plus normal read/write and
cross-process persistence, plus a scripted, asserting `raidsim demo`.
See `README.md`'s "What has and hasn't been validated" for the precise,
honest boundary of what this does and doesn't prove.

## 9. Limitations

- Simulation only — no real `mdadm`, no real block devices, until the
  VM has a third disk (see `PROJECT_SPEC.md`'s hardware note).
- No resumable rebuild across a restart (documented, not silently wrong).
- No N-way mirroring, no real GPT multi-partition support (out of scope
  by design, not an oversight).
- Single-process ownership assumed; no protection against two processes
  pointed at the same data directory simultaneously.

## 10. Possible improvements

- A `RealBlockDevice` backend wrapping an actual `/dev/sdX` — the whole
  point of the `BlockDevice` interface is that this shouldn't require
  touching `raid1.py` at all.
- A write-intent-bitmap-style mechanism to make interrupted rebuilds
  resumable instead of always starting over.
- Generalizing `RAID1Array` to N members (mechanical, not hard, just
  unneeded for this project's actual 2-disk target).

---

## Interview questions to work through yourself

No answers below on purpose — write your own, then check them against
the sections above.

1. Why does RAID1 need at least two disks, and what specifically breaks
   if you try to build it with one?
2. What is an mdadm "event counter" for, and what real-world scenario
   does it protect against? How does this simulation's `member_roles`
   go a step further than a bare event counter?
3. Walk through what happens, step by step, if the *second* disk fails
   while the *first* replacement is still rebuilding. Why is this the
   classic argument that "RAID is not a backup"?
4. This simulation added per-block checksums that stock mdadm doesn't
   have. Why doesn't stock mdadm have them, and what real technology
   *does* solve this problem in production Linux storage stacks?
5. Why is a `RAID1Array` operating on a `PartitionView` rather than the
   raw `SimulatedBlockDevice` directly the technically correct choice
   (hint: what does `/dev/sdb` vs `/dev/sdb1` actually mean)?
6. If you restart the array manager process while a rebuild is halfway
   done, what happens to that in-progress member on the next start, and
   why was that the *safe* choice rather than trying to resume?
7. Why does `read_block()` only try a REBUILDING member for blocks
   before its resync cursor, and what would go wrong if it didn't?
8. You're asked in an interview: "have you actually tested this against
   real hardware?" What's the honest, precise answer for this project
   as of tonight?
