# Dynamic Runtime Scheduling (Phase 15)

Phase 13 trained a model offline in Python. Phase 14 wrapped it in a
callable `decide()` function and scored it, still from Python, against
held-out simulation data. Both of those keep the actual scheduling
DECISION outside the hardware/software system being scheduled -- an
offline script picks which already-assembled, single-workload program
to run next. Phase 15 does something different, and closer to what
"dynamic runtime scheduling" should really mean for a hardware
project: **one RISC-V program, running in ONE simulated execution,
that computes the engine decision itself, on the CPU, using real
RV32I instructions and a real conditional branch, for each workload in
a stream** -- consistent with this project's own rule that important
CPU/accelerator behavior belongs in RTL/software, never a Python
shortcut standing in for hardware (`README.md`'s engineering rules).

## The demo program

`scheduler/runtime/gen_dynamic_scheduler_demo.py` generates
`dynamic_scheduler_demo.s`: a fixed stream of 6 workloads (vecadd
N=1,2,4; dot N=1,4; matmul N=2), each handled by its own block of
generated assembly. Every block:

1. **Computes `element_count`/`multiply_count` with real
   instructions** -- trivial register loads for vecadd/dot, but for
   matmul, two genuine runtime multiplications through the project's
   `mul32` subroutine (`ec = n*n`, `mc = ec*n`). Nothing here is
   precomputed in Python and baked in as an unconditional jump; the
   values living in registers when the branch below executes are the
   values that decide where control goes.
2. **Branches on those values** using the exact boundary the fitted
   tree learned (`scheduler/training/train_scheduler.py`'s printed
   tree: `element_count <= 2 and multiply_count == 0 -> cpu, else
   accelerator`) -- real `blt`/`bne` instructions, not a table lookup.
3. **Executes the chosen engine's real compute path** -- the same
   operand setup / compute loop / accelerator MMIO sequence already
   verified in Phase 11/13, just given unique per-block labels since
   all 6 workloads (and, for the CPU and accelerator paths of each
   dynamically-decided block, BOTH possible bodies) now live in one
   file.
4. **Writes its result to a unified RAM location** regardless of
   which engine produced it (the accelerator path copies its answer
   out of the accelerator's memory-mapped VECOUT/RESULT window with
   plain `LW`/`SW` before the next block can overwrite it) -- a real
   hardware scheduler's output contract shouldn't depend on which
   engine happened to serve a request.

Three more programs share the identical 6-workload stream and
per-block bodies but skip the decision step, forcing every block to
one fixed choice: `always_cpu_demo.s`, `always_accel_demo.s`, and
`oracle_demo.s` (whichever engine Phase 13/14's real measured data
says is actually faster for that exact workload, read from
`dataset.csv`/`heldout_dataset.csv` at generation time -- not
hand-transcribed). All four are checked for correctness -- every
block's real computed result, not just completion -- against the same
Python-computed expected-value table in
`sim/testbenches/tb_dynamic_scheduler_correctness.sv`, under both
Icarus Verilog and Verilator (`make test_dynamic_scheduler_correctness`).

### Bug found and fixed: shared labels between co-resident CPU/accelerator bodies

The first version of the generator gave a dynamically-decided block's
CPU-path and accelerator-path bodies the SAME label tag. Since BOTH
bodies are compiled into the binary for a dynamic block (only one
runs, chosen by the branch, but the assembler still needs to resolve
both), their internal loop labels (e.g. `blk1_setup_loop`) collided --
whichever definition the assembler's single global label table kept
silently corrupted the other path's jump targets. This was caught
immediately, not assumed safe, by
`tb_dynamic_scheduler_correctness.sv`: block1 (`vecadd N=2`, the one
block whose CPU-path body actually runs in `dynamic_scheduler_demo.s`)
failed with output 0 instead of the expected values, while the
identical block in `always_cpu_demo.s` (which only emits the CPU body,
no collision possible) passed. Fixed by giving each path its own
suffixed tag (`{tag}c` / `{tag}a`); re-running the correctness suite
confirmed all checks pass under both simulators. See `CHANGELOG.md`'s
Phase 15 entry.

## Real result: the dynamic scheduler LOSES to a naive baseline here

```
make run_dynamic_scheduler_demo
```

| Program | Total cycles |
|---|---|
| Dynamic (runtime decision) | 492 |
| Always CPU | 980 |
| Always accelerator | 389 |
| Oracle (best-per-block, from real data) | 379 |

This is reported exactly as measured, not adjusted or reframed to
look better: **the dynamic scheduler (492 cycles) is slower than
simply always using the accelerator (389 cycles)** for this workload
stream. Two real, separately measured costs explain it:

1. **The Phase 14 misprediction has a real cost here too.** `vecadd
   N=2` gets dispatched to the CPU, just as `decide()` predicted in
   Phase 14, when the accelerator is actually faster.
2. **The runtime decision computation itself is not free.**
   `dynamic_scheduler_demo` retires 396 instructions and takes 37
   pipeline flushes vs. `oracle_demo`'s 321 instructions and 17
   flushes for the identical 6 workloads -- every block pays real
   cycles to compute `element_count`/`multiply_count` and branch on
   them, on top of whichever engine it ends up running.

**The idea still has real value, measured separately from its
execution's flaws**: `oracle_demo` (379 cycles -- every decision
correct, but still paying nothing extra for making the decision, since
it's baked in at generation time) beats always-accelerator (389
cycles) by 10 cycles. So a perfect, free scheduler would help, even
for a stream this small. What Phase 15 shows, honestly, is that THIS
implementation's decision overhead (roughly 90+ cycles across 6
blocks) combined with one wrong call more than erases that 10-cycle
theoretical gain. Full detail: `results/dynamic_scheduling_report.md`.

## What this phase does and doesn't establish

- It demonstrates a genuinely runtime, data-dependent scheduling
  decision made in RTL/software simulation -- not an offline Python
  lookup -- for the first time in this project.
- It surfaces a real, non-obvious, and previously unmeasured cost (the
  decision computation's own cycles) that Phase 13/14's offline
  Python evaluation could never have shown, since Python doesn't pay
  RISC-V pipeline cycles.
- It does NOT show that AI-directed scheduling is a bad idea in
  general -- the oracle comparison shows the ceiling is above
  always-accelerator, just not by much for a stream this small and
  with one misprediction in it. A larger or more varied workload
  stream, or a model with fewer mispredictions, would likely change
  this result -- deliberately left as a further step rather than
  tuned to produce a nicer-looking number here.
- The workload stream, decision boundary, and baselines are all fixed
  and small (6 workloads, one 6-node tree) -- Phase 16's mixed
  heterogeneous workloads is where this gets stress-tested at more
  realistic scale and variety.
