#!/usr/bin/env python3
"""
decide.py -- Phase 14: the scheduler's actual runtime decision
function. Loads the model Phase 13 trained
(scheduler/models/scheduler_tree.pkl), and for a given workload
(operation, size_n) returns which engine it predicts will finish
faster -- using scheduler/models/features.py's extract_features(), the
SAME function scheduler/training/train_scheduler.py used to build the
training features, so a decision made here can never silently use a
different feature computation than the one the model was fit on.

This module is deliberately just the decision -- it does not itself
run any simulation. scheduler/inference/evaluate_accuracy.py is what
compares this decision against real measured ground truth; Phase 15's
dynamic runtime scheduler will be what actually acts on the decision
this returns.

Usage (CLI):
    .venv/bin/python3 scheduler/inference/decide.py vecadd 2
    .venv/bin/python3 scheduler/inference/decide.py matmul 8
"""

import os
import pickle
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scheduler", "models"))
from features import extract_features, LABEL_TO_ENGINE  # noqa: E402

MODEL_PATH = os.path.join(ROOT, "scheduler", "models", "scheduler_tree.pkl")

_model = None


def _load_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f"{MODEL_PATH} not found -- run `make train_scheduler` first "
                f"(scheduler/training/train_scheduler.py)."
            )
        with open(MODEL_PATH, "rb") as f:
            _model = pickle.load(f)
    return _model


def decide(operation: str, size_n: int) -> str:
    """Return "cpu" or "accelerator" -- the model's prediction for
    which engine will finish this workload in fewer cycles. Pure
    inference: no simulation is run here."""
    model = _load_model()
    features = [extract_features(operation, size_n)]
    label = int(model.predict(features)[0])
    return LABEL_TO_ENGINE[label]


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <vecadd|dot|matmul> <size_n>", file=sys.stderr)
        sys.exit(1)
    operation, size_n = sys.argv[1], int(sys.argv[2])
    engine = decide(operation, size_n)
    print(f"{operation} N={size_n} -> predicted engine: {engine}")


if __name__ == "__main__":
    main()
