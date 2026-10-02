#!/usr/bin/env bash
# run_mul_test.sh -- verify the optional RV32M MUL instruction and the
# control unit's full funct7 / shift-immediate validation, under both
# Icarus Verilog and Verilator:
#   1. sim/testbenches/tb_control_unit_decode.sv -- exhaustive decode
#      sweep (every funct3 x funct7 of OP and OP-IMM, ENABLE_MUL=0 and 1)
#      against a reference model written from the spec;
#   2. sim/testbenches/tb_mul.sv -- sim/programs/mul/mul_test.s on the
#      pipelined CPU in the full SoC, with ENABLE_MUL=1 (correct products
#      through forwarding / load-use / branch paths) and ENABLE_MUL=0
#      (every mul raises `illegal` and writes nothing);
#   3. sim/testbenches/tb_mul_kernels_correctness.sv -- the 14
#      hardware-MUL dot/matmul kernels from
#      scheduler/benchmarks/gen_mul_programs.py, checked against
#      Python-computed results on an ENABLE_MUL=1 SoC.
#
# Usage: scripts/run_mul_test.sh

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

echo "== Assembling sim/programs/mul/mul_test.s =="
python3 scripts/asm_to_hex.py sim/programs/mul/mul_test.s -o sim/programs/mul/mul_test.hex --words 512

echo "== Generating + assembling hardware-MUL CPU kernels =="
python3 scheduler/benchmarks/gen_mul_programs.py
for f in sim/programs/scheduler/cpu_dot_mul_n*.s sim/programs/scheduler/cpu_matmul_mul_n*.s; do
  python3 scripts/asm_to_hex.py "$f" -o "${f%.s}.hex" --words 512
done

run_both() {  # $1 = top module, $2.. = sources
  local top="$1"; shift
  local log=/tmp/${top}

  echo
  echo "== [$top] Icarus Verilog =="
  local out; out=$(mktemp)
  iverilog -g2012 -o "$out" "$@"
  vvp "$out" | tee "${log}_iverilog.log"
  rm -f "$out"
  grep -q "RESULT: ALL CHECKS PASSED" "${log}_iverilog.log" || { echo "[$top] Icarus Verilog run did NOT pass all checks." >&2; exit 1; }

  echo
  echo "== [$top] Verilator =="
  local vout; vout=$(mktemp -d)
  verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING -Wno-PINCONNECTEMPTY \
    --top-module "$top" "$@" -o simv --Mdir "$vout" >"${log}_verilator_build.log" 2>&1 \
    || { cat "${log}_verilator_build.log" >&2; exit 1; }
  "$vout/simv" | tee "${log}_verilator.log"
  rm -rf "$vout"
  grep -q "RESULT: ALL CHECKS PASSED" "${log}_verilator.log" || { echo "[$top] Verilator run did NOT pass all checks." >&2; exit 1; }
}

run_both tb_control_unit_decode rtl/cpu/riscv_pkg.sv rtl/cpu/control_unit.sv sim/testbenches/tb_control_unit_decode.sv
run_both tb_mul "${RTL_FILES[@]}" sim/testbenches/tb_mul.sv
run_both tb_mul_kernels_correctness "${RTL_FILES[@]}" sim/testbenches/tb_mul_kernels_correctness.sv

echo
echo "== Both simulators, all three testbenches: ALL CHECKS PASSED =="
