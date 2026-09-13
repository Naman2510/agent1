`timescale 1ns/1ps
// regfile.sv
//
// RV32I register file: 32 x 32-bit registers, two asynchronous read ports
// (rs1/rs2, read every cycle for the current instruction) and one
// synchronous write port (rd, written on the clock edge that retires an
// instruction).
//
// x0 is hard-wired to zero (docs/riscv.md section 1.1): reads of x0 always
// return 0 regardless of what was ever "written" to it, and writes to x0
// are accepted (rd_addr == 0 is legal to encode) but silently discarded.
// This is enforced here in hardware, not left to software convention.

module regfile (
  input  logic        clk,
  input  logic         rst_n,
  input  logic [4:0]  rs1_addr,
  input  logic [4:0]  rs2_addr,
  input  logic [4:0]  rd_addr,
  input  logic [31:0] rd_data,
  input  logic        reg_write,
  output logic [31:0] rs1_data,
  output logic [31:0] rs2_data
);

  logic [31:0] regs [1:31]; // x0 deliberately excluded: it is not storage

  integer i;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (i = 1; i <= 31; i = i + 1) regs[i] <= 32'b0;
    end else if (reg_write && rd_addr != 5'd0) begin
      regs[rd_addr] <= rd_data;
    end
  end

  // Asynchronous (combinational) reads, with x0 forced to zero.
  assign rs1_data = (rs1_addr == 5'd0) ? 32'b0 : regs[rs1_addr];
  assign rs2_data = (rs2_addr == 5'd0) ? 32'b0 : regs[rs2_addr];

endmodule
