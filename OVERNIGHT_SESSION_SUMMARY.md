# Overnight Session Summary

Written for you to read first thing — what happened while you were
asleep, what's actually proven vs. not, and what to do next. Commits:
`69379f9` through `a22b772` on `claude/sleepy-dirac-5ql9wk` (PR #2).

## What you asked for

Continue autonomously, don't wait for confirmation on routine decisions,
but **do not touch the VM or any real disk** — you have the OS disk plus
one blank disk tonight, and are deliberately not adding a third until
you're back. Instead: build the RAID1 storage/mirroring logic as a full
sandbox simulation, tested thoroughly, documented, with an honest testing
ledger — leaving the project in a state where what's left is mainly
integrating the already-tested core with real Linux block devices in the
VM.

**I did not touch the VM, run `mdadm`, `wipefs`, `sgdisk`, `fdisk`,
`parted`, or any formatting/partitioning command against real or virtual
storage, at any point tonight.** Every destructive-looking command that
ran was either `SIMULATE=1` (prints what it would do) or operated
entirely on regular files inside `storage_sim/data/` (gitignored, never
a block device).

## What got built

1. **`phase1-host-provisioning/storage_sim/`** — a from-scratch RAID1
   simulation: block devices, partitioning, superblocks, mirroring,
   degraded mode, background rebuild, corruption detection + self-heal,
   scrub, and superblock-based reassembly after a restart. CLI
   (`raidsim`) mirrors real `mdadm` verbs. Full architecture and the
   mapping onto real `mdadm`/Linux concepts: `storage_sim/README.md`.
   Structured interview-prep doc + question bank: `storage_sim/INTERVIEW_PREP.md`.

2. **Dashboard integration** — a new "Storage Simulation" panel in the
   web dashboard (`frontend/`), clearly badged SIMULATED, driving the
   RAID1 model live: create/write/read/fail/remove/add/scrub/corrupt/
   hardware-fail, with a real progress bar that updates while a rebuild
   runs in the background — something the CLI architecturally can't do
   (a CLI process can't poll a rebuild a different process started;
   the dashboard's one long-lived process can).

3. **Test suites for everything that didn't have one yet** — the
   original build (before tonight) had only manual, one-off verification
   for `telemetryd.py`, `oob_control.py`, and the dashboard. Per
   CLAUDE.md's testing rigor, that's a real gap, so it got closed:
   automated suites for all three, plus storage_sim's own 50 tests.
   **98 tests total, all genuinely executed** (`make unit-test`).

## Three real bugs found and fixed (not glossed over)

1. **Read-during-rebuild correctness.** A member being rebuilt still has
   old zeroed placeholder data (with a *valid* checksum) for blocks its
   resync cursor hasn't reached yet. A naive read path would silently
   return that stale data instead of erroring or routing to the real
   source. Fixed with resync-cursor-aware read candidate selection;
   regression test: `test_reads_during_rebuild_never_see_stale_unsynced_data`.

2. **Failed disks silently reactivated across a restart.** This one
   only showed up when I actually ran the CLI as separate process
   invocations (exactly how you'd use it for real) instead of trusting
   the in-process test suite alone. A disk that was administratively
   failed — not hardware-failed, so still a perfectly readable file —
   was silently treated as healthy again by the very next `raidsim`
   invocation, because only *which disks exist* was being persisted, not
   *which member is failed*. Fixed by adding a `member_roles` snapshot
   to the superblock (mirroring what real mdadm metadata actually
   carries for this exact reason). Full regression coverage:
   `TestArrayManagerCrossProcessLifecycle` in `storage_sim/tests/test_manager.py`.
   This also naturally closed a related gap: an interrupted rebuild is
   now correctly *not* trusted as complete after a restart either.

3. **A genuine race, found only by running the test suite in a loop.**
   After committing everything above, I ran the full suite a final time
   before writing this summary — and it failed, once, on a test that had
   passed every time before. A single flaky failure is exactly the kind
   of thing it would be easy to shrug off as "probably nothing" and
   move on; instead I re-ran it in a loop (~20-40 iterations) until it
   reproduced twice, got a real traceback, and traced it to
   `ArrayManager.close_all()` closing a rebuild's device file handles
   out from under the background thread still actively using them —
   a race that could leave two members with inconsistent metadata and,
   in the worst case, make the *next* process's reassembly crash outright
   instead of reporting a degraded array. Fixed at the root (a
   cooperative rebuild-stop, joined before any device closes — not a
   sleep or a retry), then stress-tested 40+ times with zero further
   failures before moving on. Full story: `storage_sim/README.md`'s "Why
   `RAID1Array` has a cooperative rebuild-stop".

I'm calling all three out specifically because CLAUDE.md's Honesty
section asks for it, and because "I ran the test suite once and it was
green" is a much weaker claim than "I ran it repeatedly, including after
I thought I was done, caught a real intermittent failure, and didn't
stop until I understood why" — the second one is what actually happened.

## Honest testing status (see `PROJECT_SPEC.md`'s full ledger)

Everything above is **simulation-tested or mock-tested**, not
**VM/hardware-tested**. Nothing tonight touched a real or virtual block
device. `make unit-test` (98 tests) and `make simulate` (dry-run every
destructive shell script) both pass cleanly right now if you want to
verify before reading further.

## What's actually left

The RAID1 *logic* is done, tested, and documented. What remains is
integration with real Linux block devices — genuinely a smaller step now
than it would have been from scratch:

1. Add a third virtual disk to the VM (you said you'd do this tonight —
   so you should have 3 disks now: 1 OS + 2 blank).
2. Boot the VM, run `lsblk`, and share the output. **I will not guess
   device names** — per your instructions and basic safety, the real
   `wipefs`/`sgdisk`/`mdadm` commands only go out once we've both
   confirmed which two device names are actually the blank disks.
3. From there: `phase1-host-provisioning/scripts/00-wipe-disks.sh`
   through `06-sudoers-audit.sh` are the real, already-written scripts —
   see `phase1-host-provisioning/README.md`'s run order.

## Where to look

- **Architecture & mapping to real mdadm:** `storage_sim/README.md`
- **Interview-style structured writeup + question bank:** `storage_sim/INTERVIEW_PREP.md`
- **Full testing honesty ledger, all phases:** `PROJECT_SPEC.md`
- **Try it yourself right now, zero setup:**
  ```
  cd phase1-host-provisioning
  python3 -m storage_sim.cli demo      # narrated, asserting, ~2 seconds
  python3 -m unittest discover -s storage_sim/tests -v
  ```
- **See it in the dashboard:** `make dashboard` from the repo root, then
  open `http://localhost:8080/` and scroll to "Storage Simulation".
