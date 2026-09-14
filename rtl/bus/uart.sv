`timescale 1ns/1ps
// uart.sv
//
// Phase 8: minimal memory-mapped, transmit-only UART peripheral for the
// SoC data bus (see docs/soc.md for the memory map this lives in --
// base address 0x10000000). This is a simulation model of a UART's
// SOFTWARE-VISIBLE register interface, not a bit-accurate serial-line
// model: there is no physical TX pin, start/stop bits, or real baud-rate
// timing here, because none of that is observable without physical
// hardware (task requirement: never claim/fabricate physical behavior
// that was not actually run). What IS real and testable in simulation:
// a byte written to TXDATA is captured exactly once, a STATUS busy flag
// is asserted for a short, deliberately-artificial number of cycles
// (BUSY_CYCLES) to give software something honest to poll, and the
// `tx_valid`/`tx_byte` ports expose every transmitted byte for a
// testbench to observe and print -- this is how docs/soc.md's demo
// proves "the CPU can drive a UART" without pretending to simulate an
// actual RS-232 line.
//
// Register map (byte offsets within this peripheral's own 4-bit window,
// i.e. addr[3:0] -- see rtl/bus/soc_bus.sv for how addr[31:28] routes a
// CPU access here in the first place):
//   0x0  TXDATA  (write-only, byte in wdata[7:0]): accept one byte for
//                "transmission"; ignored while busy_cnt != 0 as if the
//                real hardware FIFO were full (software is expected to
//                poll STATUS first, exactly as real UART drivers do).
//   0x4  STATUS  (read-only): bit0 = TX_BUSY.

module uart #(
  parameter int BUSY_CYCLES = 4 // simulated turnaround latency; NOT a real baud rate
) (
  input  logic        clk,
  input  logic        rst_n,
  input  logic [31:0] addr,     // decoded within this peripheral's own window
  input  logic [31:0] wdata,
  input  logic         mem_read,
  input  logic         mem_write,
  output logic [31:0] rdata,

  // Observable "transmitted byte" interface for a testbench/demo to
  // consume -- pulses tx_valid for exactly one cycle per accepted byte.
  output logic         tx_valid,
  output logic [7:0]   tx_byte
);

  localparam logic [3:0] REG_TXDATA = 4'h0;
  localparam logic [3:0] REG_STATUS = 4'h4;

  localparam int CNT_BITS = $clog2(BUSY_CYCLES + 1);

  logic [CNT_BITS-1:0] busy_cnt;
  logic [7:0]          last_tx_byte;

  wire sel_txdata = (addr[3:0] == REG_TXDATA);
  wire sel_status = (addr[3:0] == REG_STATUS);
  wire busy       = (busy_cnt != '0);
  wire accept_tx  = mem_write && sel_txdata && !busy;

  assign tx_valid = accept_tx;
  assign tx_byte  = wdata[7:0];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      busy_cnt     <= '0;
      last_tx_byte <= 8'b0;
    end else if (accept_tx) begin
      last_tx_byte <= wdata[7:0];
      busy_cnt     <= CNT_BITS'(BUSY_CYCLES);
    end else if (busy) begin
      busy_cnt <= busy_cnt - 1'b1;
    end
  end

  assign rdata = !mem_read ? 32'b0 :
                 sel_status ? {31'b0, busy} :
                 sel_txdata ? {24'b0, last_tx_byte} :
                 32'b0;

endmodule
