#!/usr/bin/env bash
# run_dynamic_v2_correctness.sh -- post-v1: verify the v2-model
# runtime-scheduling programs -- both the straightforward versions
# (dynamic_v2_demo, mixed_dynamic_v2_demo) and the lean-decision versions
# (dynamic_lean_demo, mixed_dynamic_lean_demo) -- against
# Python-computed expected results, under both Icarus Verilog and
# Verilator. The same testbench checks both pairs (they run identical
# streams with identical output layout); only the program images
# differ, passed in as SMALL_HEX / MIXED_HEX. Must pass before
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
.venv/bin/python3 scheduler/runtime/gen_dynamic_lean_demo.py

echo
echo "== Assembling demo programs =="
for stem in dynamic_v2_demo mixed_dynamic_v2_demo dynamic_lean_demo mixed_dynamic_lean_demo; do
  f="sim/programs/scheduler/${stem}.s"
  python3 scripts/asm_to_hex.py "$f" -o "${f%.s}.hex" --words 1024
done

# variant  small-stream program    mixed-stream program
VARIANTS=(
  "v2   dynamic_v2_demo   mixed_dynamic_v2_demo"
  "lean dynamic_lean_demo mixed_dynamic_lean_demo"
)

for v in "${VARIANTS[@]}"; do
  read -r name small mixed <<<"$v"
  DEFS_SMALL="SMALL_HEX=\"sim/programs/scheduler/${small}.hex\""
  DEFS_MIXED="MIXED_HEX=\"sim/programs/scheduler/${mixed}.hex\""
  LOG=/tmp/dynamic_${name}_correctness

  echo
  echo "== [$name] Icarus Verilog =="
  IVERILOG_OUT=$(mktemp)
  iverilog -g2012 -D"$DEFS_SMALL" -D"$DEFS_MIXED" -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
  vvp "$IVERILOG_OUT" | tee "${LOG}_iverilog.log"
  rm -f "$IVERILOG_OUT"
  if ! grep -q "RESULT: ALL CHECKS PASSED" "${LOG}_iverilog.log"; then
    echo "[$name] Icarus Verilog run did NOT pass all checks." >&2
    exit 1
  fi

  echo
  echo "== [$name] Verilator =="
  VOUT=$(mktemp -d)
  verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING -Wno-PINCONNECTEMPTY \
    -D"$DEFS_SMALL" -D"$DEFS_MIXED" \
    --top-module tb_dynamic_v2_correctness "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" \
    >"${LOG}_verilator_build.log" 2>&1
  "$VOUT/simv" | tee "${LOG}_verilator.log"
  rm -rf "$VOUT"
  if ! grep -q "RESULT: ALL CHECKS PASSED" "${LOG}_verilator.log"; then
    echo "[$name] Verilator run did NOT pass all checks." >&2
    exit 1
  fi
done

echo
echo "== Both simulators, both variants: ALL CHECKS PASSED =="
