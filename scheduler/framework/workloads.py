"""
workloads.py -- the catalogue of task streams the co-scheduler is
evaluated on. A task is still an (operation, size) tuple in Phase 2; the
typed workload IR is Phase 3 (docs/framework/EXTENSIBILITY_ROADMAP.md).
"""

from .operations import PHASE15_STREAM, PHASE16_STREAM

FULL_STREAM = ([("vecadd", n) for n in (1, 2, 3, 4, 6, 8, 12, 16, 32, 64)]
               + [("dot", n) for n in (1, 2, 3, 4, 6, 8, 12, 16, 32, 64)]
               + [("matmul", n) for n in (1, 2, 4, 8)])

STREAMS = {
    "phase15": list(PHASE15_STREAM),
    "phase16": list(PHASE16_STREAM),
    "full24": FULL_STREAM,
}
