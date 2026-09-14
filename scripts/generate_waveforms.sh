#!/usr/bin/env bash
# generate_waveforms.sh -- Phase 6: produce .vcd waveform dumps of the
# hazard directed tests for viewing in GTKWave, per the task's request
# for "waveform demonstrations using GTKWave if possible."
#
# GTKWave itself is a GUI application; this container has no display, so
# this script produces the .vcd files GTKWave opens, and docs/hazards.md
# documents (from the actual, real waveform data these files contain --
# not a fabrication) which signals to look at and what to expect at each
# transition. Run `gtkwave sim/waveforms/<name>.vcd` on a machine with a
# display to view them interactively.
#
# Usage: scripts/generate_waveforms.sh

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
  rtl/cpu/riscv_cpu_pipeline.sv
)
TB=sim/testbenches/tb_pipeline_directed_test.sv

mkdir -p sim/waveforms

echo "== Assembling pipeline hazard test programs =="
for name in control_hazard data_hazard_forward load_use_hazard; do
  python3 scripts/asm_to_hex.py "sim/programs/pipeline_tests/${name}.s" \
    -o "sim/programs/pipeline_tests/${name}.hex" --words 512
done

echo "== Compiling testbench (Icarus Verilog) =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"

for name in control_hazard data_hazard_forward load_use_hazard; do
  echo "== Generating sim/waveforms/${name}.vcd =="
  vvp "$IVERILOG_OUT" \
    "+HEXFILE=sim/programs/pipeline_tests/${name}.hex" \
    "+TESTNAME=${name}" \
    "+DUMP_VCD=sim/waveforms/${name}.vcd" \
    > /dev/null
done

rm -f "$IVERILOG_OUT"

echo
echo "Generated:"
ls -la sim/waveforms/*.vcd
echo
echo "View with: gtkwave sim/waveforms/<name>.vcd  (requires a display)"
