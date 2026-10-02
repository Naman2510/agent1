#!/usr/bin/env python3
"""
gen_dynamic_lean_demo.py -- post-v1: a cheaper runtime decision for
the v2 scheduler model, on Phase 15's and Phase 16's workload streams.

results/dynamic_v2_report.md measured that a runtime scheduler making
every decision correctly still loses to always-accelerator, because
deciding costs ~18-19 cycles per workload while the oracle's whole
advantage is 10 cycles per stream. This generator attacks the decision
cost, without changing the decisions themselves:

1. Fold a decision only where it is provably constant. For each
   operation, the v2 rule (extracted from the fitted tree by
   gen_dynamic_v2_demo.extract_ec_threshold, not hand-transcribed) is
   evaluated over that operation's ENTIRE legal size range on this
   accelerator -- N = 1..MAX_LEN for vecadd/dot, N = 1..MAX_DIM for
   matmul, with both bounds parsed from rtl/accelerator/accelerator.sv
   itself. If every legal N gives the same engine, no runtime check is
   emitted for that operation: the check could never change the
   outcome. For the v2 model this folds dot and matmul to the
   accelerator (their multiply_count is >= 1 for every legal N, so the
   rule's `multiply_count == 0` term can never hold), which also
   removes matmul's two runtime mul32 calls.
2. Where the decision really does depend on N (vecadd, for v2), keep a
   real runtime comparison, on the CPU: the request's size is compared
   against the threshold, which is loaded once into x28 at program
   start instead of per block. The size itself is the `li x9, N` that
   both engine bodies execute anyway, hoisted above the branch (see
   hoist_size_load), so the only instruction the decision adds to a
   request is the compare-and-branch itself. Operations the rule can't reduce to a
   single compare against size fall back to Phase 15's full decision
   block, unchanged.
3. Lay out the common path as fall-through. The accelerator body
   follows the compare directly (a not-taken branch, no pipeline
   flush); the CPU body for that block lives out of line after the
   program's final loop and jumps back.

For every workload in both streams, the engine this program will pick
is cross-checked against the v2 model's own predict() before any
assembly is written.

Writes:
  sim/programs/scheduler/dynamic_lean_demo.s        (Phase 15's stream)
  sim/programs/scheduler/mixed_dynamic_lean_demo.s  (Phase 16's stream)

Usage (needs scikit-learn to unpickle the model):
    .venv/bin/python3 scheduler/runtime/gen_dynamic_lean_demo.py
"""

import os
import pickle
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "sim", "programs", "scheduler")
MODEL_PATH = os.path.join(ROOT, "scheduler", "models", "scheduler_tree_v2.pkl")
ACCEL_RTL = os.path.join(ROOT, "rtl", "accelerator", "accelerator.sv")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scheduler", "models"))
from gen_dynamic_scheduler_demo import (  # noqa: E402
    CPU_BODY, ACCEL_BODY, MUL32, decision_block, STREAM as PHASE15_STREAM,
)
from gen_mixed_workload_demo import (  # noqa: E402
    STREAM as PHASE16_STREAM, OUTBASE_START as P16_START, OUTBASE_STRIDE as P16_STRIDE,
)
from gen_dynamic_v2_demo import extract_ec_threshold  # noqa: E402
from features import (  # noqa: E402
    ENGINE_TO_LABEL, LABEL_TO_ENGINE, element_count, multiply_count, extract_features,
)

THRESH_REG = "x28"  # unused by every body template in gen_dynamic_scheduler_demo.py
SIZE_REG = "x9"     # the register every body template loads N into anyway


def hoist_size_load(body, n):
    """Remove the body's own `li x9, N` so the block can load N once,
    before the decision, and compare against it directly -- the same
    load the always-accelerator and oracle programs execute, not an
    extra one. Asserts it is safe: exactly one such load, and no earlier
    instruction in the body writes x9."""
    lines = body.splitlines(keepends=True)
    hits = [i for i, l in enumerate(lines)
            if re.fullmatch(rf"\s*li\s+{SIZE_REG},\s*{n}\s*", l)]
    if len(hits) != 1:
        raise ValueError(f"expected exactly one `li {SIZE_REG}, {n}` in body, found {len(hits)}")
    for l in lines[:hits[0]]:
        if re.match(rf"\s*[a-z.]+\s+{SIZE_REG}\s*,", l):
            raise ValueError(f"body writes {SIZE_REG} before its size load: {l.strip()}")
    return "".join(lines[:hits[0]] + lines[hits[0] + 1:])


def accel_bounds():
    """MAX_DIM / MAX_LEN as declared in the accelerator RTL (MAX_LEN may
    be written in terms of MAX_DIM)."""
    src = open(ACCEL_RTL).read()
    dim = int(re.search(r"parameter\s+int\s+MAX_DIM\s*=\s*(\d+)", src).group(1))
    len_expr = re.search(r"parameter\s+int\s+MAX_LEN\s*=\s*([^,\n/]+)", src).group(1).strip()
    if not re.fullmatch(r"[\sMAX_DIM*+\d()]+", len_expr):
        raise ValueError(f"unexpected MAX_LEN expression: {len_expr!r}")
    return dim, int(eval(len_expr, {"__builtins__": {}}, {"MAX_DIM": dim}))


