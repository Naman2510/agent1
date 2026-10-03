#!/usr/bin/env python3
"""
run.py -- end-to-end pipeline for the concurrent CPU + accelerator
co-scheduler (docs/coschedule.md), scored against the pre-registered
docs/coschedule_scorecard.md.

  1. Profile: every task of the full 24-workload set, on each engine and
     each core configuration, as a one-task program
     (sim/testbenches/tb_accel_phase_probe.sv) -> per-task cost model.
  2. Plan: for each stream x core, the serial oracle, always-accelerator,
     and the co-schedule (scheduler/coschedule/planner.py).
  3. Generate + assemble every program (sim/programs/coschedule/).
  4. Correctness: every output word of every program, on Icarus Verilog
     AND Verilator (sim/testbenches/tb_coschedule_check.sv).
  5. Measure: every program's cycle count through the established
     harness, sim/testbenches/tb_benchmark_soc.sv -- run twice, to check
     determinism.
  6. Write results/coschedule_report.md and
     results/coschedule_scorecard.md (score computed, not hand-entered).

Usage:
    .venv/bin/python3 scheduler/coschedule/run.py
"""

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import codegen as cg  # noqa: E402
import planner as pl  # noqa: E402

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
PROG_DIR = os.path.join(ROOT, "sim", "programs", "coschedule")
PROFILE_PROG_DIR = os.path.join(ROOT, "build", "coschedule_profile")  # intermediate, gitignored
PROF_DIR = HERE
REPORT = os.path.join(ROOT, "results", "coschedule_report.md")
SCORECARD = os.path.join(ROOT, "results", "coschedule_scorecard.md")
PREREG_COMMIT = "9808c32"  # commit that pre-registered docs/coschedule_scorecard.md
CORES = {"rv32i": 0, "mul": 1}
MODES = ["always_accel", "oracle", "cosched"]

VERILATOR_FLAGS = ["--binary", "--timing", "-Wall", "-Wno-DECLFILENAME", "-Wno-UNUSEDSIGNAL",
                   "-Wno-UNUSEDPARAM", "-Wno-PINMISSING", "-Wno-PINCONNECTEMPTY"]


def sh(cmd, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def icarus(tb_file, top, params):
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".vvp").name
    sh(["iverilog", "-g2012", "-o", out] + [f"-P{top}.{k}={v}" for k, v in params.items()]
       + RTL_FILES + [tb_file])
    return out


def assemble(src_text, stem, directory=PROG_DIR):
    os.makedirs(directory, exist_ok=True)
    s = os.path.join(directory, stem + ".s")
    with open(s, "w") as f:
        f.write(src_text)
    sh([sys.executable, "scripts/asm_to_hex.py", s, "-o", s[:-2] + ".hex",
        "--words", str(cg.IMEM_WORDS)])
    return s[:-2] + ".hex"


# --------------------------------------------------------------------------- profiling

PROBE_RE = re.compile(r"PROBE total=(\d+) intervals=(\d+)")
BUSY_RE = re.compile(r"BUSY rise=(\d+) fall=(-?\d+)")


def probe(vvp, hexfile):
    out = sh(["vvp", vvp, f"+HEXFILE={hexfile}"])
    m = PROBE_RE.search(out)
    if not m:
        sys.exit(f"probe failed for {hexfile}:\n{out}")
    return int(m.group(1)), [(int(a), int(b)) for a, b in BUSY_RE.findall(out)]


