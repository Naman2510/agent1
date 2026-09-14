# Custom RISC-V Extension for Accelerator Control (Phase 10)

This document describes the `ACCEL.*` custom instructions this project
adds to the pipelined CPU (`rtl/cpu/riscv_cpu_pipeline.sv`), and how
they are verified. Everything here is a software simulation, verified
under Icarus Verilog and Verilator; no physical FPGA or hardware was
used.

## What this extension is (and is not) for

Phase 9's accelerator (`rtl/accelerator/accelerator.sv`) is already
fully controllable through ordinary `LW`/`SW` at its memory-mapped
register interface -- `sim/programs/soc/accel_demo.s` proves that. This
extension does **not** add any new capability the accelerator didn't
already have; it adds four instructions that replace the two most
repetitive, easy-to-get-wrong parts of an MMIO accelerator driver with
one instruction each:

- Starting an operation used to be `li x5, 0bNN1; sw x5, 0(x1)` --
  hand-encoding the `{opcode, START}` bit pattern into an immediate --
  becomes one instruction (`accel.vecadd`, `accel.dot`, or
  `accel.matmul`) with nothing to encode by hand.
- Reading the STATUS register used to be `lw x6, 4(x1)` -- needing the
  driver to know the STATUS offset -- becomes `accel.stat x6`.

Writing `LEN` and the `VECA`/`VECB` operands, and reading `RESULT`/
`VECOUT`, are **not** replaced -- they stay ordinary `LW`/`SW`. This
was a deliberate scope decision, not a shortcut: those accesses carry
genuinely variable addresses and data (which element, which value),
which a fixed-encoding instruction can't usefully shortcut without
either adding immediate/register operands to every accelerator
register (defeating the point of a lightweight trigger instruction) or
hardwiring a single scratchpad index (useless for anything but a
length-1 vector). The four registers this extension DOES cover --
`CTRL`'s start pulse and `STATUS`'s read -- are exactly the two with a
fixed address and, for `CTRL`, fixed data per operation.

`sim/programs/soc/accel_custom_demo.s` is line-for-line the same
program as Phase 9's `accel_demo.s`, with only the CTRL-write and
STATUS-read instructions swapped for their `ACCEL.*` equivalents --
deliberately, so the diff between the two files IS the demonstration of
what this extension buys.

## Encoding

`ACCEL.*` instructions use RISC-V's **custom-0** opcode
(`0001011`), the encoding space the spec itself reserves for exactly
this purpose (see `docs/riscv.md` section 3's introduction) -- it
cannot collide with any standard RV32I encoding. All four instructions
use the R-type field layout, though `rs1`/`rs2`/`funct7` are unused by
this extension's hardware (assembled as 0 by `scripts/asm_to_hex.py`).

| Mnemonic | funct3 | rd | Operation |
|---|---|---|---|
| `accel.vecadd` | `000` | ignored | Start `OP_VECADD` on the accelerator (writes `CTRL = {opcode=01, START=1}`) |
| `accel.dot` | `001` | ignored | Start `OP_DOT` (`CTRL = {opcode=10, START=1}`) |
| `accel.matmul` | `010` | ignored | Start `OP_MATMUL` (`CTRL = {opcode=11, START=1}`) |
| `accel.stat rd` | `011` | destination | `rd = STATUS` |

funct3 values `100`-`111` are undefined for this extension and are
flagged `illegal` by `control_unit.sv`, the same diagnose-don't-
silently-execute-garbage policy every other unsupported opcode/funct3
combination in this project already gets.

## How it's implemented

The key design choice: an `ACCEL.*` instruction's target address (and,
for the three START variants, its write data) is **hardwired**, derived
purely from which instruction it is -- never computed by the ALU or
read from a register, unlike an ordinary `LW`/`SW`. This is what lets
one instruction do the work of two.

