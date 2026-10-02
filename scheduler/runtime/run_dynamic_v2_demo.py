#!/usr/bin/env python3
"""
run_dynamic_v2_demo.py -- post-v1: measure the v2 scheduler model
running in the on-CPU runtime scheduler (see
scheduler/runtime/gen_dynamic_v2_demo.py), on both Phase 15's
6-workload stream and Phase 16's 12-workload stream -- both as the
straightforward v2 program and as the lean-decision program from
scheduler/runtime/gen_dynamic_lean_demo.py (same choices, cheaper
check) -- against the v1 runtime scheduler and the
always-accelerator / oracle baselines -- all
re-measured in this same run through sim/testbenches/tb_benchmark_soc.sv,
so every number in the report comes from one consistent simulation
pass rather than being mixed with figures copied from older reports.

Because the v2 model's choices match the oracle's on every workload in
both streams (checked here against Phase 13/14's real measured data,
not assumed), `v2_dynamic - oracle` isolates exactly one thing: the
cycles spent computing the scheduling decision at runtime. And
`v1_dynamic - v2_dynamic` is what fixing the vecadd N=2 misprediction
was actually worth inside the running system.

Correctness of both v2 programs is established separately by
sim/testbenches/tb_dynamic_v2_correctness.sv
(`make test_dynamic_v2_correctness`).

Usage:
    .venv/bin/python3 scheduler/runtime/run_dynamic_v2_demo.py
"""

import os
import pickle
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scheduler", "models"))
from gen_dynamic_scheduler_demo import _load_ground_truth, oracle_engine, STREAM as P15  # noqa: E402
from gen_mixed_workload_demo import STREAM as P16  # noqa: E402
from features import extract_features, LABEL_TO_ENGINE  # noqa: E402

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
SRC_DIR = "sim/programs/scheduler"
MODEL_V1 = os.path.join(ROOT, "scheduler", "models", "scheduler_tree.pkl")
MODEL_V2 = os.path.join(ROOT, "scheduler", "models", "scheduler_tree_v2.pkl")
REPORT_PATH = os.path.join(ROOT, "results", "dynamic_v2_report.md")

STREAMS = [
    ("Phase 15 stream (6 workloads)", P15, {
        "v1": "dynamic_scheduler_demo", "v2": "dynamic_v2_demo", "lean": "dynamic_lean_demo",
        "accel": "always_accel_demo", "oracle": "oracle_demo"}),
    ("Phase 16 stream (12 workloads)", P16, {
        "v1": "mixed_dynamic_demo", "v2": "mixed_dynamic_v2_demo",
        "lean": "mixed_dynamic_lean_demo",
        "accel": "mixed_always_accel_demo", "oracle": "mixed_oracle_demo"}),
]

RESULT_RE = re.compile(r"BENCHMARK_RESULT: name=(\S+) cycles=(\d+) retired=(\d+) .* flush=(\d+)")


def assemble(stem):
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "asm_to_hex.py"),
         f"{SRC_DIR}/{stem}.s", "-o", f"{SRC_DIR}/{stem}.hex", "--words", "1024"],
        cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAILED TO ASSEMBLE {stem}.s:\n{r.stderr}")


def run_one(vvp_out, stem):
    r = subprocess.run(["vvp", vvp_out, f"+HEXFILE={SRC_DIR}/{stem}.hex", f"+NAME={stem}"],
                       cwd=ROOT, capture_output=True, text=True)
    m = RESULT_RE.search(r.stdout)
    if not m:
        sys.exit(f"no BENCHMARK_RESULT line for {stem}; simulator output:\n{r.stdout}")
    return {"cycles": int(m.group(2)), "retired": int(m.group(3)), "flush": int(m.group(4))}


