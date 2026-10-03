// tb_accel_phase_probe.sv
//
// Profiling harness for the co-scheduler (scheduler/coschedule/). Runs one
// program on riscv_soc (program image from +HEXFILE, which imem.sv reads
// directly) until it writes the GPIO completion sentinel, and reports, in
// the CPU's own performance-counter cycles (the same counter
// tb_benchmark_soc.sv reports):
//
//   PROBE total=<cycles at sentinel> intervals=<k>
//   BUSY rise=<cycle the accelerator became busy> fall=<cycle it became idle>
//
// one BUSY line per accelerator operation. The co-scheduler's planner uses
// these to learn how long the accelerator runs on its own after each START
// -- the window in which the CPU is free to do other work. Measurement
// only: makes no correctness assertion.

`timescale 1ns/1ps

module tb_accel_phase_probe #(
  parameter bit ENABLE_MUL       = 1'b0,
  parameter int IMEM_DEPTH_WORDS = 4096,
  parameter int MAX_CYCLES       = 400000
);
  logic clk;
  logic rst_n = 1'b0;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  logic [31:0] gpio_out, cyc_count;

  riscv_soc #(
    .UART_BUSY_CYCLES(4), .ACCEL_MAX_DIM(8), .RAM_DEPTH_WORDS(4096),
    .IMEM_DEPTH_WORDS(IMEM_DEPTH_WORDS), .ENABLE_MUL(ENABLE_MUL)
  ) dut (
    .clk(clk), .rst_n(rst_n), .gpio_in(32'b0), .gpio_out(gpio_out),
    .uart_tx_valid(), .uart_tx_byte(),
    .dbg_if_pc(), .dbg_if_instr(), .dbg_id_pc(), .dbg_id_instr(),
    .dbg_ex_pc(), .dbg_ex_instr(), .dbg_mem_instr(), .dbg_wb_instr(),
    .dbg_reg_write(), .dbg_rd_addr(), .dbg_rd_data(),
    .dbg_illegal(), .dbg_stall(), .dbg_flush(),
    .perf_cycle_count(cyc_count), .perf_instr_retired_count(), .perf_stall_count(),
    .perf_branch_count(), .perf_branch_taken_count(), .perf_load_use_stall_count(),
    .perf_forwarding_event_count(), .perf_flush_count()
  );

  int unsigned rises [$];
  int unsigned falls [$];

  initial begin
    int n;
    logic prev_busy;
    rst_n = 1'b0;
    repeat (2) @(posedge clk);
    #1;
    rst_n = 1'b1;
    prev_busy = 1'b0;
    n = 0;
    while (gpio_out !== 32'hDEADBEEF && n < MAX_CYCLES) begin
      @(posedge clk);
      #1;
      n++;
      if (dut.accel_inst.busy && !prev_busy) rises.push_back(cyc_count);
      if (!dut.accel_inst.busy && prev_busy) falls.push_back(cyc_count);
      prev_busy = dut.accel_inst.busy;
    end
    if (gpio_out !== 32'hDEADBEEF) begin
      $display("PROBE_ERROR: sentinel never observed within %0d cycles", MAX_CYCLES);
      $finish;
    end
    $display("PROBE total=%0d intervals=%0d", cyc_count, rises.size());
    foreach (rises[i]) $display("BUSY rise=%0d fall=%0d", rises[i], (i < falls.size()) ? falls[i] : -1);
    $finish;
  end
endmodule
