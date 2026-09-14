#!/usr/bin/env python3
"""
gen_dynamic_scheduler_demo.py -- Phase 15: generate ONE RISC-V program
that, in a SINGLE simulated execution, processes a fixed stream of 6
workloads and -- for each one -- computes the AI scheduler's engine
decision (CPU vs. accelerator) AT RUNTIME, on the CPU, using real
RV32I instructions and a real conditional branch on real computed
values, then actually executes the chosen engine's compute path.

This is a genuinely different thing from Phase 13/14: there, an
OFFLINE Python script (scheduler/inference/decide.py) picked which
already-assembled, single-workload program to run. Here, ONE program
handles all 6 workloads, and the engine choice for each is made by the
CPU itself, mid-simulation, by evaluating the same decision boundary
the trained tree learned (`element_count <= 2 and multiply_count == 0
-> cpu, else accelerator` -- see scheduler/training/train_scheduler.py's
printed tree) directly in hardware/software, never in Python. This
keeps the "important CPU/accelerator behavior belongs in
RTL/software, not a Python shortcut" rule (see README.md's engineering
rules) even for the scheduling decision itself.

Per-workload element_count/multiply_count are computed with real
instructions every time (including, for matmul, two genuine runtime
multiplications via the mul32 subroutine) -- even though this demo's
workload sizes are fixed at generation time, nothing about the
decision is precomputed in Python and baked in as an unconditional
jump; the generated branch instructions actually depend on the
runtime register values.

Four variants of the SAME 6-workload stream are generated, so the
dynamic scheduler's real measured total can be compared against three
real (not hand-summed) baselines:

  - dynamic_scheduler_demo.s   -- runtime-computed decision per block
  - always_cpu_demo.s          -- every block forced to the CPU path
  - always_accel_demo.s        -- every block forced to the accelerator path
  - oracle_demo.s              -- every block forced to whichever engine
                                   scheduler/training/dataset.csv /
                                   heldout_dataset.csv (real measured
                                   Phase 13/14 data) says is actually
                                   faster for that exact workload --
                                   the best any per-workload-static
                                   dispatcher could possibly do

All four share identical per-block bodies (same operand setup, same
compute loops, same accelerator MMIO sequence) copied from the
already-verified templates in
scheduler/benchmarks/gen_scheduler_programs.py, just parameterized
with unique per-block labels (needed because all 6 blocks now live in
ONE file) and a unified per-block output address in ordinary RAM (so
correctness can be checked the same way regardless of which engine
actually produced the result -- a real hardware scheduler's output
contract should not depend on which engine served the request).

Usage:
    python3 scheduler/runtime/gen_dynamic_scheduler_demo.py
"""

import csv
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "sim", "programs", "scheduler")

# The fixed workload stream. Order/content chosen to exercise BOTH
# branches of the trained tree, including its one known
# misprediction (vecadd N=2 -- see docs/scheduler_pipeline.md) so the
# dynamic scheduler is shown faithfully reproducing the real model,
# flaw included, rather than a cherry-picked easy case.
STREAM = [
    ("vecadd", 1),
    ("vecadd", 2),
    ("vecadd", 4),
    ("dot", 1),
    ("dot", 4),
    ("matmul", 2),
]

MMIO_BASE = 0x30000000


def _load_ground_truth():
    """Read Phase 13/14's real measured cycles so oracle_demo.s can be
    generated from data, not hand-transcribed (this project's own
    repeated "trust the simulator/data, not hand math" lesson)."""
    truth = {}
    for fname in ("dataset.csv", "heldout_dataset.csv"):
        path = os.path.join(ROOT, "scheduler", "training", fname)
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["operation"], int(row["size_n"]))
                truth.setdefault(key, {})[row["engine"]] = int(row["cycles"])
    return truth


def oracle_engine(op, n, truth):
    cycles = truth[(op, n)]
    return "cpu" if cycles["cpu"] < cycles["accelerator"] else "accelerator"


