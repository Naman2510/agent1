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

## v2 in the runtime scheduler

Phase 15/16's on-CPU runtime scheduler evaluated Phase 13's boundary
(`element_count <= 2`), hand-transcribed into RISC-V. To run v2 there
without hand-transcribing again,
`scheduler/runtime/gen_dynamic_v2_demo.py` loads
`scheduler_tree_v2.pkl`, walks the fitted tree, and derives the
threshold from its own splits -- raising an error, rather than falling
back silently, if the tree has any shape the runtime template can't
express exactly (more than one cpu leaf, a lower bound, a split on any
other feature, a `multiply_count` bound that isn't `== 0`). It then
checks the derived rule against the model's own `predict()` for every
workload in both streams before writing any assembly. Run against
Phase 13's model, the same extractor recovers `2`, matching the value
Phase 15 transcribed by hand; against v2 it yields `1`.
`decision_block()`/`block_asm()` gained an `ec_threshold` parameter
whose default (`2`) regenerates every Phase 15/16 program
byte-identically.

Both v2 programs (`dynamic_v2_demo.s` on Phase 15's 6-workload stream,
`mixed_dynamic_v2_demo.s` on Phase 16's 12-workload stream) are
checked for correctness on both simulators
(`sim/testbenches/tb_dynamic_v2_correctness.sv`,
`make test_dynamic_v2_correctness`) -- including the `vecadd N=2`
block, whose result now comes through the accelerator path's copy-out
instead of the CPU path.

```
make run_dynamic_v2_demo
```

All four programs per stream re-measured in one run:

| Stream | v1 runtime | v2 runtime | Always accelerator | Oracle |
|---|---|---|---|---|
| Phase 15 (6 workloads) | 492 | 487 | 389 | 379 |
| Phase 16 (12 workloads) | 2590 | 2585 | 2366 | 2356 |

- **The fix is worth 5 cycles in-program, not 11.** The standalone
  benchmarks put `vecadd N=2` at 61 (CPU) vs. 50 (accelerator), but
  inside these programs the accelerator path also pays the unified
  output copy-out that the standalone benchmark doesn't, so part of
  that gap isn't there to recover.
- **v2's picks match the oracle's on every workload in both streams**,
  so `v2 - oracle` is a clean measurement of one thing: what it costs
  to compute the decision at runtime. 108 cycles on the 6-workload
  stream, 229 on the 12-workload one -- about 18-19 cycles per
  workload either way.
- **A runtime scheduler that is never wrong still loses to
  always-accelerator** on both streams (487 vs. 389; 2585 vs. 2366).
  The oracle beats always-accelerator by just 10 cycles on each
  stream, and the decision costs roughly 18 cycles per workload.

That turns Phase 16's inference into a measurement: on this
accelerator, accuracy was never the binding constraint. A runtime
scheduler here only pays off if deciding costs less than the oracle
gap it can win -- which, for these kernels, is one workload shape
(`vecadd N=1`), worth 10 cycles in-program on each stream (2 cycles
standalone; the copy-out widens it here, the same effect that narrows
the `vecadd N=2` gap). Full detail:
`results/dynamic_v2_report.md`.

## Cutting the decision cost

If decision cost is the constraint, the next question is how low it
can go without changing a single decision.
`scheduler/runtime/gen_dynamic_lean_demo.py` emits programs that make
exactly v2's choices (checked against `predict()` before any assembly
is written) but compute them more cheaply:

1. **Fold only what is provably constant.** The v2 rule is evaluated
   over each operation's entire legal size range on this accelerator
   -- N=1..`MAX_LEN` for vecadd/dot, N=1..`MAX_DIM` for matmul, both
   parsed from `rtl/accelerator/accelerator.sv`. `dot` and `matmul`
   can never satisfy `multiply_count == 0` at any legal N, so the
   check for them could never change the outcome; they go straight to
   the accelerator, with no compare and no runtime `mul32` calls.
2. **Keep the runtime decision where it genuinely varies.** For
   `vecadd` the CPU still decides at runtime: one compare against a
   threshold held in `x28` for the whole program, using the
   `li x9, N` both engine bodies already execute (hoisted above the
   branch; the generator asserts nothing in either body writes `x9`
   earlier).
3. **Common path falls through.** The accelerator body follows the
   compare (not-taken branch, no flush); the CPU body sits out of line
   and jumps back.

Correctness: the same testbench, compiled against the lean program
images (`SMALL_HEX`/`MIXED_HEX` defines), passes on both simulators
(`make test_dynamic_v2_correctness` now checks both variants).

| Stream | v2 runtime | v2 lean | Always accelerator | Oracle |
|---|---|---|---|---|
| Phase 15 (6 workloads) | 487 | **388** | 389 | 379 |
| Phase 16 (12 workloads) | 2585 | **2368** | 2366 | 2356 |

The cost of deciding over the oracle drops from 108 to 9 cycles
(Phase 15 stream) and from 229 to 12 (Phase 16 stream). The counters
account for every remaining cycle: against the oracle, the lean
programs retire 5 and 8 extra instructions respectively (the
threshold load, one compare per `vecadd` request, and the jump back
from the one out-of-line CPU dispatch) and take 2 extra pipeline
flushes each (the taken compare and that jump), at 2 cycles per flush.

The result is a near-tie, and which side it falls on depends on the
stream: the lean runtime scheduler **beats always-accelerator by 1
cycle** on the Phase 15 stream and **trails it by 2** on the Phase 16
stream. Each runtime check that ends up at the accelerator costs a
cycle; the single correct CPU dispatch earns the oracle's 10-cycle
in-program gain minus its out-of-line round trip. Phase 16's stream
has more `vecadd` requests that end up on the accelerator, so it pays
for more checks against the same one win. On this accelerator, where
only `vecadd N=1` ever favors the CPU, even an essentially free
runtime scheduler is worth a handful of cycles per stream, in either
direction. Full detail: `results/dynamic_v2_report.md`.
