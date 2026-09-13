# Single-Cycle CPU Datapath (Phase 2)

This document describes the single-cycle RV32I CPU implemented in
`rtl/cpu/riscv_cpu.sv`. One instruction fetches, decodes, executes,
accesses memory, and writes back within a single clock cycle -- there is
exactly one instruction in flight at any time, so no forwarding, stalling,
or flushing exists yet (see `docs/architecture.md` for why a single-cycle
design comes before the pipeline).

## Block diagram

```
                +-----+     PC      +-------+  instr   +---------+
   rst_n -----> | PC  |------------>| IMEM  |--------->| DECODER |---> opcode,funct3,funct7,rd,rs1,rs2
         +----->| reg |             +-------+          +----+----+
         |      +--+--+                                     |
         |         |  pc_plus4 = pc+4                        v
         |         |                                  +-------------+
         |         |                                  | CONTROL UNIT|--> reg_write, alu_src_a/b,
         |         |                                  +-------------+    imm_type, alu_op, mem_r/w,
         |         |                                                     result_src, branch, jal, jalr
         |         |
         |         |        rs1_addr,rs2_addr,rd_addr        +----------+
         |         +---------------------------------------->| REGFILE  |--- rs1_data --+
         |                                                    | (x0=0)   |--- rs2_data --+--------+
         |                                                    +----+-----+               |        |
         |                                                         ^                      |        |
         |                                                         | rd_wdata (writeback   |        |
         |                                                         | mux, below)           |        |
         |                                        instr    +--------------+                |        |
         |                                      ----------->|  IMM_GEN     |--- imm_out ----+--+     |
         |                                       imm_type   +--------------+                  |     |
         |                                                                                     v     v
         |                                              +---------+   alu_a (pc or rs1)   +---------+
         +--------------------------------------------->| alu_src |------------------------|         |
         (pc, for AUIPC)                                | _a mux  |                        |   ALU   |---> alu_result --+
                                                          +---------+   alu_b (rs2 or imm)   |         |                 |
                                                          +---------+------------------------+---------+                 |
                                                          | alu_src |                                                    |
                                              rs2_data -->| _b mux  |<-- imm_out                                          |
                                                          +---------+                                                    |
                                                                                                                          |
              rs1_data,rs2_data,funct3                                                                                   |
         +--------------------------------------------------------------------------------+                             |
         |                                    +--------------+                            |                             |
         +----------------------------------->| BRANCH UNIT  |--- branch_taken ------------+---> pc_src logic            |
                                               +--------------+                                  (see below)            |
                                                                                                                          |
                                              alu_result (address), rs2_data (store data)                               |
                                     +-----------------------------------------------------------------+                |
                                     |                                                                  v                |
                                     |                                                             +---------+           |
                                     +------------------------------------------------------------>|  DMEM   |---> dmem_rdata
                                                                                                     +---------+           |
                                                                                                                          |
                     +----------------------------------------------------------------------------------------------------+
                     |                       +--------------------------+
                     +---------------------->|  writeback mux           |
                                              |  result_src selects:     |
                                              |   00 alu_result          |----> rd_wdata --> REGFILE.rd_data
                                              |   01 dmem_rdata          |
                                              |   10 pc_plus4            |
                                              +--------------------------+
```

(A literal box-and-wire rendering is intentionally kept ASCII, not a
separate image, so it stays in the same file as its explanation and never
goes stale relative to the code -- see the module list below for where
each block actually lives.)

## Modules and where each lives

| Block | File | Notes |
|---|---|---|
| PC register + adders | `rtl/cpu/riscv_cpu.sv` | `pc`, `pc_plus4 = pc+4`, `pc_target = pc + imm_out` |
| Instruction memory | `rtl/memory/imem.sv` | Combinational read, `$readmemh`-initialized |
| Decoder (field extraction) | `rtl/decoder/decoder.sv` | Purely positional bit extraction, no interpretation |
| Control unit | `rtl/cpu/control_unit.sv` | All control signals, derived from opcode/funct3/funct7 |
| Register file | `rtl/regfile/regfile.sv` | 2 async read ports, 1 sync write port, x0 hardwired |
| Immediate generator | `rtl/decoder/imm_gen.sv` | One case per format, per docs/riscv.md §2.1 |
| ALU | `rtl/alu/alu.sv` | All R/I-type ALU ops plus internal ADD/PASSB uses |
| Branch unit | `rtl/cpu/branch_unit.sv` | Evaluates BEQ/BNE/BLT/BGE/BLTU/BGEU directly on rs1/rs2 |
| Data memory | `rtl/memory/dmem.sv` | Sync write, combinational gated read |
| Writeback mux, next-PC mux | `rtl/cpu/riscv_cpu.sv` | See below |

## Control signals (produced by `control_unit.sv`)

| Signal | Meaning |
|---|---|
| `reg_write` | Write `rd_wdata` into `rd` this cycle |
| `alu_src_a` | ALU input A: 0 = `rs1_data`, 1 = `pc` (AUIPC only) |
| `alu_src_b` | ALU input B: 0 = `rs2_data`, 1 = `imm_out` |
| `imm_type` | Which immediate format `imm_gen` should assemble |
| `alu_op` | Which operation the ALU performs (`riscv_pkg.sv` `ALU_*`) |
| `mem_read` / `mem_write` | Data memory access this cycle (LW / SW) |
| `result_src` | Writeback source: 00 = ALU, 01 = data memory, 10 = PC+4 |
| `branch` | This is a BRANCH instruction (target decided by `branch_taken`) |
| `jal` / `jalr` | This is JAL / JALR (both write PC+4 to `rd`) |
| `illegal` | Opcode not in docs/riscv.md §3.8 -- diagnosed, not executed |

