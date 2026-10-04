"""Unit tests for the framework modules (scheduler/framework). No simulator."""

import os
import tempfile
import unittest

from _paths import COSCHED_DIR
from framework import costmodel, operations, planner, plans, rv32_codegen, verification

PROF = {("vecadd", 4): {"cpu": 101, "acc": 81, "busy": 4},
        ("matmul", 8): {"cpu": 32877, "acc": 1647, "busy": 512},
        ("dot", 1): {"cpu": 59, "acc": 35, "busy": 1},
        ("vecadd", 1): {"cpu": 29, "acc": 39, "busy": 1}}


class Operations(unittest.TestCase):
    def test_registry_is_the_hardware_op_set(self):
        self.assertEqual(sorted(operations.OPERATIONS), ["dot", "matmul", "vecadd"])

    def test_unsupported_operation_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "unsupported operation 'conv2d'"):
            operations.get("conv2d")
        with self.assertRaises(ValueError):
            rv32_codegen.program([("conv2d", 4)], [("cpu",)], 0, "x")

    def test_reference_values(self):
        self.assertEqual(operations.reference("vecadd", 3), [3, 5, 7])
        self.assertEqual(operations.reference("dot", 3), [1 * 2 + 2 * 3 + 3 * 4])
        # 2x2: A = [[1,2],[2,3]], B = [[2,3],[3,4]]
        self.assertEqual(operations.reference("matmul", 2), [8, 11, 13, 18])

    def test_out_words(self):
        self.assertEqual([operations.out_words(o, 4) for o in ("vecadd", "dot", "matmul")], [4, 1, 16])


class Plans(unittest.TestCase):
    def test_validity(self):
        self.assertTrue(plans.valid([("acc",), ("win", 0)]))
        self.assertFalse(plans.valid([("cpu",), ("win", 0)]))   # host not on accelerator
        self.assertFalse(plans.valid([("win", 0)]))             # hosts itself
        with self.assertRaisesRegex(ValueError, "window host"):
            plans.validate([("cpu",), ("win", 0)])

    def test_describe(self):
        s = [("matmul", 8), ("vecadd", 4), ("dot", 1)]
        self.assertEqual(plans.describe(s, [("acc",), ("win", 0), ("cpu",)]),
                         "matmul8=ACC[vecadd4], dot1=CPU")


class CostModel(unittest.TestCase):
    def test_serial_plans_are_additive(self):
        tasks = [("vecadd", 4), ("dot", 1)]
        self.assertEqual(costmodel.plan_cost([("cpu",), ("acc",)], tasks, PROF, 8), 8 + 101 + 35)

    def test_window_cost(self):
        tasks = [("matmul", 8), ("vecadd", 4)]
        # window load 101 + RELOAD 2 < busy 512: the CPU task is hidden entirely
        self.assertEqual(costmodel.plan_cost([("acc",), ("win", 0)], tasks, PROF, 8), 8 + 1647)
        tasks = [("vecadd", 4), ("vecadd", 1)]
        # load 29 + 2 > busy 4: cost = acc - busy + load + RELOAD
        self.assertEqual(costmodel.plan_cost([("acc",), ("win", 0)], tasks, PROF, 8),
                         8 + 81 - 4 + 29 + costmodel.RELOAD)

    def test_unprofiled_size_has_no_cost(self):
        with self.assertRaises(KeyError):
            costmodel.plan_cost([("cpu",)], [("vecadd", 5)], PROF, 8)

    def test_profile_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "p.csv")
            costmodel.write_profile_csv(PROF, p)
            self.assertEqual(costmodel.read_profile_csv(p), PROF)


class Planner(unittest.TestCase):
    def test_never_worse_than_oracle_on_committed_profiles(self):
        for core in ("rv32i", "mul"):
            prof = costmodel.read_profile_csv(os.path.join(COSCHED_DIR, f"profile_{core}.csv"))
            tasks = list(prof)
            oracle = costmodel.plan_cost(planner.oracle_plan(tasks, prof), tasks, prof, 8)
            plan, cost = planner.plan_stream(tasks, prof, 8)
            self.assertTrue(plans.valid(plan))
            self.assertLessEqual(cost, oracle)

    def test_local_search_reaches_exhaustive_on_small_stream(self):
        tasks = list(PROF)
        _, opt = planner.exhaustive(tasks, PROF, 8)
        _, got = planner.plan_stream(tasks, PROF, 8)
        self.assertEqual(got, opt)


class Codegen(unittest.TestCase):
    def test_mul_substitution(self):
        rv = rv32_codegen.cpu_body("dot", 4, "t0", "0x3000", 0)
        mu = rv32_codegen.cpu_body("dot", 4, "t0", "0x3000", 1)
        self.assertIn("jal  x1, mul32", rv)
        self.assertNotIn("jal  x1, mul32", mu)
        self.assertIn("mul  x10, x11, x12", mu)
        self.assertEqual(rv32_codegen.cpu_body("vecadd", 4, "t0", "0x3000", 1),
                         rv32_codegen.cpu_body("vecadd", 4, "t0", "0x3000", 0))

    def test_accel_split(self):
        launch, wait = rv32_codegen.accel_split("matmul", 2, "t3", "0x3000")
        self.assertIn("accel.matmul", launch)
        self.assertTrue(wait.startswith("t3_wait_loop:\n"))
        self.assertNotIn("accel.stat", launch)

    def test_window_restores_mmio_base(self):
        text = rv32_codegen.program([("matmul", 2), ("vecadd", 1)], [("acc",), ("win", 0)], 0, "x")
        launch_end = text.index("accel.matmul")
        guest = text.index("window: task 1")
        restore = text.index("li   x1, 0x30000000   # CPU tasks reused x1")
        wait = text.index("t0_wait_loop:")
        self.assertTrue(launch_end < guest < restore < wait)

    def test_output_layout_bounds(self):
        self.assertEqual(rv32_codegen.layout([("vecadd", 2), ("dot", 1), ("matmul", 2)]),
                         [0x3000, 0x3008, 0x300C])
        with self.assertRaisesRegex(ValueError, "exceed"):
            rv32_codegen.layout([("matmul", 8)] * 17)   # 17 * 64 words > 1024 output words

    def test_expected_words_follow_layout(self):
        w = verification.expected_words([("vecadd", 2), ("dot", 1)])
        self.assertEqual(w, [(0xC00, 3), (0xC01, 5), (0xC02, 1 * 2)])


if __name__ == "__main__":
    unittest.main()


class CompatibilityShims(unittest.TestCase):
    """scheduler/coschedule/{codegen,planner}.py keep their pre-Phase-2 names."""

    def test_old_names_still_importable(self):
        import importlib
        import sys
        sys.path.insert(0, COSCHED_DIR)
        cg, pl = importlib.import_module("codegen"), importlib.import_module("planner")
        for name in ("STREAMS", "FULL_STREAM", "MMIO_BASE", "OUT_START", "IMEM_WORDS", "out_words",
                     "layout", "reference", "expected_words", "write_expect_file", "cpu_body",
                     "accel_split", "validate", "program", "serial_plan"):
            self.assertTrue(hasattr(cg, name), f"codegen.{name}")
        for name in ("RELOAD", "plan_cost", "valid", "oracle_plan", "local_search",
                     "plan_stream", "exhaustive"):
            self.assertTrue(hasattr(pl, name), f"planner.{name}")
        self.assertIs(cg.program, rv32_codegen.program)
        self.assertIs(pl.plan_stream, planner.plan_stream)