# ---------------------------------------------------------------------
# Per-block CPU-path bodies (adapted from gen_scheduler_programs.py's
# gen_cpu_*, parameterized with a unique `tag` for labels and a single
# `outbase` every engine writes its final result to).
# ---------------------------------------------------------------------

def cpu_vecadd_body(n, tag, outbase):
    return f"""\
    li   x1, 0x1000
    li   x2, 0x2000
    li   x3, {outbase}
    li   x9, {n}

    li   x4, 0
{tag}_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x1, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, {tag}_setup_loop

    li   x4, 0
{tag}_compute_loop:
    slli x6, x4, 2
    add  x7, x1, x6
    lw   x5, 0(x7)
    add  x7, x2, x6
    lw   x8, 0(x7)
    add  x5, x5, x8
    add  x7, x3, x6
    sw   x5, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, {tag}_compute_loop
"""


def cpu_dot_body(n, tag, outbase):
    return f"""\
    li   x23, 0x1000
    li   x2,  0x2000
    li   x9,  {n}
    li   x20, 0

    li   x4, 0
{tag}_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x23, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x2, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, {tag}_setup_loop

    li   x4, 0
{tag}_compute_loop:
    slli x6, x4, 2
    add  x7, x23, x6
    lw   x11, 0(x7)
    add  x7, x2, x6
    lw   x12, 0(x7)
    jal  x1, mul32
    add  x20, x20, x10
    addi x4, x4, 1
    bne  x4, x9, {tag}_compute_loop

    li   x27, {outbase}
    sw   x20, 0(x27)
"""


def cpu_matmul_body(n, tag, outbase):
    shift = int(math.log2(n))
    assert 1 << shift == n, f"matmul N={n} must be a power of 2"
    return f"""\
    li   x23, 0x1000
    li   x2, 0x2000
    li   x3, {outbase}
    li   x9, {n}

    li   x13, 0
{tag}_setup_i:
    li   x14, 0
{tag}_setup_j:
    add  x15, x13, x14
    slli x16, x13, {shift}
    add  x16, x16, x14
    slli x16, x16, 2

    addi x17, x15, 1
    add  x18, x23, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, {tag}_setup_j
    addi x13, x13, 1
    bne  x13, x9, {tag}_setup_i

    li   x13, 0
{tag}_mm_i:
    li   x14, 0
{tag}_mm_j:
    li   x19, 0
    li   x21, 0
{tag}_mm_k:
    slli x16, x13, {shift}
    add  x16, x16, x21
    slli x16, x16, 2
    add  x18, x23, x16
    lw   x11, 0(x18)

    slli x16, x21, {shift}
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x2, x16
    lw   x12, 0(x18)

    jal  x1, mul32
    add  x19, x19, x10

    addi x21, x21, 1
    bne  x21, x9, {tag}_mm_k

    slli x16, x13, {shift}
    add  x16, x16, x14
    slli x16, x16, 2
    add  x18, x3, x16
    sw   x19, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, {tag}_mm_j
    addi x13, x13, 1
    bne  x13, x9, {tag}_mm_i
"""


# ---------------------------------------------------------------------
# Per-block accelerator-path bodies. Each ends by copying its real
# result out of the accelerator's memory-mapped VECOUT/RESULT window
# (rtl/accelerator/accelerator.sv's own register map, read with plain
# LW -- see that file's header comment) into `outbase`, the SAME
# unified location the CPU-path body writes to, so a later block
# reusing the accelerator's internal registers can never clobber an
# earlier block's already-recorded result.
# ---------------------------------------------------------------------

def accel_vecadd_body(n, tag, outbase):
    copies = "\n".join(
        f"    lw   x25, {4*i}(x24)\n    sw   x25, {4*i}(x26)" for i in range(n)
    )
    return f"""\
    li   x1, {MMIO_BASE}
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, {n}
    li   x4, 0
{tag}_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, {tag}_setup_loop

    sw   x9, 8(x1)
    accel.vecadd

{tag}_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, {tag}_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, {outbase}
{copies}
"""


