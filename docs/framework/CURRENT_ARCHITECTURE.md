# Current Architecture (as audited, 2026-10-03)

This describes what the repository implements **today** (commit `a938891`), as
read from the code. It is the baseline the framework work must preserve.
Planned work is in `EXTENSIBILITY_ROADMAP.md`, not here.

## 1. Hardware (RTL, `rtl/`) -- unchanged by the framework work

| Block | File | What it is |
|---|---|---|
| CPU | `rtl/cpu/riscv_cpu_pipeline.sv` | RV32I, 5-stage pipeline, full forwarding, load-use stall, branch flush; optional RV32M `MUL` only (`ENABLE_MUL`, default 0) |
| Decode | `rtl/cpu/control_unit.sv` | Validates opcode x funct3 x funct7 exhaustively (262,144-check sweep); custom-0 `accel.*` instructions |
| SoC | `rtl/cpu/riscv_soc.sv`, `rtl/bus/soc_bus.sv` | `addr[31:28]` decode: RAM `0x0`, UART `0x1`, GPIO `0x2`, accelerator `0x3` |
| RAM | `rtl/memory/dmem.sv` | Word-addressed; the co-scheduler testbenches instantiate 4,096 words (16 KiB). Addresses beyond the depth **alias** (high bits ignored) |
| IMEM | `rtl/memory/imem.sv` | Separate instruction memory; 1,024 words by default, 4,096 for co-scheduler programs |
| Accelerator | `rtl/accelerator/accelerator.sv` | Memory-mapped FSM, one operation at a time, `MAX_DIM=8`, `MAX_LEN=64` |
| Perf counters | `rtl/cpu/perf_counters.sv` | cycles, retired, stalls, branches, load-use, forwarding, flushes |

### Accelerator contract (the only accelerator that exists)

| Offset (from `0x3000_0000`) | Register | Semantics |
|---|---|---|
| `0x0000` | CTRL (W) | bit0 START, bits[2:1] op: 01 VECADD, 10 DOT, 11 MATMUL; START ignored while busy |
| `0x0004` | STATUS (R) | bit0 BUSY, bit1 DONE, bit2 ERR (LEN=0 or LEN above bound: op skipped) |
| `0x0008` | LEN (R/W) | N for VECADD/DOT (1..64); matrix side for MATMUL (1..8); write ignored while busy |
| `0x000C` | RESULT (R) | DOT scalar result |
| `0x1000..` | VECA | 64 words, operand A |
| `0x2000..` | VECB | 64 words, operand B |
| `0x3000..` | VECOUT | 64 words, VECADD output / MATMUL row-major output |

Custom-0 instructions (`scripts/asm_to_hex.py`): `accel.vecadd`, `accel.dot`,
`accel.matmul` (each = write CTRL with START + op), `accel.stat rd` (read STATUS).

**Numerics (from the RTL, not assumed):** all three operations are 32-bit
two's-complement integer arithmetic **modulo 2^32**. VECADD wraps. DOT and MATMUL
form the full signed 64-bit product and accumulate in a 64-bit register, but only
the **low 32 bits** are stored, which is the same as wrapping at every step. There is no
saturation, no rounding mode, no high-product word and no fixed-point scaling.
Consequence: a Q-format multiply (which needs bits above 31 of the product) cannot
be done on the accelerator except where the operands are small enough that the
scaled product fits in 32 bits.

**Concurrency model:** once START is written, the FSM runs on its own scratchpads
(one element / one MAC per cycle). The CPU may do anything that does not
rewrite VECA/VECB/LEN/CTRL of this accelerator. RAM is a separate path, so CPU
tasks that touch only RAM can run during the busy window. That fact is the
basis of the co-scheduler.

## 2. Software stack around the hardware

```
scheduler/benchmarks, scheduler/training, scheduler/models, scheduler/inference
   Phases 13-14 + v2: datasets of measured (op, N, engine) cycles, a decision-tree
   model, held-out accuracy evaluation
scheduler/runtime
   Phases 15-16 + v2/lean: one RISC-V program that decides the engine per task at
   run time on the CPU.  ALSO the home of the per-task code bodies
   (CPU_BODY, ACCEL_BODY, MUL32 in gen_dynamic_scheduler_demo.py) that the
   co-scheduler reuses.
scheduler/coschedule            <- the subject of the framework work
   codegen.py   streams, output layout, reference values, program generation
   planner.py   cost model + local search + exhaustive optimum
   run.py       profile -> plan -> generate -> verify -> measure -> report/score
```

