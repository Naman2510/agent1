# AI Scheduler v2: Expanded Training Set (post-v1 improvement)

`docs/scheduler_pipeline.md` (Phase 14) closed with a concrete,
honestly-flagged real miss: the original model, fit on only 11
workloads, incorrectly predicted CPU for `vecadd N=2` because its only
small-`vecadd` training point was `N=1` and it had never seen anything
between N=1 and N=4. That document named the obvious fix -- "add the
new point and refit" -- and deliberately left it undone, to keep
Phase 14's held-out evaluation an uncontaminated test of the exact
model Phase 13 shipped. This document is that fix, done properly: not
by quietly patching one label, but by merging Phase 13's dataset AND
Phase 14's entire held-out set into one real, 20-workload training set,
retraining from scratch, and validating the result against brand-new
data that was never touched by either.

## What changed

`scheduler/training/train_scheduler_v2.py` merges
`scheduler/training/dataset.csv` (Phase 13, 11 workloads) and
`scheduler/training/heldout_dataset.csv` (Phase 14, 9 workloads) into
one 20-workload training set (`workload_labels_v2.csv`), fits a new
`DecisionTreeClassifier` (same hyperparameters and feature set as
Phase 13's model -- `scheduler/models/features.py`, unchanged), and
saves it as a **separate** artifact,
`scheduler/models/scheduler_tree_v2.pkl`. Phase 13's original
`scheduler_tree.pkl` is untouched, and `scheduler/inference/decide.py`
still serves it by default -- nothing about the already-shipped Phase
14/15/16 pipelines silently changed behavior. v2 is an addition, not a
retroactive edit of history.

## A fresh held-out set, because the old one just got spent

Once Phase 14's `heldout_dataset.csv` becomes training data, none of
those 9 workloads are "held out" anymore -- reusing them to claim an
accuracy number for the new model would not be honest. Two brand-new
vecadd/dot sizes, N=6 and N=12 (chosen to sit inside gaps the merged
set still doesn't cover directly: between N=4/N=8, and N=8/N=16),
were generated (`scheduler/benchmarks/gen_scheduler_programs.py`'s
`HELDOUT_V2_VECADD_DOT_SIZES`), correctness-verified against
Python-computed expected results under both Icarus Verilog and
Verilator (`sim/testbenches/tb_scheduler_v2_heldout_correctness.sv`,
`make test_scheduler_v2_heldout_correctness`), and measured for real
(`scheduler/benchmarks/collect_scheduler_v2_heldout_dataset.py`,
`make collect_scheduler_v2_heldout_dataset`) before being used to
score anything.

`matmul` gets no new round-2 size: every valid size (1, 2, 4, 8) is
bounded by `MAX_DIM=8`, an RTL parameter this maintenance pass
deliberately does not touch (changing it would mean re-verifying
already-shipped accelerator RTL, out of scope for a training-data
improvement), and all four are already training data after the merge.
Stated plainly rather than glossed over.

## Real result: the misprediction is fixed, and the fix is explainable

```
make train_scheduler_v2
```

| Metric | Phase 13/14 (n=11) | v2 (n=20) |
|---|---|---|
| Leave-one-out CV accuracy | 9/11 = 0.818 | 19/20 = 0.950 |
| Held-out accuracy | 8/9 = 0.889 | 4/4 = 1.000 (new, harder-to-compare set) |
| `vecadd N=2` prediction | **cpu (WRONG)** | **accelerator (correct)** |

The fitted tree's structure explains exactly why: with `vecadd N=2`
now correctly labeled `accelerator` in training, the split that used
to read `element_count <= 2 and multiply_count == 0 -> cpu` sharpens
to `element_count <= 1 and multiply_count == 0 -> cpu` -- i.e., the
model now isolates the TRUE crossover (only N=1) instead of
overshooting it. The one remaining LOO miss is `vecadd N=1` itself:
leave-one-out removes exactly the single point that makes N=1 special,
so a model refit without it naturally can't recover that this one
workload is different -- an expected, explainable artifact of LOO-CV
at small n, not a new problem.

The round-2 held-out set (4/4 correct) is not a hard test by
construction -- N=6 and N=12 sit well inside the region every training
point already agrees favors the accelerator, nowhere near the model's
one real decision boundary. It is included anyway, and reported as
such rather than oversold, because a real held-out check (even an
easy one) is still worth more than none, and because it is honest
about what it does and doesn't prove: full detail and the "what
changed" accounting in `results/scheduler_v2_report.md`.

## Honest scope of this round

- 20 samples is still small by any conventional ML standard -- this
  remains a demonstration of the method (measure real data, fit
  honestly, validate on genuinely unseen points), not a claim that 20
  points is enough data for a production scheduler.
- The one real decision boundary this whole project has ever found
  (`vecadd` crossover between N=1 and N=2) is now pinned down as
  tightly as N=1 vs. N=2 sampling allows -- narrower than "somewhere
  in 1..4," but still not continuous; nothing here claims to know the
  boundary would hold for, say, a non-integer or radically different
  workload shape.
- `dot` and `matmul` still show no CPU win at any tested size,
  including the smallest possible one (`N=1` for both) -- unchanged
  from Phase 13's finding, and still not contradicted by anything in
  this round's 8 additional real measurements.