def accel_dot_body(n, tag, outbase):
    return f"""\
    li   x1, {MMIO_BASE}
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, {n}
    li   x4, 0
{tag}_setup_loop:
    addi x5, x4, 1
    slli x6, x4, 2
    add  x7, x2, x6
    sw   x5, 0(x7)
    addi x8, x4, 2
    add  x7, x3, x6
    sw   x8, 0(x7)
    addi x4, x4, 1
    bne  x4, x9, {tag}_setup_loop

    sw   x9, 8(x1)
    accel.dot

{tag}_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, {tag}_wait_loop

    lw   x25, 12(x1)
    li   x26, {outbase}
    sw   x25, 0(x26)
"""


def accel_matmul_body(n, tag, outbase):
    shift = int(math.log2(n))
    assert 1 << shift == n, f"matmul N={n} must be a power of 2"
    copies = "\n".join(
        f"    lw   x25, {4*i}(x24)\n    sw   x25, {4*i}(x26)" for i in range(n * n)
    )
    return f"""\
    li   x1, {MMIO_BASE}
    li   x2, 0x1000
    li   x3, 0x2000
    add  x2, x1, x2
    add  x3, x1, x3

    li   x9, {n}

    li   x13, 0
{tag}_setup_i:
    li   x14, 0
{tag}_setup_j:
    add  x15, x13, x14
    slli x16, x13, {shift}
    add  x16, x16, x14
    slli x16, x16, 2

    addi x17, x15, 1
    add  x18, x2, x16
    sw   x17, 0(x18)

    addi x17, x15, 2
    add  x18, x3, x16
    sw   x17, 0(x18)

    addi x14, x14, 1
    bne  x14, x9, {tag}_setup_j
    addi x13, x13, 1
    bne  x13, x9, {tag}_setup_i

    sw   x9, 8(x1)
    accel.matmul

{tag}_wait_loop:
    accel.stat x6
    andi x7, x6, 1
    bne  x7, x0, {tag}_wait_loop

    li   x24, 0x3000
    add  x24, x1, x24
    li   x26, {outbase}
{copies}
"""


CPU_BODY = {"vecadd": cpu_vecadd_body, "dot": cpu_dot_body, "matmul": cpu_matmul_body}
ACCEL_BODY = {"vecadd": accel_vecadd_body, "dot": accel_dot_body, "matmul": accel_matmul_body}


def decision_block(op, n, tag):
    """Real RV32I instructions computing element_count/multiply_count
    and branching on them -- the runtime-evaluated equivalent of
    scheduler/models/features.py's extract_features() plus the fitted
    tree's decision boundary (element_count <= 2 and multiply_count ==
    0 -> cpu, else accelerator; see
    scheduler/training/train_scheduler.py's printed tree)."""
    if op == "matmul":
        return f"""\
    li   x11, {n}
    li   x12, {n}
    jal  x1, mul32
    mv   x24, x10
    mv   x11, x24
    li   x12, {n}
    jal  x1, mul32
    mv   x25, x10
    li   x26, 2
    blt  x26, x24, {tag}_accel
    bne  x25, x0, {tag}_accel
    j    {tag}_cpu
"""
    multiply_count = 0 if op == "vecadd" else n
    return f"""\
    li   x24, {n}
    li   x25, {multiply_count}
    li   x26, 2
    blt  x26, x24, {tag}_accel
    bne  x25, x0, {tag}_accel
    j    {tag}_cpu
"""


