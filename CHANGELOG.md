# Changelog

Architectural decisions and their rationale, in chronological order.
This is not a commit log — it records *why*, not just *what*.

## Phase 1 — RISC-V ISA Foundation (2026-09-13)

- **Decision: target RV32I, no standard extensions initially.**
  Rationale: RV32I is the smallest complete base ISA and is sufficient
  to compile and run real C programs (Phase 4). Extensions (M for
  multiply/divide, etc.) can be added later once the base datapath and
  pipeline are proven; adding them early would couple ALU/decoder
  complexity to phases that don't need it yet.

- **Decision: implement only `LW`/`SW` for memory access initially, not
  `LB`/`LH`/`LBU`/`LHU`/`SB`/`SH`.**
  Rationale: the project's minimum instruction list (see task spec)
  only requires word load/store. Byte/halfword access adds datapath
  complexity (byte lane muxing, sign/zero-extension select) that is
  better deferred until word-granular load/store is proven correct.
  This is documented explicitly in `docs/riscv.md` §4 rather than left
  as a silent gap.

- **Decision: include `SLTU`, `BLTU`, `BGEU` in the ALU/branch-unit even
  though the task's minimum instruction list only names the signed
  forms (`SLT`, `BLT`, `BGE`).**
  Rationale: `SLTIU` is required by the minimum list and is meaningless
  without an unsigned compare in the ALU; once that compare exists,
  exposing it as `SLTU`/`BLTU`/`BGEU` is free and keeps the ALU/branch
  unit internally consistent with the full RV32I comparison family
  rather than having an unsigned compare that only some instructions
  can reach. All three are standard RV32I encodings, not custom
  additions.

- **Decision: no CSRs, traps, interrupts, or privilege modes yet.**
  Rationale: none of Phases 1-9 require them (no OS, no exception
  handling of illegal instructions beyond a simulation-time diagnostic).
  Introducing a trap architecture prematurely would add unverified
  surface area to every later phase's control unit.

- **Decision: illegal opcodes are diagnosed in simulation rather than
  trapped.**
  Rationale: without a trap/CSR architecture (explicitly out of scope
  for now, see above) there is no defined trap target. The control unit
  will flag an illegal-opcode condition observably in simulation
  (Phase 2) so tests can catch decoder bugs, without pretending to
  implement RISC-V exception semantics that aren't there yet.

- **Toolchain selection:** Icarus Verilog + Verilator for simulation,
  GTKWave for waveform viewing (Phase 6+), `gcc-riscv64-unknown-elf`
  (bare-metal ELF target, rv32i multilib available) for the C toolchain
  (Phase 4+), Yosys for synthesis estimates (Phase 12+). All are
  open-source and installable via `apt` in the development container;
  verified present via `scripts/check_env.sh`. No proprietary or
  vendor-locked tools are required to build or verify this project.

- **Repository structure established** per the project's required
  layout (`rtl/`, `sim/`, `software/`, `scheduler/`, `scripts/`,
  `docs/`, `results/`), with hardware, software, simulation, and AI
  components kept in clearly separate trees from the start.
