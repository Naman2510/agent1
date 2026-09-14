// tb_directed_test.sv
//
// Generic Phase 3 directed-test harness. Compiled ONCE and re-run against
// every test program under sim/programs/tests/ via a `+HEXFILE=...`
// plusarg (see rtl/memory/imem.sv), so adding a new directed test never
// requires touching this file or recompiling anything -- only adding a
// new .s file (see scripts/run_directed_tests.py).
//
// Pass/fail convention (documented once here, followed by every test
// program under sim/programs/tests/):
//   - Register x31 (t6) is reserved as the test's result register.
//   - On success, the test program sets x31 = 1 and halts (infinite loop).
//   - On failure, the test program sets x31 = a *distinct* nonzero code
//     with the high bit set (0x8000_00xx) identifying which assertion
//     inside the file failed, then halts. This gives per-assertion
//     debuggability even though several related instructions share one
//     test file (see docs/testing.md for the full convention and why).
//   - x31 must never be read as an operand by the instructions under
//     test in these programs (it is reserved), so no test's own
//     computation can accidentally produce 1 and mask a real failure.
//
// This testbench also tracks whether `illegal` was EVER asserted during
// the run (not just at the final cycle) -- a well-formed RV32I test must
// never hit the control unit's default/illegal case.

`timescale 1ns/1ps

module tb_directed_test;

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

  // Only counts `illegal` while the core is out of reset: whatever
  // happens on the fetch path before/during reset is not a real
  // instruction execution and isn't what this check is verifying (see
  // the `pc` initializer comment in riscv_cpu.sv for the related fix
  // that removes the pre-reset X window at its source).
  logic saw_illegal = 1'b0;
  always_ff @(posedge clk) if (rst_n && dbg_illegal) saw_illegal <= 1'b1;

  // How long any directed test in this suite is allowed to run before
  // being declared a timeout. Every test here is a short, loop-free
  // sequence (aside from the terminal spin loop), so 300 cycles is a
  // generous margin over the longest test file in this suite.
  localparam int MAX_CYCLES = 300;

  int cyc;

  initial begin
    string testname;
    if (!$value$plusargs("TESTNAME=%s", testname)) testname = "(unnamed)";

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

    for (cyc = 0; cyc < MAX_CYCLES; cyc = cyc + 1) begin
      @(posedge clk);
    end
    #1;

    if (saw_illegal) begin
      $display("TEST_RESULT: FAIL test=%s reason=illegal_opcode_seen", testname);
    end else if (dut.regfile_inst.regs[31] === 32'd1) begin
      $display("TEST_RESULT: PASS test=%s", testname);
    end else begin
      $display("TEST_RESULT: FAIL test=%s x31=0x%08x", testname, dut.regfile_inst.regs[31]);
    end
    $finish;
  end

endmodule
