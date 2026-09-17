# System Architecture

This document tracks the overall system architecture and *why* it is
built the way it is, phase by phase. It is a living document: each phase
appends a section here once that phase is implemented and verified. Do
not read this as a finished design spec for a system that doesn't exist
yet — only what has a checked box in `README.md` is real; everything
else below is intent, kept here to explain where each earlier decision
is heading.

## Target end state

```
                APPLICATION
                     |
                     v
            +------------------+
            | AI WORKLOAD      |
            | SCHEDULER        |
            +--------+---------+
                     |
         +-----------+-----------+
         |           |           |
         v           v           v
    +---------+ +---------+ +-------------+
    | RISC-V  | | FPGA-   | | AI/MATRIX   |
    | CPU     | | STYLE   | | ACCELERATOR |
    |         | | ACCEL.  | |             |
    +---------+ +---------+ +-------------+
         |           |           |
         +-----------+-----------+
                     |
                  MEMORY
```

An AI scheduler sits above three compute engines — a general-purpose
RV32I CPU, an FPGA-style reconfigurable-flavored accelerator path, and a
matrix/vector accelerator — all sharing one memory space, and decides
per-workload which engine should run it.

## Why build in this order

The phase order in this project (ISA → single-cycle CPU → tests → real
compiled C program → pipeline → hazards → performance counters → SoC →
accelerator → custom extension → benchmarking → synthesis → scheduler →
dynamic scheduling → mixed workloads → final demo) is a deliberate
bottom-up dependency chain, not an arbitrary checklist:

- The **ISA document** (Phase 1) must exist before any RTL, because the
  decoder, ALU, and every test in every later phase have to agree on one
  specification. Writing it first and treating it as the contract avoids
  the alternative failure mode of hardware and tests silently drifting
  from each other.
- A **single-cycle CPU** (Phase 2) is built before a pipeline because a
  single-cycle design has one instruction in flight at a time — no
  hazards are possible by construction. It gives a known-correct
  reference behavior (verified against directed tests in Phase 3, and
  against a real compiled program in Phase 4) to pipeline *against* in
  Phase 5. Building the pipeline first would conflate "is the ISA
  semantics right" bugs with "is the hazard handling right" bugs.
- **Tests before the pipeline, and a real C program before the
  pipeline**, so that when hazards are introduced in Phase 6, any
  regression is unambiguous: the single-cycle CPU + tests already
  establish ground truth for every instruction and for a real compiled
  program's output.
- **Performance counters** (Phase 7) come after hazards are handled
  because CPI and stall counts are only meaningful once the pipeline
  actually stalls/forwards/flushes correctly — measuring an unverified
  pipeline would produce numbers that look plausible but mean nothing.
- **SoC, then accelerator, then custom extension** (Phases 8-10): the
  accelerator needs a memory-mapped bus to attach to, so the SoC memory
  map has to exist first; the custom instruction (Phase 10) needs a
  working accelerator to control, so it comes after, not before.
- **Benchmarking and synthesis** (Phases 11-12) need finished, tested
  RTL to produce real numbers from — anything benchmarked or synthesized
  earlier would just be re-measuring code that's about to change.
- **The AI scheduler** (Phases 13+) is trained on *measured* benchmark
  data from Phase 11, which is why it is deliberately the second-to-last
  major component, not the first: an ML model trained on fabricated or
  guessed timing data would be worthless, and the task explicitly
  prohibits fabricated benchmark numbers.

## Phase 1 — ISA Foundation

**Status:** complete (see `README.md` checklist).

**What exists:** `docs/riscv.md`, the authoritative RV32I subset
specification (registers, instruction formats, per-instruction
encodings, and what is explicitly out of scope for now). No RTL exists
yet — Phase 1 is documentation-only by design (see task requirement
"Do not jump ahead").

**Verification for this phase:** the ISA document was cross-checked
field-by-field against the RISC-V Unprivileged ISA manual's instruction
listings and immediate-encoding tables (see `docs/riscv.md` §5,
References) rather than derived from memory alone; every opcode/funct3/
funct7 tuple in `docs/riscv.md` §3 will be exercised by an automated
test in Phase 3, which is the real verification gate for this document
— a spec with a typo in an encoding would be caught the moment Phase 2's
decoder is tested against it.

