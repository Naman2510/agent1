"""
operations.py -- the operation registry.

One entry per operation the existing hardware actually supports (vecadd,
dot, matmul; rtl/accelerator/accelerator.sv). Each entry bundles what was
previously spread over three places (D3 in docs/framework/TECHNICAL_DEBT.md):
the CPU body, the accelerator body, the output size and the reference
result.

The bodies themselves stay where they were verified, in
scheduler/runtime/gen_dynamic_scheduler_demo.py (Phases 15/16 use them
too). This module is the only place in the framework that imports them.

Operands are still the synthetic in-program pattern (A[i] = i+1,
B[i] = i+2; matrices A[i][j] = i+j+1, B[i][j] = i+j+2). Data-carrying tasks
are Phase 3 work (D1).
"""

import os
import sys
from dataclasses import dataclass
from typing import Callable, List

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scheduler", "runtime"))
from gen_dynamic_scheduler_demo import CPU_BODY, ACCEL_BODY, MUL32  # noqa: E402,F401
from gen_dynamic_scheduler_demo import STREAM as PHASE15_STREAM  # noqa: E402,F401
from gen_mixed_workload_demo import STREAM as PHASE16_STREAM  # noqa: E402,F401

MASK32 = 0xFFFFFFFF


def _ref_vecadd(n):
    return [(i + 1) + (i + 2) for i in range(n)]


def _ref_dot(n):
    return [sum((i + 1) * (i + 2) for i in range(n)) & MASK32]


def _ref_matmul(n):
    A = [[i + j + 1 for j in range(n)] for i in range(n)]
    B = [[i + j + 2 for j in range(n)] for i in range(n)]
    return [sum(A[i][k] * B[k][j] for k in range(n)) & MASK32
            for i in range(n) for j in range(n)]


@dataclass(frozen=True)
class Operation:
    name: str
    cpu_body: Callable[[int, str, str], str]     # (n, tag, outbase) -> asm
    accel_body: Callable[[int, str, str], str]   # (n, tag, outbase) -> asm
    out_words: Callable[[int], int]              # output words for size n
    reference: Callable[[int], List[int]]        # expected output, synthetic operands
    cpu_uses_mul32: bool                         # CPU body calls mul32 exactly once


OPERATIONS = {
    "vecadd": Operation("vecadd", CPU_BODY["vecadd"], ACCEL_BODY["vecadd"],
                        lambda n: n, _ref_vecadd, False),
    "dot": Operation("dot", CPU_BODY["dot"], ACCEL_BODY["dot"],
                     lambda n: 1, _ref_dot, True),
    "matmul": Operation("matmul", CPU_BODY["matmul"], ACCEL_BODY["matmul"],
                        lambda n: n * n, _ref_matmul, True),
}


def get(op):
    try:
        return OPERATIONS[op]
    except KeyError:
        raise ValueError(f"unsupported operation {op!r}; supported: {sorted(OPERATIONS)}") from None


def out_words(op, n):
    return get(op).out_words(n)


def reference(op, n):
    """Python reference result: the same operand patterns every kernel uses."""
    return get(op).reference(n)
