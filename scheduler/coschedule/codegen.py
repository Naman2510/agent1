"""
codegen.py -- streams, output layout, expected values, and RISC-V code
generation for the concurrent CPU + accelerator co-scheduler
(docs/coschedule.md).

Every per-task code body is reused unchanged from
scheduler/runtime/gen_dynamic_scheduler_demo.py (CPU_BODY / ACCEL_BODY,
already correctness-verified in Phases 15/16). On the ENABLE_MUL core,
CPU dot/matmul bodies get the same single substitution
scheduler/benchmarks/gen_mul_programs.py makes (`jal x1, mul32` ->
`mul x10, x11, x12`). The only new code construct is the *window*: an
accelerator body is split at its poll loop into a LAUNCH half (write
operands, LEN, START) and a WAIT half (poll, copy result out). Whole CPU
tasks are placed between the two, so they run while the accelerator
computes. The CPU bodies reuse x1, so a window ends by reloading x1 with
the accelerator's MMIO base, which the WAIT half's copy-out needs.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scheduler", "runtime"))
from gen_dynamic_scheduler_demo import CPU_BODY, ACCEL_BODY, MUL32  # noqa: E402
from gen_dynamic_scheduler_demo import STREAM as PHASE15_STREAM  # noqa: E402
from gen_mixed_workload_demo import STREAM as PHASE16_STREAM  # noqa: E402

FULL_STREAM = ([("vecadd", n) for n in (1, 2, 3, 4, 6, 8, 12, 16, 32, 64)]
               + [("dot", n) for n in (1, 2, 3, 4, 6, 8, 12, 16, 32, 64)]
               + [("matmul", n) for n in (1, 2, 4, 8)])

STREAMS = {
    "phase15": list(PHASE15_STREAM),
    "phase16": list(PHASE16_STREAM),
    "full24": FULL_STREAM,
}

MMIO_BASE = 0x30000000
OUT_START = 0x3000        # byte address of the first task's output
IMEM_WORDS = 4096         # instruction-memory depth these programs are built for


# ---------------------------------------------------------------------------
# Output layout + expected values
# ---------------------------------------------------------------------------

def out_words(op, n):
    return n * n if op == "matmul" else (1 if op == "dot" else n)


def layout(stream):
    """Packed per-task output base addresses (bytes), in stream order."""
    bases, addr = [], OUT_START
    for op, n in stream:
        bases.append(addr)
        addr += 4 * out_words(op, n)
    if addr > 4 * 4096:
        raise ValueError("outputs exceed the 4096-word RAM")
    return bases


def reference(op, n):
    """Python reference result -- the same operand patterns every kernel uses."""
    if op == "vecadd":
        return [(i + 1) + (i + 2) for i in range(n)]
    if op == "dot":
        return [sum((i + 1) * (i + 2) for i in range(n)) & 0xFFFFFFFF]
    A = [[i + j + 1 for j in range(n)] for i in range(n)]
    B = [[i + j + 2 for j in range(n)] for i in range(n)]
    return [sum(A[i][k] * B[k][j] for k in range(n)) & 0xFFFFFFFF
            for i in range(n) for j in range(n)]


def expected_words(stream):
    """[(ram_word_index, value)] for every output word of every task."""
    out = []
    for (op, n), base in zip(stream, layout(stream)):
        for i, v in enumerate(reference(op, n)):
            out.append((base // 4 + i, v))
    return out


def write_expect_file(stream, path):
    words = expected_words(stream)
    with open(path, "w") as f:
        for idx, v in words:
            f.write(f"{idx:08x}{v:08x}\n")
    return len(words)


# ---------------------------------------------------------------------------
# Per-task code
# ---------------------------------------------------------------------------

def cpu_body(op, n, tag, outbase, mul):
    body = CPU_BODY[op](n, tag, outbase)
    if mul and op != "vecadd":
        call = "    jal  x1, mul32\n"
        if body.count(call) != 1:
            raise ValueError(f"{op} N={n}: expected one mul32 call")
        body = body.replace(call, "    mul  x10, x11, x12\n")
    return body


def accel_split(op, n, tag, outbase):
    """(launch, wait) halves of the verified accelerator body."""
    body = ACCEL_BODY[op](n, tag, outbase)
    marker = f"{tag}_wait_loop:\n"
    if body.count(marker) != 1:
        raise ValueError(f"{op} N={n}: expected one poll loop")
    i = body.index(marker)
    launch, wait = body[:i], body[i:]
    if f"accel.{op}" not in launch:
        raise ValueError(f"{op} N={n}: START not in launch half")
    return launch, wait


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
#
# A plan is a list, one entry per task in stream order:
#   ("acc",)     -- run on the accelerator, waiting for it (serial)
#   ("cpu",)     -- run on the CPU, serially
#   ("win", j)   -- run on the CPU inside task j's accelerator busy window
#                   (task j must be "acc")

def validate(plan):
    for i, p in enumerate(plan):
        if p[0] == "win" and (p[1] == i or plan[p[1]][0] != "acc"):
            raise ValueError(f"task {i}: window host {p[1]} is not an accelerator task")


def program(stream, plan, mul, title):
    validate(plan)
    bases = layout(stream)
    lines = [f"# {title}\n# generated by scheduler/coschedule/codegen.py -- see docs/coschedule.md\n\n",
             "    li   x29, 0x20000000\n    li   x30, 0xDEADBEEF\n\n"]
    for i, ((op, n), place) in enumerate(zip(stream, plan)):
        tag, ob = f"t{i}", f"0x{bases[i]:04x}"
        if place[0] == "cpu":
            lines.append(f"# -- task {i}: {op} N={n} on CPU --\n{cpu_body(op, n, tag, ob, mul)}\n")
        elif place[0] == "acc":
            guests = [j for j, p in enumerate(plan) if p == ("win", i)]
            launch, wait = accel_split(op, n, tag, ob)
            lines.append(f"# -- task {i}: {op} N={n} on accelerator"
                         + (f", window hosts tasks {guests}" if guests else "") + " --\n")
            lines.append(launch)
            for j in guests:
                gop, gn = stream[j]
                lines.append(f"# ---- window: task {j}: {gop} N={gn} on CPU, while task {i} computes ----\n"
                             f"{cpu_body(gop, gn, f't{j}', f'0x{bases[j]:04x}', mul)}")
            if guests:
                lines.append(f"    li   x1, 0x{MMIO_BASE:08x}   # CPU tasks reused x1; restore MMIO base\n")
            lines.append(wait + "\n")
        # ("win", j) tasks are emitted inside their host's window
    lines.append("    sw   x30, 0(x29)\ndone:\n    j    done\n\n")
    lines.append(MUL32)
    return "".join(lines)


def serial_plan(stream, engines):
    return [("acc",) if e == "accelerator" else ("cpu",) for e in engines]
