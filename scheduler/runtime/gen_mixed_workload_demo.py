#!/usr/bin/env python3
"""
gen_mixed_workload_demo.py -- Phase 16: the same runtime-computed
dynamic-scheduling machinery Phase 15 built
(scheduler/runtime/gen_dynamic_scheduler_demo.py), applied to a
larger, more varied "mixed heterogeneous" workload stream -- 12
workloads spanning all three operations at MEDIUM/LARGE sizes (plus
the two smallest vecadd sizes, to keep the known crossover story in
view), rather than Phase 15's small 6-workload demo. Reuses that
module's per-block body generators, decision logic, and mul32
subroutine directly (imported, not copy-pasted) so any future fix to
the underlying machinery (like Phase 15's label-collision bug) applies
here too without drifting out of sync.

Why these particular 12 workloads: Phase 15's finding (dynamic loses
to always-accelerator for a small stream) raised an obvious question --
does the runtime decision's fixed per-block overhead matter less once
each block is doing more real work? This stream is built specifically
to test that, using sizes 4-32x larger than Phase 15's on average
(`vecadd`/`dot` at N=4,8,16,32; `matmul` at N=2,4) while keeping
`vecadd` N=1 and N=2 in the mix once each so the model's one known
misprediction (see docs/scheduler_pipeline.md) still has a chance to
matter. `matmul N=8` (32885 CPU cycles standalone) is deliberately
EXCLUDED here -- including it would let one outlier workload dominate
the whole stream's total so completely that every program's totals
would look nearly identical, defeating the point of a varied
comparison; docs/mixed_workloads.md discusses this choice explicitly
rather than silently picking numbers that happen to produce a tidy
result.

Usage:
    python3 scheduler/runtime/gen_mixed_workload_demo.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "sim", "programs", "scheduler")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_dynamic_scheduler_demo import (  # noqa: E402
    block_asm, MUL32, _load_ground_truth,
)

# 12 workloads: vecadd N=1,2 (the known crossover neighborhood) plus
# vecadd/dot/matmul at medium-to-large sizes, interleaved by operation
# rather than grouped, to genuinely exercise engine-switching each
# block rather than settling into one long run of the same choice.
STREAM = [
    ("vecadd", 1),
    ("vecadd", 2),
    ("dot", 4),
    ("matmul", 2),
    ("vecadd", 4),
    ("dot", 8),
    ("vecadd", 8),
    ("matmul", 4),
    ("dot", 16),
    ("vecadd", 16),
    ("dot", 32),
    ("vecadd", 32),
]

OUTBASE_START = 0x3000
OUTBASE_STRIDE = 0x100  # 64 words/block -- covers matmul N=4's 16-word output

MODE_TO_FILENAME = {
    "dynamic_scheduler": "mixed_dynamic_demo.s",
    "always_cpu": "mixed_always_cpu_demo.s",
    "always_accel": "mixed_always_accel_demo.s",
    "oracle": "mixed_oracle_demo.s",
}

HEADER = {
    "dynamic_scheduler": "# mixed_dynamic_demo.s -- Phase 16: 12-workload mixed\n"
                          "# heterogeneous stream, engine chosen at RUNTIME per\n"
                          "# workload -- see scheduler/runtime/gen_mixed_workload_demo.py\n"
                          "# and docs/mixed_workloads.md.\n",
    "always_cpu": "# mixed_always_cpu_demo.s -- Phase 16 baseline: same 12-workload\n"
                  "# stream, every block forced to the CPU-only path.\n",
    "always_accel": "# mixed_always_accel_demo.s -- Phase 16 baseline: same\n"
                     "# 12-workload stream, every block forced to the accelerator path.\n",
    "oracle": "# mixed_oracle_demo.s -- Phase 16 baseline: same 12-workload\n"
              "# stream, every block forced to whichever engine Phase 13/14's\n"
              "# real measured data says is actually faster.\n",
}


def gen_program(mode, truth):
    lines = [HEADER[mode], "\n    li   x29, 0x20000000\n    li   x30, 0xDEADBEEF\n\n"]
    for i, (op, n) in enumerate(STREAM):
        tag = f"m{i}"
        outbase = f"0x{OUTBASE_START + i * OUTBASE_STRIDE:04x}"
        lines.append(block_asm(op, n, tag, outbase, mode, truth))
        lines.append("\n")
    lines.append("    sw   x30, 0(x29)\ndone:\n    j    done\n\n")
    lines.append(MUL32)
    return "".join(lines)


def main():
    truth = _load_ground_truth()
    os.makedirs(OUT_DIR, exist_ok=True)
    written = []
    for mode, fname in MODE_TO_FILENAME.items():
        path = os.path.join(OUT_DIR, fname)
        with open(path, "w") as f:
            f.write(gen_program(mode, truth))
        written.append(path)
    print(f"Wrote {len(written)} program(s) to {OUT_DIR}")
    for p in written:
        print(f"  {os.path.relpath(p, ROOT)}")


if __name__ == "__main__":
    main()