## Phase 2 — Basic Single-Cycle RISC-V CPU

**Status:** complete (see `README.md` checklist).

**What exists:** a complete single-cycle RV32I datapath in `rtl/`
(PC/adders, instruction memory, decoder, control unit, register file,
immediate generator, ALU, branch unit, data memory, writeback mux),
documented block-by-block with rationale in `docs/datapath.md`, verified
by `sim/testbenches/tb_riscv_cpu.sv` under both Icarus Verilog and
Verilator (`make sim_cpu`).

**Verification for this phase:** a hand-written bring-up program
exercising most of the ISA subset, checked against 19 hand-computed
expected register values. Cross-validating against two independent
simulators specifically ruled out an Icarus Verilog compiler diagnostic
being a masked correctness bug (see `docs/datapath.md`).

## Phase 3 — Instruction Execution Tests

**Status:** complete (see `README.md` checklist).

**What exists:** nine self-checking directed test programs under
`sim/programs/tests/`, one generic testbench
(`sim/testbenches/tb_directed_test.sv`) compiled once and re-run against
each via a runtime `+HEXFILE=` plusarg, and a Python runner
(`scripts/run_directed_tests.py`, `make test_isa`) that reports a
pass/fail summary under both simulators. Every instruction in
`docs/riscv.md` section 3 has at least one directed assertion; every
required test category from the task spec (arithmetic, logical,
immediate ops, loads, stores, branches, jumps, register dependencies,
negative numbers, signed comparisons, zero-register behavior) is
explicitly covered -- see the table in `docs/testing.md`.

**Verification for this phase found two real bugs**, which is the
point of building this test suite before moving on:

1. A **simulator-dependent reset race** in `riscv_cpu.sv`: `pc` had no
   explicit initial value, so it read as X for the window before the
   first clock edge, which propagated into a transient (but concrete)
   `illegal=1` that Icarus Verilog and Verilator latched differently
   depending on internal event-ordering. Fixed at the source (`pc`
   given an explicit initial value; the synchronous reset itself was
   never the problem) rather than by loosening the test. See
   `CHANGELOG.md` Phase 3 entry for the full root-cause explanation.
2. An **arithmetic mistake in a test program itself**
   (`tests/upper_imm.s` miscounted the instruction distance between two
   `auipc`s used for a relative-address check). Caught because both
   simulators agreed with each other and disagreed with the test's own
   expectation -- a reminder that test programs are code too and need
   the same scrutiny as the RTL.

Both are documented in detail rather than silently fixed, per this
project's rule against hiding what was actually found and how it was
resolved.

## Phase 4 — Execute a Real Compiled C Program

**Status:** complete (see `README.md` checklist).

**What exists:** `software/baremetal/add_test.c` (the exact program
named in the task spec), a minimal real-assembly startup stub
(`software/runtime/start.S`) and linker script
(`software/runtime/link.ld`), a build pipeline through the actual
`riscv64-unknown-elf-gcc`/`ld`/`objcopy` toolchain
(`scripts/build_c_program.sh`), and a testbench
(`sim/testbenches/tb_c_program.sv`) that runs the resulting machine code
on the unmodified Phase 2 CPU. Full walkthrough with the real compiler
output and execution trace in `docs/c_program_demo.md`.

**Verification for this phase:** the CPU produced `a0 = 30`, matching
`10 + 20` exactly, under both Icarus Verilog and Verilator, with **no
RTL changes** -- GCC's output for this program used only instructions
Phase 2/3 had already implemented and verified. That is a meaningful
validation of Phase 2/3, not just a Phase 4 result: it means the
directed-test suite's coverage was representative of what a real
compiler actually emits, not just of the instructions I happened to
think to test.

## Phase 5 — Five-Stage Pipeline

**Status:** complete (see `README.md` checklist).