def profile(core, mul):
    vvp = icarus("sim/testbenches/tb_accel_phase_probe.sv", "tb_accel_phase_probe",
                 {"ENABLE_MUL": mul})
    base, _ = probe(vvp, assemble(cg.program([], [], mul, "empty"), f"prof_{core}_base", PROFILE_PROG_DIR))
    prof = {}
    for op, n in cg.FULL_STREAM:
        t = (op, n)
        cpu_total, _ = probe(vvp, assemble(cg.program([t], [("cpu",)], mul, "profile"),
                                           f"prof_{core}_{op}{n}_cpu", PROFILE_PROG_DIR))
        acc_total, ivs = probe(vvp, assemble(cg.program([t], [("acc",)], mul, "profile"),
                                             f"prof_{core}_{op}{n}_acc", PROFILE_PROG_DIR))
        if len(ivs) != 1 or ivs[0][1] < 0:
            sys.exit(f"{core} {op} N={n}: expected one accelerator busy interval, got {ivs}")
        prof[t] = {"cpu": cpu_total - base, "acc": acc_total - base,
                   "busy": ivs[0][1] - ivs[0][0]}
    os.unlink(vvp)
    with open(os.path.join(PROF_DIR, f"profile_{core}.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["operation", "size_n", "cpu_cycles", "accel_cycles", "accel_busy_cycles"])
        for (op, n), p in prof.items():
            w.writerow([op, n, p["cpu"], p["acc"], p["busy"]])
    return base, prof


# --------------------------------------------------------------------------- main flow

RESULT_RE = re.compile(r"BENCHMARK_RESULT: name=(\S+) cycles=(\d+)")
CONFIG_RE = re.compile(r"BENCHMARK_CONFIG: name=\S+ ENABLE_MUL=(\d)")


def measure(vvp, hexfile, mul):
    out = sh(["vvp", vvp, f"+HEXFILE={hexfile}", "+NAME=x"])
    cfg, m = CONFIG_RE.search(out), RESULT_RE.search(out)
    if not cfg or int(cfg.group(1)) != mul or not m:
        sys.exit(f"measurement failed for {hexfile}:\n{out}")
    return int(m.group(2))


def check_icarus(vvp, hexfile, expfile, nexp):
    out = sh(["vvp", vvp, f"+HEXFILE={hexfile}", f"+EXPECT={expfile}", f"+NCHECK={nexp}"])
    return "RESULT: ALL CHECKS PASSED" in out and f"CHECKED {nexp} output words" in out


def build_verilator(mul):
    d = tempfile.mkdtemp()
    # sized literal: ENABLE_MUL is a 1-bit `bit` parameter, and Verilator's
    # -Wall rejects a plain (32-bit) integer override as WIDTHTRUNC
    sh(["verilator"] + VERILATOR_FLAGS + [f"-GENABLE_MUL=1'b{mul}", "--top-module",
                                          "tb_coschedule_check"] + RTL_FILES
       + ["sim/testbenches/tb_coschedule_check.sv", "-o", "simv", "--Mdir", d])
    return d


def check_verilator(d, hexfile, expfile, nexp):
    r = subprocess.run([os.path.join(d, "simv"), f"+HEXFILE={hexfile}", f"+EXPECT={expfile}",
                        f"+NCHECK={nexp}"], cwd=ROOT, capture_output=True, text=True)
    return "RESULT: ALL CHECKS PASSED" in r.stdout and f"CHECKED {nexp} output words" in r.stdout


def describe(stream, plan):
    parts = []
    for i, ((op, n), p) in enumerate(zip(stream, plan)):
        if p[0] == "acc":
            g = [f"{stream[j][0]}{stream[j][1]}" for j, q in enumerate(plan) if q == ("win", i)]
            parts.append(f"{op}{n}=ACC" + (f"[{'+'.join(g)}]" if g else ""))
        elif p[0] == "cpu":
            parts.append(f"{op}{n}=CPU")
    return ", ".join(parts)


def main():
    os.makedirs(PROG_DIR, exist_ok=True)
    data = {"profiles": {}, "rows": [], "exhaustive": {}}
    for core, mul in CORES.items():
        print(f"== profiling ({core}) ==", flush=True)
        base, prof = profile(core, mul)
        data["profiles"][core] = {"base": base}

        bench = icarus("sim/testbenches/tb_benchmark_soc.sv", "tb_benchmark_soc",
                       {"ENABLE_MUL": mul, "IMEM_DEPTH_WORDS": cg.IMEM_WORDS})
        check = icarus("sim/testbenches/tb_coschedule_check.sv", "tb_coschedule_check",
                       {"ENABLE_MUL": mul})
        print(f"== building Verilator checker ({core}) ==", flush=True)
        vdir = build_verilator(mul)

        for sname, stream in cg.STREAMS.items():
            tasks = [tuple(t) for t in stream]
            plans = {"always_accel": [("acc",)] * len(tasks),
                     "oracle": pl.oracle_plan(tasks, prof)}
            plans["cosched"], _ = pl.plan_stream(tasks, prof, base)
            expfile = os.path.join(PROG_DIR, f"{sname}.expect")
            nexp = cg.write_expect_file(tasks, expfile)
            for mode in MODES:
                plan = plans[mode]
                stem = f"{sname}_{core}_{mode}"
                hexfile = assemble(cg.program(tasks, plan, mul, f"{sname}, {core} core, {mode}"), stem)
                ok_i = check_icarus(check, hexfile, expfile, nexp)
                ok_v = check_verilator(vdir, hexfile, expfile, nexp)
                cyc1 = measure(bench, hexfile, mul)
                cyc2 = measure(bench, hexfile, mul)
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


# --------------------------------------------------------------------------- reporting

def get(data, stream, core, mode):
    return next(r for r in data["rows"] if (r["stream"], r["core"], r["mode"]) == (stream, core, mode))


def write_report(data):
    L = ["# Concurrent CPU + Accelerator Co-Scheduler: Results\n",
         "Generated by `scheduler/coschedule/run.py`. Every cycle count is measured in Icarus "
         "Verilog simulation of `rtl/cpu/riscv_soc.sv` through "
         "`sim/testbenches/tb_benchmark_soc.sv`; every program's every output word is checked "
         "on Icarus Verilog and Verilator (`sim/testbenches/tb_coschedule_check.sv`). Scored "
         "against the pre-registered `docs/coschedule_scorecard.md` in "
         "`results/coschedule_scorecard.md`.\n",
         "| Stream | Core | Always accel | Serial oracle | Co-schedule | vs. oracle | Predicted | Model error |",
         "|---|---|---|---|---|---|---|---|"]
    for sname in cg.STREAMS:
        for core in CORES:
            a, o, c = (get(data, sname, core, m) for m in MODES)
            gain = (o["cycles"] - c["cycles"]) / o["cycles"] * 100
            err = (c["predicted"] - c["cycles"]) / c["cycles"] * 100
            L.append(f"| {sname} | {core} | {a['cycles']} | {o['cycles']} | **{c['cycles']}** | "
                     f"{gain:+.1f}% faster | {c['predicted']} | {err:+.2f}% |")
    L.append("")
    L.append("## Co-schedules chosen\n")
    L.append("`ACC[...]` = accelerator task, with the CPU tasks that run inside its busy window "
             "in brackets; `CPU` = CPU task run serially.\n")
    for sname in cg.STREAMS:
        for core in CORES:
            L.append(f"- **{sname}, {core}:** {get(data, sname, core, 'cosched')['plan']}")
    L.append("")
    L.append("## Model fidelity, all programs\n")
    L.append("| Program | Measured | Predicted | Error |")
    L.append("|---|---|---|---|")
    for r in data["rows"]:
        L.append(f"| {r['stream']} / {r['core']} / {r['mode']} | {r['cycles']} | {r['predicted']} | "
                 f"{(r['predicted'] - r['cycles']) / r['cycles'] * 100:+.2f}% |")
    L.append("")
    L.append("## Limits of the method\n")
    L.append("- Tasks are independent (no task consumes another's output). A dependency graph "
             "would constrain which CPU tasks can fill which window; this planner does not model one.\n"
             "- The gain is bounded by how long the accelerator is busy on its own. The CPU does "
             "all operand marshalling for the accelerator, and that dominates accelerator tasks "
             "(`scheduler/coschedule/profile_*.csv`: e.g. vecadd N=16 is busy for 16 of its 216 "
             "cycles). So streams of small tasks gain little; streams with long-running "
             "accelerator operations (matmul) gain the most.\n"
             "- Plans are computed offline from measured per-task costs, for known streams. They "
             "are not a runtime decision.\n"
             "- One accelerator context: a window can host CPU tasks, not a second accelerator task.")
    with open(REPORT, "w") as f:
        f.write("\n".join(L) + "\n")


def write_scorecard(data):
    rows = data["rows"]
    gain = lambda s, c: get(data, s, c, "oracle")["cycles"] - get(data, s, c, "cosched")["cycles"]
    pct = lambda s, c: gain(s, c) / get(data, s, c, "oracle")["cycles"] * 100
    old_ceiling = get(data, "full24", "rv32i", "always_accel")["cycles"] - get(data, "full24", "rv32i", "oracle")["cycles"]
    errs = [abs(r["predicted"] - r["cycles"]) / r["cycles"] * 100 for r in rows if r["mode"] == "cosched"]
    ex = data["exhaustive"]
    ex_gaps = {c: (v["planner"] - v["optimum"]) / v["optimum"] * 100 for c, v in ex.items()}
    rtl_clean = subprocess.run(["git", "diff", "--quiet", PREREG_COMMIT, "--", "rtl/"], cwd=ROOT).returncode == 0
    deterministic = all(r["cycles"] == r["cycles_rerun"] for r in rows)
    report_text = open(REPORT).read()
    report_complete = all(f"| {s} | {c} |" in report_text for s in cg.STREAMS for c in CORES) \
        and "## Model fidelity" in report_text and "## Limits of the method" in report_text

    metrics = [
        ("Correctness", all(r["correct_icarus"] and r["correct_verilator"] for r in rows),
         f"{len(rows)} programs, {sum(r['checked_words'] for r in rows)} output words, all checked on "
         f"Icarus + Verilator; failures: "
         f"{[(r['stream'], r['core'], r['mode']) for r in rows if not (r['correct_icarus'] and r['correct_verilator'])] or 'none'}"),
        ("Never worse", all(gain(s, c) >= 0 for s in cg.STREAMS for c in CORES),
         ", ".join(f"{s}/{c}: {pct(s, c):+.1f}%" for s in cg.STREAMS for c in CORES)),
        ("Real speedup (RV32I) >= 5%", pct("full24", "rv32i") >= 5,
         f"full24/rv32i: {pct('full24', 'rv32i'):.2f}% ({gain('full24', 'rv32i')} cycles)"),
        ("Real speedup (MUL core) >= 5%", pct("full24", "mul") >= 5,
         f"full24/mul: {pct('full24', 'mul'):.2f}% ({gain('full24', 'mul')} cycles)"),
        ("Beats the old ceiling >= 10x", gain("full24", "rv32i") >= 10 * old_ceiling,
         f"co-schedule gain {gain('full24', 'rv32i')} cycles vs. serial ceiling "
         f"(always-accel - oracle) {old_ceiling} cycles = "
         f"{gain('full24', 'rv32i') / old_ceiling if old_ceiling else float('inf'):.1f}x"),
        ("Model fidelity <= 5%", max(errs) <= 5, f"max |error| over co-schedules: {max(errs):.2f}%"),
        ("Planner quality <= 1% of optimum", all(g <= 1 for g in ex_gaps.values()),
         ", ".join(f"{c}: planner {ex[c]['planner']} vs. optimum {ex[c]['optimum']} ({g:+.2f}%)"
                   for c, g in ex_gaps.items())),
        ("Zero hardware cost", rtl_clean, f"`git diff {PREREG_COMMIT} -- rtl/` "
         + ("is empty" if rtl_clean else "is NOT empty")),
        ("Reproducible", deterministic,
         "`make coschedule` regenerates profiles, plans, programs, checks and measurements; "
         "every program measured twice in this run: "
         + ("identical" if deterministic else "NOT identical")
         + ". The full `make demo` regression (which includes this target) is run and "
         "recorded in CHANGELOG.md's co-scheduler entry."),
        ("Honest reporting", report_complete,
         "report lists every stream x core result, the model-error table and the method's limits"),
    ]
    score = 10 * sum(1 for _, ok, _ in metrics if ok)
    L = [f"# Co-Scheduler Scorecard: {score}/100\n",
         "Computed by `scheduler/coschedule/run.py` from the measurements in "
         "`results/coschedule_report.md`, against the thresholds pre-registered in "
         f"`docs/coschedule_scorecard.md` (commit `{PREREG_COMMIT}`, made before the co-scheduler "
         "existed). Not hand-entered.\n",
         "| # | Metric | Result | Evidence |", "|---|---|---|---|"]
    for i, (name, ok, ev) in enumerate(metrics, 1):
        L.append(f"| {i} | {name} | {'PASS (10)' if ok else 'FAIL (0)'} | {ev} |")
    with open(SCORECARD, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"SCORE: {score}/100")


if __name__ == "__main__":
    main()
