# Heterogeneous Compute Framework: index and status

This is the work that turns the co-scheduler (`docs/coschedule.md`) into a reusable
framework, step by step, without changing RTL or any existing result.

| Phase | Status | Evidence |
|---|---|---|
| 1 Audit + baseline | **Done** | `PROJECT_AUDIT.md`, `CURRENT_ARCHITECTURE.md`, `TECHNICAL_DEBT.md`, `EXTENSIBILITY_ROADMAP.md`, `BENCHMARK_BASELINE.md` |
| 2 Modularize existing components | **Done** (see CHANGELOG for the regression run) | module map below; `make test_framework` |
| 3 Workload IR (+ data-carrying tasks) | Planned | `EXTENSIBILITY_ROADMAP.md` |
| 4 Backend abstraction | Planned | |
| 5 Runtime | Planned | |
| 6 Profiling + cost model | Planned | |
| 7 Application adapters | Planned | |
| 8 Equity platform integration | **Blocked**: platform repository not located | `PROJECT_AUDIT.md` §7 |
| 9 Advanced scheduling | Planned | |
| 10 Tooling + final validation | Planned | |

## Module map (Phase 2)

`scheduler/framework/`: each module imports only from those listed above it.

| Module | Responsibility | Moved from |
|---|---|---|
| `operations.py` | operation registry: CPU body, accelerator body, output size, reference result per op. The only importer of the verified Phase 15 bodies | `coschedule/codegen.py` (+ the three dicts it relied on) |
| `workloads.py` | stream catalogue (`phase15`, `phase16`, `full24`) | `coschedule/codegen.py` |
| `plans.py` | plan format, validity, text description | `coschedule/{codegen,planner,run}.py` |
| `costmodel.py` | profile records (CSV read/write) + plan cost model | `coschedule/planner.py`, `run.py` |
| `planner.py` | local search, oracle, exhaustive optimum | `coschedule/planner.py` |
| `rv32_codegen.py` | RISC-V program generation, memory layout, start/collect window splice | `coschedule/codegen.py` |
| `verification.py` | expected output words, expect-file writer | `coschedule/codegen.py` |
| `simulator.py` | RTL file list, assembler, Icarus/Verilator builds, testbench runners/parsers | `coschedule/run.py` |
| `profiler.py` | per-task profiling on the simulated SoC | `coschedule/run.py` |

`scheduler/coschedule/` keeps the scored experiment: `run.py` (orchestration only),
`report.py` (report + scorecard writers, moved verbatim), and `codegen.py` /
`planner.py` as **compatibility shims** re-exporting the old names.

## Tests

`make test_framework` (stdlib `unittest`, no simulator, about 5 s):

- `tests/test_framework_equivalence.py`: from the committed profiles, regenerates all
  18 programs and 3 expect files and compares them **byte for byte** with the committed
  ones; checks every predicted cycle count, every plan and the exhaustive optimum
  against `results.json`. Negative controls: one byte changed in a committed program
  makes it fail, and so does changing the cost-model constant `RELOAD` (3 tests fail).
- `tests/test_framework_units.py`: registry (an unsupported op fails clearly), plan
  validity, cost model (serial additivity, window cost both regimes, unprofiled size
  raises), planner (never worse than oracle; equals exhaustive on a small stream),
  codegen (MUL substitution, start/collect split, MMIO-base restore ordering, output
  bounds), and the compatibility shims.

`make demo` runs `test_framework` immediately before `coschedule`, so the golden
check compares against the committed programs before they are regenerated.
