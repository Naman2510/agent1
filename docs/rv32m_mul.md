# Decode Validation Fix + Optional RV32M `MUL` (post-v1)

Every scheduler result in this project traces back to one fact:
RV32I has no multiply instruction, so every CPU-side product in `dot`
and `matmul` is a ~10-instruction software routine (`mul32`), and the
accelerator wins almost everything. This change adds an optional
hardware `MUL` to the pipelined CPU so that fact can be varied and
measured, rather than only assumed. Adding it exposed a real decode bug
first, which had to be fixed before `MUL` could be added safely.

## Bug found and fixed: `funct7` was never validated

`rtl/cpu/control_unit.sv` decoded `OP` (R-type) instructions from
`funct3` and **only bit 5 of `funct7`**. So any `OP` encoding with a
`funct7` RV32I doesn't define, including every RV32M encoding, was
silently executed as whichever RV32I operation its `funct3`/`funct7[5]`
happened to select. A real `mul` ran as `ADD`, with `illegal` never
raised. The shift-immediates (`SLLI`/`SRLI`/`SRAI`) had the same gap in
`instr[31:25]`. That contradicts what `docs/datapath.md` says the
`illegal` flag is for: the CPU must never be found "silently executing
the ALU's default-case behavior as if it meant something".

**How it was caught:** `sim/testbenches/tb_control_unit_decode.sv`
sweeps every `funct3` × `funct7` value of both `OP` and `OP-IMM`
(1,024 encodings each) on two control units (`ENABLE_MUL=0` and `1`).
It checks `illegal`, `reg_write` and `alu_op` against a reference
decoder written independently from the spec. Run against the
unmodified control unit, it reported **2,534 failures out of 4,096
checks**. That is exactly the number the spec predicts: per setting,
1,014 invalid `OP` encodings plus 253 invalid shift-immediate
encodings were accepted as legal.

**Fix:** `OP` is legal only for `funct7 = 0000000` (all `funct3`) or
`0100000` with `funct3 = 000/101` (`SUB`/`SRA`). The shift-immediates
require `0000000` (`SLLI`/`SRLI`) or `0100000` (`SRAI`). Anything else
raises `illegal` and writes no register. After the fix, all 4,096
checks pass on both Icarus Verilog and Verilator.

**Cost and impact:** the control unit goes from 38 to 50 iCE40 cells;
the full SoC from 38,390 to 38,464 (+0.19%); the pipelined CPU's total
is unchanged at 5,923 (`results/synthesis_report.md`, re-generated).
No program this project runs is affected: the assembler and GCC only
emit valid encodings, and the full `make demo` regression passes with
every measured number unchanged.

## Same gap in four more opcodes: full decode-space sweep

The first sweep covered only `OP` and `OP-IMM`. Widening
`tb_control_unit_decode.sv` to the **entire decode space** (every
opcode × `funct3` × `funct7`, 131,072 encodings per `ENABLE_MUL`
setting, 262,144 checks) found the same bug class in four more
opcodes. The widened sweep also checks that an illegal encoding drives
no side effect at all (no register write, memory access, branch, jump
or accelerator operation), and that each legal one drives exactly the
signals its instruction needs.

| Opcode | What the core did | Invalid encodings |
|---|---|---|
| `LOAD` | never checked `funct3`: `LB`/`LH`/`LBU`/`LHU` executed as `LW` | 896 |
| `STORE` | never checked `funct3`: `SB`/`SH` executed as `SW` -- a full-word write that clobbers the neighbouring bytes | 896 |
| `BRANCH` | `funct3` 010/011 (undefined) decoded as a branch the branch unit never takes -- a silent no-op | 256 |
| `JALR` | never checked `funct3` | 896 |

