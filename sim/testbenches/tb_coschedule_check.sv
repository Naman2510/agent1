// tb_coschedule_check.sv
//
// Generic full-output correctness check for generated multi-task programs
// (co-scheduler, serial-oracle and always-accelerator programs from
// scheduler/coschedule/). Runs the program given by +HEXFILE until it
// writes the GPIO completion sentinel, then compares EVERY expected output
// word: +EXPECT names a $readmemh file of 64-bit entries
// {ram_word_index[31:0], expected_value[31:0]}, +NCHECK how many there are.
// The expected values are computed in Python by the generator, never typed
// by hand. Every word is checked -- not a spot check.

`timescale 1ns/1ps

module tb_coschedule_check #(
  parameter bit ENABLE_MUL       = 1'b0,
  parameter int IMEM_DEPTH_WORDS = 4096,
  parameter int MAX_CYCLES       = 400000,
  parameter int MAX_CHECKS       = 4096
);
  logic clk;
  logic rst_n = 1'b0;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  logic [31:0] gpio_out;

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
    .perf_cycle_count(), .perf_instr_retired_count(), .perf_stall_count(),
    .perf_branch_count(), .perf_branch_taken_count(), .perf_load_use_stall_count(),
    .perf_forwarding_event_count(), .perf_flush_count()
  );

  logic [63:0] expect_mem [0:MAX_CHECKS-1];

  initial begin
    string expect_file;
    int ncheck, errors, n;
    if (!$value$plusargs("EXPECT=%s", expect_file)) begin
      $display("ERROR: +EXPECT=... required"); $finish;
    end
    if (!$value$plusargs("NCHECK=%d", ncheck)) begin
      $display("ERROR: +NCHECK=... required"); $finish;
    end
    if (ncheck > MAX_CHECKS) begin
      $display("ERROR: NCHECK=%0d exceeds MAX_CHECKS=%0d", ncheck, MAX_CHECKS); $finish;
    end
    $readmemh(expect_file, expect_mem, 0, ncheck - 1);

    rst_n = 1'b0;
    repeat (2) @(posedge clk);
    #1;
    rst_n = 1'b1;
    n = 0;
    while (gpio_out !== 32'hDEADBEEF && n < MAX_CYCLES) begin
      @(posedge clk);
      #1;
      n++;
    end

    errors = 0;
    if (gpio_out !== 32'hDEADBEEF) begin
      $display("  [FAIL] sentinel never observed within %0d cycles", MAX_CYCLES);
      errors++;
    end
    for (int i = 0; i < ncheck; i++) begin
      logic [31:0] idx, want, got;
      idx  = expect_mem[i][63:32];
      want = expect_mem[i][31:0];
      got  = dut.ram_inst.mem[idx[11:0]];
      if (got !== want) begin
        if (errors < 10)
          $display("  [FAIL] RAM word 0x%03h: expected %0d, got %0d", idx, want, got);
        errors++;
      end
    end
    if (errors == 0) $display("CHECKED %0d output words", ncheck);
    if (errors == 0) $display("RESULT: ALL CHECKS PASSED");
    else             $display("RESULT: %0d CHECK(S) FAILED", errors);
    $finish;
  end
endmodule