def rule_engine(op, n, threshold):
    cpu = element_count(op, n) <= threshold and multiply_count(op, n) == 0
    return "cpu" if cpu else "accelerator"


def plan_ops(threshold, max_dim, max_len):
    """Return {op: ("fold", engine) | ("compare_n",) | ("full",)}."""
    domains = {"vecadd": range(1, max_len + 1), "dot": range(1, max_len + 1),
               "matmul": range(1, max_dim + 1)}
    plan = {}
    for op, dom in domains.items():
        engines = {rule_engine(op, n, threshold) for n in dom}
        if len(engines) == 1:
            plan[op] = ("fold", engines.pop())
        elif all(multiply_count(op, n) == 0 and element_count(op, n) == n for n in dom):
            # rule reduces to `N <= threshold` on this op's whole domain
            plan[op] = ("compare_n",)
        else:
            plan[op] = ("full",)
    return plan


def gen_program(stream, header, tag_prefix, outbase_start, outbase_stride, threshold, plan):
    main, cold = [header, f"\n    li   x29, 0x20000000\n    li   x30, 0xDEADBEEF\n"
                          f"    li   {THRESH_REG}, {threshold}\n\n"], []
    for i, (op, n) in enumerate(stream):
        tag, outbase = f"{tag_prefix}{i}", f"0x{outbase_start + i * outbase_stride:04x}"
        kind = plan[op]
        if kind[0] == "fold":
            body = CPU_BODY[op] if kind[1] == "cpu" else ACCEL_BODY[op]
            main.append(f"# -- block {tag}: {op} N={n} (folded: {kind[1]} for every legal N) --\n"
                        f"{body(n, tag, outbase)}\n")
        elif kind[0] == "compare_n":
            main.append(f"# -- block {tag}: {op} N={n} (runtime compare: cpu iff N <= threshold) --\n"
                        f"    li   {SIZE_REG}, {n}\n"
                        f"    bge  {THRESH_REG}, {SIZE_REG}, {tag}_cpu\n"
                        f"{hoist_size_load(ACCEL_BODY[op](n, tag + 'a', outbase), n)}"
                        f"{tag}_done:\n\n")
            cold.append(f"# -- cold path for block {tag} --\n{tag}_cpu:\n"
                        f"{hoist_size_load(CPU_BODY[op](n, tag + 'c', outbase), n)}"
                        f"    j    {tag}_done\n\n")
        else:  # full: Phase 15's decision block, inline, unchanged
            main.append(f"# -- block {tag}: {op} N={n} (full runtime decision) --\n"
                        f"{decision_block(op, n, tag, threshold)}"
                        f"{tag}_cpu:\n{CPU_BODY[op](n, tag + 'c', outbase)}"
                        f"    j    {tag}_done\n"
                        f"{tag}_accel:\n{ACCEL_BODY[op](n, tag + 'a', outbase)}"
                        f"{tag}_done:\n\n")
    main.append("    sw   x30, 0(x29)\ndone:\n    j    done\n\n")
    return "".join(main + cold) + MUL32


def main():
    with open(MODEL_PATH, "rb") as f:
        clf = pickle.load(f)
    threshold = extract_ec_threshold(clf)
    max_dim, max_len = accel_bounds()
    plan = plan_ops(threshold, max_dim, max_len)
    print(f"v2 boundary: cpu iff element_count <= {threshold} and multiply_count == 0")
    print(f"accelerator bounds from RTL: MAX_DIM={max_dim}, MAX_LEN={max_len}")
    for op, kind in plan.items():
        print(f"  {op:6s}: {' '.join(kind)}")

    for op, n in sorted(set(PHASE15_STREAM) | set(PHASE16_STREAM)):
        planned = plan[op][1] if plan[op][0] == "fold" else rule_engine(op, n, threshold)
        model = LABEL_TO_ENGINE[int(clf.predict([extract_features(op, n)])[0])]
        if planned != model:
            raise SystemExit(f"program/model disagree on {op} N={n}: {planned} vs {model}")
    print("  program's engine choice == v2 model's predict() on every workload in both streams")

    for fname, stream, prefix, start, stride, desc in [
        ("dynamic_lean_demo.s", PHASE15_STREAM, "l", 0x3000, 0x80, "Phase 15's 6-workload stream"),
        ("mixed_dynamic_lean_demo.s", PHASE16_STREAM, "k", P16_START, P16_STRIDE,
         "Phase 16's 12-workload stream"),
    ]:
        header = (f"# {fname} -- {desc}, v2 model, lean runtime decision\n"
                  f"# (generated by scheduler/runtime/gen_dynamic_lean_demo.py -- see its\n"
                  f"# docstring for what is folded, what is still decided at runtime, and why).\n")
        path = os.path.join(OUT_DIR, fname)
        with open(path, "w") as f:
            f.write(gen_program(stream, header, prefix, start, stride, threshold, plan))
        print(f"Wrote {os.path.relpath(path, ROOT)}")


if __name__ == "__main__":
    main()
