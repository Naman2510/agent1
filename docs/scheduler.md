# AI Workload Scheduler: Dataset and Model (Phase 13)

This document describes how Phase 13 builds the labeled dataset and
trains the first AI scheduler model that will, starting Phase 14,
decide whether a given workload should run on the CPU or the hardware
accelerator (`rtl/accelerator/accelerator.sv`, Phase 9/10). Every
number this phase produces -- every cycle count in
`scheduler/training/dataset.csv`, every speedup, every model accuracy
figure -- comes from an actual Icarus Verilog simulation or is
computed directly from one. Nothing here is estimated, interpolated to
pad the dataset, or presented as a physical-hardware/FPGA measurement.

## Why more programs were needed

Phase 11 (`docs/benchmarking.md`) measured exactly one size per
operation: vecadd/dot at N=16, matmul at 4x4. That gives three
CPU-vs-accelerator comparison points -- not enough to fit or evaluate
any model, and not enough to know whether the accelerator wins
*because* it's the accelerator or simply because N=16/4x4 happens to
favor it. Phase 13 needed the same three operations at multiple sizes
each, so a model can learn a dependence on workload size rather than
just memorizing "accelerator always wins."

### Generating programs instead of hand-writing them

Phase 11's benchmark kernels (`sim/programs/benchmarks/*.s`) were
hand-written and hand-verified one at a time, including working
through a real register-allocation bug (`x1`/`ra` conflict -- see
`CHANGELOG.md`'s Phase 11 entry). Hand-writing 12 more `.s` files at
new sizes would mean re-risking that same bug class 12 more times.
Instead, `scheduler/benchmarks/gen_scheduler_programs.py` generates
them programmatically from f-string templates that match Phase 11's
already-verified register usage and structure exactly, parameterized
only by N. It writes:

- `cpu_vecadd_n{N}.s` / `accel_vecadd_n{N}.s` for N in {1, 4, 64}
- `cpu_dot_n{N}.s` / `accel_dot_n{N}.s` for N in {1, 4, 64}
- `cpu_matmul_n{N}.s` / `accel_matmul_n{N}.s` for N in {2, 8}

into `sim/programs/scheduler/`. (N=16 vecadd/dot and N=4 matmul reuse
Phase 11's original programs unchanged -- see "Building the dataset"
below -- rather than generating a second, possibly-diverging copy of
an already-verified program.)

### The matmul shift-amount problem

Phase 11's `cpu_matmul_bench.s` computes each row's base address with
`slli x16, x13, 2  # i*N (N=4 -> i<<2)`. That instruction is only
correct because N happened to be 4 (`i*4 == i<<2`); at any other N it
is wrong. This could not be fixed by blind text substitution, because
the same file also contains textually-identical `slli ..., 2`
instructions that mean "*4 bytes per word" -- a completely different,
N-independent shift that must NOT change. Substituting one pattern
risks silently breaking the other.

The generator instead computes `shift = int(math.log2(n))` explicitly
in Python (asserting `1 << shift == n` first) and emits the correct
`slli` immediate for each N. This is why matmul's generated sizes are
restricted to powers of two (2, 4, 8, matching the accelerator's own
`MAX_DIM=8` parameter) -- it keeps `i*N` a single shift instruction,
consistent with what Phase 11 measured, rather than introducing a
runtime `mul32` call into address computation for non-power-of-two N
(which would change what the benchmark is actually measuring: the
*compute* cost, not new address-math overhead).

### Correctness before timing

Every one of the 12 newly generated programs is verified for
**correctness** (the actual computed result, not just that it
completes) against independently Python-computed expected values, in
`sim/testbenches/tb_scheduler_correctness.sv`, under both Icarus
Verilog and Verilator:

```
make test_scheduler_correctness
```

This checks all 20 sentinel-completion + result-value assertions
(2 checks x 14 program instances) and must print `RESULT: ALL CHECKS
PASSED` under both simulators before any of these programs'
*timing* is trusted as training data -- the same "verify once, trust
as benchmark thereafter" discipline Phase 7 and Phase 11 established.

### Raising the benchmark harness's cycle budget

`cpu_matmul_n8` (N=8, meaning 512 software multiplies via `mul32`,
8x Phase 11's original N=4 case) exceeded
`sim/testbenches/tb_benchmark_soc.sv`'s original 20000-cycle
`MAX_CYCLES` budget: `BENCHMARK_ERROR: ... sentinel never observed
within 20000 cycles`. `MAX_CYCLES` was raised to 150000 in that
shared testbench, once, for every program the harness runs -- this
only raises a timeout ceiling and does not change behavior for any
program that already completed within the old budget (confirmed by
re-running the full existing regression suite; see `CHANGELOG.md`).

## Building the dataset

```
make collect_scheduler_dataset
```

runs `scheduler/benchmarks/collect_dataset.py`, which assembles and
simulates 22 programs total -- 11 workloads (vecadd/dot at N in
{1, 4, 16, 64}; matmul at N in {2, 4, 8}) x 2 engines each -- through
`tb_benchmark_soc.sv`, and writes `scheduler/training/dataset.csv`
with one row per (operation, size, engine): real measured
`cycles`, `instructions_retired`, `stall_count`, and
`forwarding_events`, read at the exact cycle each program signals
completion via its GPIO sentinel write. N=16 vecadd/dot and N=4 matmul
reuse Phase 11's original `sim/programs/benchmarks/*_bench.s`
programs directly rather than a regenerated copy, so there is exactly
one verified source of truth for each of those three data points.

### Headline finding: a real CPU-favorable crossover

The smallest possible workload size (N=1) was deliberately tested
specifically to check whether a genuine CPU-wins case exists, rather
than assuming the accelerator always wins:

| Operation | N | CPU cycles | Accelerator cycles | Speedup | Faster engine |
|---|---|---|---|---|---|
| vecadd | 1 | 37 | 39 | 0.95x | **cpu** |
| dot | 1 | 64 | 39 | 1.64x | accelerator |

`vecadd N=1` is a genuine, measured CPU win (37 vs 39 cycles) -- RV32I
executes `ADD` natively in one cycle, so at the smallest possible
problem size the accelerator's fixed MMIO setup/handshake overhead
costs more than the CPU just doing the one addition directly. `dot`
does NOT show the same crossover at N=1: even a single software
multiply-accumulate (RV32I has no hardware multiplier; see
`docs/benchmarking.md`) already costs more than the accelerator's
setup overhead. This was discovered, not assumed -- consistent with
this project's running "trust the simulator, not hand math" practice
(`CHANGELOG.md`) -- and it is the reason Phase 13's dataset is not
degenerate: a real, non-trivial scheduling decision boundary exists in
the measured data, not just "always pick the accelerator."

Full 11-workload table (all speedups, from real measured cycles):
see `results/scheduler_report.md` (generated below) or
`scheduler/training/workload_labels.csv`.

## Training the model

```
make train_scheduler
```

(needs `numpy`/`pandas`/`scikit-learn`; run `scripts/setup_scheduler_venv.sh`
once first if `.venv/` doesn't exist yet -- see that script's header
comment for why a venv is used at all here.)

`scheduler/training/train_scheduler.py`:

1. Pivots `dataset.csv`'s 22 engine-rows into 11 workload rows (one
   per operation/size pair), each labeled with whichever engine
   measured fewer cycles -- written to
   `scheduler/training/workload_labels.csv`.
2. Extracts 6 features per workload via the single shared function
   `scheduler/models/features.py:extract_features()` -- `size_n`,
   `element_count`, `multiply_count` (0/N/N^3 for vecadd/dot/matmul --
   the feature closest to *why* the CPU falls behind, since RV32I has
   no hardware multiplier), and a one-hot operation encoding. This
   same function will be reused, unchanged, by Phase 14's live
   decision pipeline, so a training-time feature can never silently
   drift from what inference computes.
3. Fits a shallow `DecisionTreeClassifier` (`max_depth=3`,
   `class_weight="balanced"`) and reports **leave-one-out
   cross-validated accuracy** -- the only defensible generalization
   estimate at n=11 (any held-out split would leave too few points on
   either side to mean anything).
4. Saves the fitted model to `scheduler/models/scheduler_tree.pkl` and
   writes the full report to `results/scheduler_report.md`.

### Honest limitations of this model

- **11 labeled workloads, 10 sharing one label.** This is a
  genuinely tiny, imbalanced dataset -- barely enough to fit a shallow
  tree, nowhere near enough to claim a precise decision boundary.
- **The real vecadd crossover point (somewhere in N=1..4) is
  unknown** -- N=2 and N=3 were never simulated. The model can only
  have learned "somewhere in that gap," not a specific N.
- **dot and matmul showed no CPU win at any tested size, including
  N=1.** Whether either could ever cross over (at some workload this
  project didn't think to measure) is genuinely open.
- **Leave-one-out CV accuracy is 9/11 = 0.818, not 1.0** (see
  `results/scheduler_report.md` for which two workloads it misses).
  This is reported, not hidden, because a shallow tree fit to 11
  points inevitably makes mistakes on points it wasn't trained on --
  claiming perfect accuracy here would not be credible.
- **Not yet wired into a live decision path.** Phase 13's job is a
  model honestly fit to real data with a non-trivial decision
  boundary; using it to actually route a workload at runtime is
  Phase 14.
