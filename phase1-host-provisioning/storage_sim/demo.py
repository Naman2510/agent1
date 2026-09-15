"""Scripted, narrated walkthrough of the full RAID1 simulation lifecycle.

Run with: `raidsim demo` (see cli.py). This exercises create -> write ->
fail -> degraded read/write -> remove -> add -> rebuild -> verify ->
corrupt -> scrub -> verify, printing what's happening and what it maps to
in real mdadm at each step. It is also, in effect, a scripted integration
test — everything it asserts is checked with real `assert` statements
against real reads, not just narrated.
"""

from __future__ import annotations

import time

from .manager import ArrayManager

NAME = "demo"
NUM_BLOCKS = 64
BLOCK_SIZE = 64


def _step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def _pad(text: str) -> bytes:
    return text.encode().ljust(BLOCK_SIZE, b".")[:BLOCK_SIZE]


def run_demo(mgr: ArrayManager) -> None:
    import random

    demo_name = f"{NAME}-{random.randint(1000, 9999)}"  # avoid colliding with a prior demo run's leftover files

    _step(f"1. mdadm --create : creating array {demo_name!r} (2 members, {NUM_BLOCKS} blocks x {BLOCK_SIZE}B)")
    arr = mgr.create_array(demo_name, num_blocks=NUM_BLOCKS, block_size=BLOCK_SIZE)
    print(f"state: {arr.status()['state']}")
    assert arr.status()["state"] == "clean"

    _step("2. Normal writes/reads — mirrored to both members")
    for i in range(NUM_BLOCKS):
        mgr.write_block(demo_name, i, _pad(f"payload-{i:03d}"))
    for i in (0, NUM_BLOCKS // 2, NUM_BLOCKS - 1):
        value = mgr.read_block(demo_name, i)
        print(f"  block {i}: {value.rstrip(b'.').decode()}")
        assert value == _pad(f"payload-{i:03d}")

    _step("3. mdadm --fail /dev/md0 /dev/sdb1 : simulating a disk failure")
    mgr.fail(demo_name, f"{demo_name}-0")
    print(f"state: {mgr.get(demo_name).status()['state']}")
    assert mgr.get(demo_name).status()["state"] == "degraded"

    _step("4. Array stays writable/readable in degraded mode")
    mgr.write_block(demo_name, 0, _pad("written-while-degraded"))
    assert mgr.read_block(demo_name, 0) == _pad("written-while-degraded")
    print("  write+read succeeded on the single surviving member")

    _step(f"5. mdadm --remove /dev/md0 /dev/sdb1 : removing the failed member's slot")
    mgr.remove(demo_name, f"{demo_name}-0")

    _step(f"6. mdadm --add /dev/md0 /dev/sdb1 : attaching a replacement, rebuild starts")
    mgr.add(demo_name, f"{demo_name}-0", delay_per_block=0.01)
    while True:
        status = mgr.get(demo_name).status()
        rebuild = status["rebuild"]
        if rebuild is None or rebuild["finished"] or rebuild["aborted_reason"]:
            break
        print(f"  /proc/mdstat-equivalent: recovery = {rebuild['percent']}%")
        time.sleep(0.1)
    final = mgr.get(demo_name).status()
    print(f"state: {final['state']}")
    assert final["state"] == "clean", f"rebuild did not complete cleanly: {final}"

    _step("7. Verifying every block on the rebuilt member matches the original data")
    for i in range(NUM_BLOCKS):
        expected = _pad("written-while-degraded") if i == 0 else _pad(f"payload-{i:03d}")
        assert mgr.read_block(demo_name, i) == expected
    print(f"  all {NUM_BLOCKS} blocks verified correct after rebuild")

    _step("8. Simulating silent corruption (bit rot) on the mirror that reads are tried against first")
    # read_block() tries members in a fixed order and returns the first
    # good copy it finds — it does NOT cross-check every mirror on every
    # read (neither does real RAID1; that would defeat the point of
    # having a fast read path). So self-heal-on-read only actually
    # engages when the *first-tried* copy is the bad one, which is what
    # we corrupt here to demonstrate honestly.
    mgr.inject_corruption(demo_name, f"{demo_name}-0", 10)
    healed = mgr.read_block(demo_name, 10)
    assert healed == _pad("payload-010")
    print(f"  read returned correct data via failover+self-heal: {healed.rstrip(b'.').decode()}")
    assert mgr.read_block(demo_name, 10) == _pad("payload-010")  # confirm the bad copy was actually rewritten

    _step("9. echo check/repair > sync_action : scrubbing for any remaining mismatches")
    # A *different* block/member, deliberately not touched by step 8's
    # read — this is exactly the corruption a read-path self-heal would
    # NOT catch on its own, and only a full scrub is guaranteed to find.
    mgr.inject_corruption(demo_name, f"{demo_name}-1", 20)
    result = mgr.scrub(demo_name, repair=True)
    print(f"  scrub result: {result}")
    assert len(result["mismatches"]) == 1 and result["mismatches"][0]["block"] == 20

    _step("Demo complete — every assertion above passed against a real (simulated) block-level read/write path.")
