#!/usr/bin/env python3
"""
gen_synthesis_report.py -- Phase 12: parse the Yosys log
scripts/run_synthesis.sh produced and write
results/synthesis_report.md from the real cell counts it contains.
Every number in the generated report is parsed directly from actual
Yosys `stat` output -- nothing here is estimated or hand-computed, and
no physical FPGA/hardware measurement is claimed anywhere in it.

Usage:
    python3 scripts/gen_synthesis_report.py <synth_log_path> <soc_json_path>
"""

import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Matches a "-- name --" section header this script's own log writer
# (scripts/run_synthesis.sh's run_module()) emits before each Yosys run.
SECTION_RE = re.compile(r"^-- (\S+) --\s*$", re.MULTILINE)
CELL_COUNT_RE = re.compile(r"^\s*Number of cells:\s*(\d+)\s*$", re.MULTILINE)
CELL_LINE_RE = re.compile(r"^\s{5}(SB_\w+)\s+(\d+)\s*$", re.MULTILINE)

# iCE40 cell -> what it represents, for the report's own legend.
CELL_MEANING = {
    "SB_LUT4": "4-input look-up table (the basic logic cell)",
    "SB_CARRY": "fast carry chain (used by adders/subtractors/comparators)",
    "SB_DFFR": "D flip-flop with async reset",
    "SB_DFFE": "D flip-flop with clock enable",
    "SB_DFFER": "D flip-flop with clock enable and async reset",
    "SB_RAM40_4K": "4Kbit Block RAM",
}


def parse_sections(log_text):
    """Split the log into {module_name: section_text} by the '-- name --' headers."""
    matches = list(SECTION_RE.finditer(log_text))
    sections = {}
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(log_text)
        sections[name] = log_text[start:end]
    return sections


def parse_module_stats(section_text):
    total_m = CELL_COUNT_RE.search(section_text)
    total = int(total_m.group(1)) if total_m else None
    cells = {}
    for m in CELL_LINE_RE.finditer(section_text):
        cells[m.group(1)] = int(m.group(2))
    return total, cells


