#!/usr/bin/env python3
"""
train_scheduler.py -- Phase 13: fit a small, interpretable classifier
on scheduler/training/dataset.csv that predicts which engine (cpu vs
accelerator) will finish a given workload (operation, size_n) faster,
using ONLY real measured cycle counts as ground truth.

This is NOT a per-(operation,size,engine) row classifier -- it is a
per-WORKLOAD classifier. dataset.csv has one row per (operation, size,
engine) pair (22 rows: 11 workloads x 2 engines each); this script
first PIVOTS that into 11 workload rows, each labeled with whichever
engine actually measured fewer cycles for that workload. That 11-row
table -- not 22 -- is the model's real training set, and is written
out as scheduler/training/workload_labels.csv for inspection.

11 samples is a genuinely tiny dataset, and 10 of those 11 samples
share the same label ("accelerator" wins) -- only vecadd N=1 is a
measured CPU win. This script does not pretend otherwise: it reports
leave-one-out cross-validated accuracy (the only honest way to
estimate generalization with this few samples) AND prints the
imbalance plainly, rather than quoting a single train-set accuracy
number that a 1-node tree could trivially reach by always predicting
"accelerator". See docs/scheduler.md for the full discussion of what
this model can and cannot be trusted to know (in particular: it has
never seen a vecadd size between N=1 and N=4, so it cannot know the
REAL crossover point -- only that one exists somewhere in that gap).

Usage:
    .venv/bin/python3 scheduler/training/train_scheduler.py
"""

import csv
import os
import pickle
import sys

import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.model_selection import LeaveOneOut, cross_val_predict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scheduler", "models"))
from features import (  # noqa: E402
    FEATURE_NAMES, ENGINE_TO_LABEL, LABEL_TO_ENGINE, extract_features,
)

DATASET_CSV = os.path.join(ROOT, "scheduler", "training", "dataset.csv")
LABELS_CSV = os.path.join(ROOT, "scheduler", "training", "workload_labels.csv")
MODEL_PATH = os.path.join(ROOT, "scheduler", "models", "scheduler_tree.pkl")
REPORT_PATH = os.path.join(ROOT, "results", "scheduler_report.md")


def load_workloads():
    """Read dataset.csv (22 rows, one per operation/size/engine) and
    pivot into one row per (operation, size_n) workload, each carrying
    both engines' measured cycles and the faster engine's name."""
    by_key = {}
    with open(DATASET_CSV, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["operation"], int(row["size_n"]))
            by_key.setdefault(key, {})[row["engine"]] = int(row["cycles"])

    workloads = []
    for (op, n), cycles in sorted(by_key.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if "cpu" not in cycles or "accelerator" not in cycles:
            raise ValueError(f"missing engine measurement for {op} N={n}: {cycles}")
        cpu_c, acc_c = cycles["cpu"], cycles["accelerator"]
        winner = "cpu" if cpu_c < acc_c else "accelerator"
        workloads.append({
            "operation": op, "size_n": n,
            "cpu_cycles": cpu_c, "accelerator_cycles": acc_c,
            "speedup": cpu_c / acc_c,
            "winner": winner,
        })
    return workloads


def main():
    workloads = load_workloads()

    with open(LABELS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "operation", "size_n", "cpu_cycles", "accelerator_cycles",
            "speedup", "winner",
        ])
        w.writeheader()
        for row in workloads:
            w.writerow(row)
    print(f"Wrote {LABELS_CSV} ({len(workloads)} workload rows)")

    X = np.array([extract_features(w["operation"], w["size_n"]) for w in workloads])
    y = np.array([ENGINE_TO_LABEL[w["winner"]] for w in workloads])

    n_cpu = int((y == 0).sum())
    n_acc = int((y == 1).sum())
    print(f"\nLabel distribution: cpu={n_cpu} accelerator={n_acc} "
          f"(total={len(y)}) -- {'IMBALANCED, see docs/scheduler.md' if min(n_cpu, n_acc) <= 2 else ''}")

    # Small, shallow tree: with 11 samples a deep tree only memorizes.
    # class_weight="balanced" keeps the single cpu-labeled sample from
    # being ignored outright by a majority-class-always classifier.
    clf = DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=0)

    # Leave-one-out CV: the only honest generalization estimate at
    # n=11 (a held-out test split would leave too few samples on
    # either side to mean anything). Each of the 11 predictions below
    # comes from a model that never saw that workload during fitting.
    loo = LeaveOneOut()
    y_pred = cross_val_predict(clf, X, y, cv=loo)
    loo_correct = int((y_pred == y).sum())
    loo_acc = loo_correct / len(y)
    print(f"Leave-one-out CV accuracy: {loo_correct}/{len(y)} = {loo_acc:.3f}")

    misclassified = [
        (workloads[i]["operation"], workloads[i]["size_n"],
         LABEL_TO_ENGINE[y[i]], LABEL_TO_ENGINE[y_pred[i]])
        for i in range(len(y)) if y_pred[i] != y[i]
    ]
    for op, n, actual, predicted in misclassified:
        print(f"  LOO miss: {op} N={n} actual={actual} predicted={predicted}")

    # Final deployed model: fit on ALL 11 workloads (no held-out
    # split needed here since LOO above already gave the honest
    # generalization estimate; a model actually used for scheduling
    # decisions should use every real measurement it has).
    clf.fit(X, y)
    tree_text = export_text(clf, feature_names=FEATURE_NAMES)
    print("\nFitted tree structure:")
    print(tree_text)

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(clf, f)
    print(f"Wrote {MODEL_PATH}")

    # Sanity check: the final model must at least reproduce its own
    # training labels (a max_depth=3 tree on 6 features / 11 samples
    # should fit perfectly; if it doesn't, something upstream is
    # wrong and this script should say so loudly rather than silently
    # shipping a model that contradicts its own training data).
    train_pred = clf.predict(X)
    train_acc = (train_pred == y).mean()
    if train_acc < 1.0:
        print(f"WARNING: training-set accuracy is only {train_acc:.3f}, "
              f"not 1.0 -- investigate before trusting this model.", file=sys.stderr)

    write_report(workloads, loo_acc, loo_correct, len(y), misclassified, tree_text)
    print(f"Wrote {REPORT_PATH}")


