"""
planner.py -- cost model and search for the concurrent CPU + accelerator
co-scheduler (docs/coschedule.md).

Cost model (all inputs measured per task by profiling, see run.py):
  base           cycles of an empty program (header + sentinel)
  cpu[t]         extra cycles of a one-task program running t on the CPU
  acc[t]         extra cycles of a one-task program running t on the
                 accelerator, serially (launch + wait + copy-out)
  busy[t]        cycles the accelerator itself is busy for t (START -> idle)

A plan's predicted cycle count is
  base + sum over serial CPU tasks of cpu[t]
       + sum over accelerator tasks a of
           acc[a] - busy[a] + max(busy[a], sum_{g in window(a)} cpu[g] + RELOAD)
where RELOAD covers the instructions that restore the MMIO base after the
window. With empty windows this reduces to the serial cost, so the serial
oracle is itself a plan, and local search starting from it can only
improve the model's prediction. Whether the model matches real cycles is
checked against simulation (scorecard metric 6), not assumed.
"""

import itertools

RELOAD = 2  # `li x1, 0x30000000` assembles to lui + addi


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


def valid(plan):
    return all(p[0] != "win" or (p[1] != i and plan[p[1]][0] == "acc") for i, p in enumerate(plan))


def oracle_plan(tasks, prof):
    return [("cpu",) if prof[t]["cpu"] < prof[t]["acc"] else ("acc",) for t in tasks]


def _options(i, plan):
    opts = [("cpu",), ("acc",)]
    opts += [("win", j) for j, q in enumerate(plan) if j != i and q[0] == "acc"]
    return opts


def local_search(tasks, prof, base, start):
    """Deterministic best-improvement search over single-task moves.
    Moving a window host off the accelerator sends its guests to serial CPU."""
    plan = list(start)
    best = plan_cost(plan, tasks, prof, base)
    while True:
        move = None
        for i in range(len(plan)):
            for opt in _options(i, plan):
                if opt == plan[i]:
                    continue
                cand = list(plan)
                cand[i] = opt
                if opt[0] != "acc":  # i no longer hosts a window
                    cand = [("cpu",) if q == ("win", i) else q for q in cand]
                if not valid(cand):
                    continue
                c = plan_cost(cand, tasks, prof, base)
                if c < best:
                    best, move = c, cand
        if move is None:
            return plan, best
        plan = move


def plan_stream(tasks, prof, base):
    """Best of two deterministic starts: the serial oracle, and
    always-accelerator (which leaves the most windows open)."""
    results = [local_search(tasks, prof, base, oracle_plan(tasks, prof)),
               local_search(tasks, prof, base, [("acc",)] * len(tasks))]
    return min(results, key=lambda r: (r[1], str(r[0])))


def exhaustive(tasks, prof, base):
    """Model optimum over every valid placement (small streams only)."""
    n = len(tasks)
    choices = [("cpu",), ("acc",)] + [("win", j) for j in range(n)]
    best = None
    for plan in itertools.product(choices, repeat=n):
        plan = list(plan)
        if not valid(plan):
            continue
        c = plan_cost(plan, tasks, prof, base)
        if best is None or c < best[1]:
            best = (plan, c)
    return best
