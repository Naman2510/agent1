#!/usr/bin/env python3
"""
collect_mul_dataset.py -- measure every workload this project has real
data for (24: vecadd/dot N in {1,2,3,4,6,8,12,16,32,64}, matmul N in
{1,2,4,8}) on the SoC built with the optional hardware MUL
(ENABLE_MUL=1, docs/rv32m_mul.md), and compare against the RV32I
measurements every earlier phase made.

CPU dot/matmul use the hardware-MUL kernels from
scheduler/benchmarks/gen_mul_programs.py (verified by
sim/testbenches/tb_mul_kernels_correctness.sv). CPU vecadd and every
accelerator program contain no multiply, so they are the exact
programs measured before -- and this script re-measures them on the
MUL core and asserts the cycle counts are IDENTICAL to the RV32I
datasets (scheduler/training/dataset.csv, heldout_dataset.csv,
heldout_dataset_v2.csv). That checks, rather than assumes, that
enabling MUL changes nothing but the multiplies. Every run's
BENCHMARK_CONFIG line is asserted to say ENABLE_MUL=1.

Writes scheduler/training/dataset_mul.csv (same schema as dataset.csv)
and results/mul_benchmark_report.md.

Usage:
    python3 scheduler/benchmarks/collect_mul_dataset.py
"""

import csv
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRAINING = os.path.join(ROOT, "scheduler", "training")
OUT_CSV = os.path.join(TRAINING, "dataset_mul.csv")
REPORT = os.path.join(ROOT, "results", "mul_benchmark_report.md")
RV32I_CSVS = ["dataset.csv", "heldout_dataset.csv", "heldout_dataset_v2.csv"]

RTL_FILES = [
    "rtl/cpu/riscv_pkg.sv", "rtl/alu/alu.sv", "rtl/regfile/regfile.sv",
    "rtl/decoder/decoder.sv", "rtl/decoder/imm_gen.sv", "rtl/cpu/control_unit.sv",
    "rtl/cpu/branch_unit.sv", "rtl/memory/imem.sv", "rtl/memory/dmem.sv",
    "rtl/pipeline/if_id_reg.sv", "rtl/pipeline/id_ex_reg.sv", "rtl/pipeline/ex_mem_reg.sv",
    "rtl/pipeline/mem_wb_reg.sv", "rtl/pipeline/forwarding_unit.sv",
    "rtl/pipeline/hazard_unit.sv", "rtl/cpu/perf_counters.sv",
    "rtl/cpu/riscv_cpu_pipeline.sv", "rtl/bus/soc_bus.sv", "rtl/bus/uart.sv",
    "rtl/bus/gpio.sv", "rtl/accelerator/accelerator.sv", "rtl/cpu/riscv_soc.sv",
]
TB = "sim/testbenches/tb_benchmark_soc.sv"

VD_SIZES = [1, 2, 3, 4, 6, 8, 12, 16, 32, 64]
MM_SIZES = [1, 2, 4, 8]

RESULT_RE = re.compile(
    r"BENCHMARK_RESULT: name=(\S+) cycles=(\d+) retired=(\d+) stall=(\d+) "
    r"branch=(\d+) branch_taken=(\d+) load_use_stall=(\d+) forwarding=(\d+) flush=(\d+)")
CONFIG_RE = re.compile(r"BENCHMARK_CONFIG: name=(\S+) ENABLE_MUL=(\d)")


def program(op, n, engine):
    """(source dir, stem) for one workload/engine on the MUL core."""
    if engine == "cpu":
        if op == "vecadd":
            return ("sim/programs/benchmarks", "cpu_vecadd_bench") if n == 16 \
                else ("sim/programs/scheduler", f"cpu_vecadd_n{n}")
        return ("sim/programs/scheduler", f"cpu_{op}_mul_n{n}")
    if (op in ("vecadd", "dot") and n == 16) or (op == "matmul" and n == 4):
        return ("sim/programs/benchmarks", f"accel_{op}_bench")
    return ("sim/programs/scheduler", f"accel_{op}_n{n}")


