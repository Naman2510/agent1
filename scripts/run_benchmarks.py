#!/usr/bin/env python3
"""
run_benchmarks.py -- Phase 7: run the benchmark programs on the pipelined
CPU, collect real performance counter data (rtl/cpu/perf_counters.sv) via
sim/testbenches/tb_benchmark.sv, and write results/performance_report.md.

Every number in the generated report comes directly from parsing actual
Icarus Verilog simulation output -- nothing here is computed by hand or
estimated. Correctness of each benchmark program (the actual computed
result, not just its performance counters) is established separately by
sim/testbenches/tb_perf_counters.sv (make test_perf); this script only
measures and reports, per the project rule against fabricating numbers.

Usage:
    python3 scripts/run_benchmarks.py
"""

import datetime
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RTL_FILES = [
    "rtl/cpu/riscv_pkg.sv",
    "rtl/alu/alu.sv",
    "rtl/regfile/regfile.sv",
    "rtl/decoder/decoder.sv",
    "rtl/decoder/imm_gen.sv",
    "rtl/cpu/control_unit.sv",
    "rtl/cpu/branch_unit.sv",
    "rtl/memory/imem.sv",
    "rtl/memory/dmem.sv",
    "rtl/pipeline/if_id_reg.sv",
    "rtl/pipeline/id_ex_reg.sv",
    "rtl/pipeline/ex_mem_reg.sv",
    "rtl/pipeline/mem_wb_reg.sv",
    "rtl/pipeline/forwarding_unit.sv",
    "rtl/pipeline/hazard_unit.sv",
    "rtl/cpu/perf_counters.sv",
    "rtl/cpu/riscv_cpu_pipeline.sv",
]
TB = "sim/testbenches/tb_benchmark.sv"

# (name, hex file, cycles) -- cycle counts chosen as each program's own
# verified snapshot point (see sim/testbenches/tb_perf_counters.sv's
# header comment for how these were determined empirically, not guessed).
BENCHMARKS = [
    ("sum_loop", "sim/programs/benchmarks/sum_loop.s", 56),
    ("array_sum", "sim/programs/benchmarks/array_sum.s", 51),
]

RESULT_RE = re.compile(
    r"BENCHMARK_RESULT: name=(\S+) cycles=(\d+) retired=(\d+) stall=(\d+) "
    r"branch=(\d+) branch_taken=(\d+) load_use_stall=(\d+) forwarding=(\d+) flush=(\d+)"
)


def main():
    # Assemble every benchmark program.
    for name, src, _cycles in BENCHMARKS:
        hexpath = src[:-2] + ".hex"
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "asm_to_hex.py"),
             src, "-o", hexpath, "--words", "256"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"FAILED TO ASSEMBLE {src}:\n{r.stderr}", file=sys.stderr)
            sys.exit(1)

    # Compile the generic benchmark harness once.
    vvp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".vvp").name
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", vvp_out] + RTL_FILES + [TB],
        cwd=ROOT, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("Icarus compile failed:\n" + r.stdout + r.stderr, file=sys.stderr)
        sys.exit(1)

    rows = []
    for name, src, cycles in BENCHMARKS:
        hexpath = src[:-2] + ".hex"
        r = subprocess.run(
            ["vvp", vvp_out, f"+HEXFILE={hexpath}", f"+NAME={name}", f"+CYCLES={cycles}"],
            cwd=ROOT, capture_output=True, text=True,
        )
        m = RESULT_RE.search(r.stdout)
        if not m:
            print(f"no BENCHMARK_RESULT line for {name}; simulator output:\n{r.stdout}",
                  file=sys.stderr)
            sys.exit(1)
        (rname, rcycles, rretired, rstall, rbranch, rbranch_taken,
         rload_use, rforwarding, rflush) = m.groups()
        cycles_i, retired_i = int(rcycles), int(rretired)
        cpi = cycles_i / retired_i if retired_i else float("nan")
        rows.append({
            "name": rname, "cycles": cycles_i, "retired": retired_i,
            "cpi": cpi, "stall": int(rstall), "branch": int(rbranch),
            "branch_taken": int(rbranch_taken), "load_use_stall": int(rload_use),
            "forwarding": int(rforwarding), "flush": int(rflush),
        })
        print(f"{name}: cycles={cycles_i} retired={retired_i} cpi={cpi:.3f}")

    os.unlink(vvp_out)

    # Write the report.
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    report_path = os.path.join(ROOT, "results", "performance_report.md")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append("# Performance Report (Phase 7)")
    lines.append("")
    lines.append(f"Generated {now} by `scripts/run_benchmarks.py` from actual Icarus "
                  "Verilog simulation of `rtl/cpu/riscv_cpu_pipeline.sv`. Every number "
                  "below comes directly from that simulation's performance counters "
                  "(`rtl/cpu/perf_counters.sv`) -- none are estimated or hand-computed. "
                  "Each program's correctness (the actual computed result, not just its "
                  "timing) is separately verified by `sim/testbenches/tb_perf_counters.sv` "
                  "(`make test_perf`), which this report does not re-derive.")
    lines.append("")
    lines.append("| Benchmark | Cycles | Instructions retired | CPI | Stalls | Branches | Taken | Load-use stalls | Forwarding events | Flushes |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['cycles']} | {row['retired']} | {row['cpi']:.3f} | "
            f"{row['stall']} | {row['branch']} | {row['branch_taken']} | "
            f"{row['load_use_stall']} | {row['forwarding']} | {row['flush']} |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `sum_loop`: a pure-ALU loop (sum 1..10) with no memory accesses -- "
                  "zero load-use stalls, CPI close to 1 (ideal), with overhead from "
                  "pipeline fill and the taken-branch flush on every loop iteration.")
    lines.append("- `array_sum`: sums 5 memory-resident values with the loaded value used "
                  "by the very next instruction every iteration -- a genuine load-use "
                  "hazard each time, visible directly in the nonzero stall/load-use-stall "
                  "columns, and a *lower* CPI than `sum_loop` despite the stalls, because "
                  "this program is shorter and pays proportionally less pipeline-fill "
                  "overhead relative to its instruction count.")
    lines.append("- Flush counts are one higher than each program's real taken-branch "
                  "count: flush is counted when EX resolves a redirect, 3 pipeline stages "
                  "before that instruction retires, so each snapshot catches the halt "
                  "loop's first `j done` having resolved in EX without yet reaching WB. "
                  "See `sim/testbenches/tb_perf_counters.sv`'s header comment.")
    lines.append("- CPI here is `cycles / instructions retired`, computed in this script, "
                  "not in hardware -- see `rtl/cpu/perf_counters.sv`'s header comment for "
                  "why.")
    lines.append("")

    with open(report_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nWrote {report_path}")


if __name__ == "__main__":
    main()
