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

Later phases append their own sections here as they land.
