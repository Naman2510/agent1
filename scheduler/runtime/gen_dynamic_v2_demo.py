#!/usr/bin/env python3
"""
gen_dynamic_v2_demo.py -- post-v1: put the v2 scheduler model
(scheduler/models/scheduler_tree_v2.pkl, docs/scheduler_v2.md) into
the SAME runtime, on-CPU decision machinery Phase 15/16 built, and
re-run both of their workload streams with it.

Phase 15's generator hand-transcribed Phase 13's fitted boundary
("element_count <= 2 and multiply_count == 0 -> cpu") into RISC-V
assembly. This script does not hand-transcribe anything: it loads the
fitted v2 tree, walks it, and derives the boundary from the tree's own
split thresholds -- refusing (with an error, not a silent fallback) if
the tree's shape is anything other than what the runtime decision
template can express exactly: a single cpu-predicting leaf reached
only through upper bounds on element_count and multiply_count. It then
cross-checks, for every workload in both streams, that the
assembly-level rule and the Python model (sklearn's own predict())
agree, so the program can't silently disagree with the model it claims
to embody.

Writes:
  sim/programs/scheduler/dynamic_v2_demo.s        (Phase 15's 6-workload stream)
  sim/programs/scheduler/mixed_dynamic_v2_demo.s  (Phase 16's 12-workload stream)

Usage (needs scikit-learn to unpickle the model):
    .venv/bin/python3 scheduler/runtime/gen_dynamic_v2_demo.py
"""

import math
import os
import pickle
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "sim", "programs", "scheduler")
MODEL_PATH = os.path.join(ROOT, "scheduler", "models", "scheduler_tree_v2.pkl")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scheduler", "models"))
from gen_dynamic_scheduler_demo import (  # noqa: E402
    block_asm, MUL32, _load_ground_truth, STREAM as PHASE15_STREAM,
)
from gen_mixed_workload_demo import (  # noqa: E402
    STREAM as PHASE16_STREAM, OUTBASE_START as P16_START, OUTBASE_STRIDE as P16_STRIDE,
)
from features import FEATURE_NAMES, ENGINE_TO_LABEL, extract_features  # noqa: E402

CPU_LABEL = ENGINE_TO_LABEL["cpu"]
EC = FEATURE_NAMES.index("element_count")
MC = FEATURE_NAMES.index("multiply_count")


def extract_ec_threshold(clf):
    """Return the integer T such that the tree predicts cpu exactly
    when element_count <= T and multiply_count == 0 (over the
    non-negative integer features this project produces). Raise if the
    tree can't be expressed that way."""
    t = clf.tree_
    cpu_paths = []

    def walk(node, bounds):
        if t.children_left[node] == t.children_right[node]:  # leaf
            if int(t.value[node][0].argmax()) == list(clf.classes_).index(CPU_LABEL):
                cpu_paths.append(bounds)
            return
        f, thr = t.feature[node], t.threshold[node]
        walk(t.children_left[node], bounds + [(f, "<=", thr)])
        walk(t.children_right[node], bounds + [(f, ">", thr)])

    walk(0, [])
    if len(cpu_paths) != 1:
        raise ValueError(f"expected exactly one cpu leaf, found {len(cpu_paths)}")
    ec_ub, mc_ub = math.inf, math.inf
    for f, op, thr in cpu_paths[0]:
        if op != "<=" or f not in (EC, MC):
            raise ValueError(f"cpu path uses unsupported condition "
                             f"{FEATURE_NAMES[f]} {op} {thr}")
        if f == EC:
            ec_ub = min(ec_ub, thr)
        else:
            mc_ub = min(mc_ub, thr)
    if not (0 <= mc_ub < 1):
        raise ValueError(f"cpu path's multiply_count bound {mc_ub} isn't '== 0'")
    if math.isinf(ec_ub):
        raise ValueError("cpu path has no element_count bound")
    return math.floor(ec_ub)


def gen_program(stream, header, tag_prefix, outbase_start, outbase_stride, threshold, truth):
    lines = [header, "\n    li   x29, 0x20000000\n    li   x30, 0xDEADBEEF\n\n"]
    for i, (op, n) in enumerate(stream):
        outbase = f"0x{outbase_start + i * outbase_stride:04x}"
        lines.append(block_asm(op, n, f"{tag_prefix}{i}", outbase, "dynamic_scheduler",
                               truth, ec_threshold=threshold))
        lines.append("\n")
    lines.append("    sw   x30, 0(x29)\ndone:\n    j    done\n\n")
    lines.append(MUL32)
    return "".join(lines)


def main():
    with open(MODEL_PATH, "rb") as f:
        clf = pickle.load(f)
    threshold = extract_ec_threshold(clf)
    print(f"v2 tree boundary: cpu iff element_count <= {threshold} and multiply_count == 0")

    for op, n in sorted(set(PHASE15_STREAM) | set(PHASE16_STREAM)):
        feats = extract_features(op, n)
        rule_cpu = feats[EC] <= threshold and feats[MC] == 0
        model_cpu = int(clf.predict([feats])[0]) == CPU_LABEL
        if rule_cpu != model_cpu:
            raise SystemExit(f"rule/model disagree on {op} N={n}: rule_cpu={rule_cpu} "
                             f"model_cpu={model_cpu}")
        print(f"  {op:6s} N={n:<3d} -> {'cpu' if rule_cpu else 'accelerator'} (rule == model)")

    truth = _load_ground_truth()
    programs = [
        ("dynamic_v2_demo.s", PHASE15_STREAM, "v", 0x3000, 0x80,
         "# dynamic_v2_demo.s -- Phase 15's 6-workload stream, runtime decision\n"
         "# boundary extracted from scheduler/models/scheduler_tree_v2.pkl by\n"
         "# scheduler/runtime/gen_dynamic_v2_demo.py.\n"),
        ("mixed_dynamic_v2_demo.s", PHASE16_STREAM, "w", P16_START, P16_STRIDE,
         "# mixed_dynamic_v2_demo.s -- Phase 16's 12-workload stream, runtime\n"
         "# decision boundary extracted from scheduler/models/scheduler_tree_v2.pkl\n"
         "# by scheduler/runtime/gen_dynamic_v2_demo.py.\n"),
    ]
    for fname, stream, prefix, start, stride, header in programs:
        path = os.path.join(OUT_DIR, fname)
        with open(path, "w") as f:
            f.write(gen_program(stream, header, prefix, start, stride, threshold, truth))
        print(f"Wrote {os.path.relpath(path, ROOT)}")


if __name__ == "__main__":
    main()
