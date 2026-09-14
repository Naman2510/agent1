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

## Phase 2 — Basic Single-Cycle RISC-V CPU (2026-09-13)

- **Decision: single-cycle architecture before pipelining**, following
  the Harris & Harris (*Digital Design and Computer Architecture:
  RISC-V Edition*) reference structure: one PC register, one adder for
  `PC+4`, a second dedicated adder for PC-relative branch/JAL targets, a
  single shared ALU (with input muxes) for arithmetic/compare/memory
  address/AUIPC/JALR-target computation, and a 3-way writeback mux
  (ALU result / memory read data / PC+4). See `docs/datapath.md` for the
  full rationale, especially why AUIPC and JALR both reuse the main ALU
  instead of adding dedicated hardware.

- **Decision: `illegal` is a diagnostic flag, not a trap**, consistent
  with the Phase 1 decision that no CSR/trap architecture exists yet.
  `control_unit.sv`'s `default` case sets `illegal=1` and leaves every
  state-changing control signal at its safe-default (no register write,
  no memory write) rather than either crashing the simulator or
  fabricating trap semantics that aren't implemented.

- **Decision: `ALU_PASSB` as a microarchitectural (non-ISA) ALU
  operation for LUI.** Keeps the writeback mux to exactly 3 inputs
  (ALU/memory/PC+4) instead of adding a 4th path just to route the
  U-type immediate around the ALU for one instruction. Documented in
  `rtl/cpu/riscv_pkg.sv` and `docs/datapath.md` as implementation detail,
  not part of the ISA (`docs/riscv.md` is unchanged).

- **Built `scripts/asm_to_hex.py`**, a small assembler for exactly this
  project's instruction subset (not a general RISC-V assembler), because
  hand-encoding hex for directed tests (this phase's bring-up program,
  and every Phase 3 directed test) does not scale and is error-prone.
  It expands pseudo-instructions (`li`, `mv`, `j`, `ret`) into real
  instructions *before* assigning addresses, specifically because a
  large `li` expands to two words (LUI+ADDI) -- assigning addresses
  per source line first and expanding after would silently corrupt
  every label address following such an `li`. Verified against several
  independently hand-computed instruction encodings before use.

- **Verification: two independent simulators, one testbench.**
  `sim/testbenches/tb_riscv_cpu.sv` runs the same bring-up program and
  the same 18 architectural-state checks under both Icarus Verilog and
  Verilator (`scripts/run_sim_phase2.sh` / `make sim_cpu`). Both report
  identical results. This matters because Icarus Verilog 12.0 emits a
  `sorry: constant selects in always_* processes are not currently
  supported` diagnostic for several bit-select patterns used in this
  design (documented in detail in `docs/datapath.md`); rather than
  assume it's harmless, cross-validating against Verilator's
  independent implementation confirms the simulated results are correct
  bit-for-bit, including for the exact constructs the message flags.

- **Decision: generated artifacts (`.hex` program images) are not
  committed.** `sim/programs/*.hex` is produced by
  `scripts/asm_to_hex.py` from the checked-in `.s` source and is
  regenerated by `scripts/run_sim_phase2.sh` / `make sim_cpu`, per the
  "reproducible from a clean checkout" rule -- the source of truth is
  the assembly source, not its assembled output.

## Phase 3 — Directed Instruction Tests (2026-09-13)

- **Decision: group related instructions into one self-checking test
  file per category** (`sim/programs/tests/*.s`), with a reserved
  result register (`x31`) and a distinct nonzero failure code per
  assertion, rather than one file per instruction. See `docs/testing.md`
  for the full convention and the coverage table mapping every
  instruction and every required test category (arithmetic, logical,
  immediate ops, loads, stores, branches, jumps, register dependencies,
  negative numbers, signed comparisons, zero-register behavior) to the
  file that exercises it.

