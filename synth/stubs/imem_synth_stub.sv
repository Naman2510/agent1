`timescale 1ns/1ps
// imem_synth_stub.sv
//
// Phase 12 SYNTHESIS-ONLY stand-in for rtl/memory/imem.sv (declares a
// module also named `imem`, matching what riscv_cpu_pipeline.sv
// instantiates, but lives here, never under rtl/). NOT part of the
// simulated/verified design -- rtl/memory/imem.sv's own header
// comment already states it is "a behavioral simulation model, not a
// synthesizable ROM," specifically because of its runtime
// `+HEXFILE=...` plusarg override (`$value$plusargs`), a
// simulation-only SystemVerilog construct Yosys's open-source Verilog
// frontend cannot parse at all -- confirmed directly, not assumed:
//
//   $ yosys -p "read_verilog -sv rtl/memory/imem.sv"
//   ERROR: syntax error, unexpected TOK_ID
//
// This stub exists ONLY so scripts/run_synthesis.sh can obtain a
// complete top-level (riscv_cpu_pipeline / riscv_soc) resource count.
// It is never simulated and never substituted into the actual RTL
// under rtl/ -- every testbench in sim/testbenches/ continues to
// instantiate the real rtl/memory/imem.sv exactly as before. A real
// FPGA implementation of this project would map this array to vendor
// block-RAM primitives, not LUT-based flip-flops; see
// docs/synthesis.md for why this module's own resource count is
// reported and caveated separately rather than folded silently into
// the CPU's headline LUT/FF totals.

module imem #(
  parameter int DEPTH_WORDS = 1024,
  parameter      INIT_FILE  = ""
) (
  input  logic [31:0] addr, // byte address (must be word-aligned)
  output logic [31:0] instr
);

  localparam int WORD_ADDR_BITS = $clog2(DEPTH_WORDS);

  // Real (compile-time-constant, synthesizable) $readmemh initial
  // content, unlike rtl/memory/imem.sv's runtime +HEXFILE= plusarg --
  // deliberately given a real, instruction-diverse program by
  // scripts/run_synthesis.sh rather than left as all-X. An
  // uninitialized/all-X ROM is not just "pessimistic" here, it is
  // actively MISLEADING: Yosys's optimizer treats X-driven logic as
  // "don't care" and can const-propagate large swaths of downstream
  // decode/control logic away, since their output no longer
  // constrains anything observable -- discovered empirically (a first
  // synthesis attempt with no INIT_FILE reported an implausibly small
  // ~240-cell riscv_soc, corrected once real content was loaded here;
  // see docs/synthesis.md and CHANGELOG.md's Phase 12 entry for the
  // full account) rather than assumed safe.
  logic [31:0] mem [0:DEPTH_WORDS-1];
  initial if (INIT_FILE != "") $readmemh(INIT_FILE, mem);

  assign instr = mem[addr[WORD_ADDR_BITS+1:2]];

endmodule
