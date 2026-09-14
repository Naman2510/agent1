#!/usr/bin/env python3
"""
collect_dataset.py -- Phase 13: run every scheduler benchmark program
(Phase 11's original 6 CPU/accelerator pairs at N=16 vecadd/dot, N=4
matmul, PLUS this phase's 12 new size variants) through
sim/testbenches/tb_benchmark_soc.sv, and write
scheduler/training/dataset.csv -- one row per (operation, size,
engine) with its REAL measured cycle count. This is the labeled
dataset scheduler/training/train_scheduler.py fits a model on.

Every number in the dataset is parsed directly from actual Icarus
Verilog simulation output -- nothing here is estimated, interpolated,
or fabricated to pad the dataset. Correctness of every program
contributing a row is established BEFORE this script is trusted to run
them for timing: Phase 11's original 6 by
sim/testbenches/tb_bench_cpu_correctness.sv (+ Phase 9/10's own
accelerator tests), this phase's 12 new ones by
sim/testbenches/tb_scheduler_correctness.sv (`make
test_scheduler_correctness`) -- run that first if you have any doubt.

Usage:
    python3 scheduler/benchmarks/collect_dataset.py
"""

import csv
import math
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

# (operation, size, engine, program_stem, source_dir)
# size for vecadd/dot = vector length N; for matmul = matrix dimension
# N (element_count = N*N, computed below) -- see docs/scheduler.md for
# why these sizes were chosen.
PROGRAMS = []
for op, sizes, dirname in [
    ("vecadd", [1, 4, 16, 64], "benchmarks"),
    ("dot",    [1, 4, 16, 64], "benchmarks"),
    ("matmul", [2, 4, 8],      "benchmarks"),
]:
    for n in sizes:
        for engine, prefix in [("cpu", "cpu"), ("accelerator", "accel")]:
            # Phase 11's original N=16/N=4 programs kept their original
            # names (no _nNN suffix); Phase 13's new sizes use the
            # generator's _nNN naming (sim/programs/scheduler/).
            if (op in ("vecadd", "dot") and n == 16) or (op == "matmul" and n == 4):
                stem = f"{prefix}_{op}_bench"
                src_dir = "sim/programs/benchmarks"
            else:
                stem = f"{prefix}_{op}_n{n}"
                src_dir = "sim/programs/scheduler"
            PROGRAMS.append((op, n, engine, stem, src_dir))

RESULT_RE = re.compile(
    r"BENCHMARK_RESULT: name=(\S+) cycles=(\d+) retired=(\d+) stall=(\d+) "
    r"branch=(\d+) branch_taken=(\d+) load_use_stall=(\d+) forwarding=(\d+) flush=(\d+)"
)


def run_one(vvp_out, stem, src_dir):
    hexpath = f"{src_dir}/{stem}.hex"
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
        "cycles": int(m.group(2)), "retired": int(m.group(3)),
        "stall": int(m.group(4)), "forwarding": int(m.group(7)),
    }


def main():
    # Every hex file is already assembled by run_sim_accel.sh /
    # run_scheduler_correctness.sh; re-assemble here too so this script
    # can be run standalone.
    for op, n, engine, stem, src_dir in PROGRAMS:
        src = f"{src_dir}/{stem}.s"
        hexpath = f"{src_dir}/{stem}.hex"
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "asm_to_hex.py"),
             src, "-o", hexpath, "--words", "512"],
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

    rows = []
    for op, n, engine, stem, src_dir in PROGRAMS:
        result = run_one(vvp_out, stem, src_dir)
        element_count = n * n if op == "matmul" else n
        rows.append({
            "operation": op,
            "size_n": n,
            "element_count": element_count,
            "engine": engine,
            "cycles": result["cycles"],
            "instructions_retired": result["retired"],
            "stall_count": result["stall"],
            "forwarding_events": result["forwarding"],
        })
        print(f"{op} N={n} [{engine}]: cycles={result['cycles']}")

    os.unlink(vvp_out)

    os.makedirs(os.path.join(ROOT, "scheduler", "training"), exist_ok=True)
    out_path = os.path.join(ROOT, "scheduler", "training", "dataset.csv")
    fieldnames = ["operation", "size_n", "element_count", "engine", "cycles",
                  "instructions_retired", "stall_count", "forwarding_events"]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"\nWrote {out_path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
