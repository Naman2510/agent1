# Hardware Accelerator (Phase 9)

This document describes `rtl/accelerator/accelerator.sv`, a memory-mapped
hardware accelerator supporting the task's own vector-add -> dot-product
-> matrix-multiply progression, and how it is verified. It is real,
synthesizable-style sequential RTL -- an explicit finite state machine
with counters and an accumulator register -- not a combinational
unrolled multiplier tree and never a Python/software stand-in for
hardware. Everything here is a software simulation, verified under
Icarus Verilog and Verilator; no physical FPGA or hardware was used.

## Why one module, not three

The task describes the accelerator's scope as "vector add -> dot
product -> matrix multiply." Rather than three separate peripherals,
this is one module with a 2-bit opcode selecting the operation, for the
same reason `riscv_cpu_pipeline.sv` is one module evolved across Phases
5-8 instead of being rewritten each phase: the three operations share
almost everything (the same input scratchpads, the same address decode,
the same busy/done/error control flow, the same multiply-accumulate
datapath) and only differ in how their indices advance. Splitting them
into three peripherals would have meant re-deriving all of that
plumbing three times for no verification benefit -- each operation is
still tested independently and incrementally (see "Verification" below),
matching the task's "each capability compiles/simulates/tests before
the next" requirement even though the RTL exists as one file.

## Register interface

Phase 9 controls the accelerator purely through ordinary memory-mapped
I/O -- `LW`/`SW` through `rtl/bus/soc_bus.sv` at base address
`0x30000000` (see `docs/soc.md`'s memory map). Phase 10 adds a *custom
RISC-V instruction* as a more ergonomic trigger, but it will still
ultimately drive this same register interface, not a different
accelerator.

| Offset | Name | Access | Meaning |
|---|---|---|---|
| `0x0000` | `CTRL` | write-only | bit0 = START (self-clearing pulse, ignored while busy); bits[2:1] = OPCODE |
| `0x0004` | `STATUS` | read-only | bit0 = BUSY, bit1 = DONE, bit2 = ERR |
| `0x0008` | `LEN` | read/write (write ignored while busy) | vector length N (VECADD/DOT) or matrix dimension N (MATMUL) |
| `0x000C` | `RESULT` | read-only | scalar result of OP_DOT once DONE; not meaningful for the other ops |
| `0x1000..` | `VECA` | read/write | input operand A, word-addressed, up to `MAX_LEN` words |
| `0x2000..` | `VECB` | read/write | input operand B, same layout |
| `0x3000..` | `VECOUT` | read-only (written only by the FSM) | output; also the flattened row-major result matrix for MATMUL |

Opcodes (`CTRL` bits[2:1]): `01` = `OP_VECADD`, `10` = `OP_DOT`, `11` =
`OP_MATMUL`.

A typical driver sequence: write `LEN`, write the operand(s) into
`VECA`/`VECB`, write `CTRL` with the opcode and START set, then poll
`STATUS` until `DONE`, then read the result from `RESULT` (DOT) or
`VECOUT` (VECADD/MATMUL). `sim/programs/soc/accel_demo.s` is exactly
this sequence, written as real RISC-V assembly run on the actual CPU
(see "Verification" below).

### Operations

- **`OP_VECADD`**: `out[i] = a[i] + b[i]` for `i` in `[0, N)`, one
  addition per cycle (N cycles total). `N` (i.e. `LEN`) must satisfy
  `0 < N <= MAX_LEN`.
- **`OP_DOT`**: `result = sum_i a[i] * b[i]` for `i` in `[0, N)`, one
  multiply-accumulate per cycle (N cycles total), same `LEN` bound as
  VECADD.
- **`OP_MATMUL`**: treats `VECA`/`VECB`/`VECOUT` as flattened,
  row-major `N x N` matrices: `out[i,j] = sum_k a[i,k] * b[k,j]` for
  `i, j, k` in `[0, N)`. `LEN` here is the matrix dimension `N`, not an
  element count, so the operation reads/writes `N*N` scratchpad words
  from the same `LEN` value. `N` must satisfy `0 < N <= MAX_DIM`
  (`MAX_DIM*MAX_DIM == MAX_LEN` by construction, default `MAX_DIM=8`,
  i.e. up to an 8x8 matrix). Runs `i`/`j`/`k` as a real sequential
  triple-nested loop in hardware (`N^3` cycles) -- there is no shortcut
  taken here that a larger `N` wouldn't pay for honestly.

A `LEN` of 0, or a `LEN` exceeding the operation's bound, is caught at
START time: the FSM asserts `ERR` and `DONE` immediately without
touching any memory, rather than hanging or computing garbage.

### Multiplication semantics

Multiplication is 32x32 -> 64 bits, truncated to the low 32 bits and
treated as signed -- the same "low bits of the product" semantics
RV32M's `MUL` instruction uses, so results compose predictably with
ordinary RV32I arithmetic on the CPU side. This choice is independent
of whether the CPU itself implements the M extension (it does not); the
multiply is entirely internal to the accelerator's own datapath.

## A real width bug found before this file was ever simulated

An early draft sized the `LEN` register (and the FSM's running index
registers) using only `$clog2(MAX_DIM + 1)` bits -- correct for
MATMUL's dimension bound (`N <= 8` needs 4 bits) but silently
insufficient for VECADD/DOT's much larger element-count bound (`N` up
to `MAX_LEN = 64`, which needs 7 bits). A `LEN` of, say, 40 written into
a 4-bit register would have been truncated to 8 with no error reported.
This was caught in review, before the file was ever compiled, by
re-reading the register map's own two different meanings for `LEN`
side by side -- not by a failing test. The fix: size every FSM counter
(`len_r`, `idx`, `mi`, `mj`, `mk`) to `LEN_BITS = $clog2(MAX_LEN + 1)`,
the larger of the two bounds, so a full-length vector operation is
never silently truncated. See the module's own header comment and
`rtl/accelerator/accelerator.sv`'s `LEN_BITS` definition.