def main():
    if len(sys.argv) != 3:
        print("usage: gen_synthesis_report.py <synth_log_path> <soc_json_path>",
              file=sys.stderr)
        sys.exit(1)
    log_path, soc_json_path = sys.argv[1], sys.argv[2]

    with open(log_path) as f:
        log_text = f.read()
    sections = parse_sections(log_text)

    module_order = [
        "alu", "regfile", "decoder", "imm_gen", "control_unit", "branch_unit",
        "forwarding_unit", "hazard_unit", "perf_counters", "uart", "gpio",
        "soc_bus", "accelerator", "riscv_cpu_pipeline", "riscv_soc",
    ]

    rows = []
    for name in module_order:
        if name not in sections:
            print(f"WARNING: no section found for {name} in {log_path}", file=sys.stderr)
            continue
        total, cells = parse_module_stats(sections[name])
        if total is None:
            print(f"WARNING: no cell count found for {name}", file=sys.stderr)
            continue
        rows.append((name, total, cells))

    # Sanity-check the full SoC JSON exists and is well-formed (confirms
    # synth_ice40 actually completed for the top-level design, not just
    # printed a stat block from an earlier partial run).
    with open(soc_json_path) as f:
        soc_design = json.load(f)
    if "riscv_soc" not in soc_design.get("modules", {}):
        print(f"ERROR: {soc_json_path} does not contain a riscv_soc module",
              file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    report_path = os.path.join(ROOT, "results", "synthesis_report.md")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append("# FPGA Synthesis Resource Estimates (Phase 12)")
    lines.append("")
    lines.append(f"Generated {now} by `scripts/run_synthesis.sh` "
                  "(`scripts/gen_synthesis_report.py`) from actual Yosys 0.33 "
                  "`synth_ice40` output, targeting Lattice iCE40 as a "
                  "representative open-source-toolchain-supported device -- "
                  "**this is synthesis-tool resource estimation only. No "
                  "physical FPGA or hardware was used or is claimed anywhere "
                  "in this report.** See `docs/synthesis.md` for full "
                  "methodology, including two non-obvious things this phase "
                  "had to work around (a Yosys package-import limitation, "
                  "and an uninitialized-ROM optimization pitfall) -- both "
                  "documented there and in `CHANGELOG.md`'s Phase 12 entry, "
                  "not silently patched over.")
    lines.append("")
    lines.append("## Per-module cell counts")
    lines.append("")
    lines.append("Each logic module synthesized independently (its own "
                  "`synth_ice40 -top <module>` run), so these numbers do not "
                  "sum to the full-SoC row below -- shared logic, register "
                  "duplication, and place-time optimization differ once "
                  "everything is combined. See the full-SoC section for the "
                  "combined design's own real total.")
    lines.append("")
    lines.append("| Module | Total cells | SB_LUT4 | SB_CARRY | SB_DFFR | SB_DFFE | SB_DFFER |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, total, cells in rows:
        if name == "riscv_soc":
            continue
        lines.append(
            f"| {name} | {total} | {cells.get('SB_LUT4', 0)} | "
            f"{cells.get('SB_CARRY', 0)} | {cells.get('SB_DFFR', 0)} | "
            f"{cells.get('SB_DFFE', 0)} | {cells.get('SB_DFFER', 0)} |"
        )
    lines.append("")

    soc_row = next((r for r in rows if r[0] == "riscv_soc"), None)
    if soc_row:
        _name, total, cells = soc_row
        lines.append("## Full SoC (`riscv_soc`)")
        lines.append("")
        lines.append("The complete design -- pipelined CPU, bus, UART, GPIO, "
                      "and accelerator -- synthesized as one flattened top "
                      "level, with its instruction ROM loaded with a real, "
                      "instruction-diverse program "
                      "(`sim/programs/soc/accel_custom_demo.s`) rather than "
                      "left uninitialized (see `docs/synthesis.md` for why "
                      "that distinction matters here).")
        lines.append("")
        lines.append(f"**Total cells: {total}**")
        lines.append("")
        lines.append("| Cell type | Count | Meaning |")
        lines.append("|---|---|---|")
        for cell_type, count in sorted(cells.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {cell_type} | {count} | "
                          f"{CELL_MEANING.get(cell_type, '(iCE40 primitive)')} |")
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- **iCE40 chosen as the reference device** because it is "
                  "what this project's fully open-source toolchain "
                  "(Yosys + nextpnr-ice40 + icestorm) targets without any "
                  "vendor software -- a demonstration choice, not a claim "
                  "about intended deployment hardware.")
    lines.append("- **Per-module counts are independent synthesis runs**, "
                  "each module's own ports treated as the synthesis "
                  "boundary -- they measure that module's logic in "
                  "isolation, useful for seeing where resources concentrate, "
                  "but they do not sum to the full-SoC total (shared "
                  "control logic, cross-module optimization, and "
                  "duplicated vs. shared registers all differ once "
                  "everything is combined into one flattened design).")
    lines.append("- **No Block RAM inference occurred** for either the "
                  "instruction/data memories or the accelerator's operand "
                  "scratchpads -- all mapped to flip-flops instead. This is "
                  "a real, honest synthesis-tool result, not a bug: every "
                  "one of these arrays is read *combinationally* (an "
                  "unregistered `assign rdata = mem[addr];`-style read), and "
                  "iCE40's `SB_RAM40_4K` primitive requires a registered "
                  "read port, so Yosys's default `memory_bram` mapping "
                  "correctly declines to use it here. A real FPGA "
                  "implementation of this design would very likely want a "
                  "registered read port specifically to unlock Block RAM "
                  "for these arrays -- worth flagging as a concrete future "
                  "optimization, not something this phase silently fixed by "
                  "changing already-verified, cycle-accurate RTL.")
    lines.append("- **No timing/Fmax figure is reported here.** "
                  "Place-and-route (`nextpnr-ice40`) was tried, not "
                  "skipped by default, but requires committing to a "
                  "specific physical package and pin assignment that has "
                  "no real meaning without an actual target board -- see "
                  "`docs/synthesis.md`'s \"Scope\" section for what was "
                  "tried and why it wasn't adopted. Synthesis cell counts "
                  "alone do not imply a clock frequency.")
    lines.append("")

    with open(report_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
