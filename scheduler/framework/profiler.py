"""
profiler.py -- per-task profiling on the simulated SoC (moved unchanged
from scheduler/coschedule/run.py).

Every task is run as a one-task program on each engine, through
sim/testbenches/tb_accel_phase_probe.sv, which reports total cycles and
the accelerator's BUSY interval. A task's cost is its program's cycles
minus the empty program's (`base`).
"""

import os
import sys

from . import rv32_codegen as cg
from . import simulator as sim
from .costmodel import write_profile_csv

PROBE_TB = "sim/testbenches/tb_accel_phase_probe.sv"


def profile(core, mul, tasks, prog_dir, csv_path):
    """Measure every task in `tasks`; write `csv_path`; return (base, prof)."""
    vvp = sim.icarus(PROBE_TB, "tb_accel_phase_probe", {"ENABLE_MUL": mul})

    def run(text, stem):
        return sim.probe(vvp, sim.assemble(text, stem, prog_dir, cg.IMEM_WORDS))

    base, _ = run(cg.program([], [], mul, "empty"), f"prof_{core}_base")
    prof = {}
    for op, n in tasks:
        t = (op, n)
        cpu_total, _ = run(cg.program([t], [("cpu",)], mul, "profile"), f"prof_{core}_{op}{n}_cpu")
        acc_total, ivs = run(cg.program([t], [("acc",)], mul, "profile"), f"prof_{core}_{op}{n}_acc")
        if len(ivs) != 1 or ivs[0][1] < 0:
            sys.exit(f"{core} {op} N={n}: expected one accelerator busy interval, got {ivs}")
        prof[t] = {"cpu": cpu_total - base, "acc": acc_total - base,
                   "busy": ivs[0][1] - ivs[0][0]}
    os.unlink(vvp)
    write_profile_csv(prof, csv_path)
    return base, prof
