"""
costmodel.py -- per-task profile records and the plan cost model
(unchanged from scheduler/coschedule/planner.py; see docs/coschedule.md).

Profile record per task t (all measured by profiler.py):
  cpu[t]   extra cycles of a one-task program running t on the CPU
  acc[t]   extra cycles of a one-task program running t on the
           accelerator, serially (launch + wait + copy-out)
  busy[t]  cycles the accelerator itself is busy for t (START -> idle)
plus `base`, the cycles of an empty program (header + sentinel).

A plan's predicted cycle count is
  base + sum over serial CPU tasks of cpu[t]
       + sum over accelerator tasks a of
           acc[a] - busy[a] + max(busy[a], sum_{g in window(a)} cpu[g] + RELOAD)
where RELOAD covers the instructions that restore the MMIO base after the
window. With empty windows this reduces to the serial cost.

The model is an exact-size lookup: a task whose (op, n) was not profiled
has no cost (KeyError). Interpolation and uncertainty are Phase 6 work.
"""

import csv

RELOAD = 2  # `li x1, 0x30000000` assembles to lui + addi

CSV_HEADER = ["operation", "size_n", "cpu_cycles", "accel_cycles", "accel_busy_cycles"]


def plan_cost(plan, tasks, prof, base):
    total = base
    for i, (t, p) in enumerate(zip(tasks, plan)):
        if p[0] == "cpu":
            total += prof[t]["cpu"]
        elif p[0] == "acc":
            load = sum(prof[tasks[j]]["cpu"] for j, q in enumerate(plan) if q == ("win", i))
            busy = prof[t]["busy"]
            total += prof[t]["acc"] - busy + (max(busy, load + RELOAD) if load else busy)
    return total


def write_profile_csv(prof, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for (op, n), p in prof.items():
            w.writerow([op, n, p["cpu"], p["acc"], p["busy"]])


def read_profile_csv(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return {(r["operation"], int(r["size_n"])): {"cpu": int(r["cpu_cycles"]),
                                                  "acc": int(r["accel_cycles"]),
                                                  "busy": int(r["accel_busy_cycles"])}
            for r in rows}
