# System-on-Chip Integration (Phase 8)

This document describes `rtl/cpu/riscv_soc.sv`, the top-level SoC that
connects the Phase 5-7 pipelined CPU (`rtl/cpu/riscv_cpu_pipeline.sv`) to
a memory-mapped bus with three peripherals: RAM, a UART, and a GPIO
block. Everything here is a software simulation model, verified under
Icarus Verilog and Verilator exactly like every prior phase -- no
physical FPGA or hardware was used, and this document makes no claim
otherwise.

## Why the CPU had to change first: the bus-master refactor

Before Phase 8, `riscv_cpu_pipeline.sv` instantiated its own `dmem`
directly inside the MEM stage -- fine when the CPU's only possible data
memory *was* that one `dmem`, but wrong once the same address space also
needs to reach a UART and a GPIO block. The fix was to externalize the
data-memory interface: the CPU module no longer instantiates any memory
at all for data accesses. Instead it exposes a plain synchronous
bus-master port:

```
output logic [31:0] dbus_addr,
output logic [31:0] dbus_wdata,
output logic         dbus_mem_read,
output logic         dbus_mem_write,
input  logic [31:0] dbus_rdata,
```

driven directly by the MEM stage (`dbus_addr = alu_result_mem`,
`dbus_wdata = rs2_data_mem`, etc. -- see the module's own header comment
and MEM-stage section), with `mem_wb_reg`'s `mem_rdata_in` now sourced
from `dbus_rdata` instead of an internal wire. This is a pure
port-list/wiring change: no ALU, hazard, forwarding, or control logic
moved. Every testbench that instantiates `riscv_cpu_pipeline` directly
(`tb_pipeline.sv`, `tb_pipeline_directed_test.sv`, `tb_benchmark.sv`,
`tb_perf_counters.sv`) now wires a plain `dmem` to these `dbus_*` ports
itself -- functionally identical to what the CPU did internally before,
which is exactly what let this refactor be verified as a pure regression
(see "Verification" below) rather than a new feature.

Instruction memory (ROM) is **not** part of this new bus. `imem` stays
instantiated inside `riscv_cpu_pipeline` on its own dedicated,
fetch-only, combinational-read port, unchanged since Phase 2. There is
no requirement anywhere in this project for the CPU to write program
memory over the data bus, and modeling it as a separate Harvard-style
fetch path is both simpler and matches how the single-cycle CPU
(`riscv_cpu.sv`) already works.

## Memory map

Address decode (`rtl/bus/soc_bus.sv`) looks only at the top 4 bits of
the 32-bit byte address, `addr[31:28]`:

| Region | Address range | Peripheral | Module |
|---|---|---|---|
| 0x0 | `0x00000000` - `0x0FFFFFFF` | RAM | `rtl/memory/dmem.sv` |
| 0x1 | `0x10000000` - `0x1FFFFFFF` | UART | `rtl/bus/uart.sv` |
| 0x2 | `0x20000000` - `0x2FFFFFFF` | GPIO | `rtl/bus/gpio.sv` |
| 0x3 | `0x30000000` - `0x3FFFFFFF` | Accelerator (**reserved**) | none yet -- Phase 9 |
| other | everything else | unmapped | reads as 0, writes dropped |

RAM is deliberately kept at address `0x00000000`, not shifted to make
room for "device 0": every test program from Phases 2-7 was assembled
assuming `LW`/`SW` addresses start at 0, and this decoder exists
specifically so that assumption keeps holding when those same programs
run through the full SoC instead of a bare `dmem` (see "Verification"
below for how this was actually checked, not just assumed).

Within each peripheral's own 256 MB region, only the low 4 bits of the
address (`addr[3:0]`) are decoded into that peripheral's own tiny
register file -- the peripherals themselves have no idea they are memory
mapped at `0x1...` or `0x2...`; `soc_bus.sv` strips that off by simply
never asserting `mem_read`/`mem_write` to a peripheral whose region
wasn't selected (see its own header comment for the exact mechanism).

### RAM (`0x00000000` base)

Identical `dmem.sv` model used since Phase 2: word-addressed,
word-sized-only accesses (`LW`/`SW`), synchronous write, combinational
read. Same behavioral-simulation-only caveat as always -- not
synthesizable SRAM.

### UART (`0x10000000` base) -- `rtl/bus/uart.sv`

| Offset | Name | Access | Meaning |
|---|---|---|---|
| `0x0` | `TXDATA` | write-only | byte in `wdata[7:0]`; accepted only if not busy |
| `0x4` | `STATUS` | read-only | bit 0 = `TX_BUSY` |

This is a simulation model of a UART's **software-visible register
interface**, not a bit-accurate serial-line model: there is no physical
TX pin, start/stop bits, or real baud-rate timing, because none of that
is observable without physical hardware -- modeling it would mean
fabricating numbers this project's own rules forbid. What *is* real and
verified in simulation: a byte written to `TXDATA` while idle is
captured exactly once; `STATUS` asserts busy for a deliberately-small,
explicitly-labeled `BUSY_CYCLES` (a simulation parameter, not a baud
rate) so software has something honest to poll; and a write that arrives
while busy is dropped, exactly as a full hardware FIFO would reject it
-- which is why `sim/programs/soc/soc_demo.s`'s UART section is a real
polling driver (`wait_tx1`/`wait_tx2` loops) rather than back-to-back
writes that would silently lose a byte. The module also exposes
`tx_valid`/`tx_byte` ports that pulse for exactly one cycle per accepted
byte, purely for a testbench to observe and print -- this is how the
SoC testbench (`sim/testbenches/tb_soc.sv`) proves real bytes left the
CPU, without pretending to simulate an RS-232 line.

