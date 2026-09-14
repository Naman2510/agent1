#!/usr/bin/env bash
# run_perf_counters.sh -- Phase 7: assemble the benchmark programs and run
# tb_perf_counters.sv (which verifies both each program's correctness AND
# its performance counters) under both Icarus Verilog and Verilator.
#
# Usage: scripts/run_perf_counters.sh

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
)
TB=sim/testbenches/tb_perf_counters.sv

echo "== Assembling benchmark programs =="
for name in sum_loop array_sum; do
  python3 scripts/asm_to_hex.py "sim/programs/benchmarks/${name}.s" \
    -o "sim/programs/benchmarks/${name}.hex" --words 256
done

echo
echo "== Icarus Verilog =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
vvp "$IVERILOG_OUT" | tee /tmp/perf_iverilog.log
rm -f "$IVERILOG_OUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/perf_iverilog.log; then
  echo "Icarus Verilog run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Verilator =="
VOUT=$(mktemp -d)
verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM \
  --top-module tb_perf_counters "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" >/tmp/perf_verilator_build.log 2>&1
"$VOUT/simv" | tee /tmp/perf_verilator.log
rm -rf "$VOUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/perf_verilator.log; then
  echo "Verilator run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Both simulators: ALL CHECKS PASSED =="