Before running it against the unmodified RTL, the expected count was
computed from the spec: 2,944 invalid encodings per setting, 5,888 in
total. The sweep reported **exactly 5,888 failures**; every other
encoding already decoded correctly, including all 128 opcodes'
illegal/legal split, `LUI`/`AUIPC`/`JAL`, and the custom accelerator
instructions. After the fix all 262,144 checks pass on both Icarus
Verilog and Verilator. The legal-encoding count the testbench reports
(5,517 without `MUL`, 5,518 with) also matches a hand tally of the spec.

The byte/halfword loads and stores were already documented as not
implemented (`docs/riscv.md` §4). What was wrong is that they still
executed, as word accesses. No program in this project uses them: the
assembler has no mnemonics for them, and the Phase 4 GCC-compiled C
program uses only `lw`/`sw` (checked in its disassembly).

**Cost (synthesis re-run):** the control unit goes from 50 to 59 iCE40
cells (38 at Phase 12), and the full SoC from 38,464 to 38,528 (38,390
at Phase 12: +0.36% for both decode fixes together). The standalone
pipelined CPU came out *smaller*, 5,923 → 5,848 cells. That is reported
as measured: a likely cause is that invalid encodings no longer drive
any side effect, which gives Yosys more freedom to optimize, but it
wasn't investigated further. `results/synthesis_report.md` is
regenerated.

## Optional `MUL`

- **`ENABLE_MUL` parameter, default 0**, on `control_unit`, `alu`,
  `riscv_cpu_pipeline` and `riscv_soc`. With 0 the core is exactly the
  RV32I core every earlier phase measured. `MUL` (and the rest of
  RV32M) decodes as illegal, and synthesis constant-folds the
  multiplier away: the ALU stays at 843 cells, identical to before.
  The single-cycle CPU (`riscv_cpu.sv`) keeps the default.
- **With 1**, `OP funct7=0000001 funct3=000` decodes as `MUL` (low 32
  bits of `rs1 * rs2`), computed combinationally in the ALU in the EX
  stage like any other ALU op. Forwarding, stalls and flushes need no
  changes. `MULH*`, `DIV*` and `REM*` stay illegal: this is `MUL`
  only, not RV32M.
- **Area:** the ALU grows from 843 to 2,225 iCE40 cells (+1,382, all
  LUT4/CARRY). The default `synth_ice40` flow targets iCE40 parts
  without DSP blocks, so this is a LUT-built 32×32 multiplier; a part
  with `SB_MAC16` DSP blocks would be far cheaper. Only the ALU was
  re-synthesized with `ENABLE_MUL=1`.
- **Assembler:** `scripts/asm_to_hex.py` gained `mul`. Its encodings
  were checked against GNU `riscv64-unknown-elf-as -march=rv32im` and
  match bit for bit.

## Verification (`make test_mul`)

`scripts/run_mul_test.sh` runs three testbenches, each on both Icarus
Verilog and Verilator:

1. `tb_control_unit_decode.sv`: the exhaustive decode sweep above.
2. `tb_mul.sv`: `sim/programs/mul/mul_test.s` on the pipelined CPU in
   the full SoC, built both ways. With `ENABLE_MUL=1`, every product is
   correct (negative operands, low-32-bit wraparound, back-to-back
   dependent `mul`s through EX→EX forwarding, MEM→EX forwarding, a
   load-use stall into a `mul`, a branch on a `mul` result), `mul x0`
   leaves x0 reading 0 with no stale forwarding, and no instruction is
   illegal. With `ENABLE_MUL=0`, exactly 11 illegal instructions reach
   EX (one per `mul`), and every destination keeps its sentinel.
3. `tb_mul_kernels_correctness.sv`: the 14 hardware-`MUL` dot/matmul
   kernels (below), checked against Python-computed results.

Two test-design pitfalls came up along the way, and both concern the
pipeline's pre-existing observability rather than the RTL being tested.
First, the regfile's storage slot for x0 is never written and reads as
`X`, so x0 has to be checked through the real read path. Second, the
pipeline's bubbles are the all-zero word, which decodes as illegal
(already documented in `tb_pipeline_directed_test.sv`), so `tb_mul.sv`
counts only non-bubble illegal instructions reaching EX.