## A real testbench-driver bug found by the first simulation run

The first attempt at `sim/testbenches/tb_accelerator.sv` used plain
blocking assignment to drive `addr`/`wdata`/`mem_write` immediately
after `@(posedge clk)`, deasserting `mem_write` after a `#1` delay (the
same pattern already used successfully for reset sequencing elsewhere
in this project). Under simulation, this produced systematically wrong
results: a `VECADD` with `a=[1..6]`, `b=[10,20,...,60]` computed
`out=[12,23,34,0,0,0]` instead of `[11,22,...,66]` -- reading back the
scratchpad arrays directly (via hierarchical reference, before the FSM
even started) showed `veca[]` holding what should have been `vecb[]`'s
values and vice versa, shifted by one element.

Root cause: the testbench's own `always_ff`-driven DUT and the
testbench's `initial`-block task are BOTH triggered by the same
`posedge clk`. Setting `addr`/`wdata`/`mem_write` via blocking
assignment immediately after that edge races the DUT's own
`always_ff` block sampling those same signals at that exact edge --
their relative execution order within one simulation time step is
simulator-defined. The `#1` fix already used for reset sequencing only
protected the *deassertion* side; the race here was on the *assertion*
side.

Nonblocking assignment looked like the standard textbook fix for
exactly this class of bug, and it did resolve the failure under Icarus
Verilog. But Verilator explicitly flagged it with
`%Warning-INITIALDLY: Non-blocking assignment '<=' in initial/final
block ... This will be executed as a blocking assignment '='!` -- the
two simulators do not even agree on what that code means, which is
disqualifying for a project whose whole verification methodology rests
on "both simulators must produce the same result." The fix actually
used is real simulation-time separation: a `#1` delay is inserted
*before* touching any DUT input, not just before releasing it, so no
process anywhere can observe the new value until strictly after every
same-edge evaluation has already completed. This is unambiguous under
any IEEE-compliant simulator and is the same technique this project
already uses for reset sequencing (see `CHANGELOG.md`'s Phase 7 entry).
Full account, including the exact intermediate debug traces that
isolated the bug, is in `sim/testbenches/tb_accelerator.sv`'s `wr()`/
`rd()` task comments and `CHANGELOG.md`'s Phase 9 entry.

## Verification

Two testbenches, run separately and deliberately, so a failure in one
always isolates which layer broke:

**1. `sim/testbenches/tb_accelerator.sv`** drives the accelerator's own
MMIO register interface directly (no CPU involved), covering, in the
task's own vector-add -> dot-product -> matrix-multiply order:

- `OP_VECADD`, N=6: `a=[1..6]`, `b=[10,20,...,60]` -> `out=[11,22,...,66]`.
- `OP_DOT`, N=4: `a=[1,2,3,4]`, `b=[5,6,7,8]` -> `1*5+2*6+3*7+4*8 = 70`.
- `OP_MATMUL`, N=3, non-symmetric operands (so a row/column
  transposition bug would be caught): `A=[1 2 3; 4 5 6; 7 8 9]`,
  `B=[9 8 7; 6 5 4; 3 2 1]` -> `C = [30 24 18; 84 69 54; 138 114 90]`
  (full hand-derivation in the testbench's own header comment).
- `LEN=0` and `LEN > MAX_DIM` error handling: both must assert `ERR`
  and `DONE` promptly rather than hang.

**2. `sim/testbenches/tb_soc_accel.sv`** runs
`sim/programs/soc/accel_demo.s` -- real RISC-V assembly executed on the
actual pipelined CPU -- through the full `riscv_soc`, driving the same
three operations purely via `LW`/`SW` across the real address-decoded
bus at `0x30000000`, using the reserved-`x31` pass/fail convention from
`docs/testing.md`. This is what proves the accelerator is actually
reachable and controllable from software, not just correct in
isolation.

Both testbenches pass identically under Icarus Verilog and Verilator.
Run them yourself: `make test_accel` (or `./scripts/run_sim_accel.sh`).
The full Phase 2-8 regression was also re-run after wiring the
accelerator into `soc_bus.sv`/`riscv_soc.sv` and remains clean --
`sim/testbenches/tb_soc.sv`'s RAM/UART/GPIO checks are unaffected by
the accelerator's presence on the same bus.

## What Phase 9 does not do

- No physical FPGA execution or bitstream -- pure RTL simulation, as
  with every other phase. FPGA resource *estimation* is Phase 12's job.
- No DMA or CPU-independent operation -- the CPU must poll `STATUS`;
  there is no interrupt line yet (consistent with `docs/soc.md`'s note
  that there is no interrupt controller in this SoC yet).
- No floating point -- all arithmetic is RV32I-style 32-bit integer,
  matching the CPU's own ISA subset.
- Matrices are limited to `MAX_DIM x MAX_DIM` (default 8x8) and must be
  square; this bound exists to keep the scratchpad and the `N^3`-cycle
  MATMUL runtime reasonable for simulation, not because larger/
  non-square matrices are architecturally impossible.
