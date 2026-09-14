#!/usr/bin/env bash
# run_synthesis.sh -- Phase 12: run every RTL module (leaf logic blocks
# individually, plus the full riscv_soc top level) through Yosys
# targeting Lattice iCE40 (synth_ice40), and write
# results/synthesis_report.md with the real cell counts Yosys reports.
#
# This is SYNTHESIS-TOOL ESTIMATION ONLY. No physical FPGA or hardware
# is used anywhere in this project -- see docs/synthesis.md for the
# full methodology, including two real, non-obvious things this phase
# had to work around (documented there and in CHANGELOG.md's Phase 12
# entry, not silently patched over):
#   1. Yosys 0.33's open-source Verilog frontend does not support
#      `import pkg::*;` in any form -- scripts/prep_synth_rtl.py stages
#      a mechanically-transformed COPY of rtl/ (never edits rtl/
#      itself) with package references fully qualified instead.
#   2. An uninitialized (all-X) instruction ROM lets Yosys's optimizer
#      const-propagate large parts of the CPU away as "don't care,"
#      silently under-reporting resource usage -- synth/stubs/
#      imem_synth_stub.sv is loaded with a real, instruction-diverse
#      program for this reason, not left at its default empty content.
#
# iCE40 chosen as the reference device because it's the target
# nextpnr/icestorm (this project's fully open-source FPGA toolchain)
# supports without any vendor tools; it is a representative choice for
# demonstrating the open-source synthesis flow, not a claim about
# intended deployment hardware.
#
# Memory depth for the full riscv_soc run: 256 words (not the RTL's
# own 1024-word default) for both IMEM and RAM. This is a synthesis-
# time-only parameter override via `chparam`, purely for ABC
# technology-mapping tractability in this environment -- a first
# attempt at the full 1024-word default took long enough (tens of
# minutes, tens of thousands of ABC-extracted gates) that a smaller,
# still-real, still-honestly-labeled depth was substituted instead.
# This never touches any simulated/verified program or testbench (all
# of which keep using the RTL's real 1024-word default); see
# docs/synthesis.md's "Scope" section.
#
# Usage: scripts/run_synthesis.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Staging synthesis-only RTL copy (build/synth_src/) =="
python3 scripts/prep_synth_rtl.py

mkdir -p build/synth_out results

# A real, instruction-diverse program to initialize the ROM stub with
# -- see this script's header comment (point 2) for why an
# uninitialized ROM is actively misleading here, not just pessimistic.
# 256 words: matches the full-SoC synthesis run's own reduced memory
# depth (see header comment above).
echo
echo "== Assembling a representative program for ROM initialization =="
python3 scripts/asm_to_hex.py sim/programs/soc/accel_custom_demo.s \
  -o build/synth_out/imem_init.hex --words 256

SYNTH_LOG=build/synth_out/synth_log.txt
: > "$SYNTH_LOG"

# (report name, top module, file list, extra yosys commands)
# Leaf/logic modules -- no memory arrays of their own (or, for
# regfile/accelerator, memory arrays whose read logic is real enough
# that an uninitialized array doesn't collapse their resource count --
# see docs/synthesis.md's verification section for how this was
# actually checked, not assumed).
run_module () {
  local name="$1" top="$2"
  shift 2
  local files=("$@")
  echo "-- $name --" | tee -a "$SYNTH_LOG"
  yosys -p "read_verilog -sv ${files[*]}; synth_ice40 -top $top" \
    >> "$SYNTH_LOG" 2>&1 || { echo "Yosys FAILED for $name" >&2; exit 1; }
  echo >> "$SYNTH_LOG"
}

echo
echo "== Synthesizing leaf/logic modules (iCE40) =="
run_module alu             alu             build/synth_src/cpu/riscv_pkg.sv build/synth_src/alu/alu.sv
run_module regfile         regfile         build/synth_src/regfile/regfile.sv
run_module decoder         decoder         build/synth_src/decoder/decoder.sv
run_module imm_gen         imm_gen         build/synth_src/cpu/riscv_pkg.sv build/synth_src/decoder/imm_gen.sv
run_module control_unit    control_unit    build/synth_src/cpu/riscv_pkg.sv build/synth_src/cpu/control_unit.sv
run_module branch_unit     branch_unit     build/synth_src/cpu/branch_unit.sv
run_module forwarding_unit forwarding_unit build/synth_src/pipeline/forwarding_unit.sv
run_module hazard_unit     hazard_unit     build/synth_src/pipeline/hazard_unit.sv
run_module perf_counters   perf_counters   build/synth_src/cpu/riscv_pkg.sv build/synth_src/cpu/perf_counters.sv
run_module uart            uart            build/synth_src/bus/uart.sv
run_module gpio            gpio            build/synth_src/bus/gpio.sv
run_module soc_bus         soc_bus         build/synth_src/bus/soc_bus.sv
run_module accelerator     accelerator     build/synth_src/accelerator/accelerator.sv

