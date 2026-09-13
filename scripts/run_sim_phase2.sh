#!/usr/bin/env bash
# run_sim_phase2.sh -- assemble the Phase 2 bring-up program and run the
# single-cycle CPU testbench under both Icarus Verilog and Verilator, so
# a fresh checkout can reproduce Phase 2's verification with one command.
#
# Usage: scripts/run_sim_phase2.sh

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
  rtl/cpu/riscv_cpu.sv
)
TB=sim/testbenches/tb_riscv_cpu.sv

echo "== Assembling sim/programs/phase2_bringup.s =="
python3 scripts/asm_to_hex.py sim/programs/phase2_bringup.s \
  -o sim/programs/phase2_bringup.hex --words 256

echo
echo "== Icarus Verilog =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
vvp "$IVERILOG_OUT" | tee /tmp/phase2_iverilog.log
rm -f "$IVERILOG_OUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/phase2_iverilog.log; then
  echo "Icarus Verilog run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Verilator =="
VOUT=$(mktemp -d)
verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM \
  --top-module tb_riscv_cpu "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" >/tmp/phase2_verilator_build.log 2>&1
"$VOUT/simv" | tee /tmp/phase2_verilator.log
rm -rf "$VOUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/phase2_verilator.log; then
  echo "Verilator run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Both simulators: ALL CHECKS PASSED =="