- **Decision: compile the test harness once, re-run per test via a
  runtime plusarg.** `rtl/memory/imem.sv` now accepts a `+HEXFILE=...`
  plusarg (checked before its `INIT_FILE` parameter, which Phase 2's
  testbench still uses unchanged), so `scripts/run_directed_tests.py`
  builds `tb_directed_test.sv` once per simulator and re-runs that one
  binary against every test program, instead of recompiling per test.

- **Bug found and fixed: a same-clock-edge reset race producing
  simulator-dependent results.** The first version of
  `tb_directed_test.sv` tracked whether the control unit's `illegal`
  flag was *ever* asserted during a run (not just at the final cycle,
  unlike Phase 2's testbench). This immediately caught a real issue:
  `pc` in `riscv_cpu.sv` had no explicit initial value, so it read as X
  for the brief window between simulation start and the first clock
  edge. That X propagated through `imem`'s address decode into `instr`
  and `opcode`, and the control unit's `case (opcode)` -- correctly, but
  misleadingly -- fell through to its `illegal` default for an
  unresolvable opcode, asserting a *concrete* `illegal=1` for one
  transient cycle. Whether a given simulator's internal event ordering
  samples that transient before or after `pc`'s own reset assignment
  settles is unspecified by the language and genuinely differed between
  Icarus Verilog and Verilator: Icarus flagged `illegal_opcode_seen` on
  every one of the 9 directed tests while Verilator passed 8 of 9. This
  was root-caused (not worked around) two ways: (1) `pc` now has an
  explicit `= 32'b0` initializer in `riscv_cpu.sv`, removing the X
  window at its source -- the synchronous reset (`if (!rst_n) pc <=
  32'b0`) is unchanged and remains the real, synthesizable reset
  behavior; (2) `tb_directed_test.sv`'s sticky illegal-tracking is
  gated on `rst_n`, since an opcode observed while the core is still in
  reset was never a real instruction execution to begin with. After
  both fixes, Icarus Verilog and Verilator agree exactly on all 9 tests.
  This is called out in detail because it is exactly the kind of bug a
  less rigorous test (checking a signal only at a fixed final cycle, as
  Phase 2's testbench does) would never have caught.

- **Bug found and fixed: an arithmetic error in the AUIPC test itself**
  (not the RTL). `tests/upper_imm.s` originally assumed two `auipc`
  instructions used for a relative-address invariant check were 2 words
  apart when the file actually placed 5 instructions between them;
  the expected value was off by 12 bytes. Caught immediately because
  both simulators agreed with each other and disagreed with the test's
  own (miscounted) expectation -- a good example of why the test
  programs need the same scrutiny as the RTL they check.

- **Result:** all 9 directed test files (covering every instruction in
  `docs/riscv.md` section 3) pass under both Icarus Verilog and
  Verilator (`make test_isa`).

## Phase 4 — Execute a Real Compiled C Program (2026-09-13)

- **Decision: use the real `riscv64-unknown-elf-gcc` toolchain
  end-to-end, not this project's own `scripts/asm_to_hex.py`.** The
  task requires "do not simply emulate the C program in Python" --
  `scripts/asm_to_hex.py` exists only for this project's own
  hand-written directed test programs (Phases 2-3). Phase 4's C program
  goes through the real cross-compiler, real linker, and real
  `objcopy`; only the final binary-to-`$readmemh`-hex conversion
  (`scripts/bin_to_hex.py`) is this project's own code, and it does no
  semantic transformation -- it is a byte-format converter, not part of
  compilation.

- **Decision: write a minimal real-assembly startup stub
  (`software/runtime/start.S`) rather than relying on GCC's default
  startup.** There is no OS and, per Phase 1, no trap/CSR architecture,
  so `-nostartfiles` is required and something has to set up `sp` before
  `main` runs and something has to happen when `main` returns (there is
  nowhere to return to). `start.S` sets `sp` near the top of the
  4096-byte simulated data memory and parks in an infinite loop after
  `main` returns, exactly mirroring how a real bare-metal RISC-V system
  would boot.

- **Result, and why it matters beyond Phase 4 itself:** GCC (targeting
  `-march=rv32i -mabi=ilp32`, no extensions) compiled
  `software/baremetal/add_test.c` using only instructions Phase 2/3
  already implemented and verified (`addi`, `sw`, `lw`, `add`, plus the
  standard `li`/`mv`/`ret`/`j` pseudo-instructions, which expand to
  `addi`/`jalr`/`jal`). **No RTL changes were required for this phase.**
  That is itself evidence that Phases 2-3 implemented a correct, broad
  enough RV32I subset -- real, unmodified compiler output running
  correctly on the first attempt is a stronger signal than any
  additional hand-written test could provide. The CPU produced
  `a0 = 30` (`10 + 20`), matching the C program's return value exactly,
  identically under both Icarus Verilog and Verilator. Full trace and
  explanation in `docs/c_program_demo.md`.

## Phase 5 — Five-Stage Pipeline (2026-09-13)

- **Decision: a new top-level module (`riscv_cpu_pipeline`), not a
  rewrite of `riscv_cpu.sv`.** Reuses every Phase 2 submodule
  (decoder, control_unit, regfile, imm_gen, alu, branch_unit, imem,
  dmem) unchanged, wired across four new pipeline registers
  (`rtl/pipeline/`). Keeps Phases 2-4's tests passing against the
  original single-cycle CPU unmodified, and keeps both
  microarchitectures available for later comparison (Phase 11
  benchmarking). See `docs/pipeline.md`.

- **Decision: Phase 5 does not implement forwarding, load-use
  stalling, or branch/jump flush.** Per the task's own split between
  Phase 5 ("implement pipeline registers... document what information
  is stored in every pipeline register") and Phase 6 ("Control
  hazards: branches must correctly flush or redirect the pipeline"),
  those are explicitly out of scope here. Branch/JAL/JALR target
  computation and PC redirection ARE implemented and correct in EX;
  what's missing is discarding the 2 instructions already fetched from
  the wrong path before that redirect lands. Phase 5's own test
  program therefore contains no branches or jumps at all, and instead
  ends without a halt loop, with the testbench running a precisely
  bounded cycle count -- documented in full, including why even an
  unconditional `j halt` would exercise the exact unhandled case, in
  `sim/programs/pipeline_straightline.s` and `docs/pipeline.md`.

- **Bug found and fixed: a wrong assumption about how many
  instructions of gap a RAW dependency needs with no forwarding
  hardware.** The initial test program used a 2-instruction gap,
  reasoning from the classic "write in the first half of the cycle,
  read in the second half" textbook pipelined-register-file behavior.
  That reasoning does not apply here: `regfile.sv`'s write and
  `id_ex_reg`'s capture of the corresponding read both happen via
  nonblocking assignment on `posedge clk` -- the *same* edge, when a
  producer's WB and a consumer's ID land in the same cycle -- and
  Verilog resolves that race to the pre-edge value for every block
  sensitive to the edge, not just the one asserting the write. Running
  the test caught this immediately: 6 of 19 checks failed, every
  failure being exactly a 2-instruction-gap dependency, while every
  3-instruction-gap dependency in the same file passed. Fixed by
  requiring a 3-instruction gap and rerunning to confirm all 19 checks
  pass under both simulators; the (previously wrong) explanatory
  comment in `riscv_cpu_pipeline.sv` was corrected to match, not just
  the test. Full account in `docs/pipeline.md`.

- **Result:** the pipelined CPU correctly executes straight-line RV32I
  code (R-type/I-type ALU ops including shifts, LUI, AUIPC, a
  store/load round-trip, x0 hard-wire behavior) with instructions
  genuinely overlapping across all five stages, verified identically
  under Icarus Verilog and Verilator (`make sim_pipeline`). Data
  hazards closer than 3 instructions apart, and all branches/jumps,
  are known-unhandled by design and are Phase 6's job.

## Phase 6 — Pipeline Hazards (2026-09-13)

- **Decision: evolve `riscv_cpu_pipeline.sv` in place, not a third
  top-level module.** Unlike Phase 2 -> Phase 5 (genuinely different
  microarchitectures kept side by side on purpose), the task frames
  hazard handling as completing the Phase 5 pipeline, not building
  another one. Phase 5's own straight-line, branch-free test
  (`sim/programs/pipeline_straightline.s`) was specifically constructed
  to have zero hazards, so it continues to pass completely unchanged as
  a standing regression check that Phase 6 never altered hazard-free
  behavior (now also asserts `dbg_stall`/`dbg_flush` are never raised
  for that program, added as part of this phase).

- **Added `rtl/pipeline/forwarding_unit.sv`** (EX/MEM and MEM/WB
  forwarding into both ALU inputs, the branch comparison, and a store's
  data operand) **and `rtl/pipeline/hazard_unit.sv`** (load-use stall
  detection; branch/JAL/JALR flush), plus `stall`/`flush` control inputs
  on `if_id_reg.sv` and `id_ex_reg.sv`.

- **Bug found and fixed: forwarding_unit and the register file together
  left a gap at a RAW dependency exactly 2 instructions apart** (2
  independent instructions in between). Neither `EX/MEM` nor `MEM/WB`
  forwarding can reach it -- by the time the consumer is in EX, the
  producer has already fully retired and no longer exists in any
  pipeline register -- and the register file's own read races the
  producer's write on the same clock edge for exactly this gap (the
  same class of same-edge race Phase 5 found for a different gap
  distance). Caught by `load_use_hazard.s` computing a load address of
  `0` instead of `0x40`. Fixed with a new `BYPASS_WRITE_TO_READ`
  parameter on `regfile.sv` (default off, a same-cycle write-to-read
  bypass implemented as a plain combinational address comparison, not
  reliant on event ordering), enabled only for the pipelined CPU's
  regfile instance. It must stay off for the single-cycle CPU
  (`riscv_cpu.sv`): there, a self-referential instruction like `add
  x1,x1,x2` would close the bypass into a combinational loop through
  that instruction's own ALU output, since read and write there belong
  to the same instruction in the same cycle rather than two independent
  ones. Full explanation in `regfile.sv`'s header comment and
  `docs/hazards.md` §1.1.

- **Bug found and fixed in the test methodology, not the RTL: a sticky
  "illegal opcode ever seen" check (reused verbatim from Phase 3) fails
  100% of pipelined programs regardless of correctness.** A pipeline
  bubble (all-zero pipeline-register state -- present during fill,
  every flush, and every stall) decodes to opcode `0000000`, which
  `control_unit.sv` correctly flags `illegal` since it isn't a
  supported opcode -- correct for the single-cycle CPU (which never has
  bubbles) but not a meaningful check for a pipeline (which always
  does). Removed from `tb_pipeline_directed_test.sv`; verification
  relies solely on the x31 pass/fail convention, matching Phase 5's
  `tb_pipeline.sv`.

- **Added directed tests** (`sim/programs/pipeline_tests/`: forwarding
  at every reachable gap, the load-use stall including a load feeding a
  store operand and a branch condition, and control-hazard flush for
  taken/not-taken branches and JAL/JALR) and a waveform generation
  script (`scripts/generate_waveforms.sh`, `make waves`) producing real
  `.vcd` files for GTKWave, since this container has no display to run
  it interactively. `docs/hazards.md` documents actual signal
  transition timestamps read out of those generated files (the
  load-use stall is confirmed exactly one clock period wide; flush
  fires once per taken branch/JAL/JALR).

- **Result:** all 3 directed hazard test programs pass under both
  Icarus Verilog and Verilator (`make test_hazards`); Phase 5's
  hazard-free regression test still passes unchanged; Phases 2-4 are
  unaffected (`regfile.sv`'s new parameter defaults to its old,
  unparameterized behavior).

## Phase 7 — Performance Counters + CPI (2026-09-14)

- **Added `rtl/cpu/perf_counters.sv`** (cycle count, instructions
  retired, stalls, branches, branches taken, load-use stalls,
  forwarding events, flushes -- purely observational, no datapath
  feedback), instantiated in `riscv_cpu_pipeline.sv`.

- **Decision: thread an explicit `valid` bit through every pipeline
  register rather than deriving "instruction retired" from WB-stage
  signals alone.** By WB, `branch`/`jal`/`jalr` have already been
  dropped (only needed through EX), so there wasn't enough left at WB
  to distinguish a bubble from a real instruction using existing
  signals. Computed once in ID as `reg_write | mem_write | branch |
  jal | jalr` (every supported opcode sets at least one) and threaded
  through `id_ex_reg` -> `ex_mem_reg` -> `mem_wb_reg`, the same pattern
  already used for the `instr_dbg` trace field. This directly resolves
  a limitation `docs/hazards.md` had flagged as a known gap in Phase 6.

- **Bug found and fixed: a same-clock-edge race in testbench reset
  sequencing, not RTL.** `tb_perf_counters.sv` initially disagreed
  between Icarus Verilog and Verilator by exactly one cycle on the two
  free-running counters, while every conditional counter matched
  exactly. Root cause: every testbench in this project deasserted
  `rst_n` as the bare next statement after the last reset
  `@(posedge clk)` -- the same active edge every `always_ff(posedge clk
  or negedge rst_n)` block also samples it on, the same class of
  same-edge race Phase 5 found in `regfile.sv`, just never previously
  exercised by a signal that increments unconditionally every cycle
  from the start. Fixed with the standard fix (a `#1` delay before
  deasserting reset), applied to **every** testbench in the project
  (not just this one), since the same risk could in principle affect
  any of them; the full existing test suite was re-run afterward and
  continues to pass identically. Full account in `docs/pipeline.md`.

- **Added benchmark programs** `sim/programs/benchmarks/sum_loop.s`
  (pure-ALU loop, zero load-use stalls) and `array_sum.s` (load-heavy
  loop, one load-use stall per iteration) -- real, branch-driven loops,
  not synthetic NOP-padded code -- with correctness verified against
  hand-computed results by `sim/testbenches/tb_perf_counters.sv` (both
  simulators). An initial hand-derivation of `sum_loop.s`'s expected
  forwarding-event count (20, from static instruction spacing alone)
  was wrong by a third (measured: 12) -- static spacing doesn't account
  for the 2 bubble cycles a taken-branch flush inserts each iteration,
  which pushes some dependencies out of the forwarding-unit's range.
  The testbench asserts the measured value, not the flawed derivation.

- **Added `scripts/run_benchmarks.py`** (`make benchmarks`): runs both
  benchmarks via a new generic harness (`sim/testbenches/tb_benchmark.sv`)
  and writes `results/performance_report.md` from real simulation
  output -- no number in that report is estimated or hand-computed.
  CPI is computed in software from raw counters, not in hardware (no
  divider needed for a ratio nothing else in the datapath consumes).

- **Result:** `make test_perf` passes both benchmark correctness and
  counter checks under both simulators; full Phase 2-6 regression
  re-verified after the reset-sequencing fix.

## Phase 8 — System-on-Chip Integration (2026-09-14)

- **Refactored `rtl/cpu/riscv_cpu_pipeline.sv` into a data-bus master.**
  Removed its internal `dmem` instantiation and `DMEM_DEPTH_WORDS`
  parameter; added a plain bus-master port (`dbus_addr`, `dbus_wdata`,
  `dbus_mem_read`, `dbus_mem_write` as outputs, `dbus_rdata` as input),
  driven directly by the existing MEM-stage combinational assigns
  (`dbus_addr = alu_result_mem`, etc.) and consumed by `mem_wb_reg` in
  place of the old internal `dmem_rdata_mem` wire. This is a pure
  port-list/wiring change -- no ALU, hazard, forwarding, or control
  logic moved. Instruction memory (`imem`) is **not** part of this bus
  and stays internal on its own dedicated fetch-only port, unchanged
  since Phase 2 -- there is no requirement for the CPU to write program
  memory over the data bus.

- **Updated all four existing testbenches** that instantiate
  `riscv_cpu_pipeline` directly (`tb_pipeline.sv`,
  `tb_pipeline_directed_test.sv`, `tb_benchmark.sv`,
  `tb_perf_counters.sv`, the last of which needed two independent
  `dmem` instances for its two parallel DUTs) to wire a plain `dmem`
  to the new `dbus_*` ports themselves -- functionally identical to
  what the CPU module did internally before.

- **Verified the refactor as a pure regression before writing any new
  SoC code.** All four updated testbenches were re-run under both
  Icarus Verilog and Verilator: every architectural register check,
  all 3 pipeline hazard directed tests, and all 18 of
  `tb_perf_counters.sv`'s exact counter assertions reproduced their
  pre-refactor values unchanged (`sum_loop`: cycles=56 retired=34
  stall=0 branch=10 branch_taken=9 load_use=0 forwarding=12 flush=10;
  `array_sum`: cycles=51 retired=34 stall=5 branch=5 branch_taken=4
  load_use=5 forwarding=17 flush=5). `make benchmarks` was re-run
  afterward and reproduced the identical CPI figures; the only diff in
  `results/performance_report.md` is its generated-timestamp line.

- **Added the SoC memory map and bus:** `rtl/bus/soc_bus.sv` (a purely
  combinational address decoder on `addr[31:28]` routing the CPU's
  single bus-master port to RAM/UART/GPIO, with the accelerator region
  `0x30000000` reserved-but-unpopulated for Phase 9), `rtl/bus/uart.sv`
  (memory-mapped TX-only UART register interface: `TXDATA`/`STATUS`,
  a real busy flag, no fabricated serial-line timing), `rtl/bus/gpio.sv`
  (`GPIO_OUT`/`GPIO_IN` registers), and `rtl/cpu/riscv_soc.sv` (the
  top-level SoC wiring CPU + bus + RAM + UART + GPIO together). RAM is
  deliberately kept at `0x00000000` so every pre-Phase-8 test program's
  `LW`/`SW` addresses keep working unmodified through the real decoder.
  Full memory map and register tables in `docs/soc.md`.

- **Added `sim/programs/soc/soc_demo.s` and `sim/testbenches/tb_soc.sv`.**
  The test program is a real polling UART driver (write `TXDATA`, poll
  `STATUS` until idle, twice) rather than back-to-back writes, because
  `uart.sv`'s busy flag genuinely drops a write that arrives while
  busy -- this was caught while designing the test, not left as an
  untested edge case. The testbench drives `gpio_in` to a fixed pattern
  before reset and observes `uart.sv`'s `tx_valid`/`tx_byte` ports
  directly, printing every byte the CPU actually transmitted. Verified
  identical under both simulators (`make sim_soc` /
  `scripts/run_sim_soc.sh`); see `docs/soc.md`'s Verification section
  for the actual captured console output.

- **Result:** `make sim_soc` passes under both simulators; full Phase
  2-7 regression re-verified clean after the bus-master refactor.

## Phase 9 — Hardware Accelerator (2026-09-14)

- **Added `rtl/accelerator/accelerator.sv`**, one FSM-driven
  memory-mapped peripheral covering the task's vector-add ->
  dot-product -> matrix-multiply progression as three opcodes
  (`OP_VECADD`/`OP_DOT`/`OP_MATMUL`) on one shared register interface
  (`CTRL`/`STATUS`/`LEN`/`RESULT` + `VECA`/`VECB`/`VECOUT`
  scratchpads), rather than three separate peripherals -- see
  `docs/accelerator.md` for why. MATMUL runs a real sequential `N^3`
  triple-nested-loop FSM (`i`/`j`/`k` counters, one
  multiply-accumulate per cycle), not a combinational unrolled
  multiplier tree. Wired into `rtl/bus/soc_bus.sv` (new `accel_*` port)
  and `rtl/cpu/riscv_soc.sv` at `0x30000000`, the region that region's
  own Phase 8 decoder had already reserved.

- **Bug found and fixed during review, before this file was ever
  simulated: `LEN` register sized for the wrong bound.** An early
  draft sized `LEN` (and every FSM index counter) using
  `$clog2(MAX_DIM + 1)` -- correct for MATMUL's dimension bound
  (`N <= 8` needs 4 bits) but far too narrow for VECADD/DOT's element-
  count bound (`N` up to `MAX_LEN = 64`, needing 7 bits); a length of,
  say, 40 would have silently truncated to 8. Caught by re-reading the
  register map's own two different meanings for `LEN` side by side,
  not by a failing test. Fixed by sizing every FSM counter (`len_r`,
  `idx`, `mi`, `mj`, `mk`) to the larger bound
  (`LEN_BITS = $clog2(MAX_LEN + 1)`).

- **Bug found and fixed: a testbench-driver same-edge race that
  disagreed between simulators about its own fix.** The first version
  of `tb_accelerator.sv` drove `addr`/`wdata`/`mem_write` with plain
  blocking assignment immediately after `@(posedge clk)`. This raced
  the DUT's own `always_ff` block, which is triggered by that exact
  same edge -- their relative execution order within one simulation
  time step is simulator-defined. Measured effect: a `VECADD` of
  `a=[1..6]`, `b=[10,20,...,60]` computed `[12,23,34,0,0,0]` instead of
  `[11,22,...,66]` -- reading the scratchpad arrays directly (via
  hierarchical reference, before the FSM even started) showed `veca[]`
  holding `vecb[]`'s intended values and vice versa, shifted by one
  element. Nonblocking assignment is the standard textbook fix for
  exactly this class of race and resolved it under Icarus Verilog --
  but Verilator flagged it with `%Warning-INITIALDLY`, stating plainly
  that a nonblocking assignment inside an `initial`-block task executes
  as blocking under Verilator. Two simulators disagreeing about what
  the same source code even means is disqualifying for a project whose
  entire verification methodology is "both simulators must agree," so
  nonblocking assignment was rejected even though it "worked." Fixed
  instead with genuine simulation-time separation: a `#1` delay
  inserted *before* touching any DUT input (not just before releasing
  it), guaranteeing no process anywhere can observe the change until
  strictly after every same-edge evaluation has completed -- the same
  technique this project has used for reset sequencing since Phase 7,
  applied here to ordinary register-write stimulus for the first time.
  Full derivation (including the intermediate hierarchical-reference
  debug traces that isolated it) in `docs/accelerator.md` and
  `sim/testbenches/tb_accelerator.sv`'s task comments.

- **Added two testbenches verifying different layers, deliberately
  kept separate:** `sim/testbenches/tb_accelerator.sv` drives the
  accelerator's MMIO registers directly (VECADD N=6, DOT N=4, MATMUL
  N=3 with non-symmetric hand-computed operands so a row/column
  transposition bug would be caught, plus LEN=0 and LEN>MAX_DIM error
  handling); `sim/testbenches/tb_soc_accel.sv` runs
  `sim/programs/soc/accel_demo.s` -- real RISC-V assembly executed on
  the actual pipelined CPU -- through the full SoC, driving all three
  operations purely via `LW`/`SW` across the real bus. A failure in
  either always isolates which layer (accelerator RTL vs. CPU/bus
  path) actually broke.

- **Result:** `make test_accel` passes both testbenches under both
  simulators; full Phase 2-8 regression (`tb_soc.sv`'s RAM/UART/GPIO
  checks included) re-verified clean after wiring the accelerator onto
  the shared bus.

## Phase 10 — Custom RISC-V Extension for Accelerator Control (2026-09-14)

- **Added four `ACCEL.*` instructions** (`accel.vecadd`, `accel.dot`,
  `accel.matmul`, `accel.stat rd`) on RISC-V's custom-0 opcode
  (`0001011`, reserved by the spec for exactly this purpose). These
  replace the two most repetitive parts of Phase 9's MMIO accelerator
  driver -- hand-encoding `CTRL`'s `{opcode, START}` bit pattern, and
  knowing `STATUS`'s offset -- with one instruction each; every other
  accelerator register (`LEN`, `VECA`/`VECB`, `RESULT`/`VECOUT`) is
  deliberately left as ordinary `LW`/`SW`, since those accesses carry
  genuinely variable addresses/data a fixed-encoding instruction can't
  usefully shortcut. See `docs/custom_extension.md` for the full
  rationale.

- **Implementation reuses every existing pipeline mechanism rather than
  adding new ones.** `control_unit.sv` decodes `OP_CUSTOM0`+`funct3`
  into a new 3-bit `accel_sel` signal (`riscv_pkg.sv`'s new
  `ACCEL_SEL_*` constants) alongside the SAME `mem_read`/`mem_write`/
  `reg_write`/`result_src` signals an ordinary load or store would set
  -- so forwarding, the load-use hazard detector, and the MEM/WB
  writeback mux all handle these instructions correctly with zero
  changes of their own (`accel.stat` behaves exactly like a `LW` to the
  hazard unit). `accel_sel` is threaded through `id_ex_reg` and
  `ex_mem_reg` like any other control signal (forced to
  `ACCEL_SEL_NONE` on reset/flush, so a bubble is never mistaken for an
  `ACCEL.*` instruction). The only new logic is one MEM-stage mux in
  `riscv_cpu_pipeline.sv` substituting a hardwired address/data pair
  for `alu_result_mem`/`rs2_data_mem` when `accel_sel_mem !=
  ACCEL_SEL_NONE`; every other instruction takes the unchanged
  pre-Phase-10 path.

- **Build-tooling wrinkle found and fixed (not a functional bug):**
  adding a new `control_unit` output port meant `riscv_cpu.sv` (Phase
  2's single-cycle CPU, which shares `control_unit.sv` but predates the
  SoC bus this extension targets and has nothing to drive with it) had
  to explicitly leave the port unconnected. Verilator's default lint
  flagged this twice in a row: first `%Warning-PINMISSING` for simply
  omitting the port, then `%Warning-PINCONNECTEMPTY` for the explicit
  `.accel_sel()` connection that fixed the first warning -- both
  correctly describing the same underlying fact (an intentionally
  unconnected port) from two different angles. Resolved by keeping the
  explicit empty connection (the SystemVerilog-correct way to spell
  "intentional," not an oversight) and suppressing
  `PINCONNECTEMPTY` specifically in `scripts/run_sim_phase2.sh`'s
  Verilator invocation, with a comment explaining why -- not by
  disabling the warning class project-wide, since it remains a useful
  check everywhere else.

- **Added `sim/programs/soc/accel_custom_demo.s`**, deliberately a
  near-line-for-line copy of Phase 9's `accel_demo.s` with only the
  CTRL-write and STATUS-read instructions swapped for their `ACCEL.*`
  equivalents (same operands, same expected VECADD/DOT/MATMUL results)
  -- so the diff between the two files IS the demonstration of what
  this extension buys, and a pass on both testbenches proves the
  extension reaches the *same* accelerator behavior through a different
  instruction path, not a separately-verified, potentially-divergent
  one. Verified via `sim/testbenches/tb_soc_accel_custom.sv`.

- **Result:** `make test_accel_custom` passes under both simulators;
  full Phase 2-9 regression re-verified clean after the shared
  `control_unit.sv`/`id_ex_reg.sv`/`ex_mem_reg.sv` changes (every
  instruction in every existing test flows through those modules).
