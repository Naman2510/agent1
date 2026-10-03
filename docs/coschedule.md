# Concurrent CPU + Accelerator Co-Scheduler

## The idea

Every scheduler this project built before (Phases 13-16 and the v2/lean
follow-ups) answered one question: *which engine should run this task?*
It ran the tasks one after another, so the best any of them could do was
the **serial oracle**, every task on its faster engine. Measurement showed
that ceiling is nearly worthless here. On every stream, the serial oracle
beats "always use the accelerator" by just 10-15 cycles, because the
accelerator wins almost everything (`docs/scheduler_v2.md`,
`docs/rv32m_mul.md`).

The co-scheduler asks a different question: **what can the CPU do while
the accelerator works?** The accelerator runs autonomously once started.
Its only constraint (`docs/accelerator.md`) is that the CPU must not
rewrite its operand window while it is busy, and RAM is a separate path.
Yet in every earlier program the CPU spent the accelerator's entire busy
time in a polling loop. Instrumenting that busy time
(`sim/testbenches/tb_accel_phase_probe.sv`) shows how much was wasted:
from 1 cycle (vecadd N=1) up to 512 cycles (matmul N=8) per accelerator
task.

So the co-scheduler places **whole CPU tasks inside accelerator busy
windows**: start an accelerator task, run other tasks on the CPU, then
collect the accelerator's result. Two engines doing useful work at the
same time is something no serial scheduler can express. It needs **no
hardware change**: it runs on the RTL every earlier phase verified, at
zero area cost.

## How it works

`scheduler/coschedule/` (`make coschedule`):

1. **Profile** (`run.py`, `tb_accel_phase_probe.sv`). Every task of the
   24-workload set is run as a one-task program on each engine and each
   core configuration. This gives its CPU cost, its serial accelerator
   cost, and how long the accelerator itself is busy, all in real
   simulated cycles (`profile_rv32i.csv`, `profile_mul.csv`).
2. **Plan** (`planner.py`). Each task is placed on the accelerator, on the
   CPU serially, or on the CPU *inside a named accelerator task's
   window*. The cost model:
   `base + sum(serial CPU tasks) + sum over accelerator tasks of
   (serial cost - busy + max(busy, window load + 2))`. A deterministic
   best-improvement local search starts from both the serial oracle and
   all-accelerator, so the plan can never be worse than the serial oracle
   *under the model*. Whether the model is right is measured, not
   assumed.
3. **Generate** (`codegen.py`). The per-task code is the already-verified
   Phase 15/16 bodies, unchanged. The one new construct is the window:
   each accelerator body is split at its poll loop into a LAUNCH half and
   a WAIT half, the window's CPU tasks go in between, and `x1` (reused by
   the CPU bodies) is restored to the MMIO base before WAIT.
4. **Verify**. Every output word of every program, for all 3 streams × 2
   cores × 3 schedules (2,058 words), is checked against Python-computed
   values on Icarus Verilog and Verilator
   (`sim/testbenches/tb_coschedule_check.sv`). That checker was itself
   shown to catch a single corrupted word on both simulators.
5. **Measure and score**. Every program is measured twice through the
   established harness (`tb_benchmark_soc.sv`). The score against the
   pre-registered `docs/coschedule_scorecard.md` is computed by the
   script into `results/coschedule_scorecard.md`.

## Results

Measured cycles (`results/coschedule_report.md`):

| Stream | Core | Always accel | Serial oracle | Co-schedule | Gain vs. oracle |
|---|---|---|---|---|---|
| Phase 15 (6 tasks) | RV32I | 389 | 379 | **365** | 3.7% |
| Phase 15 | MUL | 389 | 374 | **356** | 4.8% |
| Phase 16 (12 tasks) | RV32I | 2,366 | 2,356 | **2,262** | 4.0% |
| Phase 16 | MUL | 2,366 | 2,356 | **2,262** | 4.0% |
| All 24 workloads | RV32I | 6,592 | 6,582 | **6,072** | **7.7%** |
| All 24 workloads | MUL | 6,592 | 6,577 | **6,004** | **8.7%** |

- On the full workload set, the co-scheduler saves **510 cycles** over
  the serial oracle. The serial oracle's entire advantage over
  always-accelerator, the ceiling of every scheduler built before, is
  **10 cycles**. That is **51 times** the old ceiling.
- The biggest single win is matmul N=8. Its 512-cycle busy window hosts
  vecadd N=4 and vecadd N=16 on the CPU, and on the MUL core matmul N=1
  as well. Those tasks become effectively free.
- The model predicts measured cycles to within **2.25%** on every
  co-schedule, and is exact on every serial program.
- On the 6-task stream, small enough to enumerate every possible
  placement, the planner's choice **equals the exhaustive optimum** on
  both cores.

## Limits

- **The gain is bounded by accelerator busy time.** The CPU still does
  all of the accelerator's operand marshalling, and that dominates
  accelerator tasks (vecadd N=16 is busy for 16 of its 216 cycles). Streams
  of small tasks gain about 4%; the full set, which has long matmuls,
  gains 8-9%. A DMA-capable accelerator, which fetches its own operands,
  would widen the windows. That is the natural hardware follow-up, and it
  is not part of this work.
- **Independent tasks only.** No task consumes another's output. A
  dependency graph would constrain window placement; the planner doesn't
  model one.
- **Offline plans for known streams.** The planner runs ahead of time on
  measured costs. It is not a runtime decision, and new task types need
  profiling first.
- **One accelerator context.** A window hosts CPU tasks, never a second
  accelerator task.
