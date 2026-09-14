#!/usr/bin/env bash
# run_sim_soc.sh -- assemble the Phase 8 SoC demo program and run the
# top-level SoC testbench (RAM + UART + GPIO through the real
# address-decoded bus) under both Icarus Verilog and Verilator, so a
# fresh checkout can reproduce Phase 8's verification with one command
# (same pattern as scripts/run_sim_pipeline.sh for Phase 5).
#
# Usage: scripts/run_sim_soc.sh

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
  rtl/cpu/riscv_soc.sv
)
TB=sim/testbenches/tb_soc.sv

echo "== Assembling sim/programs/soc/soc_demo.s =="
python3 scripts/asm_to_hex.py sim/programs/soc/soc_demo.s \
  -o sim/programs/soc/soc_demo.hex --words 256

echo
echo "== Icarus Verilog =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
vvp "$IVERILOG_OUT" | tee /tmp/soc_iverilog.log
rm -f "$IVERILOG_OUT"
if ! grep -q "TEST_RESULT: PASS" /tmp/soc_iverilog.log; then
  echo "Icarus Verilog run did NOT pass." >&2
  exit 1
fi

echo
echo "== Verilator =="
VOUT=$(mktemp -d)
verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING \
  --top-module tb_soc "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" >/tmp/soc_verilator_build.log 2>&1
"$VOUT/simv" | tee /tmp/soc_verilator.log
rm -rf "$VOUT"
if ! grep -q "TEST_RESULT: PASS" /tmp/soc_verilator.log; then
  echo "Verilator run did NOT pass." >&2
  exit 1
fi

echo
echo "== Both simulators: PASS =="
