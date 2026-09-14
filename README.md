# AI-Directed RISC-V Heterogeneous Computing System

A from-scratch, fully software-simulated heterogeneous computing system
built around a custom RV32I RISC-V CPU, a hardware accelerator, and an
AI workload scheduler that learns which engine should execute a given
workload.

**No FPGA board or other physical hardware is required.** Everything in
this project — the CPU, the accelerator, the SoC, and the scheduler —
runs as software simulation on a normal laptop, using open-source RTL
simulators (Icarus Verilog, Verilator) and open-source synthesis tooling
(Yosys) for resource *estimates* only.

This is an educational hardware/software co-design project. The goal is
not to produce code that merely looks like a CPU — every core datapath
and control decision is implemented explicitly in SystemVerilog and is
backed by simulation waveforms and automated tests, not hidden behind
opaque IP or emulated in Python.

## Target architecture

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

This is the *end state*. The project is built in ordered phases, each of
which must compile, simulate, pass its tests, and be documented before
the next phase begins — see [Project status](#project-status) below.

## Repository layout

```
ai-riscv/
├── rtl/            SystemVerilog hardware: cpu, pipeline, alu, regfile,
│                    decoder, memory, bus, accelerator
├── sim/             Testbenches, RISC-V test programs, waveform output
├── software/        Bare-metal C programs and a minimal runtime
├── scheduler/        AI workload scheduler: models, benchmarks, training
├── scripts/          Setup, build, simulation and benchmark scripts
├── synth/            Synthesis-only stand-ins (Phase 12) -- never simulated,
│                      never part of the verified design under rtl/
├── docs/             Architecture and design documentation (see below)
└── results/          Benchmark reports and synthesis reports (generated)
```

## Getting started

```bash
./scripts/check_env.sh   # verify required tools are installed
make sim_cpu              # assemble + run the Phase 2 CPU testbench
                           # (Icarus Verilog and Verilator, both must pass)
make test_isa              # run the Phase 3 directed instruction test suite
make run_c_demo            # Phase 4: compile and run a real C program (GCC -> CPU)
make sim_pipeline          # Phase 5: assemble + run the pipelined CPU testbench
make test_hazards          # Phase 6: run the pipeline hazard directed test suite
make waves                 # Phase 6: generate GTKWave .vcd waveforms of the hazards
make test_perf              # Phase 7: verify benchmark correctness + perf counters
make benchmarks              # Phase 7: write results/performance_report.md
make sim_soc                # Phase 8: assemble + run the top-level SoC testbench
                              # (RAM/UART/GPIO through the real address-decoded bus)
make test_accel              # Phase 9: accelerator unit test + CPU-driven end-to-end
                              # demo (vector add, dot product, matrix multiply)
make test_accel_custom       # Phase 10: ACCEL.* custom instruction end-to-end demo
make test_bench_correctness  # Phase 11: verify CPU-only benchmark kernels
make benchmarks_accel        # Phase 11: CPU vs. accelerator benchmarks + report
make synthesize               # Phase 12: Yosys (iCE40) resource estimates + report
make test_scheduler_correctness  # Phase 13: verify the 12 new-size scheduler programs
make collect_scheduler_dataset   # Phase 13: write scheduler/training/dataset.csv
make train_scheduler             # Phase 13: fit the model + write results/scheduler_report.md
make test_scheduler_heldout_correctness  # Phase 14: verify the 9 held-out workloads
make collect_scheduler_heldout_dataset   # Phase 14: write scheduler/training/heldout_dataset.csv
make evaluate_scheduler_accuracy         # Phase 14: score the model vs. held-out ground truth
make test_dynamic_scheduler_correctness  # Phase 15: verify the dynamic-scheduling demo
make run_dynamic_scheduler_demo          # Phase 15: measure real runtime decision overhead
make test_mixed_workload_correctness     # Phase 16: verify the 12-workload mixed stream demo
make run_mixed_workload_demo             # Phase 16: measure the scheduler at larger scale
```

Required tools by phase (see `scripts/check_env.sh` for the full,
version-checked list):

| Phase | Tools |
|-------|-------|
| 2+  | Icarus Verilog, Verilator |
| 4+  | `riscv64-unknown-elf-gcc` / `binutils-riscv64-unknown-elf` (rv32i multilib) |
| 6+  | GTKWave (optional, for viewing `.vcd` waveforms locally) |
| 12+ | Yosys |
| 13+ | Python 3 + numpy / pandas / scikit-learn (`scripts/setup_scheduler_venv.sh`) |

This project was developed and verified inside a plain Ubuntu 24.04
container with no FPGA or other physical hardware attached.

## Documentation

- [`docs/riscv.md`](docs/riscv.md) — the RV32I ISA subset this project implements (registers, instruction formats, encodings). **Start here.**
- `docs/architecture.md` — overall system architecture and phase-by-phase design rationale.
- `docs/datapath.md` — single-cycle CPU datapath (Phase 2+).
- `docs/testing.md` — directed instruction test convention and coverage (Phase 3+).
- `docs/c_program_demo.md` — real C program compiled and executed end-to-end (Phase 4).
- `docs/pipeline.md` — five-stage pipeline design, register contents, and what Phase 5 does/doesn't yet handle (Phase 5+).
- `docs/hazards.md` — data/load-use/control hazard handling, forwarding, stalling, flush, and the directed tests + waveforms that verify them (Phase 6).
- [`docs/soc.md`](docs/soc.md) — SoC memory map, peripherals, and the CPU's bus-master refactor (Phase 8).
- [`docs/accelerator.md`](docs/accelerator.md) — accelerator architecture, register interface, and the two real bugs found building/verifying it (Phase 9).
- [`docs/custom_extension.md`](docs/custom_extension.md) — the ACCEL.* custom RISC-V instructions: encoding, what they replace, and why some accelerator registers deliberately aren't covered (Phase 10).
- [`docs/scheduler.md`](docs/scheduler.md) — AI scheduler dataset generation, the matmul shift-amount fix, a real measured CPU-wins crossover, and the model's honest limitations at n=11 (Phase 13).
- [`docs/scheduler_pipeline.md`](docs/scheduler_pipeline.md) — the scheduler's runtime decision function, a genuinely held-out (never-trained-on) accuracy evaluation, and a real 8/9 result with one instructive miss (Phase 14).
- [`docs/dynamic_scheduling.md`](docs/dynamic_scheduling.md) — a single RISC-V program that computes the scheduling decision itself, on the CPU, at runtime, and the honest real result that its own decision overhead can outweigh the benefit for small workload streams (Phase 15).
- [`docs/mixed_workloads.md`](docs/mixed_workloads.md) — the same runtime scheduler at a larger, more varied 12-workload scale: overhead shrinks roughly 3x as predicted, but the real limiting factor turns out to be a small oracle-vs-baseline ceiling, not overhead (Phase 16).
- [`docs/benchmarking.md`](docs/benchmarking.md) — CPU-vs-accelerator benchmark methodology, real measured results, and a real bug it caught (Phase 11).
- [`docs/synthesis.md`](docs/synthesis.md) — Yosys/iCE40 synthesis methodology, two real tooling problems it solved, and why place-and-route was tried but not adopted (Phase 12).
- `CHANGELOG.md` — chronological log of architectural decisions.

## Engineering rules this project follows

1. Every phase must compile, simulate, and pass its own tests before the next phase starts.
2. No fabricated benchmark numbers — every number in `results/` comes from an actual simulation or synthesis run, and each report says which.
3. Physical FPGA performance is never claimed; this project only produces simulation and synthesis-tool *estimates* (see `docs/synthesis.md`).
4. Hardware logic lives in SystemVerilog under `rtl/`; software/runtime logic is kept separate under `software/` and `scheduler/`.
5. Important CPU/accelerator behavior is implemented in RTL, never as a Python shortcut standing in for hardware.

## Project status

Tracked phase-by-phase; each phase below is only checked once it compiles, simulates, is tested, and is documented.

- [x] Phase 1 — RISC-V ISA foundation (this document set)
- [x] Phase 2 — Basic single-cycle RISC-V CPU
- [x] Phase 3 — Instruction execution tests
- [x] Phase 4 — Execute a real compiled C program
- [x] Phase 5 — Five-stage pipeline
- [x] Phase 6 — Pipeline hazards (forwarding/stalling/flushing)
- [x] Phase 7 — Performance counters / CPI
- [x] Phase 8 — SoC (memory map, peripherals)
- [x] Phase 9 — Hardware accelerator RTL
- [x] Phase 10 — Custom RISC-V extension for accelerator control
- [x] Phase 11 — CPU vs accelerator benchmarking
- [x] Phase 12 — FPGA synthesis resource estimates
- [x] Phase 13 — AI workload scheduler (trained model)
- [x] Phase 14 — Scheduler decision pipeline + accuracy tracking
- [x] Phase 15 — Dynamic runtime scheduling
- [x] Phase 16 — Mixed/heterogeneous workloads
- [ ] Phase 17 — End-to-end demo + full documentation

See `CHANGELOG.md` for what changed in each completed phase and why.

## License

TBD by the project owner.
