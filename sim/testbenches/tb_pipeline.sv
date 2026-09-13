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
// This test program deliberately contains no branches or jumps (see its
// header comment and docs/pipeline.md): Phase 5 does not yet flush
// wrong-path instructions after a taken redirect, so the testbench runs
// for a precisely bounded cycle count instead of relying on a `j halt`
// parking loop.

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

  riscv_cpu_pipeline #(
    .IMEM_INIT_FILE("sim/programs/pipeline_straightline.hex")
  ) dut (
    .clk(clk), .rst_n(rst_n),
    .dbg_if_pc(dbg_if_pc), .dbg_if_instr(dbg_if_instr),
    .dbg_id_pc(dbg_id_pc), .dbg_id_instr(dbg_id_instr),
    .dbg_ex_pc(dbg_ex_pc), .dbg_ex_instr(dbg_ex_instr),
    .dbg_mem_instr(dbg_mem_instr),
    .dbg_wb_instr(dbg_wb_instr),
    .dbg_reg_write(dbg_reg_write), .dbg_rd_addr(dbg_rd_addr), .dbg_rd_data(dbg_rd_data),
    .dbg_illegal(dbg_illegal)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  int errors = 0;

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

    $display("");
    if (errors == 0) begin
      $display("RESULT: ALL CHECKS PASSED");
    end else begin
      $display("RESULT: %0d CHECK(S) FAILED", errors);
    end
    $finish;
  end

endmodule
