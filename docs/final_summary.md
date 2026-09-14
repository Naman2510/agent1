# Final Project Summary (Phase 17)

This document is the capstone for the AI-Directed RISC-V Heterogeneous
Computing System: what was actually built, across all 17 phases, and
what the real (never fabricated, never hardware-claimed) measurements
say about it. It does not replace any phase's own documentation --
`README.md`'s Documentation section links every phase's detailed
writeup -- it ties them together and states, once, what the whole
system's real result is.

**Run it yourself**: `make demo` (`scripts/run_full_demo.sh`) runs
this entire pipeline end-to-end -- every phase's tests, benchmarks, and
reports, in order -- and prints this same headline-numbers summary,
pulled directly from the `results/*.md` files each step generates (not
retyped here). Pass `ARGS=--with-synthesis` to also include Phase 12's
slow FPGA resource-estimate step.

## What exists

A from-scratch RV32I RISC-V CPU (single-cycle, then a five-stage
pipeline with real hazard handling), a memory-mapped hardware
accelerator (vector add / dot product / matrix multiply) with its own
custom RISC-V instruction extension, a complete SoC tying CPU, RAM,
UART, GPIO, and the accelerator together over a real address-decoded
bus -- and, on top of that hardware, an AI workload scheduler: a model
trained on real measured CPU-vs-accelerator timing data, wired into
both an offline decision pipeline and a genuinely runtime,
hardware-computed scheduling decision. Every one of these was verified
under both Icarus Verilog and Verilator before being trusted, and
every timing number anywhere in this project comes from an actual
simulation run -- never estimated, never hand-computed, and never
presented as a physical FPGA/hardware measurement (Phase 12's Yosys
resource counts are explicitly synthesis-tool *estimates*, stated as
such throughout).

## Headline real findings, phase by phase

| Phase | Real, measured finding |
|---|---|
| 7 | Pipelined CPU CPI ~1.5-1.65 on real hand-written benchmarks (`results/performance_report.md`) |
| 11 | Accelerator speedup over CPU-only: 1.84x (vecadd), 5.03x (dot), 11.90x (matmul) at N=16/4x4 -- the gap widens with multiply count because RV32I has no hardware multiplier (`results/accelerator_benchmark_report.md`) |
| 12 | Full SoC synthesizes to 38,390 iCE40 cells (Yosys resource *estimate*, no physical FPGA); no memory array inferred Block RAM under default settings -- a real, flagged finding (`results/synthesis_report.md`) |
| 13 | A genuine CPU-favorable crossover exists: `vecadd N=1` is 37 CPU cycles vs. 39 accelerator cycles -- found by deliberately testing the smallest possible workload, not assumed. Trained model's leave-one-out CV accuracy: 9/11 = 0.818 (`results/scheduler_report.md`) |
| 14 | Genuinely held-out accuracy (9 workloads never trained on): 8/9 = 0.889, with one honest, instructive miss (`vecadd N=2`) exactly where Phase 13's documented uncertainty said one might occur (`results/scheduler_accuracy_report.md`) |
| 15 | A single RISC-V program computing the scheduling decision itself, at runtime, on the CPU -- and the honest result that its own decision overhead made it SLOWER than a naive "always use the accelerator" baseline for a small workload stream (`results/dynamic_scheduling_report.md`) |
| 16 | At 4-32x the per-workload scale, that overhead penalty shrank from 26.5% to 9.5% -- but the deeper finding is that even a perfect, zero-overhead scheduler could only ever have saved 10 cycles on a realistic 12-workload stream, because the accelerator already wins almost everything (`results/mixed_workloads_report.md`) |

## The honest conclusion this project's own data supports

This project's AI scheduler is not a triumphant "the AI always knows
best" story, and it was never allowed to be spun into one. The real,
repeatedly-measured conclusion is more specific and more useful: **for
this accelerator design (fast, cheap fixed overhead, genuinely faster
at nearly everything) and these three kernels (vector add, dot
product, matrix multiply), a learned scheduler has only a narrow
opportunity to add value** -- one small corner of workload-size space
(`vecadd` at N=1) where the CPU wins, surrounded by a much larger
region where "always use the accelerator" is already close to optimal.
Phases 15 and 16 show, with real measurements rather than assumption,
that the runtime cost of MAKING a scheduling decision is itself
non-trivial and must be weighed against how much that decision could
possibly be worth. That is a genuine, transferable systems-engineering
lesson, and it is what this project's data actually says -- not a
weaker version of a more exciting claim.

## Scope decision: the optional LLM layer was not built

The original task specification named an LLM layer as an *optional*
Phase 17 addition. It was not built, and that is a deliberate choice,
stated here rather than left unexplained:

- This project's entire discipline is measuring real things and never
  fabricating a result. A "Claude decides the schedule" layer that
  isn't actually backed by a live model call -- because this simulated
  environment has no general-purpose LLM API credential configured for
  the running system to call at inference time -- would be exactly the
  kind of fabricated component this project spent 16 phases refusing
  to build (see every phase's own "no Python shortcut standing in for
  hardware" and "never claim what wasn't measured" rules in
  `README.md`).
- Even with a live LLM available, Phase 16's own finding argues against
  it here: an LLM call is orders of magnitude more expensive (wall
  clock, and conceptually cycles-equivalent) than the ~15-cycle
  decision-tree evaluation Phase 15 already found to be too costly for
  this accelerator's tiny oracle-vs-baseline gap. Adding a much heavier
  decision mechanism on top of a system that Phase 16 showed has
  little room for ANY scheduler to add value would not be a meaningful
  extension of this project's findings -- it would bury a working,
  honest result under an untested, unjustifiable one.
- If a future phase revisits this, the right scope is narrow and
  testable: an LLM used for something an 11-sample decision tree
  genuinely cannot do (e.g., explaining a scheduling decision in
  natural language, or handling a kernel this project has never
  measured), evaluated with the same real-measurement discipline as
  every other phase -- not a wholesale replacement for a model that
  Phase 13/14 already showed works about as well as this tiny dataset
  allows.

## Full documentation index

See `README.md`'s Documentation section for the complete, linked list
(one file per phase/topic): `docs/riscv.md`, `docs/datapath.md`,
`docs/testing.md`, `docs/c_program_demo.md`, `docs/pipeline.md`,
`docs/hazards.md`, `docs/soc.md`, `docs/accelerator.md`,
`docs/custom_extension.md`, `docs/benchmarking.md`,
`docs/synthesis.md`, `docs/scheduler.md`, `docs/scheduler_pipeline.md`,
`docs/dynamic_scheduling.md`, `docs/mixed_workloads.md`, and
`CHANGELOG.md` for the full chronological record of every architectural
decision, bug found and fixed, and honest limitation across all 17
phases.
