// tb_c_program.sv
//
// Phase 4 testbench: runs a real, GCC-compiled C program on the CPU
// (see scripts/build_c_program.sh, software/baremetal/add_test.c). This
// is the same generic plusarg-driven pattern as
// sim/testbenches/tb_directed_test.sv (+HEXFILE=... selects the memory
// image), but checks the C calling convention's return-value register
// (a0 / x10) against an expected value passed via +EXPECTED=..., since
// different C programs return different results, instead of the
// directed-test suite's x31 pass/fail sentinel (a bare-metal C program
// compiled by a real, unmodified compiler has no reason to know about
// this project's own directed-test convention).

`timescale 1ns/1ps

module tb_c_program;

  logic clk;
  logic rst_n = 0;

  logic [31:0] dbg_pc, dbg_instr, dbg_rd_data, dbg_alu_result;
  logic        dbg_reg_write, dbg_illegal;
  logic [4:0]  dbg_rd_addr;

  riscv_cpu dut (
    .clk           (clk),
    .rst_n         (rst_n),
    .dbg_pc        (dbg_pc),
    .dbg_instr     (dbg_instr),
    .dbg_reg_write (dbg_reg_write),
    .dbg_rd_addr   (dbg_rd_addr),
    .dbg_rd_data   (dbg_rd_data),
    .dbg_alu_result(dbg_alu_result),
    .dbg_illegal   (dbg_illegal)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  logic saw_illegal = 1'b0;
  always_ff @(posedge clk) if (rst_n && dbg_illegal) saw_illegal <= 1'b1;

  localparam int MAX_CYCLES = 100;

  initial begin
    string testname;
    int expected;
    if (!$value$plusargs("TESTNAME=%s", testname)) testname = "(unnamed)";
    if (!$value$plusargs("EXPECTED=%d", expected)) expected = 0;

    rst_n = 0;
    repeat (2) @(posedge clk);
    // A small delay (not the bare next statement) before deasserting
    // reset: driving rst_n=1 exactly on the same active clock edge
    // every always_ff(posedge clk or negedge rst_n) block also samples
    // it on is a same-edge race whose outcome is simulator-defined --
    // found when Icarus Verilog and Verilator disagreed by exactly one
    // cycle on free-running counters in tb_perf_counters.sv (Phase 7;
    // see CHANGELOG.md). This #1 delay is the standard fix and costs
    // nothing (rst_n is not sampled at that instant by anything else).
    #1;
    rst_n = 1;

    for (int cyc = 0; cyc < MAX_CYCLES; cyc = cyc + 1) begin
      @(posedge clk);
      #1;
      if (dbg_reg_write && dbg_rd_addr != 0)
        $display("  t=%0t PC=0x%08x INSTR=0x%08x  x%0d <= 0x%08x",
                  $time, dbg_pc, dbg_instr, dbg_rd_addr, dbg_rd_data);
    end

    if (saw_illegal) begin
      $display("TEST_RESULT: FAIL test=%s reason=illegal_opcode_seen", testname);
    end else if (dut.regfile_inst.regs[10] === expected[31:0]) begin
      $display("TEST_RESULT: PASS test=%s a0=0x%08x (%0d)",
                testname, dut.regfile_inst.regs[10], $signed(dut.regfile_inst.regs[10]));
    end else begin
      $display("TEST_RESULT: FAIL test=%s expected_a0=0x%08x actual_a0=0x%08x",
                testname, expected, dut.regfile_inst.regs[10]);
    end
    $finish;
  end

endmodule
