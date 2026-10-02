#!/usr/bin/env bash
# run_dynamic_v2_correctness.sh -- post-v1: verify the two
# v2-model runtime-scheduling programs (dynamic_v2_demo, mixed_dynamic_v2_demo) against
# Python-computed expected results, under both Icarus Verilog and
# Verilator. Must pass before
# scheduler/runtime/run_dynamic_v2_demo.py's measured cycle totals
# are trusted.
#
# Usage: scripts/run_dynamic_v2_correctness.sh

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
TB=sim/testbenches/tb_dynamic_v2_correctness.sv

echo "== Generating v2-model runtime-scheduling programs =="
.venv/bin/python3 scheduler/runtime/gen_dynamic_v2_demo.py

echo
echo "== Assembling demo programs =="
for f in sim/programs/scheduler/dynamic_v2_demo.s sim/programs/scheduler/mixed_dynamic_v2_demo.s; do
  python3 scripts/asm_to_hex.py "$f" -o "${f%.s}.hex" --words 1024
done

echo
echo "== Icarus Verilog =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
vvp "$IVERILOG_OUT" | tee /tmp/dynamic_v2_correctness_iverilog.log
rm -f "$IVERILOG_OUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/dynamic_v2_correctness_iverilog.log; then
  echo "Icarus Verilog run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Verilator =="
VOUT=$(mktemp -d)
verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING -Wno-PINCONNECTEMPTY \
  --top-module tb_dynamic_v2_correctness "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" \
  >/tmp/dynamic_v2_correctness_verilator_build.log 2>&1
"$VOUT/simv" | tee /tmp/dynamic_v2_correctness_verilator.log
rm -rf "$VOUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/dynamic_v2_correctness_verilator.log; then
  echo "Verilator run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Both simulators: ALL CHECKS PASSED =="