echo
echo "== Synthesizing the standalone pipelined CPU (iCE40, real ROM image) =="
cat > build/synth_out/cpu_pipeline.ys <<EOF
read_verilog -sv build/synth_src/cpu/riscv_pkg.sv \\
  build/synth_src/alu/alu.sv \\
  build/synth_src/regfile/regfile.sv \\
  build/synth_src/decoder/decoder.sv \\
  build/synth_src/decoder/imm_gen.sv \\
  build/synth_src/cpu/control_unit.sv \\
  build/synth_src/cpu/branch_unit.sv \\
  synth/stubs/imem_synth_stub.sv \\
  build/synth_src/pipeline/if_id_reg.sv \\
  build/synth_src/pipeline/id_ex_reg.sv \\
  build/synth_src/pipeline/ex_mem_reg.sv \\
  build/synth_src/pipeline/mem_wb_reg.sv \\
  build/synth_src/pipeline/forwarding_unit.sv \\
  build/synth_src/pipeline/hazard_unit.sv \\
  build/synth_src/cpu/perf_counters.sv \\
  build/synth_src/cpu/riscv_cpu_pipeline.sv
chparam -set IMEM_INIT_FILE "$(pwd)/build/synth_out/imem_init.hex" riscv_cpu_pipeline
chparam -set IMEM_DEPTH_WORDS 256 riscv_cpu_pipeline
synth_ice40 -top riscv_cpu_pipeline -json build/synth_out/riscv_cpu_pipeline.json
EOF
echo "-- riscv_cpu_pipeline --" | tee -a "$SYNTH_LOG"
yosys -s build/synth_out/cpu_pipeline.ys >> "$SYNTH_LOG" 2>&1 || {
  echo "Yosys FAILED for riscv_cpu_pipeline" >&2; exit 1;
}

echo
echo "== Synthesizing full riscv_soc (iCE40, with a real ROM image) =="
cat > build/synth_out/full_soc.ys <<EOF
read_verilog -sv build/synth_src/cpu/riscv_pkg.sv \\
  build/synth_src/alu/alu.sv \\
  build/synth_src/regfile/regfile.sv \\
  build/synth_src/decoder/decoder.sv \\
  build/synth_src/decoder/imm_gen.sv \\
  build/synth_src/cpu/control_unit.sv \\
  build/synth_src/cpu/branch_unit.sv \\
  synth/stubs/imem_synth_stub.sv \\
  synth/stubs/dmem_synth_stub.sv \\
  build/synth_src/pipeline/if_id_reg.sv \\
  build/synth_src/pipeline/id_ex_reg.sv \\
  build/synth_src/pipeline/ex_mem_reg.sv \\
  build/synth_src/pipeline/mem_wb_reg.sv \\
  build/synth_src/pipeline/forwarding_unit.sv \\
  build/synth_src/pipeline/hazard_unit.sv \\
  build/synth_src/cpu/perf_counters.sv \\
  build/synth_src/cpu/riscv_cpu_pipeline.sv \\
  build/synth_src/bus/soc_bus.sv \\
  build/synth_src/bus/uart.sv \\
  build/synth_src/bus/gpio.sv \\
  build/synth_src/accelerator/accelerator.sv \\
  build/synth_src/cpu/riscv_soc.sv
chparam -set IMEM_INIT_FILE "$(pwd)/build/synth_out/imem_init.hex" riscv_soc
chparam -set IMEM_DEPTH_WORDS 256 riscv_soc
chparam -set RAM_DEPTH_WORDS 256 riscv_soc
synth_ice40 -top riscv_soc -json build/synth_out/riscv_soc.json
EOF
echo "-- riscv_soc --" | tee -a "$SYNTH_LOG"
yosys -s build/synth_out/full_soc.ys >> "$SYNTH_LOG" 2>&1 || {
  echo "Yosys FAILED for riscv_soc" >&2; exit 1;
}

echo
echo "== Parsing results and writing results/synthesis_report.md =="
python3 scripts/gen_synthesis_report.py "$SYNTH_LOG" build/synth_out/riscv_soc.json

echo
echo "Done. See results/synthesis_report.md"
