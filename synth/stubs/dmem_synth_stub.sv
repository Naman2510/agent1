`timescale 1ns/1ps
// dmem_synth_stub.sv
//
// Phase 12 SYNTHESIS-ONLY stand-in for rtl/memory/dmem.sv (declares a
// module also named `dmem`, matching what riscv_cpu_pipeline.sv's
// testbenches and riscv_soc.sv's RAM instance expect). See
// imem_synth_stub.sv's header comment for the full rationale --
// identical situation: rtl/memory/dmem.sv is documented as "a
// behavioral simulation model, not synthesizable SRAM," and while
// dmem.sv itself has no plusarg (its non-synthesizability is about
// being a behavioral model generally, not one specific construct),
// this stub keeps the same "never touch rtl/, never simulate this"
// discipline as imem_synth_stub.sv for consistency and so a reader
// only has to understand the rule once.
//
// A real FPGA implementation would map this to vendor block-RAM
// primitives, not LUT-based flip-flops -- see docs/synthesis.md.

module dmem #(
  parameter int DEPTH_WORDS = 1024
) (
  input  logic         clk,
  input  logic [31:0]  addr,   // byte address (must be word-aligned)
  input  logic [31:0]  wdata,
  input  logic         mem_read,
  input  logic         mem_write,
  output logic [31:0]  rdata
);

  localparam int WORD_ADDR_BITS = $clog2(DEPTH_WORDS);

  // Zero-initialized for the same reason imem_synth_stub.sv loads real
  // content instead of leaving its ROM at all-X: an uninitialized
  // memory's reads are formally "don't care" to Yosys's optimizer and
  // can be const-propagated away, silently shrinking the reported
  // design. The actual values don't matter here (unlike imem, this is
  // read-write data memory, not fixed firmware), only that they are
  // DEFINED.
  logic [31:0] mem [0:DEPTH_WORDS-1];
  initial for (int i = 0; i < DEPTH_WORDS; i++) mem[i] = 32'b0;

  always_ff @(posedge clk) begin
    if (mem_write) mem[addr[WORD_ADDR_BITS+1:2]] <= wdata;
  end

  assign rdata = mem_read ? mem[addr[WORD_ADDR_BITS+1:2]] : 32'b0;

endmodule
