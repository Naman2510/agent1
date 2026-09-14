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

Later phases append their own sections here as they land.
