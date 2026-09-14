`timescale 1ns/1ps
// gpio.sv
//
// Phase 8: minimal memory-mapped GPIO peripheral for the SoC data bus
// (see docs/soc.md for the memory map -- base address 0x20000000). This
// models exactly what is observable/testable in a software-only
// simulation: a 32-bit output register software can write and a 32-bit
// input value software can read back. There is no physical pin, pad, or
// I/O buffer here (never claimed) -- `gpio_in` is simply an input port a
// testbench can drive to simulate an external signal, and `gpio_out` is
// an output port a testbench can observe to prove software can toggle
// bits and have that value leave the CPU's register file and land on a
// real output net.
//
// Register map (byte offsets within this peripheral's own window,
// addr[3:0] -- see rtl/bus/soc_bus.sv for how addr[31:28] routes a CPU
// access here):
//   0x0  GPIO_OUT (read/write): value drives the gpio_out output port.
//   0x4  GPIO_IN  (read-only):  reflects the gpio_in input port.

module gpio (
  input  logic        clk,
  input  logic        rst_n,
  input  logic [31:0] addr,
  input  logic [31:0] wdata,
  input  logic         mem_read,
  input  logic         mem_write,
  output logic [31:0] rdata,

  output logic [31:0] gpio_out,
  input  logic [31:0] gpio_in
);

  localparam logic [3:0] REG_OUT = 4'h0;
  localparam logic [3:0] REG_IN  = 4'h4;

  wire sel_out = (addr[3:0] == REG_OUT);
  wire sel_in  = (addr[3:0] == REG_IN);

  logic [31:0] out_reg;
  assign gpio_out = out_reg;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) out_reg <= 32'b0;
    else if (mem_write && sel_out) out_reg <= wdata;
  end

  assign rdata = !mem_read ? 32'b0 :
                 sel_out   ? out_reg :
                 sel_in    ? gpio_in :
                 32'b0;

endmodule
