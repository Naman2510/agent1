#!/usr/bin/env bash
# run_bench_correctness.sh -- Phase 11: verify the three CPU-only
# benchmark kernels (cpu_vecadd_bench.s, cpu_dot_bench.s,
# cpu_matmul_bench.s) against Python-computed expected results, at
# their actual benchmark sizes, under both Icarus Verilog and
# Verilator. Must pass before scripts/run_benchmarks_accel.py's numbers
# for those kernels are trusted.
#
# Usage: scripts/run_bench_correctness.sh

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
TB=sim/testbenches/tb_bench_cpu_correctness.sv

echo "== mul32 software multiply routine (single-cycle CPU, Phase 3 harness) =="
# Verified in isolation, before it's trusted inside cpu_dot_bench.s /
# cpu_matmul_bench.s, on the single-cycle CPU (the simplest correct
# reference, no pipeline hazards to reason about) via the same
# generic directed-test harness Phase 3 established.
python3 scripts/asm_to_hex.py sim/programs/benchmarks/mul32_test.s \
  -o sim/programs/benchmarks/mul32_test.hex --words 256
MUL32_OUT=$(mktemp)
iverilog -g2012 -o "$MUL32_OUT" \
  rtl/cpu/riscv_pkg.sv rtl/alu/alu.sv rtl/regfile/regfile.sv rtl/decoder/decoder.sv \
  rtl/decoder/imm_gen.sv rtl/cpu/control_unit.sv rtl/cpu/branch_unit.sv \
  rtl/memory/imem.sv rtl/memory/dmem.sv rtl/cpu/riscv_cpu.sv \
  sim/testbenches/tb_directed_test.sv
MUL32_LOG=$(vvp "$MUL32_OUT" +HEXFILE=sim/programs/benchmarks/mul32_test.hex +TESTNAME=mul32_test)
echo "$MUL32_LOG"
rm -f "$MUL32_OUT"
if ! echo "$MUL32_LOG" | grep -q "TEST_RESULT: PASS"; then
  echo "mul32 correctness check did NOT pass." >&2
  exit 1
fi

echo
echo "== Assembling CPU-only benchmark kernels =="
python3 scripts/asm_to_hex.py sim/programs/benchmarks/cpu_vecadd_bench.s \
  -o sim/programs/benchmarks/cpu_vecadd_bench.hex --words 512
python3 scripts/asm_to_hex.py sim/programs/benchmarks/cpu_dot_bench.s \
  -o sim/programs/benchmarks/cpu_dot_bench.hex --words 512
python3 scripts/asm_to_hex.py sim/programs/benchmarks/cpu_matmul_bench.s \
  -o sim/programs/benchmarks/cpu_matmul_bench.hex --words 512

echo
echo "== Icarus Verilog =="
IVERILOG_OUT=$(mktemp)
iverilog -g2012 -o "$IVERILOG_OUT" "${RTL_FILES[@]}" "$TB"
vvp "$IVERILOG_OUT" | tee /tmp/bench_correctness_iverilog.log
rm -f "$IVERILOG_OUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/bench_correctness_iverilog.log; then
  echo "Icarus Verilog run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Verilator =="
VOUT=$(mktemp -d)
verilator --binary --timing -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINMISSING -Wno-PINCONNECTEMPTY \
  --top-module tb_bench_cpu_correctness "${RTL_FILES[@]}" "$TB" -o simv --Mdir "$VOUT" \
  >/tmp/bench_correctness_verilator_build.log 2>&1
"$VOUT/simv" | tee /tmp/bench_correctness_verilator.log
rm -rf "$VOUT"
if ! grep -q "RESULT: ALL CHECKS PASSED" /tmp/bench_correctness_verilator.log; then
  echo "Verilator run did NOT pass all checks." >&2
  exit 1
fi

echo
echo "== Both simulators: ALL CHECKS PASSED =="
