#!/usr/bin/env python3
"""
run_pipeline_hazard_tests.py -- Phase 6 directed-test runner for the
pipelined CPU's hazard handling.

Same structure as scripts/run_directed_tests.py (Phase 3): assembles
every .s file under sim/programs/pipeline_tests/, builds
sim/testbenches/tb_pipeline_directed_test.sv ONCE per simulator, re-runs
it once per test via a +HEXFILE=... +TESTNAME=... plusarg pair, and
requires both Icarus Verilog and Verilator to agree.

Usage:
    python3 scripts/run_pipeline_hazard_tests.py
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(ROOT, "sim", "programs", "pipeline_tests")

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
TB = "sim/testbenches/tb_pipeline_directed_test.sv"

RESULT_RE = re.compile(r"TEST_RESULT: (PASS|FAIL) test=(\S+)(.*)")


def assemble_all():
    tests = sorted(glob.glob(os.path.join(TESTS_DIR, "*.s")))
    if not tests:
        print(f"no test programs found under {TESTS_DIR}", file=sys.stderr)
        sys.exit(1)
    names = []
    for src in tests:
        name = os.path.splitext(os.path.basename(src))[0]
        hexpath = os.path.join(TESTS_DIR, name + ".hex")
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "asm_to_hex.py"),
             src, "-o", hexpath, "--words", "512"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"FAILED TO ASSEMBLE {src}:\n{r.stderr}", file=sys.stderr)
            sys.exit(1)
        names.append(name)
    return names


def parse_result(output, name):
    for line in output.splitlines():
        m = RESULT_RE.search(line)
        if m and m.group(2) == name:
            return (m.group(1), m.group(3).strip())
    return ("FAIL", "(no TEST_RESULT line found -- simulation may have hung or crashed)")


def run_icarus(names):
    vvp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".vvp").name
    cmd = ["iverilog", "-g2012", "-o", vvp_out] + RTL_FILES + [TB]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print("Icarus compile failed:\n" + r.stdout + r.stderr, file=sys.stderr)
        sys.exit(1)

    results = {}
    for name in names:
        hexpath = os.path.join("sim", "programs", "pipeline_tests", name + ".hex")
        r = subprocess.run(
            ["vvp", vvp_out, f"+HEXFILE={hexpath}", f"+TESTNAME={name}"],
            cwd=ROOT, capture_output=True, text=True,
        )
        results[name] = parse_result(r.stdout, name)
    os.unlink(vvp_out)
    return results


def run_verilator(names):
    vdir = tempfile.mkdtemp()
    cmd = ["verilator", "--binary", "--timing", "-Wno-fatal",
           "--top-module", "tb_pipeline_directed_test"] + RTL_FILES + \
          [TB, "-o", "simv", "--Mdir", vdir]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print("Verilator build failed:\n" + r.stdout + r.stderr, file=sys.stderr)
        sys.exit(1)

    results = {}
    binpath = os.path.join(vdir, "simv")
    for name in names:
        hexpath = os.path.join("sim", "programs", "pipeline_tests", name + ".hex")
        r = subprocess.run(
            [binpath, f"+HEXFILE={hexpath}", f"+TESTNAME={name}"],
            cwd=ROOT, capture_output=True, text=True,
        )
        results[name] = parse_result(r.stdout, name)

    shutil.rmtree(vdir, ignore_errors=True)
    return results


def report(sim_name, results):
    print(f"\n== {sim_name} ==")
    all_pass = True
    for name, (status, detail) in results.items():
        mark = "PASS" if status == "PASS" else "FAIL"
        if status != "PASS":
            all_pass = False
        print(f"  [{mark}] {name:28s} {detail}")
    return all_pass


def main():
    names = assemble_all()
    print(f"Assembled {len(names)} pipeline hazard test program(s): {', '.join(names)}")

    icarus_results = run_icarus(names)
    icarus_ok = report("Icarus Verilog", icarus_results)

    verilator_results = run_verilator(names)
    verilator_ok = report("Verilator", verilator_results)

    print()
    if icarus_ok and verilator_ok:
        print(f"RESULT: ALL {len(names)} PIPELINE HAZARD TESTS PASSED UNDER BOTH SIMULATORS")
        sys.exit(0)
    else:
        print("RESULT: ONE OR MORE PIPELINE HAZARD TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
