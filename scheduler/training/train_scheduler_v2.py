#!/usr/bin/env python3
"""
train_scheduler_v2.py -- post-Phase-17 improvement: retrain the AI
scheduler on ALL 20 workloads this project has real measured data for
(Phase 13's original 11 + Phase 14's 9 held-out ones, now merged),
directly fixing the "only 11 samples, and the real vecadd crossover
point (N=1..4) was never pinned down" limitations
docs/scheduler_pipeline.md documented.

This does NOT edit or invalidate scheduler/training/train_scheduler.py
(Phase 13's model stays exactly as it was, an honest historical
record of what that phase measured and built) -- it is a new,
clearly-versioned script and model, evaluated against a FRESH held-out
set (scheduler/training/heldout_dataset_v2.csv: vecadd/dot N=6, N=12,
truly never used anywhere before) so no accuracy claim here is
contaminated by data the model was fit on.

Usage:
    .venv/bin/python3 scheduler/training/train_scheduler_v2.py
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

TRAINING_CSVS = ["dataset.csv", "heldout_dataset.csv"]  # Phase 13 + Phase 14 -- now merged
NEW_HELDOUT_CSV = "heldout_dataset_v2.csv"              # genuinely unseen (this round)

TRAINING_DIR = os.path.join(ROOT, "scheduler", "training")
LABELS_PATH = os.path.join(TRAINING_DIR, "workload_labels_v2.csv")
MODEL_PATH = os.path.join(ROOT, "scheduler", "models", "scheduler_tree_v2.pkl")
REPORT_PATH = os.path.join(ROOT, "results", "scheduler_v2_report.md")


def load_workloads_from(*csv_names):
    by_key = {}
    for name in csv_names:
        path = os.path.join(TRAINING_DIR, name)
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["operation"], int(row["size_n"]))
                by_key.setdefault(key, {})[row["engine"]] = int(row["cycles"])

    workloads = []
    for (op, n), cycles in sorted(by_key.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if "cpu" not in cycles or "accelerator" not in cycles:
            raise ValueError(f"missing engine measurement for {op} N={n}: {cycles}")
        cpu_c, acc_c = cycles["cpu"], cycles["accelerator"]
        workloads.append({
            "operation": op, "size_n": n,
            "cpu_cycles": cpu_c, "accelerator_cycles": acc_c,
            "speedup": cpu_c / acc_c,
            "winner": "cpu" if cpu_c < acc_c else "accelerator",
        })
    return workloads


def main():
    train_workloads = load_workloads_from(*TRAINING_CSVS)
    n_train = len(train_workloads)
    print(f"Merged training set: {n_train} workloads "
          f"({'+'.join(TRAINING_CSVS)}) -- Phase 13's model used 11.")

    with open(LABELS_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "operation", "size_n", "cpu_cycles", "accelerator_cycles", "speedup", "winner",
        ])
        w.writeheader()
        for row in train_workloads:
            w.writerow(row)
    print(f"Wrote {LABELS_PATH} ({n_train} workload rows)")

    X = np.array([extract_features(w["operation"], w["size_n"]) for w in train_workloads])
    y = np.array([ENGINE_TO_LABEL[w["winner"]] for w in train_workloads])
    n_cpu, n_acc = int((y == 0).sum()), int((y == 1).sum())
    print(f"Label distribution: cpu={n_cpu} accelerator={n_acc} (total={n_train})")

    clf = DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=0)

    loo = LeaveOneOut()
    y_pred = cross_val_predict(clf, X, y, cv=loo)
    loo_correct = int((y_pred == y).sum())
    loo_acc = loo_correct / n_train
    print(f"Leave-one-out CV accuracy (n={n_train}): {loo_correct}/{n_train} = {loo_acc:.3f} "
          f"(Phase 13's n=11 model: 9/11 = 0.818)")
    loo_misses = [
        (train_workloads[i]["operation"], train_workloads[i]["size_n"],
         LABEL_TO_ENGINE[y[i]], LABEL_TO_ENGINE[y_pred[i]])
        for i in range(n_train) if y_pred[i] != y[i]
    ]
    for op, n, actual, predicted in loo_misses:
        print(f"  LOO miss: {op} N={n} actual={actual} predicted={predicted}")

    clf.fit(X, y)
    tree_text = export_text(clf, feature_names=FEATURE_NAMES)
    print("\nFitted tree structure (v2, n=20 training points):")
    print(tree_text)

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(clf, f)
    print(f"Wrote {MODEL_PATH}")

    # Genuinely held-out evaluation: 4 workloads (vecadd/dot N=6, N=12)
    # never in any training CSV above.
    new_heldout = load_workloads_from(NEW_HELDOUT_CSV)
    held_results = []
    for w in new_heldout:
        pred_label = int(clf.predict([extract_features(w["operation"], w["size_n"])])[0])
        predicted = LABEL_TO_ENGINE[pred_label]
        cycles_by_engine = {"cpu": w["cpu_cycles"], "accelerator": w["accelerator_cycles"]}
        regret = cycles_by_engine[predicted] - min(cycles_by_engine.values())
        correct = predicted == w["winner"]
        held_results.append({**w, "predicted": predicted, "correct": correct, "regret": regret})
        status = "OK   " if correct else "WRONG"
        print(f"[{status}] {w['operation']:8s} N={w['size_n']:<3d} "
              f"predicted={predicted:11s} actual={w['winner']:11s} regret={regret}")

    held_correct = sum(1 for r in held_results if r["correct"])
    held_total = len(held_results)
    held_acc = held_correct / held_total
    print(f"\nRound-2 held-out accuracy: {held_correct}/{held_total} = {held_acc:.3f} "
          f"(Phase 14's original n=9 held-out set: 8/9 = 0.889)")

    write_report(train_workloads, loo_acc, loo_correct, n_train, loo_misses, tree_text,
                 held_results, held_acc, held_correct, held_total)
    print(f"Wrote {REPORT_PATH}")


def write_report(train_workloads, loo_acc, loo_correct, n_train, loo_misses, tree_text,
                  held_results, held_acc, held_correct, held_total):
    lines = []
    lines.append("# AI Scheduler v2: Expanded Training Set Report\n")
    lines.append(
        "Generated by `scheduler/training/train_scheduler_v2.py`. Retrains the AI "
        "scheduler on ALL 20 workloads this project has real measured data for "
        "(Phase 13's `dataset.csv` + Phase 14's `heldout_dataset.csv`, merged), "
        "directly addressing `docs/scheduler_pipeline.md`'s documented limitation "
        "that the original model saw only 11 samples and never had data between "
        "`vecadd` N=1 and N=4. Every cycle count is real Icarus Verilog simulation "
        "output, none estimated or hand-computed. Scored against a FRESH held-out "
        "set (`heldout_dataset_v2.csv`: `vecadd`/`dot` N=6, N=12) never used in any "
        "training CSV, so this accuracy claim is not contaminated by data the model "
        "was fit on.\n"
    )
    lines.append(f"## Training set: {n_train} workloads (was 11 in Phase 13)\n")
    lines.append("| Operation | N | CPU cycles | Accelerator cycles | Speedup | Winner |")
    lines.append("|---|---|---|---|---|---|")
    for w in train_workloads:
        lines.append(f"| {w['operation']} | {w['size_n']} | {w['cpu_cycles']} | "
                      f"{w['accelerator_cycles']} | {w['speedup']:.2f}x | {w['winner']} |")
    lines.append("")
    lines.append(
        f"**Leave-one-out CV accuracy: {loo_correct}/{n_train} = {loo_acc:.3f}** "
        f"(Phase 13's original n=11 model: 9/11 = 0.818). The larger, denser sample -- "
        f"now including `vecadd` N=2 and N=3, directly inside the old model's "
        f"untested gap -- gives a meaningfully more reliable generalization estimate."
    )
    if loo_misses:
        lines.append("\nLOO misclassifications:\n")
        for op, n, actual, predicted in loo_misses:
            lines.append(f"- {op} N={n}: actual={actual}, predicted={predicted}")
    else:
        lines.append("\nNo LOO misclassifications.")
    lines.append("\n```\n" + tree_text.rstrip() + "\n```\n")

    lines.append("## Round-2 held-out evaluation (4 brand-new workloads)\n")
    lines.append(
        "`vecadd`/`dot` at N=6 and N=12 -- inside gaps the merged training set still "
        "doesn't cover directly (between N=4/N=8 and N=8/N=16) -- generated, "
        "correctness-verified (`sim/testbenches/tb_scheduler_v2_heldout_correctness.sv`, "
        "`make test_scheduler_v2_heldout_correctness`), and measured for the first time "
        "in this round.\n"
    )
    lines.append("| Operation | N | CPU cycles | Accelerator cycles | Actual | Predicted | Correct | Regret |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in held_results:
        mark = "yes" if r["correct"] else "**NO**"
        lines.append(f"| {r['operation']} | {r['size_n']} | {r['cpu_cycles']} | "
                      f"{r['accelerator_cycles']} | {r['winner']} | {r['predicted']} | "
                      f"{mark} | {r['regret']} |")
    lines.append("")
    lines.append(f"**Round-2 held-out accuracy: {held_correct}/{held_total} = {held_acc:.3f}** "
                  f"(Phase 14's original held-out set: 8/9 = 0.889).")
    if held_correct == held_total:
        lines.append(
            "\nAll four new points are correctly classified. This is expected, not "
            "surprising: N=6 and N=12 sit well inside the region (element_count > 2) "
            "where every training point -- old and new -- already favors the "
            "accelerator; they were never near the model's one uncertain decision "
            "boundary (which Phase 14 already showed sits between vecadd N=1 and "
            "N=2, both now correctly in the merged training set)."
        )
    lines.append("")
    lines.append("## What changed vs. the Phase 13/14 model\n")
    lines.append(
        "- **`vecadd` N=2 (the Phase 14 misprediction) is now correctly in the "
        "training set** rather than something the old model had to extrapolate to. "
        "The merged model no longer needs to guess across that gap.\n"
        "- **The LOO-CV estimate is now over 20 points instead of 11** -- still "
        "small by conventional ML standards, but a meaningfully more stable "
        "estimate of generalization than n=11 allowed.\n"
        "- **This is a new, separate model artifact "
        "(`scheduler/models/scheduler_tree_v2.pkl`)**, not an overwrite of Phase "
        "13's `scheduler_tree.pkl` -- both remain available; "
        "`scheduler/inference/decide.py` still serves the original Phase 13 model "
        "unless explicitly pointed at v2, so nothing about the already-shipped "
        "Phase 14/15/16 pipelines silently changed behavior."
    )
    lines.append("")
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
