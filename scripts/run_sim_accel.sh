#!/usr/bin/env bash
# run_sim_accel.sh -- Phase 9: assemble the accelerator unit test's data
# (none needed -- tb_accelerator.sv drives the accelerator's MMIO
# registers directly, no .hex program) and the CPU-driven end-to-end
# demo program, then run both testbenches under Icarus Verilog and
# Verilator. Two separate testbenches are run here deliberately (see
# each one's own header comment): tb_accelerator.sv isolates the
# accelerator's own RTL correctness, tb_soc_accel.sv isolates the
# CPU/bus path to it.
#
# Usage: scripts/run_sim_accel.sh

set -euo pipefail
cd "$(dirname "$0")/.."

CORE_RTL=(
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

echo "== Assembling sim/programs/soc/accel_demo.s =="
python3 scripts/asm_to_hex.py sim/programs/soc/accel_demo.s \
  -o sim/programs/soc/accel_demo.hex --words 512

run_case () {
  local top="$1"; shift
  local tb="$1"; shift
  local check_string="$1"; shift

  echo
  echo "== Icarus Verilog: $top =="
  IVERILOG_OUT=$(mktemp)
  # -s "$top": CORE_RTL includes both riscv_cpu_pipeline.sv and
  # riscv_soc.sv so this one script/function serves both testbenches
  # without duplicating the file list; without an explicit top, Icarus
  # would treat every module nothing else instantiates (e.g. riscv_soc
  # when running tb_accelerator) as its own simulated root.
  iverilog -g2012 -s "$top" -o "$IVERILOG_OUT" "${CORE_RTL[@]}" "$tb"
  vvp "$IVERILOG_OUT" | tee "/tmp/${top}_iverilog.log"
  rm -f "$IVERILOG_OUT"
  if ! grep -q "$check_string" "/tmp/${top}_iverilog.log"; then
    echo "Icarus Verilog run of $top did NOT pass." >&2
    exit 1
  fi

  echo
  echo "== Verilator: $top =="
  VOUT=$(mktemp -d)
  verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING \
    --top-module "$top" "${CORE_RTL[@]}" "$tb" -o simv --Mdir "$VOUT" \
    >"/tmp/${top}_verilator_build.log" 2>&1
  "$VOUT/simv" | tee "/tmp/${top}_verilator.log"
  rm -rf "$VOUT"
  if ! grep -q "$check_string" "/tmp/${top}_verilator.log"; then
    echo "Verilator run of $top did NOT pass." >&2
    exit 1
  fi
}

run_case tb_accelerator sim/testbenches/tb_accelerator.sv "RESULT: ALL CHECKS PASSED"
run_case tb_soc_accel    sim/testbenches/tb_soc_accel.sv    "TEST_RESULT: PASS"

echo
echo "== Both simulators, both testbenches: PASS =="
