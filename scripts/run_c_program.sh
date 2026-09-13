#!/usr/bin/env bash
# run_c_program.sh -- Phase 4: build a bare-metal C program with the real
# RISC-V GCC toolchain and run it on this project's CPU under both
# simulators.
#
# Usage: scripts/run_c_program.sh <name> <expected_a0>
#   e.g. scripts/run_c_program.sh add_test 30

set -euo pipefail
cd "$(dirname "$0")/.."

NAME="${1:?usage: scripts/run_c_program.sh <name> <expected_a0>}"
EXPECTED="${2:?usage: scripts/run_c_program.sh <name> <expected_a0>}"

./scripts/build_c_program.sh "$NAME"

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
TB=sim/testbenches/tb_c_program.sv
HEXFILE="software/baremetal/${NAME}.hex"

echo
echo "== Icarus Verilog =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
vvp "$IVERILOG_OUT" "+HEXFILE=${HEXFILE}" "+TESTNAME=${NAME}" "+EXPECTED=${EXPECTED}" \
  | tee /tmp/c_program_iverilog.log
rm -f "$IVERILOG_OUT"
grep -q "TEST_RESULT: PASS" /tmp/c_program_iverilog.log || { echo "Icarus run FAILED" >&2; exit 1; }

echo
echo "== Verilator =="
VOUT=$(mktemp -d)
verilator --binary --timing -Wno-fatal --top-module tb_c_program \
  "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" >/tmp/c_program_verilator_build.log 2>&1
"$VOUT/simv" "+HEXFILE=${HEXFILE}" "+TESTNAME=${NAME}" "+EXPECTED=${EXPECTED}" \
  | tee /tmp/c_program_verilator.log
rm -rf "$VOUT"
grep -q "TEST_RESULT: PASS" /tmp/c_program_verilator.log || { echo "Verilator run FAILED" >&2; exit 1; }

echo
echo "== Both simulators: PASS =="