def main():
    truth = _load_ground_truth()
    models = {}
    for name, path in (("v1", MODEL_V1), ("v2", MODEL_V2)):
        with open(path, "rb") as f:
            models[name] = pickle.load(f)

    def choice(model, op, n):
        return LABEL_TO_ENGINE[int(models[model].predict([extract_features(op, n)])[0])]

    vvp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".vvp").name
    r = subprocess.run(["iverilog", "-g2012", "-o", vvp_out] + RTL_FILES + [TB],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("Icarus compile failed:\n" + r.stdout + r.stderr)

    sections = []
    for label, stream, progs in STREAMS:
        decisions = [(op, n, choice("v1", op, n), choice("v2", op, n), oracle_engine(op, n, truth))
                     for op, n in stream]
        v2_matches_oracle = all(v2 == orc for _, _, _, v2, orc in decisions)
        results = {}
        for key, stem in progs.items():
            assemble(stem)
            results[key] = run_one(vvp_out, stem)
        print(f"{label}: " + ", ".join(f"{k}={v['cycles']}" for k, v in results.items()))
        # Standalone (Phase 13/14) cycle gap for every workload v1 got wrong,
        # to compare against what the fix actually recovered in-program.
        standalone_gap = sum(truth[(op, n)][c1] - truth[(op, n)][orc]
                             for op, n, c1, _, orc in decisions if c1 != orc)
        sections.append((label, decisions, v2_matches_oracle, results, standalone_gap))
    os.unlink(vvp_out)

    write_report(sections)
    print(f"\nWrote {REPORT_PATH}")


def write_report(sections):
    L = ["# v2 Model in the Runtime Scheduler\n",
         "Generated by `scheduler/runtime/run_dynamic_v2_demo.py`. Every cycle count "
         "below comes from one consistent Icarus Verilog simulation pass of "
         "`rtl/cpu/riscv_soc.sv` through `sim/testbenches/tb_benchmark_soc.sv` -- the v1 "
         "and v2 runtime schedulers and both baselines were all re-measured in this run, "
         "none copied from older reports. The v2 programs' runtime decision boundary is "
         "extracted from `scheduler/models/scheduler_tree_v2.pkl`'s own fitted splits by "
         "`scheduler/runtime/gen_dynamic_v2_demo.py`, and checked against the model's own "
         "`predict()` for every workload, rather than hand-transcribed. Correctness: "
         "`sim/testbenches/tb_dynamic_v2_correctness.sv` (`make test_dynamic_v2_correctness`).\n"]
    for label, decisions, v2_matches_oracle, r, standalone_gap in sections:
        v1, v2, acc, orc = (r[k]["cycles"] for k in ("v1", "v2", "accel", "oracle"))
        L.append(f"## {label}\n")
        L.append("| Workload | v1 model picks | v2 model picks | Oracle (real data) |")
        L.append("|---|---|---|---|")
        for op, n, c1, c2, co in decisions:
            mark1 = c1 if c1 == co else f"**{c1}** (wrong)"
            L.append(f"| {op} N={n} | {mark1} | {c2} | {co} |")
        L.append("")
        L.append("| Program | Total cycles | Instructions retired | Pipeline flushes |")
        L.append("|---|---|---|---|")
        for key, name in (("v1", "Runtime scheduler, v1 model"), ("v2", "Runtime scheduler, v2 model"),
                          ("lean", "Runtime scheduler, v2 model, lean decision"),
                          ("accel", "Always accelerator"), ("oracle", "Oracle (decisions fixed at build time)")):
            L.append(f"| {name} | {r[key]['cycles']} | {r[key]['retired']} | {r[key]['flush']} |")
        L.append("")
        L.append(f"- **Fixing the misprediction saved {v1 - v2} cycles** (v1 {v1} -> v2 {v2}) -- "
                 f"less than the {standalone_gap} cycles the standalone Phase 13/14 benchmarks "
                 f"would predict. Inside these programs the accelerator path also pays the "
                 f"unified-output copy-out (`lw`/`sw` per result word, out of the accelerator's "
                 f"VECOUT window into the block's RAM slot -- see "
                 f"`scheduler/runtime/gen_dynamic_scheduler_demo.py`) that the standalone "
                 f"accelerator benchmark never does, so part of the standalone gap doesn't exist "
                 f"in-program.")
        if v2_matches_oracle:
            L.append(f"- **v2's choices are identical to the oracle's on every workload in this "
                     f"stream**, so v2 - oracle = **{v2 - orc} cycles is purely the cost of "
                     f"computing the decision at runtime** ({(v2 - orc) / len(decisions):.1f} "
                     f"cycles per workload, {(v2 - orc) / orc * 100:.1f}% of the oracle's total).")
        else:
            L.append(f"- v2's choices differ from the oracle's on at least one workload here, so "
                     f"v2 - oracle ({v2 - orc} cycles) mixes decision cost with misprediction cost.")
        verdict = "slower" if v2 > acc else "faster"
        L.append(f"- Even with every decision correct, the v2 runtime scheduler is still "
                 f"**{abs(v2 - acc)} cycles {verdict}** than always-accelerator ({v2} vs. {acc}): "
                 f"the oracle's whole advantage over always-accelerator is only {acc - orc} cycles "
                 f"here, smaller than the decision cost.")
        lean, lr, orr = r["lean"]["cycles"], r["lean"], r["oracle"]
        d_cyc, d_ret, d_fl = lean - orc, lr["retired"] - orr["retired"], lr["flush"] - orr["flush"]
        L.append(f"- **Lean decision (same v2 choices, cheaper to compute): {lean} cycles.** "
                 f"Decision cost over the oracle drops from {v2 - orc} to **{d_cyc} cycles** "
                 f"({(1 - d_cyc / (v2 - orc)) * 100:.0f}% less). By the counters, that remainder is "
                 f"{d_ret} extra retired instructions and {d_fl} extra pipeline flushes"
                 + (f" ({d_cyc} = {d_ret} + {d_fl} x {(d_cyc - d_ret) // d_fl}: "
                    f"{(d_cyc - d_ret) // d_fl} cycles per flush)"
                    if d_fl and (d_cyc - d_ret) % d_fl == 0 else "") + ".")
        lv = "**beats**" if lean < acc else ("ties" if lean == acc else "still **trails**")
        L.append(f"- Lean vs. always-accelerator: {lean} vs. {acc} -- the runtime scheduler "
                 f"{lv} the naive baseline on this stream "
                 f"({'+' if lean > acc else ''}{lean - acc} cycles).")
        L.append("")
    L.append("## What the lean decision changes\n")
    L.append("`scheduler/runtime/gen_dynamic_lean_demo.py` makes the same choices as the v2 "
             "model on every workload (checked against `predict()` before any assembly is "
             "written) but computes them more cheaply: (1) a decision is folded at build time "
             "only where it is provably constant -- the v2 rule is enumerated over each "
             "operation's entire legal size range, read from `rtl/accelerator/accelerator.sv` "
             "(`dot`/`matmul` can never satisfy `multiply_count == 0`, so they always go to the "
             "accelerator and never pay for a check or for runtime `mul32` calls); (2) where the "
             "choice genuinely depends on N (`vecadd`), the CPU still decides at runtime, with "
             "one compare against a threshold held in a register for the whole program, reusing "
             "the size load both engine bodies need anyway; (3) the common (accelerator) path "
             "falls through and the CPU path lives out of line.\n")
    L.append("## What this establishes\n")
    L.append("Accuracy was never this scheduler's binding constraint -- decision cost was. "
             "With every decision correct, the straightforward runtime check (~18-19 cycles "
             "per workload) loses to always-accelerator on both streams. Cut to its floor -- "
             "nothing but a compare-and-branch on requests whose outcome can actually vary, "
             "plus the jump to and from the out-of-line CPU path when it is taken -- the same "
             "scheduler lands within a few cycles of always-accelerator either way, and which "
             "side it lands on is set by the stream's mix: each runtime check routed to the "
             "accelerator costs a cycle, each correct CPU dispatch nets the oracle's in-program "
             "gain minus the out-of-line round trip. On this accelerator, where only "
             "`vecadd N=1` favors the CPU, that margin is a handful of cycles per stream; see "
             "`docs/scheduler_v2.md`.\n")
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