## Hardware-`MUL` CPU kernels

`scheduler/benchmarks/gen_mul_programs.py` derives `dot` (N = 1, 2, 3,
4, 6, 8, 12, 16, 32, 64) and `matmul` (N = 1, 2, 4, 8) kernels from the
already-verified Phase 13 templates. It makes exactly one substitution,
`jal x1, mul32` → `mul x10, x11, x12`, which is the same operation at
that call site, and removes the now-unreachable `mul32` routine. Both
edits are asserted to match exactly once. `sim/testbenches/tb_benchmark_soc.sv`
gained an `ENABLE_MUL` parameter (default 0) and prints a separate
`BENCHMARK_CONFIG` line naming the core it measured. That line is
needed because an illegal `mul` still occupies its pipeline slot, so
cycle counts alone can't show which core ran.

## Result: a multiplier closes the multiply gap, and almost nothing else

```
make collect_mul_dataset
```

`scheduler/benchmarks/collect_mul_dataset.py` re-measures all 24
workloads with real data (vecadd/dot N = 1..64, matmul N = 1..8) on
the `ENABLE_MUL=1` SoC. It asserts that every run's harness reports
that core. It also asserts that the 34 programs which never multiply
(CPU `vecadd` and every accelerator program) measure exactly the same
cycle counts as in the RV32I datasets, which they do. Full table:
`results/mul_benchmark_report.md`; data:
`scheduler/training/dataset_mul.csv`.

- **The CPU gets much faster where it multiplies:** `dot` 1.8-3.6x
  (N=64: 5,270 → 1,484 cycles), `matmul` 1.5-3.2x (N=8: 32,885 →
  10,237).
- **It flips exactly one workload.** `dot` N=1 becomes a CPU win (35
  vs. 39 cycles). The CPU now wins 2 of 24 workloads instead of 1
  (`vecadd` N=1 was already a CPU win). The accelerator still wins
  the other 22, including every `dot` with N ≥ 2 and every `matmul`.
- **Why:** with the multiplier, the accelerator's lead on `dot` lands
  within 5% of its lead on `vecadd` at every size (e.g. N=64: 1.87x vs.
  1.96x), down from 1.64-6.65x without it. The software multiply was
  the entire extra gap on `dot`. What remains is the per-element loop,
  address and load/store overhead the accelerator beats even on plain
  additions, and a multiplier doesn't touch that. `matmul` keeps a
  bigger lead (2.6x at N=2, 7.0x at N=8) because its innermost loop
  pays that overhead N³ times.

For the scheduler, this is the counterfactual every earlier phase
pointed at, now measured: giving the CPU the instruction it was missing
roughly doubles the size of the CPU-favorable region (one more
workload shape), but it stays confined to the smallest possible problem
size. The conclusion of Phases 15-16 and `docs/scheduler_v2.md` holds
with a multiplier too: on this accelerator, "always use the
accelerator" stays close to optimal, because the accelerator's
advantage comes from loop overhead, which a multiplier doesn't touch.

## Data fix found while writing this

`collect_dataset.py`, `collect_heldout_dataset.py` and
`collect_scheduler_v2_heldout_dataset.py` (Phases 13, 14 and scheduler
v2) stored regex group 7 of the harness's `BENCHMARK_RESULT` line in
the `forwarding_events` column. Group 7 is `load_use_stall`;
forwarding is group 8. Every committed `dataset*.csv` therefore held
load-use stall counts under that name; for example, CPU `vecadd` N=16
showed 16 instead of the 200 that Phase 11's report prints for the same
program. All three scripts are fixed and the CSVs regenerated. Only
that column changed (checked column by column), and nothing reads it:
the models train on cycle counts and the size/operation features in
`scheduler/models/features.py`. So no model, accuracy figure or report
number was affected.
