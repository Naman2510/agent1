#!/usr/bin/env python3
"""plan_from_lsblk — turn real `lsblk -J` output into a reviewable command
plan for Phase 1 provisioning, WITHOUT ever executing anything itself.

This exists specifically for the hard safety rule this project runs
under: real device names are never guessed, and real destructive
commands (`wipefs`, `sgdisk`, `mdadm`, ...) are only issued after a human
has confirmed which two device paths are genuinely blank, dedicated RAID
members — never the disk the OS is running from.

This script automates the *analysis* of `lsblk` output (which disks look
like the OS disk, which look like safe blank candidates) so that step is
fast and consistent, but it deliberately still requires an explicit
`--i-confirm-these-are-blank-disks` flag before it will print anything
that looks like a ready-to-run command — the actual judgment call always
stays with a human looking at real output, not with this script's
heuristics alone.

Usage
-----
    lsblk -J -O > disks.json          # on the real VM
    python3 plan_from_lsblk.py disks.json                              # analysis only
    python3 plan_from_lsblk.py disks.json --i-confirm-these-are-blank-disks  # + command plan

    # or piped directly:
    lsblk -J -O | python3 plan_from_lsblk.py -

Heuristic (conservative by design — false positives on "in use" are
fine, false negatives are not)
--------------------------------------------------------------------
A disk is treated as IN USE (never a RAID candidate) if, anywhere in its
own record or any descendant (partition, etc.):
  - a `mountpoint` is set, or
  - a `fstype` is set, or
  - it's flagged read-only, or
  - it has children present at all (an unpartitioned blank disk has none)

A disk is a CANDIDATE only if none of the above apply anywhere in its
subtree. This will correctly refuse to treat a disk with an old,
unmounted-but-still-present filesystem as "blank" — exactly the
conservative direction to err in.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DiskAssessment:
    name: str
    path: str
    size: Optional[str]
    in_use: bool
    reasons: List[str] = field(default_factory=list)


def _walk_in_use_reasons(node: Dict[str, Any], reasons: List[str], prefix: str = "") -> None:
    """Recursively collect reasons a disk (or one of its descendants)
    should be considered in-use. Mutates `reasons` in place."""
    label = prefix + node.get("name", "?")
    if node.get("mountpoint"):
        reasons.append(f"{label} is mounted at {node['mountpoint']!r}")
    if node.get("fstype"):
        reasons.append(f"{label} has a filesystem ({node['fstype']!r})")
    if node.get("ro") in (True, "1", 1):
        reasons.append(f"{label} is marked read-only")
    for child in node.get("children") or []:
        _walk_in_use_reasons(child, reasons, prefix=f"{label}>")


def assess(lsblk_json: Dict[str, Any]) -> List[DiskAssessment]:
    results: List[DiskAssessment] = []
    for node in lsblk_json.get("blockdevices", []):
        if node.get("type") != "disk":
            continue  # only whole disks are ever RAID-member candidates
        reasons: List[str] = []
        _walk_in_use_reasons(node, reasons)
        children = node.get("children") or []
        if children and not reasons:
            # Partitioned but somehow nothing tripped a reason above
            # (e.g. an unmounted, typeless partition) — still not blank.
            reasons.append(f"{node.get('name')} already has a partition table ({len(children)} partition(s))")
        results.append(
            DiskAssessment(
                name=node.get("name", "?"),
                path=f"/dev/{node.get('name', '?')}",
                size=node.get("size"),
                in_use=bool(reasons),
                reasons=reasons,
            )
        )
    return results


def render_report(assessments: List[DiskAssessment]) -> str:
    lines = ["=== Disk assessment (from lsblk) ===", ""]
    in_use = [a for a in assessments if a.in_use]
    candidates = [a for a in assessments if not a.in_use]

    lines.append(f"Total disks seen: {len(assessments)}")
    lines.append(f"In use (NOT RAID candidates): {len(in_use)}")
    for a in in_use:
        lines.append(f"  - {a.path} ({a.size}): " + "; ".join(a.reasons))
    lines.append(f"Blank candidates: {len(candidates)}")
    for a in candidates:
        lines.append(f"  - {a.path} ({a.size}): no mountpoint, no filesystem, no partitions detected")
    lines.append("")

    if len(assessments) < 3:
        lines.append(
            f"WARNING: only {len(assessments)} disk(s) total were seen. This project's plan calls for "
            "3 (1 OS + 2 blank RAID members). Do not proceed until a third disk is actually present."
        )
    if len(candidates) < 2:
        lines.append(
            f"REFUSING to generate a command plan: only {len(candidates)} blank candidate disk(s) found, "
            "need exactly 2. Re-run lsblk after confirming the disk layout."
        )
    elif len(candidates) > 2:
        lines.append(
            f"REFUSING to generate a command plan: {len(candidates)} blank candidates found (ambiguous — "
            "need exactly 2). Identify which two are the intended RAID members and re-run with only those "
            "disks considered, or double check none of the 'candidates' above is actually your OS disk "
            "under an unexpected name."
        )
    return "\n".join(lines)


def render_command_plan(candidates: List[DiskAssessment]) -> str:
    d1, d2 = candidates[0].path, candidates[1].path
    return "\n".join([
        "=== Command plan (REVIEW BEFORE RUNNING — nothing here has been executed) ===",
        "",
        f"Candidate RAID members identified: {d1} and {d2}",
        "Run these yourself, in order, from phase1-host-provisioning/ — this script has not",
        "and will not run any of them:",
        "",
        f"  sudo DISK1={d1} DISK2={d2} ./scripts/00-wipe-disks.sh",
        f"  sudo DISK1={d1} DISK2={d2} ./scripts/01-partition-raid.sh",
        f"  sudo PART1={d1}1 PART2={d2}1 ./scripts/02-assemble-raid.sh",
        "  sudo ./scripts/03-format-mount.sh",
        "",
        "Consider a SIMULATE=1 dry run of each first:",
        f"  SIMULATE=1 DISK1={d1} DISK2={d2} ./scripts/00-wipe-disks.sh",
        "",
        "Bootloader mirroring (04) and beyond are separate, later steps — see",
        "phase1-host-provisioning/README.md for the full run order.",
    ])


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="path to lsblk -J output, or '-' for stdin")
    p.add_argument(
        "--i-confirm-these-are-blank-disks",
        action="store_true",
        dest="confirmed",
        help="also print a ready-to-review real command plan (still never executes anything)",
    )
    args = p.parse_args(argv)

    if args.input == "-":
        text = sys.stdin.read()
    else:
        with open(args.input, "r", encoding="utf-8") as fh:
            text = fh.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"error: input is not valid JSON (did you use `lsblk -J`?): {exc}", file=sys.stderr)
        return 1

    assessments = assess(data)
    print(render_report(assessments))

    candidates = [a for a in assessments if not a.in_use]
    if len(candidates) == 2:
        if args.confirmed:
            print()
            print(render_command_plan(candidates))
        else:
            print()
            print("(pass --i-confirm-these-are-blank-disks to also print a ready-to-review command plan)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