- `control_unit.sv` decodes `OP_CUSTOM0` + `funct3` into a 3-bit
  `accel_sel` signal (`rtl/cpu/riscv_pkg.sv`'s `ACCEL_SEL_*`
  constants) alongside the *same* `mem_read`/`mem_write`/`reg_write`/
  `result_src` control signals an ordinary load or store would set --
  so every existing piece of pipeline machinery (forwarding, the
  load-use hazard detector, the MEM/WB writeback mux) already handles
  these instructions correctly with no changes of its own. `accel.stat`
  in particular behaves exactly like a `LW` from the hazard unit's
  point of view (same one-cycle load-use stall applies if the very
  next instruction needs its result).
- `accel_sel` is threaded through `id_ex_reg` and `ex_mem_reg` exactly
  like every other control signal already threaded through those
  registers (and forced to `ACCEL_SEL_NONE` on reset/flush, so a
  bubble is never mistaken for an `ACCEL.*` instruction).
- In the MEM stage, `riscv_cpu_pipeline.sv` adds one small mux: when
  `accel_sel_mem != ACCEL_SEL_NONE`, `dbus_addr`/`dbus_wdata` are
  overridden with a hardwired constant (looked up from `accel_sel_mem`)
  instead of the ordinary `alu_result_mem`/`rs2_data_mem` path. Every
  other instruction is completely unaffected (the mux's default case is
  the pre-Phase-10 behavior).

The `{opcode, START}` bit layout this mux writes for the three START
variants matches `rtl/accelerator/accelerator.sv`'s `CTRL` register
exactly, and is deliberately duplicated in `riscv_cpu_pipeline.sv`
rather than shared via the package: a real custom instruction's
hardware behavior for one specific accelerator is expected to be baked
into the CPU, not parameterized around a peripheral that might change
later -- see the MEM stage's own comment for the full reasoning.

### The single-cycle CPU does not implement this extension

`rtl/cpu/riscv_cpu.sv` (Phase 2's single-cycle design) shares
`control_unit.sv` and therefore decodes `ACCEL.*` instructions
correctly, but it predates Phase 8's SoC bus entirely -- it still owns
its own internal `dmem` and was never connected to an accelerator. Its
`control_unit` instantiation leaves the new `accel_sel` output
deliberately unconnected (with a comment saying so, not silently
dropped) since there is nothing on that CPU for it to drive.

## Verification

`sim/testbenches/tb_soc_accel_custom.sv` runs
`sim/programs/soc/accel_custom_demo.s` on the full `riscv_soc`, using
the same reserved-`x31` pass/fail convention as every other directed
test (`docs/testing.md`), and passes identically under Icarus Verilog
and Verilator. Because the program is a near-exact copy of Phase 9's
`accel_demo.s` (same operands, same expected VECADD/DOT/MATMUL
results), a pass here combined with `tb_soc_accel.sv`'s pass on the
plain-MMIO version is what proves the custom extension reaches the
*same* accelerator hardware behavior through a different instruction
path -- not a separately-verified, potentially-divergent one.

The full Phase 2-9 regression was also re-run after this change
(`control_unit.sv`'s new output port, and the new `accel_sel` field
threaded through `id_ex_reg`/`ex_mem_reg`, touch every instruction that
passes through those shared modules) and remains clean -- see
`CHANGELOG.md`'s Phase 10 entry for the one build-tooling wrinkle this
surfaced (a Verilator lint warning on the single-cycle CPU's
intentionally-unconnected new port) and its fix.

Run it yourself: `make test_accel_custom` (or
`./scripts/run_sim_accel_custom.sh`).

## What Phase 10 does not do

- No new *capability* -- see "What this extension is (and is not)
  for" above. Everything `ACCEL.*` can do, plain MMIO could already do.
- No custom instructions for `LEN`, `VECA`/`VECB` writes, or
  `RESULT`/`VECOUT` reads -- deliberately out of scope, per the same
  section.
- No physical FPGA execution -- pure RTL simulation, as with every
  other phase.
