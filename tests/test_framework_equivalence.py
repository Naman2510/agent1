"""
Golden equivalence: the modular framework must reproduce the committed
co-scheduler baseline exactly -- every plan, every predicted cycle count,
and every generated program and expect file byte for byte -- from the
committed per-task profiles. No simulator needed.

The baseline files are the ones `make coschedule` wrote and the full
regression verified (results/coschedule_report.md). If this test fails,
the framework changed behaviour, not just structure.
"""

import json
import os
import tempfile
import unittest

from _paths import COSCHED_DIR, PROG_DIR
from framework import costmodel, planner, plans, rv32_codegen, verification, workloads

CORES = {"rv32i": 0, "mul": 1}


def load_baseline():
    with open(os.path.join(COSCHED_DIR, "results.json")) as f:
        data = json.load(f)
    profs = {c: costmodel.read_profile_csv(os.path.join(COSCHED_DIR, f"profile_{c}.csv"))
             for c in CORES}
    return data, profs


def make_plans(tasks, prof, base):
    return {"always_accel": [("acc",)] * len(tasks),
            "oracle": planner.oracle_plan(tasks, prof),
            "cosched": planner.plan_stream(tasks, prof, base)[0]}


class GoldenPrograms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.profs = load_baseline()

    def test_every_program_byte_identical(self):
        checked = 0
        for core, mul in CORES.items():
            base = self.data["profiles"][core]["base"]
            for sname, stream in workloads.STREAMS.items():
                tasks = [tuple(t) for t in stream]
                for mode, plan in make_plans(tasks, self.profs[core], base).items():
                    stem = f"{sname}_{core}_{mode}"
                    text = rv32_codegen.program(tasks, plan, mul, f"{sname}, {core} core, {mode}")
                    with open(os.path.join(PROG_DIR, stem + ".s")) as f:
                        self.assertEqual(text, f.read(), stem)
                    checked += 1
        self.assertEqual(checked, 18)

    def test_predictions_and_plans_match_results(self):
        for row in self.data["rows"]:
            core, sname, mode = row["core"], row["stream"], row["mode"]
            tasks = [tuple(t) for t in workloads.STREAMS[sname]]
            base = self.data["profiles"][core]["base"]
            plan = make_plans(tasks, self.profs[core], base)[mode]
            self.assertEqual(costmodel.plan_cost(plan, tasks, self.profs[core], base),
                             row["predicted"], (sname, core, mode))
            self.assertEqual(plans.describe(tasks, plan), row["plan"], (sname, core, mode))

    def test_exhaustive_optimum_matches(self):
        tasks = [tuple(t) for t in workloads.STREAMS["phase15"]]
        for core in CORES:
            base = self.data["profiles"][core]["base"]
            _, cost = planner.exhaustive(tasks, self.profs[core], base)
            self.assertEqual(cost, self.data["exhaustive"][core]["optimum"], core)

    def test_expect_files_identical(self):
        for sname, stream in workloads.STREAMS.items():
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "x.expect")
                verification.write_expect_file([tuple(t) for t in stream], p)
                with open(p) as a, open(os.path.join(PROG_DIR, f"{sname}.expect")) as b:
                    self.assertEqual(a.read(), b.read(), sname)


if __name__ == "__main__":
    unittest.main()
