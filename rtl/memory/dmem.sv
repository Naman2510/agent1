`timescale 1ns/1ps
// dmem.sv
//
// Simulated data memory for Phase 2. Word-addressed, word-sized accesses
// only (LW/SW -- see docs/riscv.md section 4 for what is intentionally
// out of scope). Write is synchronous (committed on the clock edge, like
// a real synchronous SRAM); read is combinational and gated by mem_read
// so that non-load instructions don't drive spurious data onto the
// writeback mux. This is a behavioral simulation model, not synthesizable
// SRAM -- see docs/soc.md (Phase 8) for the real SoC memory map.

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

  logic [31:0] mem [0:DEPTH_WORDS-1];

  initial begin
    for (int i = 0; i < DEPTH_WORDS; i++) mem[i] = 32'b0;
  end

  always_ff @(posedge clk) begin
    if (mem_write) mem[addr[WORD_ADDR_BITS+1:2]] <= wdata;
  end

  assign rdata = mem_read ? mem[addr[WORD_ADDR_BITS+1:2]] : 32'b0;

endmodule