**What exists:** `rtl/cpu/riscv_cpu_pipeline.sv`, a five-stage
(IF/ID/EX/MEM/WB) pipelined CPU reusing every Phase 2 submodule
unchanged, wired through four new pipeline registers in `rtl/pipeline/`.
The original single-cycle CPU (`rtl/cpu/riscv_cpu.sv`) is untouched.
Full stage-by-stage explanation, register contents, and an explicit
account of what this phase deliberately does not yet handle (forwarding,
stalling, branch/jump flush -- all Phase 6) in `docs/pipeline.md`.

**Verification for this phase found a real bug in the test's own
assumptions, not the RTL's logic, but one that would have produced a
silently-wrong verification result if not caught:** the first attempt
at `pipeline_straightline.s` assumed a classic pipelined-register-file
textbook result (2 instructions of gap is enough with no forwarding)
that does not hold for this specific implementation, because this
regfile's write and the consuming pipeline register's capture both
happen via nonblocking assignment on the same clock edge in that case --
a same-edge race Verilog resolves to the pre-write value. Running the
test caught it immediately (6 of 19 checks failed, every one exactly a
2-instruction-gap case); the fix was requiring a 3-instruction gap, not
loosening or removing the check. See `docs/pipeline.md` and
`CHANGELOG.md` for the full account.

## Phase 6 — Pipeline Hazards

**Status:** complete (see `README.md` checklist).

**What exists:** `rtl/pipeline/forwarding_unit.sv` and
`rtl/pipeline/hazard_unit.sv`, wired into `riscv_cpu_pipeline.sv`
(evolved in place, not a new module -- see `docs/hazards.md` for why
that's the right call here unlike Phase 2 -> Phase 5). Data-hazard
forwarding, the load-use stall, and branch/JAL/JALR flush are all
implemented and verified with directed tests and real GTKWave waveform
data.

**Verification for this phase found two real bugs, in two different
places, both documented in full rather than smoothed over:**

1. A genuine RTL gap: neither the EX-stage forwarding unit nor the
   register file's ordinary same-cycle behavior correctly handles a RAW
   dependency exactly 2 instructions apart -- caught by a load computing
   the wrong address, fixed with a parameterized write-to-read bypass in
   `regfile.sv` that is carefully scoped to never affect the
   single-cycle CPU (where it would create a combinational loop).
2. A test methodology bug: reusing Phase 3's "illegal opcode ever seen"
   check verbatim against a pipelined CPU fails on 100% of programs,
   because ordinary pipeline bubbles decode as illegal opcodes by
   construction -- true and harmless for a pipeline, unlike the
   single-cycle CPU this check was designed for.

Both are in `docs/hazards.md` and `CHANGELOG.md` with full root-cause
explanations, not just "fixed it."

## Phase 7 — Performance Counters + CPI

**Status:** complete (see `README.md` checklist).

**What exists:** `rtl/cpu/perf_counters.sv` (8 free-running counters),
a `valid` bit threaded through every pipeline register so "instruction
retired" can be counted without miscounting bubbles, two real
branch-driven benchmark programs, and `scripts/run_benchmarks.py`
generating `results/performance_report.md` from actual simulation
output.

**Verification for this phase found two more real bugs, both
documented in full:**

1. A genuine gap in Phase 6's `valid`-bit-free design: WB-stage signals
   alone can't distinguish a bubble from a real instruction, because
   `branch`/`jal`/`jalr` are dropped before WB. Fixed with an explicit
   `valid` bit threaded through every register -- not a workaround, the
   actual textbook-correct fix `docs/hazards.md` had already flagged as
   missing.
2. A same-clock-edge race in every testbench's reset sequencing (not
   the RTL): deasserting `rst_n` on the same edge synchronous logic
   samples it on is simulator-defined, and finally got exercised by a
   free-running counter. Fixed project-wide (all six existing
   testbenches, not just the new one) with the standard `#1`-delay fix,
   with the full existing suite re-verified afterward.

Both are in `docs/pipeline.md` and `CHANGELOG.md` with full
explanations, continuing this project's practice of treating directed
testing as a real verification tool -- catching two more bugs here,
after two in Phase 5 and two in Phase 6 -- rather than a formality.

## Phase 8 — System-on-Chip Integration

**Status:** complete (see `README.md` checklist).

