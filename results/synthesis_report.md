# FPGA Synthesis Resource Estimates (Phase 12)

Generated 2026-09-14 23:04 UTC by `scripts/run_synthesis.sh` (`scripts/gen_synthesis_report.py`) from actual Yosys 0.33 `synth_ice40` output, targeting Lattice iCE40 as a representative open-source-toolchain-supported device -- **this is synthesis-tool resource estimation only. No physical FPGA or hardware was used or is claimed anywhere in this report.** See `docs/synthesis.md` for full methodology, including two non-obvious things this phase had to work around (a Yosys package-import limitation, and an uninitialized-ROM optimization pitfall) -- both documented there and in `CHANGELOG.md`'s Phase 12 entry, not silently patched over.

## Per-module cell counts

Each logic module synthesized independently (its own `synth_ice40 -top <module>` run), so these numbers do not sum to the full-SoC row below -- shared logic, register duplication, and place-time optimization differ once everything is combined. See the full-SoC section for the combined design's own real total.

| Module | Total cells | SB_LUT4 | SB_CARRY | SB_DFFR | SB_DFFE | SB_DFFER |
|---|---|---|---|---|---|---|
| alu | 843 | 717 | 126 | 0 | 0 | 0 |
| regfile | 2820 | 1828 | 0 | 0 | 0 | 992 |
| decoder | 0 | 0 | 0 | 0 | 0 | 0 |
| imm_gen | 40 | 40 | 0 | 0 | 0 | 0 |
| control_unit | 38 | 38 | 0 | 0 | 0 | 0 |
| branch_unit | 127 | 63 | 64 | 0 | 0 | 0 |
| forwarding_unit | 20 | 20 | 0 | 0 | 0 | 0 |
| hazard_unit | 10 | 10 | 0 | 0 | 0 | 0 |
| perf_counters | 755 | 258 | 241 | 64 | 0 | 192 |
| uart | 29 | 17 | 1 | 0 | 0 | 11 |
| gpio | 100 | 68 | 0 | 0 | 0 | 32 |
| soc_bus | 108 | 108 | 0 | 0 | 0 | 0 |
| accelerator | 17074 | 10630 | 194 | 0 | 6144 | 106 |
| riscv_cpu_pipeline | 5923 | 3579 | 490 | 544 | 0 | 1309 |

## Full SoC (`riscv_soc`)

The complete design -- pipelined CPU, bus, UART, GPIO, and accelerator -- synthesized as one flattened top level, with its instruction ROM loaded with a real, instruction-diverse program (`sim/programs/soc/accel_custom_demo.s`) rather than left uninitialized (see `docs/synthesis.md` for why that distinction matters here).

**Total cells: 38390**

| Cell type | Count | Meaning |
|---|---|---|
| SB_LUT4 | 21365 | 4-input look-up table (the basic logic cell) |
| SB_DFFE | 14336 | D flip-flop with clock enable |
| SB_DFFER | 1458 | D flip-flop with clock enable and async reset |
| SB_CARRY | 686 | fast carry chain (used by adders/subtractors/comparators) |
| SB_DFFR | 544 | D flip-flop with async reset |
| SB_DFFS | 1 | (iCE40 primitive) |

## Notes

- **iCE40 chosen as the reference device** because it is what this project's fully open-source toolchain (Yosys + nextpnr-ice40 + icestorm) targets without any vendor software -- a demonstration choice, not a claim about intended deployment hardware.
- **Per-module counts are independent synthesis runs**, each module's own ports treated as the synthesis boundary -- they measure that module's logic in isolation, useful for seeing where resources concentrate, but they do not sum to the full-SoC total (shared control logic, cross-module optimization, and duplicated vs. shared registers all differ once everything is combined into one flattened design).
- **No Block RAM inference occurred** for either the instruction/data memories or the accelerator's operand scratchpads -- all mapped to flip-flops instead. This is a real, honest synthesis-tool result, not a bug: every one of these arrays is read *combinationally* (an unregistered `assign rdata = mem[addr];`-style read), and iCE40's `SB_RAM40_4K` primitive requires a registered read port, so Yosys's default `memory_bram` mapping correctly declines to use it here. A real FPGA implementation of this design would very likely want a registered read port specifically to unlock Block RAM for these arrays -- worth flagging as a concrete future optimization, not something this phase silently fixed by changing already-verified, cycle-accurate RTL.
- **No timing/Fmax figure is reported here.** Place-and-route (`nextpnr-ice40`) was tried, not skipped by default, but requires committing to a specific physical package and pin assignment that has no real meaning without an actual target board -- see `docs/synthesis.md`'s "Scope" section for what was tried and why it wasn't adopted. Synthesis cell counts alone do not imply a clock frequency.

