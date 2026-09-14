#!/usr/bin/env bash
# run_full_demo.sh -- Phase 17: run this project's entire verified
# pipeline end-to-end, phase by phase, and print a consolidated
# summary of real measured results pulled directly from the
# results/*.md reports each step generates (never hand-typed here, so
# this summary can't drift out of sync with what was actually
# measured). This is the project's single "does everything still
# work, together, right now" gate -- every phase's own test/build
# script is still the authoritative check for that phase; this just
# runs all of them in order and reports what happened.
#
# FPGA synthesis (Phase 12, `make synthesize`) is SKIPPED by default:
# it is the slowest step by a wide margin (tens of minutes, see
# docs/synthesis.md) and orthogonal to the scheduler story Phases
# 13-16 tell -- pass --with-synthesis to include it.
#
# Usage:
#   scripts/run_full_demo.sh [--with-synthesis]

set -euo pipefail
cd "$(dirname "$0")/.."

WITH_SYNTHESIS=0
if [[ "${1:-}" == "--with-synthesis" ]]; then
  WITH_SYNTHESIS=1
fi

section() {
  echo
  echo "================================================================"
  echo "  $1"
  echo "================================================================"
}

run() {
  echo "+ make $1"
  make "$1"
}

section "Phase 1-2: RISC-V ISA foundation + single-cycle CPU"
run sim_cpu

section "Phase 3: Instruction execution tests"
run test_isa

section "Phase 4: Real C program via RISC-V GCC"
run run_c_demo

section "Phase 5: Five-stage pipeline"
run sim_pipeline

section "Phase 6: Pipeline hazards"
run test_hazards

section "Phase 7: Performance counters"
run test_perf
run benchmarks

section "Phase 8: SoC integration"
run sim_soc

section "Phase 9-10: Hardware accelerator + custom extension"
run test_accel
run test_accel_custom

section "Phase 11: CPU vs. accelerator benchmarking"
run test_bench_correctness
run benchmarks_accel

if [[ "$WITH_SYNTHESIS" == "1" ]]; then
  section "Phase 12: FPGA synthesis resource estimates (slow)"
  run synthesize
else
  section "Phase 12: FPGA synthesis resource estimates -- SKIPPED"
  echo "(pass --with-synthesis to include; see docs/synthesis.md -- this step"
  echo " alone can take tens of minutes and doesn't affect the scheduler results)"
fi

section "Phase 13: AI workload scheduler -- dataset + trained model"
run test_scheduler_correctness
run collect_scheduler_dataset
run train_scheduler

section "Phase 14: Scheduler decision pipeline + held-out accuracy"
run test_scheduler_heldout_correctness
run collect_scheduler_heldout_dataset
run evaluate_scheduler_accuracy

section "Phase 15: Dynamic runtime scheduling"
run test_dynamic_scheduler_correctness
run run_dynamic_scheduler_demo

section "Phase 16: Mixed heterogeneous workloads"
run test_mixed_workload_correctness
run run_mixed_workload_demo

section "SUMMARY -- real measured headline numbers (read from results/*.md)"

extract() {
  # $1 = file, $2 = sed/grep expression description not used; just cat matches
  grep -m1 -E "$2" "results/$1" || echo "  (pattern not found in $1)"
}

echo
echo "-- Phase 7: CPU performance (results/performance_report.md) --"
grep -E '^\|' results/performance_report.md | head -5

echo
echo "-- Phase 11: CPU vs. accelerator (results/accelerator_benchmark_report.md) --"
grep -E '^\| (vecadd|dot|matmul) \|' results/accelerator_benchmark_report.md

if [[ "$WITH_SYNTHESIS" == "1" ]]; then
  echo
  echo "-- Phase 12: synthesis (results/synthesis_report.md) --"
  grep -m1 -E '^\| riscv_soc' results/synthesis_report.md || true
fi

echo
echo "-- Phase 13: scheduler model (results/scheduler_report.md) --"
grep -m1 "Leave-one-out cross-validation accuracy" results/scheduler_report.md

echo
echo "-- Phase 14: held-out accuracy (results/scheduler_accuracy_report.md) --"
grep -m1 "Held-out accuracy" results/scheduler_accuracy_report.md

echo
echo "-- Phase 15: dynamic scheduling, small stream (results/dynamic_scheduling_report.md) --"
grep -m1 -E '^\| Dynamic' results/dynamic_scheduling_report.md

echo
echo "-- Phase 16: dynamic scheduling, mixed stream (results/mixed_workloads_report.md) --"
grep -m1 -E '^\| Dynamic' results/mixed_workloads_report.md
grep -m1 "vs. always-accelerator:" results/mixed_workloads_report.md

echo
echo "================================================================"
echo "  ALL STEPS COMPLETED"
echo "================================================================"