## Key design decisions

**Why does the ALU have an `alu_src_a` mux (PC vs rs1) instead of only
`rs1`?** AUIPC's result is `PC + (imm << 12)` -- there is no register
operand at all for the base of that add. Rather than adding a second,
mostly-idle adder just for AUIPC, the existing ALU is reused by feeding
it `PC` on the `A` input for that one opcode. This is the standard
approach used in reference single-cycle RISC-V designs (e.g. Harris &
Harris, *Digital Design and Computer Architecture: RISC-V Edition*) and
keeps exactly one adder/ALU doing all arithmetic.

**Why is there a separate `pc_target = pc + imm_out` adder instead of
routing branch/JAL targets through the main ALU?** Branch resolution
(`branch_unit.sv`) needs `rs1_data`/`rs2_data` for the *comparison* in the
same cycle that the *target* (`pc + imm`) is being computed -- if the
target computation also needed the ALU, the ALU would be doing two
unrelated jobs (comparison operands vs. PC-relative address) in the same
cycle for a single instruction, which isn't possible with one ALU. A
second, dedicated adder for PC-relative targets avoids that conflict.
This mirrors how real single-cycle/pipelined RISC-V implementations
separate "ALU operations" from "branch target computation."

**Why does JALR reuse the main ALU instead of the dedicated PC adder?**
JALR's target is `(rs1 + imm) & ~1`, which is exactly a register+immediate
add -- something the main ALU already computes for every I-type
instruction, and JALR doesn't need to route rs1/rs2 through the branch
comparator. Control unit sets `alu_src_a=0` (rs1), `alu_src_b=1` (imm),
`alu_op=ADD` for the `JALR` opcode, so `alu_result` already equals the raw
target; the CPU top level only has to mask bit 0 (`{alu_result[31:1],
1'b0}`) before loading it into PC, per the ISA's JALR bit-0-clear rule.

**Why does LUI use an ALU op (`ALU_PASSB`) instead of bypassing the ALU
entirely?** `docs/riscv.md` deliberately does not define `ALU_PASSB` as an
ISA-level operation -- it is a microarchitectural convenience so that the
writeback mux only ever needs one "ALU result" input rather than a fourth
mux input just for LUI. `alu_src_b=1` puts the U-type immediate on the
ALU's B input, and `ALU_PASSB` makes the ALU output exactly that value.

**Why is illegal-opcode handling a `illegal` flag rather than a trap?**
Per `docs/riscv.md` §4 and `CHANGELOG.md`, this project has no CSR/trap
architecture yet (deliberately out of scope until a later phase, if ever
added). An opcode outside the supported set therefore can't be trapped to
a handler that doesn't exist; instead, `control_unit.sv` raises `illegal`
so simulation (and later, performance counters) can observe and fail on
it, rather than the CPU silently executing the ALU's default-case
behavior as if it meant something.

## Verified behavior (Phase 2)

`sim/testbenches/tb_riscv_cpu.sv` runs `sim/programs/phase2_bringup.s`
(assembled by `scripts/asm_to_hex.py`) through the CPU and checks the
final architectural register state against hand-computed expected values,
covering: R-type ALU ops (ADD/SUB/AND/OR/XOR/SLT), I-type ALU ops
including shifts (ADDI/SLLI/SRLI), LUI, AUIPC, SW/LW (store then
load-back), x0 hard-wire behavior (an attempted write to x0 followed by
`add x18, x0, x0`, which only reads back 0 if both the write was
discarded *and* x0 still reads as zero), a taken branch (BEQ) that must
skip a "poison" instruction if control flow is wrong, and a JAL/JALR
call-return pair. It also asserts `illegal` is never raised for this
program.

Run it with:

```bash
make sim_cpu
# or directly:
./scripts/run_sim_phase2.sh
```

This assembles the program and runs the same testbench under **two
independent tools** -- Icarus Verilog and Verilator -- and requires both
to report `RESULT: ALL CHECKS PASSED`. Both currently pass.

**A note on an Icarus Verilog diagnostic:** compiling this design under
Icarus Verilog 12.0 prints repeated messages of the form `sorry: constant
selects in always_* processes are not currently supported (all bits will
be included)` for bit-selects inside `always_comb` blocks (e.g.
`imm_gen.sv`'s per-format case, `control_unit.sv`'s `funct7[5]` check).
This is a documented Icarus limitation in how it internally represents
certain constant bit-selects for its synthesis-oriented backend -- it is
not a simulation correctness issue: the compiler still exits 0, and this
project's testbench (which independently hand-computes every expected
register value from the source program) passes every check under Icarus
*and* passes identically under Verilator, a completely independent tool
with a different internal representation. If Icarus were silently
computing a wrong bit-select, the two tools would not agree bit-for-bit
on every one of the checks in `tb_riscv_cpu.sv`, including values that
depend on exactly the constructs the message flags (sign-extended
immediates, the `funct7[5]` SUB/SRA select, ALU shift amounts, and the
JALR bit-0 mask). This is called out explicitly here rather than
suppressed, per this project's rule against hiding tool behavior.
