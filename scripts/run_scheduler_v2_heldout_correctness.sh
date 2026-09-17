#!/usr/bin/env bash
# run_scheduler_v2_heldout_correctness.sh -- post-Phase-17: verify the
# 4 round-2 held-out scheduler workloads (vecadd/dot N=6, N=12)
# against Python-computed expected results, under both Icarus Verilog
# and Verilator. Must pass before
# scheduler/benchmarks/collect_scheduler_v2_heldout_dataset.py's
# measured cycle counts for these programs are trusted.
#
# Usage: scripts/run_scheduler_v2_heldout_correctness.sh

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
TB=sim/testbenches/tb_scheduler_v2_heldout_correctness.sv

echo "== Generating scheduler programs (includes round-2 held-out sizes) =="
python3 scheduler/benchmarks/gen_scheduler_programs.py

echo
echo "== Assembling this check's own programs =="
STEMS=(
  cpu_vecadd_n6 cpu_dot_n6 accel_vecadd_n6 accel_dot_n6
  cpu_vecadd_n12 cpu_dot_n12 accel_vecadd_n12 accel_dot_n12
)
for stem in "${STEMS[@]}"; do
  f="sim/programs/scheduler/${stem}.s"
  python3 scripts/asm_to_hex.py "$f" -o "${f%.s}.hex" --words 512
done

echo
echo "== Icarus Verilog =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
vvp "$IVERILOG_OUT" | tee /tmp/scheduler_v2_heldout_correctness_iverilog.log
rm -f "$IVERILOG_OUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/scheduler_v2_heldout_correctness_iverilog.log; then
  echo "Icarus Verilog run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Verilator =="
VOUT=$(mktemp -d)
verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING -Wno-PINCONNECTEMPTY \
  --top-module tb_scheduler_v2_heldout_correctness "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" \
  >/tmp/scheduler_v2_heldout_correctness_verilator_build.log 2>&1
"$VOUT/simv" | tee /tmp/scheduler_v2_heldout_correctness_verilator.log
rm -rf "$VOUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/scheduler_v2_heldout_correctness_verilator.log; then
  echo "Verilator run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Both simulators: ALL CHECKS PASSED =="
