# AI Scheduler Decision Pipeline + Accuracy Tracking (Phase 14)

Phase 13 (`docs/scheduler.md`) produced a model fit to 11 real measured
workloads and reported its leave-one-out cross-validated accuracy
(9/11 = 0.818) -- the only honest generalization estimate LOO-CV can
give, since it only ever refits the model on 10 of the SAME 11 points.
Phase 14 does two new things: it turns the model into an actual
callable decision function, and it scores that decision function
against workloads the model has **never been fit on in any form** --
a genuinely held-out test, not a re-slicing of the training set.

## The decision function

`scheduler/inference/decide.py` loads
`scheduler/models/scheduler_tree.pkl` once and exposes
`decide(operation, size_n) -> "cpu" | "accelerator"`. It calls
`scheduler/models/features.py:extract_features()` -- the exact same
function `train_scheduler.py` used to build the training features --
so a decision made here can never silently compute a feature
differently than the model was fit on (a real bug class in ML
pipelines generally, not something specific to this project, but one
this project would rather design out than discover later). This
module makes no simulation calls; it is pure inference, intended to be
fast enough for Phase 15's dynamic runtime scheduler to call directly.

```
.venv/bin/python3 scheduler/inference/decide.py vecadd 2
# vecadd N=2 -> predicted engine: cpu
```

## Building genuinely held-out ground truth

To score `decide()` honestly, this phase needed workloads the model
had truly never seen -- not another LOO-CV slice of the same 11
points. `scheduler/benchmarks/gen_scheduler_programs.py`'s
`HELDOUT_VECADD_DOT_SIZES = [2, 3, 8, 32]` and
`HELDOUT_MATMUL_SIZES = [1]` were chosen specifically:

- **N=2, N=3 (vecadd/dot)** sit exactly inside the "real vecadd
  crossover point is unknown" gap Phase 13 documented (N=1 was a CPU
  win, N=4 was not, and N=2/N=3 were never simulated) -- the single
  most informative place to test the model's extrapolation.
- **N=8, N=32 (vecadd/dot)** test extrapolation further outside the
  trained range in the other direction.
- **N=1 (matmul)**, a degenerate 1x1 case, is the only additional
  matmul size the power-of-two/`MAX_DIM=8` constraint (documented in
  `docs/scheduler.md`) allows -- matmul's other valid sizes (2, 4, 8)
  are already training data.

Correctness of all 9 held-out workloads (18 `riscv_soc` instances, CPU
and accelerator each) is verified against Python-computed expected
values in `sim/testbenches/tb_scheduler_heldout_correctness.sv`, under
both Icarus Verilog and Verilator:

```
make test_scheduler_heldout_correctness
```

`scheduler/benchmarks/collect_heldout_dataset.py`
(`make collect_scheduler_heldout_dataset`) then runs all 18 programs
through `tb_benchmark_soc.sv` (unchanged from Phase 13 -- every
held-out program here is cheaper than Phase 13's `cpu_matmul_n8`, so
no `MAX_CYCLES` adjustment was needed) and writes
`scheduler/training/heldout_dataset.csv`. This file is deliberately
separate from `scheduler/training/dataset.csv`: mixing ground truth
with training data would make it impossible to tell a real held-out
result from an inflated training-set number.

## Real result: 8/9 held-out, with one genuine, instructive miss

```
make evaluate_scheduler_accuracy
```

runs `scheduler/inference/evaluate_accuracy.py`, which calls
`decide()` on all 9 held-out workloads and compares each prediction
against the actual faster engine (from real measured cycles in
`heldout_dataset.csv`):

| Operation | N | CPU cycles | Accelerator cycles | Actual winner | Predicted | Correct |
|---|---|---|---|---|---|---|
| vecadd | 2 | 61 | 50 | accelerator | **cpu** | **NO** |
| vecadd | 3, 8, 32 | -- | -- | accelerator | accelerator | yes |
| dot | 2, 3, 8, 32 | -- | -- | accelerator | accelerator | yes |
| matmul | 1 | 88 | 45 | accelerator | accelerator | yes |

**Held-out accuracy: 8/9 = 0.889.** The one miss (`vecadd N=2`) is not
noise or a fabricated caveat -- it is exactly what Phase 13's
documented limitation predicted might happen. The fitted tree's only
`vecadd`-at-small-size split (`element_count <= 2.5 and
multiply_count <= 0.5 -> cpu`) was learned from a SINGLE training
point (`vecadd N=1`, where the CPU really does win) and extrapolated
that straight through N=2 -- but N=2 is already an accelerator win
(50 vs 61 cycles): the real crossover sits strictly between N=1 and
N=2, not at "N=1 and everything adjacent to it." Predicting CPU here
would have cost a real scheduler 11 extra cycles (regret) versus
picking the accelerator -- a small, honestly quantified cost, not a
catastrophic one, but a real miss nonetheless.

Full detail: `results/scheduler_accuracy_report.md`.

## What this phase does and doesn't establish

- It shows the model generalizes reasonably (8/9) to workloads it
  never trained on, at both interpolated (N=2, N=3) and extrapolated
  (N=8, N=32) sizes -- not just refitting well on its own 11 points.
- It shows, concretely rather than hypothetically, why Phase 13's
  "only 11 samples, one crossover point never pinned down" caveat
  matters: a real, quantifiable misprediction happened exactly where
  that caveat said one might.
- It does NOT retrain or otherwise change the Phase 13 model --
  `scheduler_tree.pkl` is scored as-is. Whether to add `vecadd N=2` to
  the training set and refit (which would very likely fix this one
  miss, since a single new point at exactly the disputed boundary is
  highly informative) is a real, reasonable next step, deliberately
  left for a later iteration rather than done reflexively here, so
  this phase's held-out evaluation stays a clean, uncontaminated test
  of the exact model Phase 13 shipped.
- The decision function itself is not yet wired into any live
  scheduling loop that actually dispatches a workload -- that is
  Phase 15's job.
