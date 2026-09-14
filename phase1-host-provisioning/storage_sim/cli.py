#!/usr/bin/env python3
"""raidsim — command-line interface for the storage simulation.

Deliberately mirrors real `mdadm` verbs (create / fail / remove / add) so
the mapping to real commands is obvious. Every invocation is a fresh
process — like `mdadm`, state is recovered by scanning disk images'
superblocks (`assemble_all()`), not by any separate daemon or database.

Examples
--------
    raidsim create tank --num-blocks 4096 --block-size 4096
    raidsim status tank
    raidsim write tank 0 "hello world"
    raidsim read tank 0
    raidsim fail tank tank-0
    raidsim remove tank tank-0
    raidsim add tank tank-0 --delay-per-block 0.01   # blocks until the rebuild finishes; see cmd_add
    raidsim scrub tank
    raidsim corrupt tank tank-1 5
    raidsim hardware-fail tank tank-0
    raidsim list
    raidsim demo              # scripted end-to-end walkthrough
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .exceptions import StorageSimError
from .manager import ArrayManager

DEFAULT_DATA_DIR = Path(os.environ.get("STORAGE_SIM_DATA_DIR", Path(__file__).resolve().parent / "data"))


def _get_manager(data_dir: Path) -> ArrayManager:
    mgr = ArrayManager(data_dir)
    reports = mgr.assemble_all()
    for r in reports:
        print(f"[assemble] {r.name}: included {r.included_labels}", file=sys.stderr)
        for stale in r.excluded_stale:
            print(
                f"[assemble] {r.name}: EXCLUDED stale member {stale['label']} "
                f"(event_count={stale['event_count']}, current={stale['current_event_count']})",
                file=sys.stderr,
            )
        for untrusted in r.untrusted_by_state:
            print(f"[assemble] {r.name}: NOT TRUSTED {untrusted['label']} — {untrusted['reason']}", file=sys.stderr)
    return mgr


def cmd_create(mgr: ArrayManager, args) -> int:
    mgr.create_array(args.name, num_blocks=args.num_blocks, block_size=args.block_size)
    print(f"created array {args.name!r}: {args.num_blocks} blocks x {args.block_size} bytes, 2 members, state=clean")
    return 0


def cmd_status(mgr: ArrayManager, args) -> int:
    print(json.dumps(mgr.get(args.name).status(), indent=2))
    return 0


def cmd_list(mgr: ArrayManager, args) -> int:
    print(json.dumps(mgr.list_arrays(), indent=2))
    return 0


def cmd_write(mgr: ArrayManager, args) -> int:
    arr = mgr.get(args.name)
    data = args.data.encode().ljust(arr.block_size, b"\0")[: arr.block_size]
    mgr.write_block(args.name, args.block_index, data)
    print(f"wrote block {args.block_index}")
    return 0


def cmd_read(mgr: ArrayManager, args) -> int:
    data = mgr.read_block(args.name, args.block_index)
    print(data.rstrip(b"\0").decode(errors="replace"))
    return 0


def cmd_fail(mgr: ArrayManager, args) -> int:
    mgr.fail(args.name, args.label)
    print(f"failed {args.label} — array is now {mgr.get(args.name).status()['state']}")
    return 0


def cmd_remove(mgr: ArrayManager, args) -> int:
    mgr.remove(args.name, args.label)
    print(f"removed {args.label}")
    return 0


def cmd_add(mgr: ArrayManager, args) -> int:
    # NOTE on why this blocks: the rebuild runs on a background thread
    # inside THIS process's ArrayManager, and a CLI invocation is a
    # fresh process every time (mirroring mdadm itself being stateless
    # per-invocation) — there is no persistent daemon here for a later,
    # separate `raidsim` command to poll. Real mdadm doesn't have this
    # limitation because the kernel's md driver runs the resync
    # independent of any userspace process. The dashboard (frontend/),
    # which keeps one ArrayManager alive for its whole run, is where
    # this rebuild is actually watchable live — see its README.
    mgr.add(args.name, args.label, delay_per_block=args.delay_per_block)
    print(f"added {args.label}, rebuilding...")
    progress = mgr.get(args.name).wait_for_rebuild(timeout=args.timeout)
    print(json.dumps(progress.__dict__, indent=2, default=str))
    print(f"state: {mgr.get(args.name).status()['state']}")
    return 0 if progress.finished else 1


def cmd_scrub(mgr: ArrayManager, args) -> int:
    result = mgr.scrub(args.name, repair=not args.no_repair)
    print(json.dumps(result, indent=2))
    return 0


def cmd_corrupt(mgr: ArrayManager, args) -> int:
    mgr.inject_corruption(args.name, args.label, args.block_index)
    print(f"injected silent corruption at {args.label} block {args.block_index}")
    return 0


def cmd_hardware_fail(mgr: ArrayManager, args) -> int:
    mgr.simulate_hardware_failure(args.name, args.label)
    print(f"{args.label} now simulates a hardware failure (every I/O will raise)")
    return 0


def cmd_demo(mgr: ArrayManager, args) -> int:
    from .demo import run_demo

    run_demo(mgr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("create", help="create a new simulated RAID1 array")
    c.add_argument("name")
    c.add_argument("--num-blocks", type=int, default=4096)
    c.add_argument("--block-size", type=int, default=4096)
    c.set_defaults(func=cmd_create)

    c = sub.add_parser("status", help="show one array's status")
    c.add_argument("name")
    c.set_defaults(func=cmd_status)

    c = sub.add_parser("list", help="list all assembled arrays")
    c.set_defaults(func=cmd_list)

    c = sub.add_parser("write", help="write a string into one block (padded/truncated to block_size)")
    c.add_argument("name")
    c.add_argument("block_index", type=int)
    c.add_argument("data")
    c.set_defaults(func=cmd_write)

    c = sub.add_parser("read", help="read one block back as text")
    c.add_argument("name")
    c.add_argument("block_index", type=int)
    c.set_defaults(func=cmd_read)

    c = sub.add_parser("fail", help="mark a member failed (mdadm --fail)")
    c.add_argument("name")
    c.add_argument("label")
    c.set_defaults(func=cmd_fail)

    c = sub.add_parser("remove", help="remove a failed member's slot (mdadm --remove)")
    c.add_argument("name")
    c.add_argument("label")
    c.set_defaults(func=cmd_remove)

    c = sub.add_parser(
        "add",
        help="attach a replacement and rebuild (mdadm --add) — blocks until the rebuild finishes; see cmd_add's docstring for why",
    )
    c.add_argument("name")
    c.add_argument("label")
    c.add_argument("--delay-per-block", type=float, default=0.0, help="artificial delay per block, to make progress visible")
    c.add_argument("--timeout", type=float, default=None)
    c.set_defaults(func=cmd_add)

    c = sub.add_parser("scrub", help="verify (and by default repair) every block across members")
    c.add_argument("name")
    c.add_argument("--no-repair", action="store_true")
    c.set_defaults(func=cmd_scrub)

    c = sub.add_parser("corrupt", help="[fault injection] flip a block's data without updating its checksum")
    c.add_argument("name")
    c.add_argument("label")
    c.add_argument("block_index", type=int)
    c.set_defaults(func=cmd_corrupt)

    c = sub.add_parser("hardware-fail", help="[fault injection] make a member's every I/O raise")
    c.add_argument("name")
    c.add_argument("label")
    c.set_defaults(func=cmd_hardware_fail)

    c = sub.add_parser("demo", help="run a scripted end-to-end lifecycle walkthrough")
    c.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    mgr = _get_manager(args.data_dir)
    try:
        return args.func(mgr, args)
    except StorageSimError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        mgr.close_all()


if __name__ == "__main__":
    sys.exit(main())
