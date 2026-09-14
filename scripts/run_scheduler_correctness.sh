#!/usr/bin/env bash
# run_scheduler_correctness.sh -- Phase 13: verify all 12 new-size
# scheduler-dataset programs (sim/programs/scheduler/*.s) against
# Python-computed expected results, under both Icarus Verilog and
# Verilator. Must pass before scheduler/benchmarks/collect_dataset.py's
# measured cycle counts for those programs are trusted as AI-scheduler
# training data.
#
# Usage: scripts/run_scheduler_correctness.sh

set -euo pipefail
cd "$(dirname "$0")/.."

RTL_FILES=(
  rtl/cpu/riscv_pkg.sv
  rtl/alu/alu.sv
  rtl/regfile/regfile.sv
  rtl/decoder/decoder.sv
  rtl/decoder/imm_gen.sv
  rtl/cpu/control_unit.sv
  rtl/cpu/branch_unit.sv
  rtl/memory/imem.sv
  rtl/memory/dmem.sv
  rtl/pipeline/if_id_reg.sv
  rtl/pipeline/id_ex_reg.sv
  rtl/pipeline/ex_mem_reg.sv
  rtl/pipeline/mem_wb_reg.sv
  rtl/pipeline/forwarding_unit.sv
  rtl/pipeline/hazard_unit.sv
  rtl/cpu/perf_counters.sv
  rtl/cpu/riscv_cpu_pipeline.sv
  rtl/bus/soc_bus.sv
  rtl/bus/uart.sv
  rtl/bus/gpio.sv
  rtl/accelerator/accelerator.sv
  rtl/cpu/riscv_soc.sv
)
TB=sim/testbenches/tb_scheduler_correctness.sv

echo "== Generating scheduler-dataset programs =="
python3 scheduler/benchmarks/gen_scheduler_programs.py

echo
echo "== Assembling this phase's own programs =="
# Only the 16 files tb_scheduler_correctness.sv actually references --
# NOT a directory-wide glob. sim/programs/scheduler/ is shared with
# later phases (Phase 14's held-out set, Phase 15/16's dynamic-
# scheduling demos), and a blind `*.s` glob here broke the first time
# one of those grew past this script's --words budget (a real
# regression caught by scripts/run_full_demo.sh -- see CHANGELOG.md's
# Phase 17 entry). Listing exactly what this phase needs is immune to
# whatever else the directory later gains.
STEMS=(
  cpu_vecadd_n1 cpu_dot_n1 accel_vecadd_n1 accel_dot_n1
  cpu_vecadd_n4 cpu_dot_n4 accel_vecadd_n4 accel_dot_n4
  cpu_vecadd_n64 cpu_dot_n64 accel_vecadd_n64 accel_dot_n64
  cpu_matmul_n2 accel_matmul_n2 cpu_matmul_n8 accel_matmul_n8
)
for stem in "${STEMS[@]}"; do
  f="sim/programs/scheduler/${stem}.s"
  python3 scripts/asm_to_hex.py "$f" -o "${f%.s}.hex" --words 512
done

echo
echo "== Icarus Verilog =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
vvp "$IVERILOG_OUT" | tee /tmp/scheduler_correctness_iverilog.log
rm -f "$IVERILOG_OUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/scheduler_correctness_iverilog.log; then
  echo "Icarus Verilog run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Verilator =="
VOUT=$(mktemp -d)
verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING -Wno-PINCONNECTEMPTY \
  --top-module tb_scheduler_correctness "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" \
  >/tmp/scheduler_correctness_verilator_build.log 2>&1
"$VOUT/simv" | tee /tmp/scheduler_correctness_verilator.log
rm -rf "$VOUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/scheduler_correctness_verilator.log; then
  echo "Verilator run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Both simulators: ALL CHECKS PASSED =="