def block_asm(op, n, tag, outbase, mode, truth):
    if mode == "dynamic_scheduler":
        # Both the CPU-path and accelerator-path bodies for this SAME
        # block are compiled into the binary here (only one runs, per
        # the branch above, but both exist as code) -- each needs its
        # OWN label tag (not just `tag`) or their internal loop labels
        # (e.g. "{tag}_setup_loop") collide, corrupting the other
        # path's branch targets. Found by this phase's own correctness
        # testbench (sim/testbenches/tb_dynamic_scheduler_correctness.sv)
        # failing exactly the one block (vecadd N=2) whose dynamic
        # decision takes the CPU path while the accel body for the
        # same block is also present -- see CHANGELOG.md's Phase 15 entry.
        return (
            f"# -- block {tag}: {op} N={n} (runtime-computed decision) --\n"
            f"{decision_block(op, n, tag)}"
            f"{tag}_cpu:\n"
            f"{CPU_BODY[op](n, tag + 'c', outbase)}"
            f"    j    {tag}_done\n"
            f"{tag}_accel:\n"
            f"{ACCEL_BODY[op](n, tag + 'a', outbase)}"
            f"{tag}_done:\n"
        )
    if mode == "always_cpu":
        return f"# -- block {tag}: {op} N={n} (forced cpu) --\n{CPU_BODY[op](n, tag, outbase)}"
    if mode == "always_accel":
        return f"# -- block {tag}: {op} N={n} (forced accelerator) --\n{ACCEL_BODY[op](n, tag, outbase)}"
    if mode == "oracle":
        engine = oracle_engine(op, n, truth)
        body_fn = CPU_BODY[op] if engine == "cpu" else ACCEL_BODY[op]
        return f"# -- block {tag}: {op} N={n} (oracle: {engine}, from real measured data) --\n{body_fn(n, tag, outbase)}"
    raise ValueError(mode)


MUL32 = """\
mul32:
    li   x10, 0
    mv   x5, x11
    mv   x6, x12
mul32_loop:
    beq  x6, x0, mul32_done
    andi x7, x6, 1
    beq  x7, x0, mul32_skip
    add  x10, x10, x5
mul32_skip:
    slli x5, x5, 1
    srli x6, x6, 1
    j    mul32_loop
mul32_done:
    ret
"""

HEADER = {
    "dynamic_scheduler": "# dynamic_scheduler_demo.s -- Phase 15: ONE program, 6 workloads,\n"
               "# engine chosen at RUNTIME per workload by real RV32I instructions\n"
               "# evaluating the trained scheduler's decision boundary -- see\n"
               "# scheduler/runtime/gen_dynamic_scheduler_demo.py and\n"
               "# docs/dynamic_scheduling.md.\n",
    "always_cpu": "# always_cpu_demo.s -- Phase 15 baseline: same 6-workload stream,\n"
                  "# every block forced to the CPU-only path (no decision logic).\n",
    "always_accel": "# always_accel_demo.s -- Phase 15 baseline: same 6-workload stream,\n"
                     "# every block forced to the accelerator path (no decision logic).\n",
    "oracle": "# oracle_demo.s -- Phase 15 baseline: same 6-workload stream, every\n"
              "# block forced to whichever engine Phase 13/14's real measured data\n"
              "# says is actually faster for that exact workload -- the best any\n"
              "# per-workload-static dispatcher could possibly do.\n",
}


def gen_program(mode, truth):
    lines = [HEADER[mode], "\n    li   x29, 0x20000000\n    li   x30, 0xDEADBEEF\n\n"]
    for i, (op, n) in enumerate(STREAM):
        tag = f"blk{i}"
        outbase = f"0x{0x3000 + i * 0x80:04x}"
        lines.append(block_asm(op, n, tag, outbase, mode, truth))
        lines.append("\n")
    lines.append("    sw   x30, 0(x29)\ndone:\n    j    done\n\n")
    lines.append(MUL32)
    return "".join(lines)


def main():
    truth = _load_ground_truth()
    os.makedirs(OUT_DIR, exist_ok=True)
    written = []
    for mode in ("dynamic_scheduler", "always_cpu", "always_accel", "oracle"):
        path = os.path.join(OUT_DIR, f"{mode}_demo.s")
        with open(path, "w") as f:
            f.write(gen_program(mode, truth))
        written.append(path)
    print(f"Wrote {len(written)} program(s) to {OUT_DIR}")
    for p in written:
        print(f"  {os.path.relpath(p, ROOT)}")


if __name__ == "__main__":
    main()
