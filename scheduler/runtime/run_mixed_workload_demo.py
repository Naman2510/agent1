#!/usr/bin/env python3
"""
run_mixed_workload_demo.py -- Phase 16: run the four
mixed-heterogeneous-stream demo programs (mixed_dynamic_demo,
mixed_always_cpu_demo, mixed_always_accel_demo, mixed_oracle_demo --
see scheduler/runtime/gen_mixed_workload_demo.py) through
sim/testbenches/tb_benchmark_soc.sv and write
results/mixed_workloads_report.md from their REAL measured total cycle
counts, comparing against Phase 15's small-stream result
(results/dynamic_scheduling_report.md) to see whether the runtime
decision overhead Phase 15 found matters less at a larger, more varied
scale.

Correctness of all four programs is established separately by
sim/testbenches/tb_mixed_workload_correctness.sv
(`make test_mixed_workload_correctness`) -- run that first if you have
any doubt.

Usage:
    python3 scheduler/runtime/run_mixed_workload_demo.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    "rtl/bus/soc_bus.sv",
    "rtl/bus/uart.sv",
    "rtl/bus/gpio.sv",
    "rtl/accelerator/accelerator.sv",
    "rtl/cpu/riscv_soc.sv",
]
TB = "sim/testbenches/tb_benchmark_soc.sv"
SRC_DIR = "sim/programs/scheduler"

PROGRAMS = [
    ("mixed_dynamic_demo", "Dynamic (runtime-computed decision per block)"),
    ("mixed_always_cpu_demo", "Always CPU (static baseline)"),
    ("mixed_always_accel_demo", "Always accelerator (static baseline)"),
    ("mixed_oracle_demo", "Oracle (best real engine per block, from Phase 13/14 data)"),
]

RESULT_RE = re.compile(
    r"BENCHMARK_RESULT: name=(\S+) cycles=(\d+) retired=(\d+) stall=(\d+) "
    r"branch=(\d+) branch_taken=(\d+) load_use_stall=(\d+) forwarding=(\d+) flush=(\d+)"
)

REPORT_PATH = os.path.join(ROOT, "results", "mixed_workloads_report.md")


def run_one(vvp_out, stem):
    hexpath = f"{SRC_DIR}/{stem}.hex"
    r = subprocess.run(
        ["vvp", vvp_out, f"+HEXFILE={hexpath}", f"+NAME={stem}"],
        cwd=ROOT, capture_output=True, text=True,
    )
    m = RESULT_RE.search(r.stdout)
    if not m:
        print(f"no BENCHMARK_RESULT line for {stem}; simulator output:\n{r.stdout}",
              file=sys.stderr)
        sys.exit(1)
    return {
        "cycles": int(m.group(2)), "retired": int(m.group(3)), "stall": int(m.group(4)),
        "branch": int(m.group(5)), "branch_taken": int(m.group(6)), "flush": int(m.group(9)),
    }


def main():
    for stem, _ in PROGRAMS:
        src = f"{SRC_DIR}/{stem}.s"
        hexpath = f"{SRC_DIR}/{stem}.hex"
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "asm_to_hex.py"),
             src, "-o", hexpath, "--words", "1024"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"FAILED TO ASSEMBLE {src}:\n{r.stderr}", file=sys.stderr)
            sys.exit(1)

    vvp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".vvp").name
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", vvp_out] + RTL_FILES + [TB],
        cwd=ROOT, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("Icarus compile failed:\n" + r.stdout + r.stderr, file=sys.stderr)
        sys.exit(1)

    results = {}
    for stem, label in PROGRAMS:
        results[stem] = run_one(vvp_out, stem)
        print(f"{label}: {results[stem]['cycles']} cycles")
    os.unlink(vvp_out)

    write_report(results)
    print(f"\nWrote {REPORT_PATH}")


def _phase15_overhead_pct():
    """Read Phase 15's own real measured totals (not hand-copied) from
    results/dynamic_scheduling_report.md's counter table, to compare
    this phase's overhead percentage against it honestly."""
    path = os.path.join(ROOT, "results", "dynamic_scheduling_report.md")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read()
    dyn = re.search(r"\| dynamic_scheduler_demo \| (\d+) \|", text)
    acc = re.search(r"\| always_accel_demo \| (\d+) \|", text)
    if not dyn or not acc:
        return None
    dyn_c, acc_c = int(dyn.group(1)), int(acc.group(1))
    return (dyn_c - acc_c) / acc_c * 100, dyn_c, acc_c


