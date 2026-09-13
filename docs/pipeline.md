# Five-Stage Pipeline (Phase 5)

This document describes `rtl/cpu/riscv_cpu_pipeline.sv`, a five-stage
(IF / ID / EX / MEM / WB) pipelined implementation of the same RV32I
subset the single-cycle CPU (`rtl/cpu/riscv_cpu.sv`, Phase 2) implements.
It reuses every submodule Phase 2 already verified (decoder,
control_unit, regfile, imm_gen, alu, branch_unit, imem, dmem) unchanged
-- only the datapath wiring around them changes, split across four new
pipeline register modules in `rtl/pipeline/`. The single-cycle CPU is
left in place, not replaced, so Phases 2-4's tests keep passing against
it exactly as before.

## Why a new top-level module, not a rewrite of riscv_cpu.sv

The task says "replace/extend" the basic CPU with a pipeline. Extending
via a new top-level module (`riscv_cpu_pipeline`) rather than rewriting
`riscv_cpu.sv` in place:

- keeps `make sim_cpu`, `make test_isa`, and `make run_c_demo` (Phases
  2-4) working unmodified, so nothing already proven correct can regress
  silently while the pipeline is being built and debugged;
- lets a later phase (benchmarking, Phase 11) compare the single-cycle
  and pipelined CPUs directly, which would be impossible if one had
  overwritten the other;
- reflects that they are genuinely different microarchitectures
  implementing the same ISA, which is worth keeping visible in the
  repository rather than treating the pipeline as a patch.

## What Phase 5 does and does not handle

**Phase 5 builds the pipeline registers and the datapath split across
five stages.** It deliberately does **not** implement:

- **Forwarding/bypassing** for data hazards closer than what plain
  sequencing already handles (see below) -- that is Phase 6.
- **Load-use stalling** -- Phase 6.
- **Flushing** the pipeline after a taken branch or an unconditional
  jump -- Phase 6. Branch/JAL/JALR target computation and PC redirect
  *are* implemented and *are* correct (see "Control flow" below); what's
  missing is discarding the 2 instructions already fetched from the
  sequential path before the redirect takes effect. Those 2 wrong-path
  instructions will incorrectly continue through the pipeline and could
  commit register or memory writes.

This is not an oversight -- it is the explicit split in the task
between Phase 5 ("implement pipeline registers... document what
information is stored in every pipeline register") and Phase 6 ("Control
hazards: Branches must correctly flush or redirect the pipeline").
Phase 5's own test program (`sim/programs/pipeline_straightline.s`)
is deliberately restricted to straight-line code (no branches, no jumps)
with enough instruction spacing to avoid needing forwarding, so that
what it verifies is the pipeline plumbing itself, not hazard handling
that doesn't exist yet.

## Stage-by-stage datapath

```
   IF          ID            EX            MEM           WB
 +------+   +--------+   +---------+   +---------+   +---------+
 |  PC  |-->| decode |-->| ALU     |-->| dmem    |-->| wb mux  |--> regfile
 | imem |   | control|   | branch  |   |         |   |         |     (write
 +------+   | regfile|   | unit    |   |         |   |         |      port)
    ^       | imm_gen|   | (redir- |   |         |   |         |
    |       +--------+   |  ect to |   +---------+   +---------+
    |                    |  PC)    |
    +--------------------+---------+
      redirect target (EX -> IF, same cycle)
```

- **IF**: PC register (explicit `= 32'b0` initializer, same rationale as
  `riscv_cpu.sv` -- avoids an X window before the first clock edge), PC+4
  adder, instruction memory read.
- **ID**: field decode (`decoder.sv`), control signal generation
  (`control_unit.sv`), register file read (`regfile.sv`), immediate
  generation (`imm_gen.sv`).
- **EX**: ALU (`alu.sv`), branch condition evaluation (`branch_unit.sv`),
  branch/JAL target address (`pc + imm`), and the PC redirect decision
  that feeds back to IF.
- **MEM**: data memory access (`dmem.sv`).
- **WB**: 3-way writeback mux (ALU result / memory read data / PC+4),
  register file write port.

## Pipeline register contents

Each register module's file header documents every field and why it's
there; summarized here:

| Register | Fields | Why |
|---|---|---|
| `if_id_reg` | `pc`, `pc_plus4`, `instr` | Everything ID needs to decode and compute the immediate/branch target. |
| `id_ex_reg` | `pc`, `pc_plus4`, `rs1_data`, `rs2_data`, `imm_out`, `rd_addr`, `rs1_addr`, `rs2_addr`, `funct3`, all control signals, `instr` (debug only) | Operands and control for EX; `rs1_addr`/`rs2_addr` (not their *values*) are carried through unused in Phase 5 specifically so Phase 6's forwarding unit can compare them against downstream `rd_addr`s without changing this register's port list again. |
| `ex_mem_reg` | `pc_plus4`, `alu_result`, `rs2_data` (store data), `rd_addr`, `reg_write`, `mem_read`, `mem_write`, `result_src`, `illegal`, `instr` (debug only) | What MEM and WB still need; `branch`/`jal`/`jalr`/`funct3` stop at EX since nothing downstream uses them again. |
| `mem_wb_reg` | `pc_plus4`, `alu_result`, `mem_rdata`, `rd_addr`, `reg_write`, `result_src`, `illegal`, `instr` (debug only) | What WB needs for its writeback mux and register write. |

The `instr` (raw instruction word) debug-only field carried through
`id_ex_reg`/`ex_mem_reg`/`mem_wb_reg` is not read by any functional
logic -- it exists purely so `sim/testbenches/tb_pipeline.sv` can print
which instruction occupies every stage each cycle, directly
demonstrating pipelined concurrency (see "Verified behavior" below).

Every register clears every control signal to its inactive value (0) on
reset, which is what makes an empty pipeline stage a safe no-op bubble:
`reg_write=0`, `mem_read=0`, `mem_write=0`, `branch=0`/`jal=0`/`jalr=0`
mean nothing observable happens for a bubble, without needing a separate
explicit "valid" bit in Phase 5.

## A same-clock-edge race, found and fixed during this phase's own verification

The first version of `pipeline_straightline.s` used a 2-instruction gap
between a producer and a dependent consumer, reasoning (from the classic
"write in the first half of the cycle, read in the second half"
textbook description of pipelined register files) that this should be
enough for a producer's WB-stage write to be visible to a consumer 3
positions behind it, with no forwarding hardware.

**That textbook result assumes the register file's write is clocked on
a different edge (or half-cycle) than the pipeline registers that
capture the read.** This design's `regfile.sv` (reused unchanged from
Phase 2) writes on `posedge clk` with a nonblocking assignment --
*the same edge* that `id_ex_reg` uses to capture its own read of that
same register file. When a producer's WB and a consumer's ID land in the
same cycle, both the register file's write and `id_ex_reg`'s capture of
the read value are nonblocking assignments evaluated on the *same*
clock edge. Per Verilog's scheduling semantics, nonblocking-assignment
RHS values for every block sensitive to an edge are evaluated using
*pre-edge* signal state, regardless of whether that block happens to be
the one doing the writing or the one doing the reading -- so `id_ex_reg`
captures the *old* register value, not the value the write is
committing this same edge.

