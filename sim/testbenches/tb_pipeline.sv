// tb_pipeline.sv
//
// Phase 5 testbench for the pipelined CPU (rtl/cpu/riscv_cpu_pipeline.sv).
// Loads sim/programs/pipeline_straightline.s (assembled to hex), traces
// all five stages every cycle -- showing five different instructions
// occupying five different stages simultaneously, which is the actual,
// observable point of pipelining -- and checks final register state
// against hand-computed expected values, the same style as Phase 2's
// tb_riscv_cpu.sv.
//
// This test program deliberately contains no branches or jumps: it
// predates Phase 6's forwarding/stall/flush additions to this same
// module (which does now handle them -- see
// sim/programs/pipeline_tests/ and docs/pipeline.md for the tests that
// exercise that), and is kept exactly as originally written as a
// standing regression check that Phase 6's changes never altered
// hazard-free straight-line execution. dbg_stall/dbg_flush (added in
// Phase 6) are connected below for completeness but not asserted on by
// this test, since a program with no hazards never drives either.

`timescale 1ns/1ps

module tb_pipeline;

  logic clk;
  logic rst_n = 0;

  logic [31:0] dbg_if_pc, dbg_if_instr;
  logic [31:0] dbg_id_pc, dbg_id_instr;
  logic [31:0] dbg_ex_pc, dbg_ex_instr;
  logic [31:0] dbg_mem_instr;
  logic [31:0] dbg_wb_instr;
  logic        dbg_reg_write;
  logic [4:0]  dbg_rd_addr;
  logic [31:0] dbg_rd_data;
  logic        dbg_illegal;
  logic        dbg_stall, dbg_flush;

  // Phase 8: riscv_cpu_pipeline no longer instantiates its own data
  // memory -- it's a bus master (dbus_*) so riscv_soc.sv can route it
  // to RAM/UART/GPIO instead. This testbench isn't an SoC, so it just
  // wires a plain dmem straight to that bus, functionally identical to
  // what the CPU module did internally before Phase 8.
  logic [31:0] dbus_addr, dbus_wdata, dbus_rdata;
  logic        dbus_mem_read, dbus_mem_write;

  riscv_cpu_pipeline #(
    .IMEM_INIT_FILE("sim/programs/pipeline_straightline.hex")
  ) dut (
    .clk(clk), .rst_n(rst_n),
    .dbus_addr(dbus_addr), .dbus_wdata(dbus_wdata),
    .dbus_mem_read(dbus_mem_read), .dbus_mem_write(dbus_mem_write),
    .dbus_rdata(dbus_rdata),
    .dbg_if_pc(dbg_if_pc), .dbg_if_instr(dbg_if_instr),
    .dbg_id_pc(dbg_id_pc), .dbg_id_instr(dbg_id_instr),
    .dbg_ex_pc(dbg_ex_pc), .dbg_ex_instr(dbg_ex_instr),
    .dbg_mem_instr(dbg_mem_instr),
    .dbg_wb_instr(dbg_wb_instr),
    .dbg_reg_write(dbg_reg_write), .dbg_rd_addr(dbg_rd_addr), .dbg_rd_data(dbg_rd_data),
    .dbg_illegal(dbg_illegal), .dbg_stall(dbg_stall), .dbg_flush(dbg_flush)
  );

  dmem dmem_inst (
    .clk(clk), .addr(dbus_addr), .wdata(dbus_wdata),
    .mem_read(dbus_mem_read), .mem_write(dbus_mem_write), .rdata(dbus_rdata)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  int errors = 0;

  // This program has no data hazards closer than 3 instructions and no
  // branches/jumps at all (see its header comment), so hazard_unit
  // should never assert either signal here -- a standing regression
  // check that Phase 6's additions didn't change hazard-free behavior.
  logic saw_stall = 1'b0, saw_flush = 1'b0;
  always_ff @(posedge clk) begin
    if (dbg_stall) saw_stall <= 1'b1;
    if (dbg_flush) saw_flush <= 1'b1;
  end

  task automatic check(string name, logic [31:0] actual, logic [31:0] expected);
    if (actual !== expected) begin
      $display("  [FAIL] %-28s expected=0x%08x actual=0x%08x", name, expected, actual);
      errors++;
    end else begin
      $display("  [PASS] %-28s = 0x%08x", name, actual);
    end
  endtask

  initial begin
    $display("=== Phase 5 pipeline testbench ===");

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

    // Per-cycle 5-stage trace: demonstrates that five different
    // instructions genuinely occupy five different stages in the same
    // cycle (real pipelined concurrency), not just that the final
    // answer comes out right.
    fork
      begin
        forever begin
          @(posedge clk);
          #1;
          $display("  t=%0t  IF=0x%08x  ID=0x%08x  EX=0x%08x  MEM=0x%08x  WB=0x%08x%s",
                    $time, dbg_if_instr, dbg_id_instr, dbg_ex_instr, dbg_mem_instr, dbg_wb_instr,
                    (dbg_reg_write && dbg_rd_addr != 0) ?
                      $sformatf("   x%0d <= 0x%08x", dbg_rd_addr, dbg_rd_data) : "");
        end
      end
    join_none

    // 44 real instructions; the last one's WB completes at cycle
    // (43+1)+4 = 48 after reset deasserts (WB is the 5th stage). 60
    // cycles leaves comfortable margin without running so long that it
    // matters that the program has no halt loop (see file header).
    repeat (60) @(posedge clk);
    #1;

    $display("");
    $display("=== Final architectural state check ===");
    check("x1  (12)",              dut.regfile_inst.regs[1],  32'd12);
    check("x2  (10)",              dut.regfile_inst.regs[2],  32'd10);
    check("x3  (12+10)",           dut.regfile_inst.regs[3],  32'd22);
    check("x4  (5)",               dut.regfile_inst.regs[4],  32'd5);
    check("x5  (3)",               dut.regfile_inst.regs[5],  32'd3);
    check("x6  (5-3)",             dut.regfile_inst.regs[6],  32'd2);
    check("x7  (12&0xF)",          dut.regfile_inst.regs[7],  32'd12);
    check("x8  (10|1)",            dut.regfile_inst.regs[8],  32'd11);
    check("x9  (12^0xFF)",         dut.regfile_inst.regs[9],  32'h000000F3);
    check("x10 (10<<2)",           dut.regfile_inst.regs[10], 32'd40);
    check("x11 (40>>1)",           dut.regfile_inst.regs[11], 32'd20);
    check("x12 (-16)",             dut.regfile_inst.regs[12], -32'd16);
    check("x13 (-16>>>2)",         dut.regfile_inst.regs[13], -32'd4);
    check("x14 (lui 0x12345)",     dut.regfile_inst.regs[14], 32'h12345000);
    check("x15 (auipc pc+0)",      dut.regfile_inst.regs[15], 32'h00000074);
    check("x16 (100)",             dut.regfile_inst.regs[16], 32'd100);
    check("x17 (lw mem[0])",       dut.regfile_inst.regs[17], 32'd100);
    check("x18 (copy of x17)",     dut.regfile_inst.regs[18], 32'd100);
    check("x19 (x0 hardwire)",     dut.regfile_inst.regs[19], 32'd0);
    check("no stall ever asserted", {31'b0, saw_stall}, 32'b0);
    check("no flush ever asserted", {31'b0, saw_flush}, 32'b0);

    $display("");
    if (errors == 0) begin
      $display("RESULT: ALL CHECKS PASSED");
    end else begin
      $display("RESULT: %0d CHECK(S) FAILED", errors);
    end
    $finish;
  end

endmodule
