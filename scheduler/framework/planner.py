"""
planner.py -- plan search for the concurrent CPU + accelerator
co-scheduler (unchanged from scheduler/coschedule/planner.py).

A deterministic best-improvement local search over single-task moves,
started from the serial oracle and from all-accelerator; the cheaper plan
wins (ties broken by the plan's text form, as before). exhaustive()
enumerates every valid placement (small streams only).
"""

import itertools

from .costmodel import plan_cost
from .plans import valid


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