This was not caught by reasoning about it -- it was caught by running
the test: a first attempt with 2-instruction spacing failed 6 of 19
checks, every failure being exactly a 2-instruction-gap dependency (a
3-instruction gap, one more than the failing case, passed in every
instance, including the same instruction pair in the same file). The
fix was to require a 3-instruction gap (4 positions behind the
producer), verified by rerunning: all 19 checks pass, identically under
Icarus Verilog and Verilator. The code comment in
`riscv_cpu_pipeline.sv` explaining this was corrected to match, and this
document states the corrected number, not the originally-assumed one.

This is exactly the kind of subtlety Phase 6's forwarding unit exists to
remove: once forwarding is added, a 1-instruction gap (or even 0, for
everything except loads) will work correctly without the programmer (or
compiler) needing to reason about clock-edge races at all.

## Control flow: what works, what doesn't yet

Branch condition evaluation, branch/JAL target computation (`pc + imm`),
and JALR's target (`(rs1+imm) & ~1`) are all computed correctly in EX,
and `next_pc` **is** correctly redirected the cycle after EX resolves a
taken branch or any JAL/JALR. What is missing is discarding the 2
instructions already in IF and ID (fetched from the sequential path)
at the moment of redirect -- Phase 6 flushes those by turning them into
bubbles. Because of this, Phase 5's own test program contains no
branches or jumps at all (see its file header for the full reasoning);
proving branches/jumps execute *correctly through the pipeline* is
Phase 6's verification job, once flushing exists to make that true.

## Verified behavior (Phase 5)

`sim/testbenches/tb_pipeline.sv` runs `pipeline_straightline.s` and
checks 19 final register values (R-type and I-type ALU ops including
shifts, LUI, AUIPC, a store/load round-trip, and x0's hard-wire
behavior), all correctly computed despite -- and because of --
instructions overlapping in the pipeline. It also prints a full
five-stage trace every cycle; an excerpt showing three different
instructions genuinely occupying three different stages at once
(`sub x6,x4,x5` moving from EX to MEM to WB while `andi`/`ori`/`xori`
follow behind it) -- unedited output:

```
  t=126000  IF=0x40520333(sub) ID=0x00000013(nop)   EX=0x00000013(nop)   MEM=0x00000013(nop)   WB=0x00300293(li x5,3)
  t=136000  IF=0x00f0f393(andi) ID=0x40520333(sub)  EX=0x00000013(nop)   MEM=0x00000013(nop)   WB=0x00000013(nop)
  t=146000  IF=0x00116413(ori)  ID=0x00f0f393(andi) EX=0x40520333(sub)   MEM=0x00000013(nop)   WB=0x00000013(nop)
  t=156000  IF=0x0ff0c493(xori) ID=0x00116413(ori)  EX=0x00f0f393(andi) MEM=0x40520333(sub)    WB=0x00000013(nop)
  t=166000  IF=0x00000013(nop)  ID=0x0ff0c493(xori) EX=0x00116413(ori)  MEM=0x00f0f393(andi)   WB=0x40520333(sub)
```

Run it with:

```bash
make sim_pipeline
# or directly:
./scripts/run_sim_pipeline.sh
```

Like every other phase's simulation, this runs under **both** Icarus
Verilog and Verilator, and both must (and do) agree exactly.
