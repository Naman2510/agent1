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
```

Required tools by phase (see `scripts/check_env.sh` for the full,
version-checked list):

| Phase | Tools |
|-------|-------|
| 2+  | Icarus Verilog, Verilator |
| 4+  | `riscv64-unknown-elf-gcc` / `binutils-riscv64-unknown-elf` (rv32i multilib) |
| 6+  | GTKWave (optional, for viewing `.vcd` waveforms locally) |
| 12+ | Yosys |
| 13+ | Python 3 + numpy / pandas / scikit-learn |

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
- `docs/scheduler.md` — AI scheduler design (Phase 13+).
- [`docs/benchmarking.md`](docs/benchmarking.md) — CPU-vs-accelerator benchmark methodology, real measured results, and a real bug it caught (Phase 11).
- `docs/synthesis.md` — synthesis methodology and resource estimates (Phase 12+).
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
- [ ] Phase 12 — FPGA synthesis resource estimates
- [ ] Phase 13 — AI workload scheduler (trained model)
- [ ] Phase 14 — Scheduler decision pipeline + accuracy tracking
- [ ] Phase 15 — Dynamic runtime scheduling
- [ ] Phase 16 — Mixed/heterogeneous workloads
- [ ] Phase 17 — End-to-end demo + full documentation

See `CHANGELOG.md` for what changed in each completed phase and why.

## License

TBD by the project owner.
