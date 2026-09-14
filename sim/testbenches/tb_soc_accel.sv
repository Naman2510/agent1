// tb_soc_accel.sv
//
// Phase 9 end-to-end testbench: runs sim/programs/soc/accel_demo.s on
// the full riscv_soc (rtl/cpu/riscv_soc.sv), which drives the hardware
// accelerator (rtl/accelerator/accelerator.sv) purely through ordinary
// LW/SW instructions across the real address-decoded bus at
// 0x30000000. This is deliberately separate from
// sim/testbenches/tb_accelerator.sv (which drives the accelerator's
// register interface directly): a failure here means the CPU/bus path
// to the accelerator is wrong even if the accelerator's own unit test
// passes, and vice versa -- exactly the same "isolate which layer
// broke" reasoning behind every other unit-then-integration testbench
// pair in this project (e.g. ALU/regfile directed tests vs. Phase 3's
// full-CPU directed tests).
//
// A larger MAX_CYCLES budget than tb_soc.sv's is needed here: the
// MATMUL portion of accel_demo.s (N=2) takes only 2^3=8 accelerator
// cycles internally, but each CPU-side STATUS poll and register access
// costs several pipeline cycles of its own, and the program issues many
// of them across three separate accelerator operations.

`timescale 1ns/1ps

module tb_soc_accel;

  logic clk;
  logic rst_n = 0;

  logic [31:0] gpio_in = 32'b0;
  logic [31:0] gpio_out;
  logic         uart_tx_valid;
  logic [7:0]   uart_tx_byte;

  logic [31:0] dbg_if_pc, dbg_if_instr, dbg_id_pc, dbg_id_instr, dbg_ex_pc, dbg_ex_instr;
  logic [31:0] dbg_mem_instr, dbg_wb_instr, dbg_rd_data;
  logic         dbg_reg_write, dbg_illegal, dbg_stall, dbg_flush;
  logic [4:0]  dbg_rd_addr;
  logic [31:0] perf_cycle_count, perf_instr_retired_count, perf_stall_count;
  logic [31:0] perf_branch_count, perf_branch_taken_count, perf_load_use_stall_count;
  logic [31:0] perf_forwarding_event_count, perf_flush_count;

  riscv_soc #(
    .IMEM_INIT_FILE("sim/programs/soc/accel_demo.hex"),
    .UART_BUSY_CYCLES(4),
    .ACCEL_MAX_DIM(8)
  ) dut (
    .clk(clk), .rst_n(rst_n),
    .gpio_in(gpio_in), .gpio_out(gpio_out),
    .uart_tx_valid(uart_tx_valid), .uart_tx_byte(uart_tx_byte),
    .dbg_if_pc(dbg_if_pc), .dbg_if_instr(dbg_if_instr),
    .dbg_id_pc(dbg_id_pc), .dbg_id_instr(dbg_id_instr),
    .dbg_ex_pc(dbg_ex_pc), .dbg_ex_instr(dbg_ex_instr),
    .dbg_mem_instr(dbg_mem_instr), .dbg_wb_instr(dbg_wb_instr),
    .dbg_reg_write(dbg_reg_write), .dbg_rd_addr(dbg_rd_addr), .dbg_rd_data(dbg_rd_data),
    .dbg_illegal(dbg_illegal), .dbg_stall(dbg_stall), .dbg_flush(dbg_flush),
    .perf_cycle_count(perf_cycle_count),
    .perf_instr_retired_count(perf_instr_retired_count),
    .perf_stall_count(perf_stall_count),
    .perf_branch_count(perf_branch_count),
    .perf_branch_taken_count(perf_branch_taken_count),
    .perf_load_use_stall_count(perf_load_use_stall_count),
    .perf_forwarding_event_count(perf_forwarding_event_count),
    .perf_flush_count(perf_flush_count)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  localparam int MAX_CYCLES = 2000;

  initial begin
    $display("=== Phase 9 SoC + accelerator end-to-end testbench ===");

    rst_n = 0;
    repeat (2) @(posedge clk);
    #1; // same-edge reset race fix, see CHANGELOG.md's Phase 7 entry
    rst_n = 1;

    repeat (MAX_CYCLES) @(posedge clk);
    #1;

    $display("cycles=%0d instr_retired=%0d", perf_cycle_count, perf_instr_retired_count);

    if (dut.cpu_inst.regfile_inst.regs[31] === 32'd1) begin
      $display("TEST_RESULT: PASS test=accel_demo");
    end else begin
      $display("TEST_RESULT: FAIL test=accel_demo x31=0x%08x",
                dut.cpu_inst.regfile_inst.regs[31]);
    end
    $finish;
  end

endmodule