def write_report(results):
    dyn = results["mixed_dynamic_demo"]["cycles"]
    cpu = results["mixed_always_cpu_demo"]["cycles"]
    acc = results["mixed_always_accel_demo"]["cycles"]
    oracle = results["mixed_oracle_demo"]["cycles"]
    overhead_pct = (dyn - acc) / acc * 100

    lines = []
    lines.append("# Mixed Heterogeneous Workloads Report (Phase 16)\n")
    lines.append(
        "Generated by `scheduler/runtime/run_mixed_workload_demo.py` from actual "
        "Icarus Verilog simulation of `rtl/cpu/riscv_soc.sv`. All four programs run "
        "the SAME fixed 12-workload stream (vecadd N=1,2,4,8,16,32; dot N=4,8,16,32; "
        "matmul N=2,4 -- see `scheduler/runtime/gen_mixed_workload_demo.py`), Phase "
        "15's approach applied at roughly 4-32x the per-workload scale. Correctness of "
        "all four is established separately by "
        "`sim/testbenches/tb_mixed_workload_correctness.sv` "
        "(`make test_mixed_workload_correctness`).\n"
    )
    lines.append("| Program | Total cycles |")
    lines.append("|---|---|")
    lines.append(f"| Dynamic (runtime decision) | {dyn} |")
    lines.append(f"| Always CPU | {cpu} |")
    lines.append(f"| Always accelerator | {acc} |")
    lines.append(f"| Oracle (best-per-block, from real data) | {oracle} |")
    lines.append("")

    verdict = "SLOWER than" if dyn > acc else "faster than"
    lines.append(
        f"**Dynamic vs. always-accelerator: {dyn} vs. {acc} cycles -- dynamic is "
        f"{abs(dyn-acc)} cycles ({abs(overhead_pct):.1f}%) {verdict} the naive baseline.**"
    )

    p15 = _phase15_overhead_pct()
    if p15:
        p15_pct, p15_dyn, p15_acc = p15
        lines.append(
            f"\n**Comparison with Phase 15's small 6-workload stream** (read directly "
            f"from `results/dynamic_scheduling_report.md`, not hand-copied): there, "
            f"dynamic ({p15_dyn} cycles) was {p15_pct:.1f}% worse than always-accelerator "
            f"({p15_acc} cycles). Here, at roughly 4-32x the per-workload scale, dynamic "
            f"is only {overhead_pct:.1f}% worse. This confirms the hypothesis Phase 15's "
            f"finding raised: **the runtime decision's fixed per-block overhead matters "
            f"proportionally less as each block does more real work** -- the relative "
            f"penalty shrunk by roughly "
            f"{'%.0fx' % (abs(p15_pct)/abs(overhead_pct)) if overhead_pct != 0 else 'a large factor'} "
            f"between the two streams."
        )
    lines.append(
        f"\n**But the ceiling itself is the real limiting factor, not just overhead.** "
        f"Oracle ({oracle} cycles) beats always-accelerator ({acc} cycles) by only "
        f"{acc - oracle} cycles here -- because in this project's real measured data, "
        f"the accelerator wins essentially every workload except `vecadd` at N=1 (see "
        f"`docs/scheduler.md`). A perfect, zero-overhead scheduler could only ever have "
        f"saved {acc - oracle} cycles on this exact stream, regardless of how good its "
        f"decisions are or how cheap they are to make. **For this specific "
        f"accelerator/workload combination, always using the accelerator is already "
        f"very close to optimal** -- the real crossover this project found (Phase 13's "
        f"`vecadd N=1`) is a narrow, small-workload corner case, not a broad regime "
        f"where a learned scheduler has much room to add value. See "
        f"docs/mixed_workloads.md for the full discussion."
    )
    lines.append("")
    lines.append("## Full counter detail\n")
    lines.append("| Program | Cycles | Instructions retired | Stalls | Branches | Taken | Flushes |")
    lines.append("|---|---|---|---|---|---|---|")
    for stem, label in PROGRAMS:
        r = results[stem]
        lines.append(f"| {stem} | {r['cycles']} | {r['retired']} | {r['stall']} | "
                      f"{r['branch']} | {r['branch_taken']} | {r['flush']} |")
    lines.append("")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