### GPIO (`0x20000000` base) -- `rtl/bus/gpio.sv`

| Offset | Name | Access | Meaning |
|---|---|---|---|
| `0x0` | `GPIO_OUT` | read/write | drives the `gpio_out` SoC output port |
| `0x4` | `GPIO_IN` | read-only | reflects the `gpio_in` SoC input port |

`gpio_out`/`gpio_in` are plain 32-bit ports at the SoC boundary. There
is no physical pin/pad/IO-buffer model here (never claimed) -- `gpio_in`
is simply an input a testbench drives to simulate an external signal,
and `gpio_out` is an output a testbench observes to prove software can
change it. `sim/testbenches/tb_soc.sv` drives `gpio_in` to a fixed
constant (`0xCAFEBABE`) before reset deasserts and checks the CPU reads
that exact value back through the bus.

### Accelerator region (`0x30000000` base) -- reserved

`soc_bus.sv`'s decoder already recognizes this region (`SEL_ACCEL`) but
routes it nowhere -- there is no peripheral behind it yet. Reads return
0 and writes are silently dropped, both simply because nothing claims
the address, not because anything is being hidden. Phase 9 is expected
to populate this region with the hardware accelerator and wire it into
`soc_bus.sv` the same way UART/GPIO were added here.

## `rtl/cpu/riscv_soc.sv`: top-level wiring

Instantiates, in order: `riscv_cpu_pipeline` (all of its Phase 7
debug/perf ports passed straight through the SoC boundary, so an
SoC-level testbench keeps the same observability earlier testbenches
had) -> `soc_bus` (address decode) -> `dmem` (as RAM) + `uart` + `gpio`
in parallel, each wired to its own slice of `soc_bus`'s per-peripheral
port set. `IMEM_INIT_FILE`, `IMEM_DEPTH_WORDS`, `RAM_DEPTH_WORDS`, and
`UART_BUSY_CYCLES` are all exposed as SoC-level parameters so a
testbench can select a program and tune the UART's simulated latency
without editing any RTL.

## Verification

Two separate things were verified, in this order, exactly because
conflating them would hide which change broke what:

**1. The bus-master refactor is a pure regression (no behavior
changed).** Every one of the four existing testbenches that instantiate
`riscv_cpu_pipeline` directly (`tb_pipeline.sv`,
`tb_pipeline_directed_test.sv`, `tb_benchmark.sv`,
`tb_perf_counters.sv`) was re-run, unmodified in intent (only their
`dmem` instantiation moved from inside the CPU module to inside the
testbench itself), under both Icarus Verilog and Verilator. Every check
value -- architectural register state, all 3 hazard directed tests'
pass/fail, and every one of `tb_perf_counters.sv`'s 18 exact counter
assertions (`sum_loop`: cycles=56 retired=34 stall=0 branch=10
branch_taken=9 load_use=0 forwarding=12 flush=10; `array_sum`: cycles=51
retired=34 stall=5 branch=5 branch_taken=4 load_use=5 forwarding=17
flush=5) -- matched exactly, cycle for cycle, against the pre-refactor
numbers recorded in `results/performance_report.md`. `make benchmarks`
was also re-run afterward and reproduced the identical CPI figures
(`sum_loop` 1.647, `array_sum` 1.500) -- the report file's diff after
re-generating is a timestamp line only.

**2. The new SoC itself is correct.** `sim/testbenches/tb_soc.sv` runs
`sim/programs/soc/soc_demo.s` against `riscv_soc` and checks, through
the real address-decoded bus (not by touching any peripheral directly):

- a `SW`/`LW` round-trip through RAM at `0x00000000` still works;
- `GPIO_OUT` is writable and reads back what was written;
- `GPIO_IN` correctly reflects the testbench's externally-driven
  `0xCAFEBABE`;
- a real UART polling driver (write `TXDATA`, poll `STATUS` until
  idle, twice) completes and leaves `STATUS` idle.

The program uses the reserved-`x31` pass/fail convention from
`docs/testing.md`, same as every directed test since Phase 3. Run under
both simulators, this actual measured console output was produced (not
hand-written or fabricated):

```
=== Phase 8 SoC testbench ===
  gpio_in driven to 0xcafebabe
  [UART TX] byte=0x48 ('H') @ t=265000
  [UART TX] byte=0x49 ('I') @ t=385000

gpio_out final value = 0x000000a5
UART bytes actually transmitted this run: 2

TEST_RESULT: PASS test=soc_demo
```

identically from Icarus Verilog and Verilator. The `[UART TX]` lines are
real per-byte events captured from `uart.sv`'s `tx_valid`/`tx_byte`
ports as the simulation ran, not a description written after the fact.

Run it yourself: `make sim_soc` (or `./scripts/run_sim_soc.sh`).

## What Phase 8 does not do

- No physical FPGA bitstream, pin constraints, or board I/O -- this
  is, and is documented as, a pure RTL simulation of the SoC's logical
  behavior. FPGA resource *estimation* (still not physical execution)
  is Phase 12's job, using Yosys synthesis, not this phase's.
- No interrupt controller, DMA, or bus arbitration -- there is exactly
  one bus master (the CPU) and no interrupt sources yet, so none of
  that machinery has anything to arbitrate or interrupt.
- No UART receive path (RX) -- only the TX direction the task's own
  "UART" peripheral mention implies is exercised by this phase's demo;
  nothing currently needs the CPU to receive bytes.
- The accelerator region is address-space-reserved only, per above --
  Phase 9 builds the actual peripheral behind it.
