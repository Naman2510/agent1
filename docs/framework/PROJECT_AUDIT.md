# Project Audit (Framework Phase 1, 2026-10-03)

Audited commit: `a938891` on `claude/trusting-johnson-7huj1k`, clean working tree.
Companion documents: `CURRENT_ARCHITECTURE.md` (how it works), `TECHNICAL_DEBT.md`
(itemized problems D1-D17), `EXTENSIBILITY_ROADMAP.md` (plan), `BENCHMARK_BASELINE.md`
(numbers to preserve).

## 1. What was inspected

| Area | Files read |
|---|---|
| Docs / instructions | `README.md`, `CHANGELOG.md`, `docs/coschedule.md`, `docs/coschedule_scorecard.md`, `docs/accelerator.md` (via the RTL header), `Makefile`, `scripts/run_full_demo.sh` |
| RTL / hardware interface | `rtl/accelerator/accelerator.sv` (register map, FSM, numerics), `rtl/cpu/riscv_soc.sv` (parameters), `rtl/bus/soc_bus.sv` (address decode), `rtl/memory/dmem.sv` (addressing) |
| ISA | `scripts/asm_to_hex.py` (custom-0 `accel.*` encodings), `rtl/cpu/control_unit.sv` (via `docs/rv32m_mul.md`) |
| Workloads / generated programs | `scheduler/runtime/gen_dynamic_scheduler_demo.py` (task bodies, `mul32`), `sim/programs/coschedule/*.s` (18 programs, sizes) |
| Profiling / cost model / planner / codegen | `scheduler/coschedule/{run,planner,codegen}.py`, `profile_*.csv`, `results.json` |
| Simulation / measurement | `tb_benchmark_soc.sv`, `tb_coschedule_check.sv`, `tb_accel_phase_probe.sv` (instantiation parameters) |
| Tests | the 25 testbenches under `sim/testbenches/` (inventory), Make targets |
| Repository | `git status`, `git log`; the repositories reachable from this session |

## 2. What works (with evidence)

- **The full regression passes on the audited commit.** `make demo` was re-run on
  clean `a938891` for this audit; the result is recorded in `BENCHMARK_BASELINE.md`.
- **Co-scheduler results reproduce exactly.** All 18 programs give identical cycle counts
  to the committed report, are correct on Icarus Verilog and Verilator, and score 100/100.
- **Deterministic.** Every program measured twice per run is identical, and
  the counts are identical across the two separate full regressions run today.
- **Hardware verification is deep.** There is an exhaustive decode sweep (262,144 checks),
  hazard and directed ISA suites, and accelerator unit and end-to-end tests on two simulators.
- **The cost model is exact for serial plans** (12/12 programs) and within 2.25% for
  co-schedules; the planner equals the exhaustive optimum on the 6-task stream.

## 3. What is incomplete

- **No input data path** (D1): workloads are `(op, N)` with operands generated
  in code. This is the main blocker for every application adapter.
- **No typed workload, dependency or id model** (D6), so tasks cannot be
  told apart or ordered by data dependency.
- **No capability declaration** (D9, D17): limits such as N<=64, matmul N<=8, matmul N a power of
  two (CPU body), and mod-2^32 arithmetic live in code and RTL comments.
- **No safe-failure path** (D2): generated code ignores STATUS.ERR; correctness of
  sizes relies on the hard-coded stream lists.
- **No Python tests** (D13) before this work.
- **No measured cost for unprofiled sizes or real data** (D7, D8).

## 4. Tightly coupled points

1. Task bodies ↔ Phase 15 demo script (imported by path manipulation) (D3).
2. Start/collect protocol ↔ the *text* of each accelerator body (split at
   `"{tag}_wait_loop:"`) and the implicit register convention (only x1 is restored) (D11, D12).
3. Memory layout ↔ constants in codegen (scratch `0x1000`/`0x2000`, outputs from `0x3000`,
   1,024 output words) with silent RAM aliasing past the instantiated depth (D10).
4. Cost model ↔ exact `(op, N)` keys and a single accelerator (D7, D14).
5. Pipeline orchestration, simulator invocation and reporting in one script (D4, D15).
6. Reference values ↔ the synthetic operand pattern (D1).

## 5. Assumptions embedded in the current design

- Tasks are independent and every task writes a disjoint output region.
- One accelerator context; a window hosts CPU tasks only.
- The CPU tasks' RAM scratch can be reused because tasks run one at a time on the CPU.
- Operand values are small positive integers (affects `mul32` latency, D8, and
  hides overflow behaviour, which is wrap-around in both engines).
- Every stream is known ahead of time (plans are offline).

## 6. Numerical facts that constrain applications

From the RTL: 32-bit two's-complement, wrap-around (mod 2^32) add and multiply, low
32 bits of each product, no saturation, no rounding, no high product word. The
CPU paths (`add`, software `mul32`, optional hardware `MUL`) have the same
mod-2^32 semantics, which is why CPU and accelerator results agree bit for bit.
Implication: fixed-point *addition* and integer x fixed-point products are exact
within range; Q-format x Q-format products need the high word and are **not
supported** on the accelerator. Details: `NUMERICAL_REPRESENTATION.md` (Phase 4).

## 7. External application: the equity platform

The "Ultimate Equity Research & Quantitative Intelligence Platform" was **not found**.
It is not in this repository, and none of the repositories reachable from this
session is identifiably it (the closest by name, `razorpay-ib-portfolio`, was not
inspected and is not assumed to be it). Phase 8 is blocked until the
owner identifies the repository. Phase 7's finance adapter does not depend on it.

## 8. Test inventory before changes

- 25 SystemVerilog testbenches; regression entry point `make demo`
  (`scripts/run_full_demo.sh`), which runs Phases 1-17 and every post-v1 stage on both
  simulators where applicable.
- Correctness evidence for the co-scheduler: `tb_coschedule_check.sv` (every output
  word, both simulators; negative control previously demonstrated).
- Python: no unit tests.

## 9. Git state at audit time

Branch `claude/trusting-johnson-7huj1k`, HEAD `a938891`, clean tree, pushed. Recent
history: co-scheduler (a938891), scorecard pre-registration (9808c32), decode-space
validation (0e0d047), MUL dataset (248327c), decode fix + optional MUL (c0eb549).