**What exists:** a bus-master refactor of `rtl/cpu/riscv_cpu_pipeline.sv`
(its data-memory interface is now an external `dbus_*` port instead of
an internally-instantiated `dmem`), a new memory-mapped bus and address
decoder (`rtl/bus/soc_bus.sv`), two new peripherals (`rtl/bus/uart.sv`,
`rtl/bus/gpio.sv`), a top-level SoC (`rtl/cpu/riscv_soc.sv`) tying CPU +
bus + RAM + UART + GPIO together, a real polling-driver test program
(`sim/programs/soc/soc_demo.s`) exercising all three peripherals through
the actual address decoder, and `sim/testbenches/tb_soc.sv`. Full detail,
including the exact memory map and every register, is in `docs/soc.md`.

**Why the CPU needed a refactor first, not just new peripherals:** the
pre-Phase-8 `riscv_cpu_pipeline.sv` owned its `dmem` directly -- there
was no bus for a UART or GPIO to share. Externalizing that interface as
a plain bus-master port is a pure port-list/wiring change (no ALU,
hazard, or control logic moved), which made it possible to verify as a
strict regression: every pre-existing testbench that talks to the CPU
directly was updated to wire a plain `dmem` to the new port itself
(functionally identical to what the CPU did internally before) and
re-run under both simulators, reproducing every one of Phase 7's exact
counter values unchanged before any new SoC code was written. Only once
that regression was clean did `soc_bus.sv`/`uart.sv`/`gpio.sv`/
`riscv_soc.sv` get built on top of it -- the same "verify the foundation
before building on it" discipline used for every prior phase.

**Design choice worth calling out:** RAM stays at address `0x00000000`,
not shifted to make room for peripherals at lower addresses, specifically
so every test program from Phases 2-7 (whose `LW`/`SW` addresses all
assume RAM starts at 0) keeps working unmodified through the real SoC
address decoder -- verified, not just assumed (see `docs/soc.md`'s
Verification section).

## Phase 9 — Hardware Accelerator

**Status:** complete (see `README.md` checklist).

