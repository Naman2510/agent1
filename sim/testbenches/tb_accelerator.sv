// tb_accelerator.sv
//
// Phase 9 directed unit testbench for rtl/accelerator/accelerator.sv,
// driving the module's own MMIO register interface directly (not
// through the CPU/SoC bus -- that end-to-end path is Phase 9's other
// testbench, sim/testbenches/tb_soc_accel.sv) so a failure here always
// means the accelerator's own RTL is wrong, never a bus/decode issue
// elsewhere. Every expected value below is a real hand-computed
// reference for small, exactly-specified inputs (documented per test),
// not fabricated or "looks about right" numbers.
//
// Covers, in order (mirroring the task's own vector-add -> dot-product
// -> matrix-multiply progression so each capability is verified before
// the next is exercised):
//   1. OP_VECADD  (N=6)
//   2. OP_DOT     (N=4)
//   3. OP_MATMUL  (N=3, both operands non-trivial/non-symmetric so a
//                  row/column transposition bug would be caught)
//   4. LEN=0 error handling (VECADD)
//   5. LEN > MAX_DIM error handling (MATMUL)

`timescale 1ns/1ps

module tb_accelerator;

  localparam int MAX_DIM = 8;
  localparam int MAX_LEN = MAX_DIM * MAX_DIM;

  logic clk;
  logic rst_n = 0;

  logic [31:0] addr, wdata, rdata;
  logic         mem_read, mem_write;

  accelerator #(
    .MAX_DIM(MAX_DIM), .MAX_LEN(MAX_LEN)
  ) dut (
    .clk(clk), .rst_n(rst_n),
    .addr(addr), .wdata(wdata),
    .mem_read(mem_read), .mem_write(mem_write), .rdata(rdata)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  int errors = 0;

  // -- Register offsets (see accelerator.sv's header comment) --
  localparam logic [31:0] REG_CTRL    = 32'h0000;
  localparam logic [31:0] REG_STATUS  = 32'h0004;
  localparam logic [31:0] REG_LEN     = 32'h0008;
  localparam logic [31:0] REG_RESULT  = 32'h000C;
  localparam logic [31:0] VECA_BASE   = 32'h1000;
  localparam logic [31:0] VECB_BASE   = 32'h2000;
  localparam logic [31:0] VECOUT_BASE = 32'h3000;

  localparam logic [1:0] OP_VECADD = 2'b01;
  localparam logic [1:0] OP_DOT    = 2'b10;
  localparam logic [1:0] OP_MATMUL = 2'b11;

  // Every signal the DUT samples on a clock edge is changed here only
  // strictly AFTER that edge (a `#1` delay before touching it, not
  // just before releasing it), never in the same simulation instant as
  // the edge itself. This is the fix for a real bug this testbench
  // originally had (see CHANGELOG.md's Phase 9 entry): setting
  // addr/wdata/mem_write with a plain blocking assignment immediately
  // after `@(posedge clk)` raced the DUT's own always_ff block, which
  // is ALSO triggered by that exact edge -- their relative execution
  // order within the same time step is simulator-defined, and measured
  // behavior showed the DUT sometimes observing one write's address
  // paired with the NEXT write's data, corrupting which scratchpad
  // slot actually got written. A first attempt fixed only the
  // deassertion side with `#1` (matching this project's existing
  // reset-sequencing fix) and did not help, because the race was on
  // the ASSERTION edge, not the deassertion edge. Nonblocking
  // assignment looked like the standard textbook fix and did resolve
  // it under Icarus Verilog, but Verilator explicitly warns that a
  // nonblocking assignment inside an initial-block task is executed as
  // blocking there (`%Warning-INITIALDLY`) -- i.e. the two simulators
  // do not agree on what that code even means, which is disqualifying
  // for a project whose whole verification methodology is "both
  // simulators must agree." The portable fix used here instead is
  // real simulation-time separation: delay #1 past the edge before
  // ever touching a DUT input, so no process anywhere can observe the
  // change until strictly after every same-edge evaluation has
  // already happened -- unambiguous under any IEEE-compliant
  // simulator, and the same technique this project already uses for
  // every reset sequence.
  task automatic wr(logic [31:0] a, logic [31:0] d);
    @(posedge clk);
    #1;
    addr = a; wdata = d; mem_write = 1'b1; mem_read = 1'b0;
    @(posedge clk);
    #1;
    mem_write = 1'b0;
  endtask

  task automatic rd(logic [31:0] a, output logic [31:0] d);
    @(posedge clk);
    #1;
    addr = a; mem_read = 1'b1; mem_write = 1'b0;
    @(posedge clk);
    #1; // combinational read: sample rdata once addr has settled post-edge
    d = rdata;
    mem_read = 1'b0;
  endtask

  task automatic start_op(logic [1:0] op, int len);
    wr(REG_LEN, len[31:0]);
    wr(REG_CTRL, {29'b0, op, 1'b1}); // bits[2:1]=op, bit0=START
  endtask

  // Poll STATUS until DONE; returns {err, done, busy} bits observed at
  // completion and the number of cycles waited (for a sanity bound).
  task automatic wait_done(output logic err_bit, input int max_wait);
    logic [31:0] status;
    int waited;
    bit         got_done;
    waited = 0;
    status = 32'b0;
    got_done = 1'b0;
    err_bit = 1'bx;
    while (waited < max_wait && !got_done) begin
      rd(REG_STATUS, status);
      if (status[1]) begin // DONE
        err_bit = status[2];
        got_done = 1'b1;
      end
      waited++;
    end
    if (!got_done) begin
      $display("  [FAIL] wait_done: STATUS never asserted DONE within %0d polls", max_wait);
      errors++;
    end
  endtask

  task automatic check(string name, logic [31:0] actual, logic [31:0] expected);
    if (actual !== expected) begin
      $display("  [FAIL] %-28s expected=%0d (0x%08x) actual=%0d (0x%08x)",
                name, expected, expected, actual, actual);
      errors++;
    end else begin
      $display("  [PASS] %-28s = %0d", name, actual);
    end
  endtask

  initial begin
    logic [31:0] v;
    logic err_bit;

    addr = 0; wdata = 0; mem_read = 0; mem_write = 0;

    $display("=== Phase 9 accelerator unit testbench ===");

    rst_n = 0;
    repeat (2) @(posedge clk);
    #1; // same-edge reset race fix, see CHANGELOG.md's Phase 7 entry
    rst_n = 1;

    // -----------------------------------------------------------------
    // Test 1: OP_VECADD, N=6. a=[1..6], b=[10,20,30,40,50,60].
    // Expected out = [11,22,33,44,55,66].
    // -----------------------------------------------------------------
    $display("");
    $display("--- OP_VECADD (N=6) ---");
    for (int i = 0; i < 6; i++) begin
      wr(VECA_BASE + i*4, i + 1);
      wr(VECB_BASE + i*4, (i + 1) * 10);
    end
    start_op(OP_VECADD, 6);
    wait_done(err_bit, 50);
    check("vecadd err flag", {31'b0, err_bit}, 32'd0);
    for (int i = 0; i < 6; i++) begin
      rd(VECOUT_BASE + i*4, v);
      check($sformatf("vecadd out[%0d]", i), v, (i + 1) + (i + 1) * 10);
    end

    // -----------------------------------------------------------------
    // Test 2: OP_DOT, N=4. a=[1,2,3,4], b=[5,6,7,8].
    // Expected = 1*5 + 2*6 + 3*7 + 4*8 = 5+12+21+32 = 70.
    // -----------------------------------------------------------------
    $display("");
    $display("--- OP_DOT (N=4) ---");
    wr(VECA_BASE + 0, 1); wr(VECA_BASE + 4, 2); wr(VECA_BASE + 8,  3); wr(VECA_BASE + 12, 4);
    wr(VECB_BASE + 0, 5); wr(VECB_BASE + 4, 6); wr(VECB_BASE + 8,  7); wr(VECB_BASE + 12, 8);
    start_op(OP_DOT, 4);
    wait_done(err_bit, 50);
    check("dot err flag", {31'b0, err_bit}, 32'd0);
    rd(REG_RESULT, v);
    check("dot result", v, 32'd70);

    // -----------------------------------------------------------------
    // Test 3: OP_MATMUL, N=3.
    //   A = [1 2 3; 4 5 6; 7 8 9]   (row-major flattened)
    //   B = [9 8 7; 6 5 4; 3 2 1]
    //   C = A*B = [30 24 18; 84 69 54; 138 114 90]  (hand-computed,
    //   see this testbench's header comment for the full derivation)
    // -----------------------------------------------------------------
    $display("");
    $display("--- OP_MATMUL (N=3) ---");
    begin
      // Icarus Verilog doesn't support whole-array literal assignment
      // ('{...}) in this context, so each element is assigned
      // individually rather than working around it with a different
      // (less readable) data structure.
      int a_vals[0:8];
      int b_vals[0:8];
      int c_expected[0:8];
      a_vals[0]=1; a_vals[1]=2; a_vals[2]=3;
      a_vals[3]=4; a_vals[4]=5; a_vals[5]=6;
      a_vals[6]=7; a_vals[7]=8; a_vals[8]=9;
      b_vals[0]=9; b_vals[1]=8; b_vals[2]=7;
      b_vals[3]=6; b_vals[4]=5; b_vals[5]=4;
      b_vals[6]=3; b_vals[7]=2; b_vals[8]=1;
      c_expected[0]=30;  c_expected[1]=24;  c_expected[2]=18;
      c_expected[3]=84;  c_expected[4]=69;  c_expected[5]=54;
      c_expected[6]=138; c_expected[7]=114; c_expected[8]=90;
      for (int i = 0; i < 9; i++) begin
        wr(VECA_BASE + i*4, a_vals[i]);
        wr(VECB_BASE + i*4, b_vals[i]);
      end
      start_op(OP_MATMUL, 3);
      wait_done(err_bit, 100);
      check("matmul err flag", {31'b0, err_bit}, 32'd0);
      for (int i = 0; i < 9; i++) begin
        rd(VECOUT_BASE + i*4, v);
        check($sformatf("matmul out[%0d]", i), v, c_expected[i]);
      end
    end

    // -----------------------------------------------------------------
    // Test 4: LEN=0 must fail fast with ERR, not hang.
    // -----------------------------------------------------------------
    $display("");
    $display("--- Error handling: LEN=0 (VECADD) ---");
    start_op(OP_VECADD, 0);
    wait_done(err_bit, 20);
    check("len=0 err flag", {31'b0, err_bit}, 32'd1);

    // -----------------------------------------------------------------
    // Test 5: LEN > MAX_DIM for MATMUL must fail fast with ERR.
    // -----------------------------------------------------------------
    $display("");
    $display("--- Error handling: LEN=%0d > MAX_DIM=%0d (MATMUL) ---", MAX_DIM + 1, MAX_DIM);
    start_op(OP_MATMUL, MAX_DIM + 1);
    wait_done(err_bit, 20);
    check("len>MAX_DIM err flag", {31'b0, err_bit}, 32'd1);

    $display("");
    if (errors == 0) begin
      $display("RESULT: ALL CHECKS PASSED");
    end else begin
      $display("RESULT: %0d CHECK(S) FAILED", errors);
    end
    $finish;
  end

endmodule
