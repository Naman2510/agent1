#!/usr/bin/env python3
"""
run.py -- end-to-end pipeline for the concurrent CPU + accelerator
co-scheduler (docs/coschedule.md), scored against the pre-registered
docs/coschedule_scorecard.md.

  1. Profile: every task of the full 24-workload set, on each engine and
     each core configuration, as a one-task program
     (framework/profiler.py, sim/testbenches/tb_accel_phase_probe.sv).
  2. Plan: for each stream x core, the serial oracle, always-accelerator,
     and the co-schedule (framework/planner.py).
  3. Generate + assemble every program (sim/programs/coschedule/).
  4. Correctness: every output word of every program, on Icarus Verilog
     AND Verilator (sim/testbenches/tb_coschedule_check.sv).
  5. Measure: every program's cycle count through the established
     harness, sim/testbenches/tb_benchmark_soc.sv -- run twice, to check
     determinism.
  6. Write results/coschedule_report.md and
     results/coschedule_scorecard.md (score computed, not hand-entered;
     scheduler/coschedule/report.py).

The components live in scheduler/framework/ (docs/framework/); this file
only wires them together for the scored co-scheduler experiment.

Usage:
    .venv/bin/python3 scheduler/coschedule/run.py
"""

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scheduler"))
sys.path.insert(0, HERE)
from framework import planner as pl  # noqa: E402
from framework import rv32_codegen as cg  # noqa: E402
from framework import simulator as sim  # noqa: E402
from framework.plans import describe  # noqa: E402
from framework.profiler import profile  # noqa: E402
from framework.verification import write_expect_file  # noqa: E402
from framework.workloads import FULL_STREAM, STREAMS  # noqa: E402
from report import CORES, MODES, REPORT, SCORECARD, write_report, write_scorecard  # noqa: E402

PROG_DIR = os.path.join(ROOT, "sim", "programs", "coschedule")
PROFILE_PROG_DIR = os.path.join(ROOT, "build", "coschedule_profile")  # intermediate, gitignored
PROF_DIR = HERE


def main():
    os.makedirs(PROG_DIR, exist_ok=True)
    data = {"profiles": {}, "rows": [], "exhaustive": {}}
    for core, mul in CORES.items():
        print(f"== profiling ({core}) ==", flush=True)
        base, prof = profile(core, mul, FULL_STREAM, PROFILE_PROG_DIR,
                             os.path.join(PROF_DIR, f"profile_{core}.csv"))
        data["profiles"][core] = {"base": base}

        bench = sim.icarus("sim/testbenches/tb_benchmark_soc.sv", "tb_benchmark_soc",
                           {"ENABLE_MUL": mul, "IMEM_DEPTH_WORDS": cg.IMEM_WORDS})
        check = sim.icarus("sim/testbenches/tb_coschedule_check.sv", "tb_coschedule_check",
                           {"ENABLE_MUL": mul})
        print(f"== building Verilator checker ({core}) ==", flush=True)
        vdir = sim.build_verilator(mul)

        for sname, stream in STREAMS.items():
            tasks = [tuple(t) for t in stream]
            plans = {"always_accel": [("acc",)] * len(tasks),
                     "oracle": pl.oracle_plan(tasks, prof)}
            plans["cosched"], _ = pl.plan_stream(tasks, prof, base)
            expfile = os.path.join(PROG_DIR, f"{sname}.expect")
            nexp = write_expect_file(tasks, expfile)
            for mode in MODES:
                plan = plans[mode]
                stem = f"{sname}_{core}_{mode}"
                hexfile = sim.assemble(cg.program(tasks, plan, mul, f"{sname}, {core} core, {mode}"),
                                       stem, PROG_DIR, cg.IMEM_WORDS)
                ok_i = sim.check_icarus(check, hexfile, expfile, nexp)
                ok_v = sim.check_verilator(vdir, hexfile, expfile, nexp)
                cyc1 = sim.measure(bench, hexfile, mul)
                cyc2 = sim.measure(bench, hexfile, mul)
                pred = pl.plan_cost(plan, tasks, prof, base)
                row = {"stream": sname, "core": core, "mode": mode, "cycles": cyc1,
                       "cycles_rerun": cyc2, "predicted": pred, "correct_icarus": ok_i,
                       "correct_verilator": ok_v, "checked_words": nexp,
                       "plan": describe(tasks, plan)}
                data["rows"].append(row)
                print(f"  {stem:28s} cycles={cyc1:6d} predicted={pred:6d} "
                      f"icarus={'ok' if ok_i else 'FAIL'} verilator={'ok' if ok_v else 'FAIL'}",
                      flush=True)
            if sname == "phase15":
                ex_plan, ex_cost = pl.exhaustive(tasks, prof, base)
                data["exhaustive"][core] = {"planner": pl.plan_cost(plans["cosched"], tasks, prof, base),
                                            "optimum": ex_cost, "plan": describe(tasks, ex_plan)}
        for f in (bench, check):
            os.unlink(f)
        shutil.rmtree(vdir, ignore_errors=True)

    with open(os.path.join(PROF_DIR, "results.json"), "w") as f:
        json.dump(data, f, indent=1)
    write_report(data)
    write_scorecard(data)
    print(f"\nWrote {REPORT}\nWrote {SCORECARD}")


if __name__ == "__main__":
    main()