## 3. The co-scheduler pipeline (`make coschedule` -> `scheduler/coschedule/run.py`)

```
            +-------------------------- per core: rv32i (ENABLE_MUL=0), mul (ENABLE_MUL=1)
            v
 1 PROFILE  each of the 24 (op, N) tasks as a one-task program, CPU and accelerator
            tb_accel_phase_probe.sv -> total cycles + accelerator busy interval
            -> profile_{core}.csv : cpu, acc, busy (cycles, minus empty-program base=8)
 2 PLAN     per stream (phase15: 6 tasks, phase16: 12, full24: 24):
            always_accel, serial oracle, co-schedule (planner.plan_stream)
 3 GENERATE codegen.program(stream, plan, mul) -> RISC-V assembly -> asm_to_hex.py
 4 VERIFY   every output word vs. Python reference, Icarus AND Verilator
            (tb_coschedule_check.sv, +EXPECT file of {ram_word_index, value})
 5 MEASURE  tb_benchmark_soc.sv, twice per program (determinism check)
 6 REPORT   results/coschedule_report.md, results/coschedule_scorecard.md,
            scheduler/coschedule/results.json
```

### Workload representation

A task is a tuple `(op, n)` with `op in {vecadd, dot, matmul}`. There is **no
input data**: every CPU and accelerator body generates its own operands in code
(`A[i] = i+1`, `B[i] = i+2`; matrices `A[i][j] = i+j+1`, `B[i][j] = i+j+2`), and
`codegen.reference(op, n)` recomputes the same pattern in Python. The streams are
hard-coded lists of these tuples.

### Plan representation

One entry per task, in stream order: `("acc",)`, `("cpu",)` or `("win", j)` =
run on the CPU inside accelerator task `j`'s busy window. Validity: a window
host must be an `"acc"` task other than itself.

### Cost model (`planner.plan_cost`)

```
cost = base + sum_{cpu tasks} cpu[t]
            + sum_{acc tasks a} ( acc[a] - busy[a] + max(busy[a], load(a) + RELOAD) )
load(a) = sum of cpu[g] for g hosted in a's window; RELOAD = 2 (li x1, MMIO base)
```

With no windows it is exactly additive. Measured: exact on all 12 serial programs,
within 2.25% on the 6 co-schedules. It looks up `(op, n)` in the profile; an
unprofiled size has no cost.

### Planner

A deterministic best-improvement local search over single-task moves, started from
the serial oracle and from all-accelerator; the cheaper plan is kept.
`exhaustive()` enumerates every valid plan (used for the 6-task stream).

### Code generation and the start/collect protocol

`codegen.accel_split` cuts each verified accelerator body at the text
`"{tag}_wait_loop:"`:

- **LAUNCH**: set up x1 = MMIO base, write VECA/VECB, `sw LEN`, `accel.<op>`
- *(window: the hosted CPU task bodies, verbatim)*
- `li x1, 0x30000000` (the CPU bodies clobber x1)
- **WAIT/COLLECT**: poll `accel.stat` until BUSY=0, copy RESULT/VECOUT to the
  task's RAM output slot

### Memory layout used by generated programs

| Region | Use |
|---|---|
| `0x1000..`, `0x2000..` (RAM) | CPU tasks' operand scratch (shared by all CPU tasks, rewritten per task) |
| `0x3000..0x3FFF` (RAM) | packed per-task outputs, stream order (max 1,024 words) |
| `0x2000_0000` (GPIO) | completion sentinel `0xDEADBEEF` |
| x1..x27 | freely clobbered by every body; no calling convention beyond `mul32` (x10-x12, x5-x7, ra=x1) |

### Verification and measurement

- `tb_coschedule_check.sv`: compares N RAM words to an expect file; shown to fail
  on one corrupted word on both simulators.
- `tb_benchmark_soc.sv`: runs to the GPIO sentinel and reports the performance-counter
  cycle count (`BENCHMARK_RESULT`) and the core configuration (`BENCHMARK_CONFIG`).
- `tb_accel_phase_probe.sv`: records perf-cycle stamps at accelerator BUSY rise/fall.

## 4. Test and regression surface

- 25 SystemVerilog testbenches under `sim/testbenches/`, driven by Make targets
  (`make help`); `make demo` (`scripts/run_full_demo.sh`) runs every phase in order,
  on both simulators where applicable, and ends with the co-scheduler.
- **No Python unit tests exist.** Python code is verified only by its end-to-end effect
  in simulation.
- Synthesis (`make synthesize`, Yosys) is opt-in (`ARGS=--with-synthesis`).
