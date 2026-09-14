// tb_soc_accel_custom.sv
//
// Phase 10 end-to-end testbench: runs
// sim/programs/soc/accel_custom_demo.s -- the SAME three operations
// and SAME expected results as Phase 9's tb_soc_accel.sv, but using
// the new ACCEL.* custom RISC-V instructions (docs/custom_extension.md)
// instead of plain MMIO for the CTRL write and STATUS read -- on the
// full riscv_soc. A pass here, combined with tb_soc_accel.sv's pass on
// the plain-MMIO version, is what proves the custom extension is a
// genuine alternate path to the SAME hardware behavior, not a
// different (and unverified) one.

`timescale 1ns/1ps

module tb_soc_accel_custom;

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
    .IMEM_INIT_FILE("sim/programs/soc/accel_custom_demo.hex"),
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
    $display("=== Phase 10 SoC + ACCEL.* custom instruction testbench ===");

    rst_n = 0;
    repeat (2) @(posedge clk);
    #1; // same-edge reset race fix, see CHANGELOG.md's Phase 7 entry
    rst_n = 1;

    repeat (MAX_CYCLES) @(posedge clk);
    #1;

    $display("cycles=%0d instr_retired=%0d", perf_cycle_count, perf_instr_retired_count);

    // dbg_illegal is NOT checked here (or by any other pipelined-CPU
    // testbench since Phase 6): a pipeline bubble decodes as opcode
    // 0000000, which control_unit.sv correctly flags as `illegal` --
    // completely normal at any instant a bubble happens to be in ID,
    // including during this program's `done: j done` halt loop. See
    // CHANGELOG.md's Phase 6 entry. The x31 pass/fail convention below
    // is the only correctness signal this testbench relies on.
    if (dut.cpu_inst.regfile_inst.regs[31] === 32'd1) begin
      $display("TEST_RESULT: PASS test=accel_custom_demo");
    end else begin
      $display("TEST_RESULT: FAIL test=accel_custom_demo x31=0x%08x",
                dut.cpu_inst.regfile_inst.regs[31]);
    end
    $finish;
  end

endmodule
