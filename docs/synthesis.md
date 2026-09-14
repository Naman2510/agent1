# FPGA Synthesis Resource Estimates (Phase 12)

This document describes how Phase 12 produces FPGA resource estimates
for this project's RTL using Yosys (and, where noted, nextpnr-ice40 /
icestorm for place-and-route and timing). **This is synthesis-tool
estimation only. No physical FPGA or hardware was used anywhere in
this project, and no number in `results/synthesis_report.md` is, or
should be read as, a measurement taken on real silicon.** Every
number is parsed directly from actual Yosys output by
`scripts/gen_synthesis_report.py` -- nothing is estimated by hand or
guessed.

## Toolchain

- **Yosys 0.33** (`apt install yosys`) -- synthesis, targeting Lattice
  iCE40 via its built-in `synth_ice40` flow.
- **nextpnr-ice40** and **icestorm** (`icetime`) -- place-and-route and
  static timing analysis, where a full-design run completes in
  reasonable time (see "Scope" below for why the full SoC's own
  place-and-route is not always run).

iCE40 was chosen as the reference device specifically because it's
what this fully open-source toolchain supports without any vendor
software -- a demonstration/tooling choice, not a claim about intended
deployment hardware. A different reference device (e.g. Lattice ECP5,
also nextpnr-supported) would produce different absolute numbers; the
methodology here would transfer directly.

## Two real problems this phase had to solve

Both are documented here, and in `CHANGELOG.md`'s Phase 12 entry, in
full -- neither was silently worked around.

### 1. Yosys's open-source frontend rejects `import pkg::*;` entirely

Confirmed directly against Yosys itself, not assumed:

```
$ yosys -p "read_verilog -sv <file with 'import riscv_pkg::*;'>"
ERROR: syntax error, unexpected TOK_ID, expecting '(' or ';' or '#'
```

This is a real limitation of Yosys 0.33's built-in (non-commercial)
SystemVerilog frontend: it accepts fully-qualified references
(`riscv_pkg::ALU_ADD`) but rejects `import pkg::*;` in any placement
(module header or module body, wildcard or explicit -- all four
combinations were tried and all four fail). Eight files in `rtl/`
import `riscv_pkg` this way.

**Fix:** `scripts/prep_synth_rtl.py` stages a mechanically-transformed
COPY of `rtl/` into `build/synth_src/` (gitignored, regenerated every
run) -- it never edits `rtl/` itself. The transformation, applied only
to the affected files: delete the `import riscv_pkg::*;` line, and
replace every whole-word reference to one of `riscv_pkg.sv`'s own
exported parameter names (extracted directly from `riscv_pkg.sv`, so
the script can't silently drift out of sync with the package) with its
fully-qualified form. Per the SystemVerilog LRM, a wildcard import and
a fully-qualified reference to the same symbol resolve to the
identical declaration -- this is a syntactic transformation, not a
semantic one.

### 2. An uninitialized ROM lets Yosys optimize the CPU away

`rtl/memory/imem.sv` is explicitly documented (in its own header
comment, since Phase 2) as "a behavioral simulation model, not a
synthesizable ROM" -- its runtime `+HEXFILE=...` plusarg override
(`$value$plusargs`) is a simulation-only construct with no synthesis
meaning. A first synthesis attempt used a naive stand-in with no
defined instruction content (an all-X array) and reported an
implausibly small `riscv_soc`: about 240 cells total for a complete
pipelined RV32I CPU plus bus, UART, GPIO, and accelerator -- clearly
wrong for a design whose accelerator module ALONE synthesizes to over
17,000 cells in isolation.

**Root cause:** an array with no defined initial value and no write
port is, to Yosys, a source of "don't care" (X) values. Logic driven
by X doesn't constrain any observable output, so `opt`/`opt_clean`
aggressively const-propagate large swaths of the decode/execute
pipeline away, since -- as far as the optimizer can prove -- their
result doesn't matter. This is not a bug in Yosys; it is exactly what
"don't care" optimization is supposed to do, applied to a memory this
project's own testbenches always initialize with a real program before
ever caring about its output.

**Fix:** `synth/stubs/imem_synth_stub.sv` -- a synthesis-only stand-in
for `rtl/memory/imem.sv` (same module name `imem`, matching what
`riscv_cpu_pipeline.sv` instantiates, but lives outside `rtl/` and is
never simulated or substituted into the real design) -- accepts a
compile-time `INIT_FILE` parameter and loads it via `$readmemh` (a
real, synthesizable construct, unlike the plusarg version).
`scripts/run_synthesis.sh` loads it with a real, instruction-diverse
program (`sim/programs/soc/accel_custom_demo.s`, which exercises
ordinary RV32I arithmetic/branches AND the `ACCEL.*` custom
instructions) rather than leaving it empty. `synth/stubs/dmem_synth_stub.sv`
is zero-initialized for the same reason (its actual values don't
matter, only that they're *defined*).

Both stubs' header comments carry this same explanation, so a reader
encountering `synth/stubs/` for the first time understands immediately
why these files exist and why they must never be confused with, or
substituted for, the verified RTL under `rtl/`.

## Scope: synthesis (Yosys), not place-and-route

The task's own framing for this phase names Yosys specifically ("FPGA
synthesis estimates without physical hardware (Yosys)"), and that is
this document's primary deliverable: real `synth_ice40` cell counts
(LUT4/carry/flip-flop counts) for every module, parsed directly from
Yosys output.

**Place-and-route (`nextpnr-ice40`) and timing (`icetime`) were tried,
not skipped by default**, and the result is reported honestly rather
than hidden: `nextpnr-ice40` requires either a pin-constraint file
(`.pcf`) mapping every top-level port to a physical package pin, or
enough unconstrained general-purpose I/O pins on the chosen package to
auto-place everything. A trial run against a small module (`uart`, ~29
cells) on a small iCE40 package failed with `Unable to find a
placement location for cell 'wdata[2]$sb_io'` -- not a logic problem
(synthesis for that same module succeeds cleanly), but a physical-pin-
budget problem that only has a real answer once a specific target
board and its actual pinout are chosen. Since this project deliberately
targets no physical board, inventing a `.pcf` file and a package choice
just to produce a placement result would mean fabricating a piece of
hardware context this project doesn't have -- exactly what the task's
own rules prohibit. Cell-count synthesis estimates don't have this
problem (they describe the design's own logic, not a hypothetical
board's pin budget), which is this document's honest reason for
reporting those and not place-and-route results.

A second, separate practical constraint: ABC's technology-mapping pass
on the full SoC, with the RTL's own full 1024-word memory depths, took
long enough in this environment (tens of minutes, tens of thousands of
gates extracted) that a smaller, clearly-labeled 256-word memory depth
was substituted for the full-SoC synthesis run specifically via a
`chparam` override -- never for anything that was simulated or
correctness-tested, which all keep using the RTL's real 1024-word
default. See `results/synthesis_report.md`'s own notes for the exact
parameters used.

## What Phase 12 does not do

- No physical FPGA execution, bitstream generation, or hardware
  measurement of any kind.
- No claim that the reported cell counts would be identical on a
  different vendor's FPGA, a different synthesis tool, or a
  commercial-grade optimizer -- these are real, honestly-obtained
  numbers from one specific open-source toolchain and reference
  device, not a universal resource figure.
- No RTL was changed to make it synthesize "better" -- where synthesis
  revealed a real inefficiency (see `results/synthesis_report.md`'s
  note on Block RAM inference not triggering for combinationally-read
  memories), it is reported as a finding, not silently fixed in RTL
  that Phases 2-11 already verified and depends on that exact timing.
