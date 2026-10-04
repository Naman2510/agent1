"""
plans.py -- the plan format shared by the planner and the code generator.

A plan is a list, one entry per task in stream order:
  ("acc",)     -- run on the accelerator, waiting for it (serial)
  ("cpu",)     -- run on the CPU, serially
  ("win", j)   -- run on the CPU inside task j's accelerator busy window
                  (task j must be "acc", and j != this task)
"""


def valid(plan):
    return all(p[0] != "win" or (p[1] != i and plan[p[1]][0] == "acc") for i, p in enumerate(plan))


def validate(plan):
    for i, p in enumerate(plan):
        if p[0] == "win" and (p[1] == i or plan[p[1]][0] != "acc"):
            raise ValueError(f"task {i}: window host {p[1]} is not an accelerator task")


def guests(plan, host):
    """Indices of the tasks placed in `host`'s window, in stream order."""
    return [j for j, p in enumerate(plan) if p == ("win", host)]


def serial_plan(stream, engines):
    return [("acc",) if e == "accelerator" else ("cpu",) for e in engines]


def describe(stream, plan):
    """Compact text form: `op N=ACC[guest+guest]` / `op N=CPU`."""
    parts = []
    for i, ((op, n), p) in enumerate(zip(stream, plan)):
        if p[0] == "acc":
            g = [f"{stream[j][0]}{stream[j][1]}" for j in guests(plan, i)]
            parts.append(f"{op}{n}=ACC" + (f"[{'+'.join(g)}]" if g else ""))
        elif p[0] == "cpu":
            parts.append(f"{op}{n}=CPU")
    return ", ".join(parts)
