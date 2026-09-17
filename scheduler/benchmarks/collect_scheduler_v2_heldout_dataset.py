#!/usr/bin/env python3
"""
collect_scheduler_v2_heldout_dataset.py -- post-Phase-17: run the 4
round-2 held-out workloads (vecadd/dot N=6, N=12 -- see
scheduler/benchmarks/gen_scheduler_programs.py's
HELDOUT_V2_VECADD_DOT_SIZES) through sim/testbenches/tb_benchmark_soc.sv
and write scheduler/training/heldout_dataset_v2.csv.

This is the genuinely-unseen evaluation set for
scheduler/training/train_scheduler_v2.py's retrained model: once that
script merges Phase 13's dataset.csv AND Phase 14's heldout_dataset.csv
into one 20-workload training set, none of those 20 are held-out
anymore, so a fresh set is needed to keep any held-out accuracy claim
honest.

Correctness of these 4 workloads (the actual computed result, not just
completion) is established by
sim/testbenches/tb_scheduler_v2_heldout_correctness.sv
(`make test_scheduler_v2_heldout_correctness`) -- run that first if
you have any doubt.

Usage:
    python3 scheduler/benchmarks/collect_scheduler_v2_heldout_dataset.py
"""

import csv
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

PROGRAMS = []
for op in ("vecadd", "dot"):
    for n in (6, 12):
        for engine, prefix in [("cpu", "cpu"), ("accelerator", "accel")]:
            PROGRAMS.append((op, n, engine, f"{prefix}_{op}_n{n}"))

RESULT_RE = re.compile(
    r"BENCHMARK_RESULT: name=(\S+) cycles=(\d+) retired=(\d+) stall=(\d+) "
    r"branch=(\d+) branch_taken=(\d+) load_use_stall=(\d+) forwarding=(\d+) flush=(\d+)"
)


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
        "cycles": int(m.group(2)), "retired": int(m.group(3)),
        "stall": int(m.group(4)), "forwarding": int(m.group(7)),
    }


def main():
    for op, n, engine, stem in PROGRAMS:
        src = f"{SRC_DIR}/{stem}.s"
        hexpath = f"{SRC_DIR}/{stem}.hex"
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
    for op, n, engine, stem in PROGRAMS:
        result = run_one(vvp_out, stem)
        rows.append({
            "operation": op, "size_n": n, "element_count": n, "engine": engine,
            "cycles": result["cycles"], "instructions_retired": result["retired"],
            "stall_count": result["stall"], "forwarding_events": result["forwarding"],
        })
        print(f"{op} N={n} [{engine}]: cycles={result['cycles']}")

    os.unlink(vvp_out)

    os.makedirs(os.path.join(ROOT, "scheduler", "training"), exist_ok=True)
    out_path = os.path.join(ROOT, "scheduler", "training", "heldout_dataset_v2.csv")
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
