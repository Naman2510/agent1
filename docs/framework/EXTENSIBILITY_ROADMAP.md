# Extensibility Roadmap

Target: turn `scheduler/coschedule/` into a workload-independent framework
(`scheduler/framework/`, working name) without changing RTL and without changing
any existing result. Each phase has acceptance criteria. A phase is marked done
only when all of them are met, with the evidence recorded in `CHANGELOG.md`.

## Target layers mapped onto what exists

| Layer | Exists today as | Gap |
|---|---|---|
| 1 Application interface | none (streams are hard-coded lists) | API: submit task / batch / graph, get validated result |
| 2 Workload IR | `(op, n)` tuples | typed tasks with ids, **data**, dtype, dims, deps, constraints (D1, D6) |
| 3 Profiler | `run.profile()` for 24 fixed tasks | reusable over sizes **and data**, measured vs. estimated, versioned records (D7, D8) |
| 4 Cost model | `planner.plan_cost` (exact lookup) | interface + backends; interpolation labelled as such; error reporting |
| 5 Planner | `planner.plan_stream` / `exhaustive` | interface; dependency-aware variant (separate, benchmarked) |
| 6 Backends | CPU bodies, accel bodies, window splice inside `codegen` | declared capabilities (ops, dtypes, limits, numerics, availability) (D9, D11, D12, D17) |
| 7 Runtime + validation | `run.py` (verify + measure) | validate -> compatibility -> plan -> execute -> check -> record; fail safe (D2) |

## Phases

### Phase 1: Audit and baseline (this document set)
Acceptance: the five audit documents exist; the full regression has been run on the
audited commit and passed; the baseline numbers are reproduced and recorded
with hashes of every generated program.

### Phase 2: Modularize existing components
Split `scheduler/coschedule/` into separate modules: workload catalogue,
profile/cost model, planner, program generation, simulator execution, verification,
reporting. The old entry point is kept.
Acceptance: **every generated program byte-identical** to the baseline
(SHA-256), every measured cycle count and the scorecard identical, `make coschedule`
and `make demo` pass; a fast Python unit-test suite (stdlib `unittest`) exists.

### Phase 3: Workload IR
Typed task / task-graph format (JSON-serializable): `task_id, operation, inputs,
outputs, dependencies, data_type, dimensions, precision, constraints, validation,
backend_preferences`, plus a validator (missing/invalid refs, cycles, type and
dimension errors, unsupported ops, conflicting constraints).
**Data-carrying tasks**: operands are part of the task. The backend emits them as
data rather than generating them in code. This needs only a new emission path, not new
hardware: the CPU can `sw` constants into RAM / accelerator scratchpads.
Acceptance: the 24 existing workloads are expressed in the IR (with their
synthetic operands as explicit data); the "synthetic-pattern" path still produces
byte-identical programs; the explicit-data path is verified separately on both
simulators; the validator rejects every negative case in its test suite.

### Phase 4: Backend abstraction
`Backend` interface: capabilities (ops, dtypes, size limits, numeric semantics,
availability), cost source, emit/execute, validation method. Implementations:
RV32I CPU (`ENABLE_MUL` 0/1), accelerator, co-scheduled (window composition), and a
Python **reference** backend (exact mod-2^32 integer semantics, used to validate).
Acceptance: an unsupported (op, dtype, size) is rejected **before** codegen with a
clear error (tests for each); emitted accelerator code checks STATUS.ERR (D2) and
that change is measured. Its cycle cost goes into the record: the baseline numbers are
kept for the unchecked variant and the delta is reported, not hidden.

### Phase 5: Generalized runtime
`submit(task | batch | graph) -> Result{outputs, validation, performance, provenance}`.
Fail-safe: no result is returned without passing validation against the
reference backend.
Acceptance: end-to-end tests for single, batch and simple dependent graphs;
negative tests (bad graph, unsupported op, overflow detected, simulator missing)
produce explicit errors.

### Phase 6: Profiling and cost model
Versioned profile records (config, git commit, simulator, data distribution);
size sweeps; interpolation only between measured sizes, labelled; extrapolation
refused or labelled; profiles taken **with representative data** (D8). The current
model is the baseline the new one is compared against.
Acceptance: `COST_MODEL_VALIDATION.md` with predicted vs. measured on held-out
sizes and held-out data.

### Phase 7: Application adapters
A. Generic integer/fixed-point batches. B. Quant finance: first candidate
**integer-scaled** (fixed-point) returns, moving sums/averages and dot-product-based
covariance, all within the mod-2^32 semantics, with overflow detection and
tolerances defined before any run.
Acceptance: per adapter, a reference implementation, pre-registered tolerances,
both-simulator correctness, and measured end-to-end cost **including data
conversion and load overhead**.

### Phase 8: Equity platform integration
**Blocked on locating the platform.** None of the repositories this session can
reach is identifiably the "Equity Research & Quantitative Intelligence Platform".
The integration is designed as an optional backend behind a config flag, with the
platform's Python path as the default and fallback.

### Phase 9: Advanced scheduling
Dependency-aware list scheduling over task graphs (window placement respecting
data readiness), as a separate planner with its own tests and benchmark. Dynamic
and multi-accelerator scheduling are design studies only until hardware exists.

### Phase 10: Tooling and final validation
Plan explanation (why each task went where, with costs labelled measured vs.
estimated), execution traces, overlap timelines from the BUSY probe, exports;
full regression and held-out workloads.

## Requires hardware work (separate hardware phases, not part of this refactor)

| Capability | Why software cannot provide it |
|---|---|
| Fixed-point multiply on the accelerator (Q-format) | needs the product's high word or a configurable shift; RTL stores only bits [31:0] |
| Saturating arithmetic | RTL wraps |
| Larger windows (accelerator fetching its own operands) | needs a DMA/bus-master port; today the CPU marshals every operand |
| Multiple accelerators / queued operations | one FSM, one context |
| Non-power-of-two matmul on the CPU path | software-only, but needs new verified bodies (not hardware) |

## Explicitly out of scope unless an execution environment appears

GPU, NPU, FPGA-board and other-ISA backends. The interface will not preclude them,
but none will be listed as available, and no stub will pretend to execute.