def write_report(workloads, loo_acc, loo_correct, n_total, misclassified, tree_text):
    lines = []
    lines.append("# AI Scheduler Training Report (Phase 13)\n")
    lines.append(
        "Generated by `scheduler/training/train_scheduler.py` from "
        "`scheduler/training/dataset.csv`, which itself comes entirely from "
        "real Icarus Verilog simulation of `rtl/cpu/riscv_soc.sv` "
        "(`scheduler/benchmarks/collect_dataset.py`) -- no cycle count in "
        "this report is estimated, interpolated, or measured on physical "
        "hardware/FPGA. See `docs/scheduler.md` for full methodology.\n"
    )
    lines.append("## Measured workloads (11 operation/size pairs)\n")
    lines.append("| Operation | N | CPU cycles | Accelerator cycles | Speedup | Faster engine |")
    lines.append("|---|---|---|---|---|---|")
    for w in workloads:
        lines.append(
            f"| {w['operation']} | {w['size_n']} | {w['cpu_cycles']} | "
            f"{w['accelerator_cycles']} | {w['speedup']:.2f}x | {w['winner']} |"
        )
    lines.append("")
    lines.append(
        "**Headline finding**: `vecadd N=1` is the only measured workload where "
        "the CPU-only kernel wins (37 vs 39 cycles) -- discovered by deliberately "
        "testing the smallest possible problem size, not assumed. Every other "
        "measured workload favors the accelerator, increasingly so as N or the "
        "multiply count grows (RV32I has no hardware multiplier; see "
        "`results/accelerator_benchmark_report.md`)."
    )
    lines.append("")
    lines.append("## Model\n")
    lines.append(
        "A `DecisionTreeClassifier` (`max_depth=3`, `class_weight=\"balanced\"`) "
        "over 6 features (`scheduler/models/features.py`: `size_n`, "
        "`element_count`, `multiply_count`, one-hot operation), predicting "
        "which engine wins. Fit on all 11 measured workloads; saved to "
        "`scheduler/models/scheduler_tree.pkl`."
    )
    lines.append("")
    lines.append(f"**Leave-one-out cross-validation accuracy: {loo_correct}/{n_total} = {loo_acc:.3f}**")
    lines.append(
        "\nLOO-CV is the only defensible generalization estimate at this sample "
        "size (n=11) -- a held-out train/test split would leave too few points on "
        "either side to mean anything."
    )
    if misclassified:
        lines.append("\nLOO misclassifications:\n")
        for op, n, actual, predicted in misclassified:
            lines.append(f"- {op} N={n}: actual={actual}, predicted={predicted}")
    else:
        lines.append("\nNo LOO misclassifications.")
    lines.append("\n```\n" + tree_text.rstrip() + "\n```\n")
    lines.append("## Honest limitations\n")
    lines.append(
        "- **Only 11 labeled workloads, 10 of which share one label.** "
        "This is not a data-hungry model's dream dataset; it is barely enough "
        "to fit a shallow tree at all, let alone claim a precise decision "
        "boundary. Treat every prediction outside the exact 11 measured "
        "points as an extrapolation, not a measurement."
    )
    lines.append(
        "- **The real vecadd crossover point is unknown.** This project measured "
        "N=1 (CPU wins) and N=4 (accelerator wins) but nothing in between -- N=2 "
        "and N=3 were never simulated. The model can only have learned "
        "\"somewhere in [1,4]\"; do not read a specific N out of the fitted tree "
        "as the true crossover."
    )
    lines.append(
        "- **dot and matmul never showed a CPU win at any tested size**, "
        "including N=1 -- even a single software multiply already costs more "
        "than the accelerator's fixed MMIO setup overhead. Whether a real "
        "crossover exists for these operations at N=0 (i.e., never) or some "
        "size smaller than 1 (i.e., never, since N=1 is the smallest possible) "
        "was not established beyond \"not observed in this project's tested range\"."
    )
    lines.append(
        "- **This model has not yet been wired into a live scheduling decision "
        "path** -- that is Phase 14. Phase 13 only establishes that a model can "
        "be honestly fit to real measured data with a non-trivial (not "
        "all-one-class) decision boundary."
    )
    lines.append("")
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