def workloads():
    for op, sizes in (("vecadd", VD_SIZES), ("dot", VD_SIZES), ("matmul", MM_SIZES)):
        for n in sizes:
            yield op, n


def load_rv32i():
    truth = {}
    for name in RV32I_CSVS:
        with open(os.path.join(TRAINING, name), newline="") as f:
            for row in csv.DictReader(f):
                truth[(row["operation"], int(row["size_n"]), row["engine"])] = int(row["cycles"])
    return truth


def main():
    rv32i = load_rv32i()
    vvp = tempfile.NamedTemporaryFile(delete=False, suffix=".vvp").name
    r = subprocess.run(["iverilog", "-g2012", "-Ptb_benchmark_soc.ENABLE_MUL=1", "-o", vvp]
                       + RTL_FILES + [TB], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("Icarus compile failed:\n" + r.stdout + r.stderr)

    rows, mismatches = [], []
    for op, n in workloads():
        for engine in ("cpu", "accelerator"):
            d, stem = program(op, n, engine)
            a = subprocess.run([sys.executable, "scripts/asm_to_hex.py", f"{d}/{stem}.s",
                                "-o", f"{d}/{stem}.hex", "--words", "512"],
                               cwd=ROOT, capture_output=True, text=True)
            if a.returncode != 0:
                sys.exit(f"FAILED TO ASSEMBLE {d}/{stem}.s:\n{a.stderr}")
            out = subprocess.run(["vvp", vvp, f"+HEXFILE={d}/{stem}.hex", f"+NAME={stem}"],
                                 cwd=ROOT, capture_output=True, text=True).stdout
            cfg, m = CONFIG_RE.search(out), RESULT_RE.search(out)
            if not cfg or cfg.group(2) != "1":
                sys.exit(f"{stem}: harness did not report ENABLE_MUL=1:\n{out}")
            if not m:
                sys.exit(f"no BENCHMARK_RESULT for {stem}:\n{out}")
            cycles = int(m.group(2))
            rows.append({"operation": op, "size_n": n,
                         "element_count": n * n if op == "matmul" else n, "engine": engine,
                         "cycles": cycles, "instructions_retired": int(m.group(3)),
                         "stall_count": int(m.group(4)), "forwarding_events": int(m.group(8))})
            uses_mul = engine == "cpu" and op != "vecadd"
            if not uses_mul and rv32i.get((op, n, engine)) != cycles:
                mismatches.append((op, n, engine, rv32i.get((op, n, engine)), cycles))
            print(f"{op:6s} N={n:<3d} [{engine:11s}] {stem:22s} cycles={cycles}")
    os.unlink(vvp)

    if mismatches:
        sys.exit("non-multiplying programs changed cycle count on the MUL core "
                 f"(op, N, engine, RV32I, MUL): {mismatches}")
    print(f"\nall {sum(1 for r in rows if not (r['engine'] == 'cpu' and r['operation'] != 'vecadd'))} "
          "non-multiplying programs: cycle counts identical to the RV32I datasets")

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {OUT_CSV} ({len(rows)} rows)")
    write_report(rows, rv32i)
    print(f"Wrote {REPORT}")


def write_report(rows, rv32i):
    mul = {(r["operation"], r["size_n"], r["engine"]): r["cycles"] for r in rows}
    L = ["# CPU with Hardware MUL vs. Accelerator\n",
         "Generated by `scheduler/benchmarks/collect_mul_dataset.py` from Icarus Verilog "
         "simulation of `rtl/cpu/riscv_soc.sv` built with `ENABLE_MUL=1` (every run's "
         "`BENCHMARK_CONFIG` line checked), next to the RV32I measurements every earlier "
         "phase made (`scheduler/training/dataset.csv`, `heldout_dataset.csv`, "
         "`heldout_dataset_v2.csv`). CPU `dot`/`matmul` use the hardware-`MUL` kernels "
         "(`scheduler/benchmarks/gen_mul_programs.py`, correctness verified by "
         "`sim/testbenches/tb_mul_kernels_correctness.sv`). CPU `vecadd` and all "
         "accelerator programs contain no multiply; they were re-measured on the MUL "
         "core and their cycle counts are identical to the RV32I datasets (checked by "
         "the script, not assumed).\n",
         "| Workload | CPU (RV32I, software mul) | CPU (hardware MUL) | Accelerator | "
         "Winner, RV32I | Winner, with MUL |",
         "|---|---|---|---|---|---|"]
    flips, cpu_rv, cpu_mul = [], [], []
    for op, n in workloads():
        c0, c1, a = rv32i[(op, n, "cpu")], mul[(op, n, "cpu")], mul[(op, n, "accelerator")]
        w0 = "cpu" if c0 < a else "accelerator"
        w1 = "cpu" if c1 < a else "accelerator"
        if w0 == "cpu":
            cpu_rv.append(f"{op} N={n}")
        if w1 == "cpu":
            cpu_mul.append(f"{op} N={n}")
        if w0 != w1:
            flips.append((op, n, c0, c1, a))
        mark = f"**{w1}**" if w0 != w1 else w1
        L.append(f"| {op} N={n} | {c0} | {c1} | {a} | {w0} | {mark} |")
    L.append("")
    L.append(f"**CPU-favorable workloads: {len(cpu_rv)} of {len(rows) // 2} on RV32I "
             f"({', '.join(cpu_rv) or 'none'}); {len(cpu_mul)} of {len(rows) // 2} with "
             f"hardware MUL ({', '.join(cpu_mul) or 'none'}).**\n")
    if flips:
        L.append("Workloads whose faster engine changes when the CPU gets a multiplier:\n")
        for op, n, c0, c1, a in flips:
            L.append(f"- `{op}` N={n}: CPU {c0} -> {c1} cycles vs. accelerator {a}.")
        L.append("")
    sp = [(op, n, mul[(op, n, "cpu")] / mul[(op, n, "accelerator")]) for op, n in workloads()
          if op != "vecadd"]
    L.append("Accelerator speedup over the MUL-equipped CPU, multiply-heavy kernels: "
             + ", ".join(f"{op} N={n} {s:.2f}x" for op, n, s in sp) + ".\n")
    L.append("## Where the accelerator's remaining advantage comes from\n")
    L.append("Accelerator speedup at the same N -- `vecadd` (the CPU never multiplied) vs. "
             "`dot` on RV32I (software multiply) vs. `dot` with hardware MUL:\n")
    L.append("| N | vecadd | dot, RV32I | dot, hardware MUL |")
    L.append("|---|---|---|---|")
    for n in VD_SIZES:
        a = mul[("vecadd", n, "accelerator")]
        L.append(f"| {n} | {rv32i[('vecadd', n, 'cpu')] / a:.2f}x | "
                 f"{rv32i[('dot', n, 'cpu')] / mul[('dot', n, 'accelerator')]:.2f}x | "
                 f"{mul[('dot', n, 'cpu')] / mul[('dot', n, 'accelerator')]:.2f}x |")
    L.append("")
    gap = max(abs((mul[("dot", n, "cpu")] / mul[("dot", n, "accelerator")])
                  / (rv32i[("vecadd", n, "cpu")] / mul[("vecadd", n, "accelerator")]) - 1)
              for n in VD_SIZES)
    L.append(f"With a hardware multiplier the CPU's `dot` kernel lands within {gap * 100:.0f}% of "
             "its `vecadd` kernel's position relative to the accelerator, at every size: the "
             "software multiply was the entire extra gap on `dot`. What is left is the same "
             "per-element loop, address and load/store overhead the accelerator beats even on "
             "plain additions -- which a multiplier does nothing about. `matmul` keeps a larger "
             "lead because the CPU kernel pays that overhead N^3 times in its innermost loop.\n")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