**What exists:** `rtl/accelerator/accelerator.sv`, one FSM-driven
memory-mapped peripheral implementing the task's own vector-add ->
dot-product -> matrix-multiply progression as three opcodes on a shared
register interface (rather than three separate peripherals -- see
`docs/accelerator.md`'s rationale), wired into `rtl/bus/soc_bus.sv` at
`0x30000000`, plus two testbenches verifying it at different layers:
`tb_accelerator.sv` (direct MMIO, isolates the accelerator's own RTL)
and `tb_soc_accel.sv` (real RISC-V assembly run on the CPU, isolates
the CPU/bus path to it).

**Verification for this phase found two more real bugs, both
documented in full:**

1. A width-sizing bug caught in review, before any simulation ran: an
   early draft sized the `LEN` register for MATMUL's smaller bound
   (`MAX_DIM`) rather than VECADD/DOT's larger one (`MAX_LEN`), which
   would have silently truncated any vector length above 15. Fixed by
   sizing every FSM counter to the larger bound.
2. A testbench-driver same-edge race, the same general class as every
   prior same-edge race in this project but a new variant of it: the
   testbench's own blocking-assignment stimulus raced the DUT's
   `always_ff` block at the very edge meant to sample it, corrupting
   which scratchpad address received which write's data. Nonblocking
   assignment is the textbook fix and worked under Icarus Verilog, but
   Verilator explicitly warns that nonblocking assignment inside an
   `initial`-block task is executed as blocking there -- the two
   simulators disagreeing about what the code even means is
   disqualifying for this project's "both simulators must agree"
   methodology. Fixed instead with genuine simulation-time separation
   (a `#1` delay before touching any DUT input, not just before
   releasing it), which is unambiguous under any simulator and is the
   same technique already used for reset sequencing since Phase 7.

Both are in `docs/accelerator.md` and `CHANGELOG.md` with full
explanations, continuing this project's practice of treating directed
testing (and, in the first case, plain re-reading of the register map)
as real verification tools rather than formalities -- 11 substantive
bugs found and fixed across Phases 2-9 now, every one documented rather
than glossed over.

## Phase 10 — Custom RISC-V Extension for Accelerator Control

**Status:** complete (see `README.md` checklist).

**What exists:** four `ACCEL.*` instructions (`accel.vecadd`,
`accel.dot`, `accel.matmul`, `accel.stat rd`) on RISC-V's reserved
custom-0 opcode, decoded by `control_unit.sv` into a 3-bit `accel_sel`
signal threaded through `id_ex_reg`/`ex_mem_reg` alongside the ordinary
control signals, consumed by one new MEM-stage mux in
`riscv_cpu_pipeline.sv` that substitutes a hardwired address/data pair
for the ordinary ALU-computed one. See `docs/custom_extension.md` for
the full design rationale, especially why this extension deliberately
does NOT cover every accelerator register (only `CTRL`'s start pulse
and `STATUS`'s read, the two with fixed address/data per operation).

**Verification:** `sim/programs/soc/accel_custom_demo.s` is
deliberately a near-line-for-line copy of Phase 9's `accel_demo.s`,
with only the CTRL-write and STATUS-read instructions swapped for
their `ACCEL.*` equivalents, so a pass on both proves the custom
extension reaches the *same* accelerator behavior through a different
instruction path. Full Phase 2-9 regression re-run and clean after this
change (touching `control_unit.sv`'s port list and two shared pipeline
registers affects every instruction that flows through them).

**One build-tooling wrinkle, documented rather than silently worked
around:** adding a new `control_unit` output port required Phase 2's
single-cycle CPU (`riscv_cpu.sv`, which shares `control_unit.sv` but
predates the SoC bus this extension targets) to explicitly leave the
new port unconnected. Verilator's default lint flagged this two
different ways in succession (`PINMISSING` for the omitted port, then
`PINCONNECTEMPTY` for the explicit empty connection that fixed the
first warning) -- resolved by explicitly connecting the port to nothing
(the correct way to spell "intentionally unconnected" in SystemVerilog)
and suppressing the resulting, now-expected `PINCONNECTEMPTY` warning
in `scripts/run_sim_phase2.sh`'s Verilator invocation, with a comment
explaining why.

## Phase 11 — CPU vs. Accelerator Benchmarking

**Status:** complete (see `README.md` checklist).

**What exists:** six benchmark programs (CPU-only and accelerator-
driven versions of vecadd/dot/matmul, identical operands each pair), a
software `mul32` multiply routine RV32I's CPU-only kernels need (no M
extension implemented) verified in isolation first, a GPIO-sentinel-
based generic harness (`tb_benchmark_soc.sv`) that detects program
completion automatically instead of relying on a hand-picked cycle
count, and `results/accelerator_benchmark_report.md` generated by
`scripts/run_benchmarks_accel.py` from real simulation. See
`docs/benchmarking.md` for full methodology and results.

**Verification found one more real bug, documented in full:** the
first version of the CPU-only `dot`/`matmul` kernels used register x1
both as a data pointer and as `jal`'s return-address target,
corrupting the pointer after the first subroutine call and producing a
wrong-but-plausible result. Caught by
`sim/testbenches/tb_bench_cpu_correctness.sv` comparing against
Python-computed expected values, not by hand-checking the assembly.
See `docs/benchmarking.md` and `CHANGELOG.md`'s Phase 11 entry.

**Headline result:** vecadd shows a modest ~1.8x accelerator speedup
(RV32I already does addition natively); dot and matmul show ~5x and
~12x respectively, because RV32I has no hardware multiplier and the
CPU-only kernels pay for every multiplication in software. This
measured, honest gap -- not a favorable cherry-pick -- is exactly the
kind of data Phase 13's AI scheduler needs.

## Phase 12 — FPGA Synthesis Resource Estimates

**Status:** complete (see `README.md` checklist).

**What exists:** a full open-source synthesis flow (Yosys 0.33
targeting Lattice iCE40 via `synth_ice40`) run against every RTL
module individually plus the full `riscv_soc`, writing
`results/synthesis_report.md` with real, parsed cell counts. No
physical FPGA or hardware is used or claimed anywhere in this phase --
see `docs/synthesis.md`.

**Two real tooling problems solved, both documented in full rather
than silently worked around:**

1. Yosys's open-source Verilog frontend rejects `import pkg::*;`
   entirely (confirmed directly against the tool, in every placement
   and form tried). `scripts/prep_synth_rtl.py` stages a mechanically
   transformed copy of `rtl/` (never edits `rtl/` itself) with package
   references fully qualified instead -- a syntactic transformation
   only, per the SystemVerilog LRM.
2. An uninitialized instruction ROM let Yosys's optimizer
   const-propagate large parts of the CPU away as "don't care" --
   caught when a first attempt reported an implausibly small ~240-cell
   `riscv_soc` (smaller than the accelerator module synthesizes to
   *by itself*, over 17,000 cells). Fixed by loading the synthesis-only
   ROM stand-in (`synth/stubs/imem_synth_stub.sv`, kept outside `rtl/`
   and never simulated) with a real, instruction-diverse program.

**Scope decision:** place-and-route (`nextpnr-ice40`) was tried, not
skipped by default -- it failed on a small test module with a physical
I/O pin-budget error specific to an arbitrarily-chosen package, which
only has a real answer once an actual target board is chosen. Since
this project deliberately targets no physical hardware, inventing a
pin-constraint file just to get a number would mean fabricating
hardware context that doesn't exist; Yosys cell-count synthesis (which
the task's own Phase 12 description names) doesn't have this problem
and is this phase's real deliverable.

## Phase 13 — AI Workload Scheduler: Dataset + Trained Model

**Status:** complete (see `README.md` checklist).

**What exists:** a labeled dataset of 11 real measured
CPU-vs-accelerator workload comparisons (`scheduler/training/dataset.csv`,
`make collect_scheduler_dataset`) and a shallow, interpretable
`DecisionTreeClassifier` fit on it (`scheduler/training/train_scheduler.py`,
`make train_scheduler`), predicting which engine finishes a workload
faster from real measured cycle data -- not fabricated, estimated, or
hand-picked to make the ML problem look tidier. Full methodology,
including the matmul address-generation fix and the model's honest
limitations at n=11, is in `docs/scheduler.md`.

**Why this needed new benchmark programs:** Phase 11 measured exactly
one size per operation -- three data points total, not enough to fit
or evaluate anything. Twelve new-size programs were generated (not
hand-written, to avoid re-risking Phase 11's register-allocation bug
class) by `scheduler/benchmarks/gen_scheduler_programs.py`, each
independently verified for correctness (not just completion) against
Python-computed expected values before its timing was trusted
(`sim/testbenches/tb_scheduler_correctness.sv`, `make
test_scheduler_correctness`).

**Real finding, not an assumption:** testing the smallest possible
workload size (N=1) surfaced a genuine CPU-favorable crossover for
vecadd (37 CPU cycles vs. 39 accelerator cycles) that does not occur
for dot at the same size (RV32I's lack of a hardware multiplier makes
even one software multiply-accumulate cost more than the
accelerator's setup overhead). This is what keeps the scheduler's
decision boundary non-trivial -- see `docs/scheduler.md` and
`results/scheduler_report.md`.

**Shared feature extraction, forward-looking:** `scheduler/models/features.py`
is the single function both this phase's training and Phase 14's
runtime decision pipeline will call, specifically so a feature can
never silently differ between what the model was trained on and what
it sees at inference time.

**Honest scope:** 11 samples, 10 sharing one label, leave-one-out
cross-validated accuracy 9/11 = 0.818 (reported, not a same-data
number that would overstate generalization); the real vecadd crossover
point was narrowed to "somewhere in N=1..4" but not pinned down further
(N=2/N=3 were never simulated); the model is not yet wired into any
live scheduling decision -- that is Phase 14's job.

## Phase 14 — Scheduler Decision Pipeline + Accuracy Tracking

**Status:** complete (see `README.md` checklist).

**What exists:** `scheduler/inference/decide.py`, a callable decision
function (`decide(operation, size_n) -> "cpu"|"accelerator"`) wrapping
Phase 13's trained model, using the same shared
`scheduler/models/features.py:extract_features()` the model was
trained with so training and inference can never compute a feature
differently. `scheduler/inference/evaluate_accuracy.py` scores that
function against 9 workloads the model has never been fit on in any
form -- a genuinely held-out test, not another leave-one-out slice of
the same 11 training points. Full writeup: `docs/scheduler_pipeline.md`.

**Real result:** 8/9 held-out accuracy. The one miss (`vecadd N=2`,
predicted CPU, actually an accelerator win by 61 vs 50 cycles) is a
concrete, honestly reported instance of exactly the limitation Phase
13 documented -- the model's only small-`vecadd` split was learned
from a single training point (`N=1`) and extrapolated past the real
crossover, which this new data shows sits strictly between N=1 and
N=2. This was measured, not asserted: `sim/testbenches/tb_scheduler_heldout_correctness.sv`
verifies all 9 held-out workloads' actual computed results (18
`riscv_soc` instances) before their timing was trusted, under both
Icarus Verilog and Verilator.

**Scope decision:** the model is scored as Phase 13 shipped it, not
retrained on the newly discovered `vecadd N=2` point -- keeping this
phase's held-out evaluation an uncontaminated test of that exact
model, with incorporating the new point left as a clearly-flagged
future step rather than done reflexively.

## Phase 15 — Dynamic Runtime Scheduling

**Status:** complete (see `README.md` checklist).

**What exists:** `scheduler/runtime/gen_dynamic_scheduler_demo.py`
generates a single RISC-V program (`dynamic_scheduler_demo.s`) that
processes a fixed 6-workload stream in ONE simulated execution,
computing the CPU-vs-accelerator decision for each workload AT
RUNTIME with real RV32I instructions and a real conditional branch --
not an offline Python lookup like Phase 13/14. Three baseline programs
sharing the identical stream and per-block bodies (`always_cpu_demo`,
`always_accel_demo`, `oracle_demo`, the last generated from Phase
13/14's real measured data) let the dynamic scheduler's actual
overhead be measured, not estimated. Full writeup:
`docs/dynamic_scheduling.md`.

**Bug found and fixed:** a dynamically-decided block compiles BOTH its
CPU-path and accelerator-path bodies into the binary (only one runs,
per the branch, but the assembler must resolve both) -- giving them
the same label tag let their internal loop labels collide, corrupting
the unrun path's targets. Caught immediately by
`sim/testbenches/tb_dynamic_scheduler_correctness.sv` (the affected
block failed only in the dynamic program, not in the single-body
baseline programs using the identical body), fixed with per-path
suffixed tags, reconfirmed passing under both simulators.

**Real, honestly reported result:** the dynamic scheduler (492 cycles)
is SLOWER than the naive always-accelerator baseline (389 cycles) for
this workload stream -- not hidden or reframed. Two measured causes:
Phase 14's one known misprediction (`vecadd N=2`) costs real cycles
here too, and the runtime decision computation itself has a real,
non-zero cost (396 vs. 321 instructions retired, 37 vs. 17 flushes,
dynamic vs. oracle). The oracle baseline still beats always-accelerator
by 10 cycles, showing the idea has real value here -- it's the
combination of decision overhead and one wrong call that erases it for
a stream this small.

**Scope decision:** the workload stream and decision boundary are
fixed and small by design, to keep this phase's result cleanly
attributable; testing at larger/more varied scale is Phase 16's job.

## Phase 16 — Mixed Heterogeneous Workloads

**Status:** complete (see `README.md` checklist).

**What exists:** `scheduler/runtime/gen_mixed_workload_demo.py` reuses
Phase 15's per-block body generators, decision logic, and `mul32`
subroutine (imported, not copy-pasted) against a larger, 12-workload
stream (`vecadd` N=1,2,4,8,16,32; `dot` N=4,8,16,32; `matmul` N=2,4 --
roughly 4-32x Phase 15's average per-workload scale), to test whether
Phase 15's finding (decision overhead outweighs the benefit) holds at
a more realistic scale. Full writeup: `docs/mixed_workloads.md`.

**Real result:** dynamic scheduling is still slower than
always-accelerator (2590 vs. 2366 cycles, 9.5% worse) -- but that is a
large improvement over Phase 15's 26.5% worse on the small stream,
confirming that the decision's fixed per-block overhead matters
proportionally less as each workload grows. The more important
finding, though: the oracle baseline only beats always-accelerator by
10 cycles on this entire 12-workload stream, because in this project's
real measured data the accelerator wins almost every workload except
`vecadd` at N=1 -- so even a perfect, zero-overhead scheduler has very
little room to add value for this specific accelerator design and
these three kernels. This reframes Phase 15's result: the limiting
factor was never primarily overhead, but a narrow oracle-vs-baseline
ceiling.

**Scope decision:** `matmul N=8` (32885 CPU cycles standalone, by far
this project's largest measured single workload) was deliberately
excluded from the stream -- including it would let one outlier
dominate every program's total so completely that the four programs'
results would look nearly identical, obscuring rather than answering
the question this phase asked.

## Phase 17 — Final End-to-End Demo + Full Documentation

**Status:** complete (see `README.md` checklist).

**What exists:** `scripts/run_full_demo.sh` (`make demo`) runs every
phase's own verified test/build step in order -- Phase 2 through
Phase 16 -- and prints a consolidated summary of real headline numbers
pulled directly from each phase's own `results/*.md` report (never
retyped by hand into the script, so the summary can't drift out of
sync with what was actually measured). Phase 12's FPGA synthesis is
skipped by default (it is this project's slowest single step and
orthogonal to the scheduler results) and available via
`ARGS=--with-synthesis`. `docs/final_summary.md` is the project's
capstone document: headline findings from every phase, this project's
own honest conclusion about where its AI scheduler actually helps
(a narrow one), and why the specification's optional LLM layer was
deliberately not built.

**Real regression caught and fixed by running the whole pipeline
together for the first time:** Phase 13's and Phase 14's own
correctness scripts (`scripts/run_scheduler_correctness.sh`,
`scripts/run_scheduler_heldout_correctness.sh`) glob-assembled every
`.s` file in the shared `sim/programs/scheduler/` directory with a
fixed word-count budget sized for their own programs. Once Phase 15/16
added larger files to that same directory, the glob started trying (and
failing) to assemble programs neither script actually needed. This is
exactly the kind of cross-phase interaction a phase-by-phase test
suite, run only phase-by-phase, cannot catch -- caught here by
`scripts/run_full_demo.sh` itself, on its first real end-to-end run.
Fixed by having each script assemble only the exact files its own
testbench references, rather than glob the shared directory -- immune
to whatever later phases add there. See `CHANGELOG.md`'s Phase 17
entry.

**Scope decision:** the LLM layer named as optional in the original
specification was not built -- see `docs/final_summary.md` for the
full reasoning (no live LLM credential available to this simulated
environment to make a fabricated "AI decides" layer honest, and Phase
16's own finding that this system has little room for ANY scheduler,
however implemented, to add much value here).

This is the final phase of the original 17-phase specification.

## Post-v1 — AI Scheduler v2: Expanded Training Set

**Status:** complete. Tracked as a dated improvement in `CHANGELOG.md`,
not a renumbered phase -- the specification's 17 phases above are
unchanged.

**What exists:** `scheduler/training/train_scheduler_v2.py` merges
Phase 13's 11-workload `dataset.csv` and Phase 14's 9-workload
`heldout_dataset.csv` into one real 20-workload training set and
refits, saved as a separate artifact
(`scheduler/models/scheduler_tree_v2.pkl`) that does not change Phase
13's original model or `scheduler/inference/decide.py`'s default
behavior. A brand-new held-out set (`vecadd`/`dot` N=6, N=12,
correctness-verified and measured fresh) scores the retrained model
honestly, since Phase 14's old held-out set is now training data and
can no longer be used to claim generalization. Full writeup:
`docs/scheduler_v2.md`.

**Real result:** this directly fixes the `vecadd N=2` misprediction
Phase 14 found and explicitly left unfixed (to keep that phase's own
evaluation uncontaminated). Leave-one-out CV accuracy rose from 9/11 =
0.818 to 19/20 = 0.950; the fitted tree's split sharpened from
`element_count <= 2` (which wrongly covered `vecadd N=2`) to
`element_count <= 1` (which correctly isolates only the true
crossover, `vecadd N=1`) -- an explainable, not just numeric,
improvement.
