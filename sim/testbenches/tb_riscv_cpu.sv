// tb_riscv_cpu.sv
//
// Phase 2 testbench for the single-cycle RV32I CPU. Loads
// sim/programs/phase2_bringup.hex into instruction memory, runs the CPU
// for a fixed number of cycles (comfortably more than the program needs
// to reach its final infinite loop), traces every retired instruction
// (fetch/decode-visible PC+instruction word, and any register writeback),
// and then checks the final architectural register state against the
// values hand-computed in sim/programs/phase2_bringup.s.
//
// Run with: make sim_cpu   (see Makefile / scripts/run_sim.sh)

`timescale 1ns/1ps

module tb_riscv_cpu;

  logic clk;
  logic rst_n = 0;

  logic [31:0] dbg_pc, dbg_instr, dbg_rd_data, dbg_alu_result;
  logic        dbg_reg_write, dbg_illegal;
  logic [4:0]  dbg_rd_addr;

  riscv_cpu #(
    .IMEM_INIT_FILE("sim/programs/phase2_bringup.hex")
  ) dut (
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

  // 100 MHz-equivalent simulation clock (period is arbitrary in
  // simulation time -- there is no real timing target until synthesis,
  // Phase 12). Generated from an initial/forever block rather than a bare
  // `always #5 clk = ~clk;` so lint tools don't mistake a free-running
  // clock generator for sequential logic driven by itself.
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
    $display("=== Phase 2 CPU bring-up testbench ===");

    // Reset for two clock edges.
    rst_n = 0;
    repeat (2) @(posedge clk);
    rst_n = 1;

    // Trace every cycle: PC, fetched instruction, and any register
    // writeback -- the Phase 2 visibility requirement (fetch, decode,
    // register values, ALU operation, PC progression).
    fork
      begin
        forever begin
          @(posedge clk);
          #1; // let combinational logic settle for display
          if (dbg_illegal)
            $display("  t=%0t PC=0x%08x INSTR=0x%08x  *** ILLEGAL OPCODE ***",
                      $time, dbg_pc, dbg_instr);
          else if (dbg_reg_write && dbg_rd_addr != 0)
            $display("  t=%0t PC=0x%08x INSTR=0x%08x  ALU=0x%08x  x%0d <= 0x%08x",
                      $time, dbg_pc, dbg_instr, dbg_alu_result, dbg_rd_addr, dbg_rd_data);
          else
            $display("  t=%0t PC=0x%08x INSTR=0x%08x", $time, dbg_pc, dbg_instr);
        end
      end
    join_none

    // 70 cycles is comfortably more than the ~25 instructions in
    // phase2_bringup.s need before the program parks in its final
    // infinite loop (see sim/programs/phase2_bringup.s comments for the
    // expected control flow).
    repeat (70) @(posedge clk);
    #1;

    $display("");
    $display("=== Final architectural state check ===");
    // Hierarchical reference into the register file for verification --
    // simulation-only visibility, not part of any synthesizable module.
    check("x1  (10)",             dut.regfile_inst.regs[1],  32'd10);
    check("x2  (20)",             dut.regfile_inst.regs[2],  32'd20);
    check("x3  (10+20)",          dut.regfile_inst.regs[3],  32'd30);
    check("x4  (30-10)",          dut.regfile_inst.regs[4],  32'd20);
    check("x5  (30&20)",          dut.regfile_inst.regs[5],  32'd20);
    check("x6  (10|20)",          dut.regfile_inst.regs[6],  32'd30);
    check("x7  (10^20)",          dut.regfile_inst.regs[7],  32'd30);
    check("x8  (slt 10<20)",      dut.regfile_inst.regs[8],  32'd1);
    check("x9  (addi x0,-1)",     dut.regfile_inst.regs[9],  32'hFFFFFFFF);
    check("x11 (10<<2)",          dut.regfile_inst.regs[11], 32'd40);
    check("x12 (40>>1)",          dut.regfile_inst.regs[12], 32'd20);
    check("x13 (lw mem[0])",      dut.regfile_inst.regs[13], 32'd30);
    check("x18 (x0 write discarded, x0+x0=0)", dut.regfile_inst.regs[18], 32'd0);
    check("x15 (subroutine)",     dut.regfile_inst.regs[15], 32'd42);
    check("x16 (lui 0x12345)",    dut.regfile_inst.regs[16], 32'h12345000);
    check("x17 (auipc pc+0)",     dut.regfile_inst.regs[17], 32'h00000030);
    check("x10 (final result)",   dut.regfile_inst.regs[10], 32'd40);
    check("PC parked at halt",    dbg_pc,                    32'h00000060);
    check("no illegal opcode",    {31'b0, dbg_illegal},      32'b0);

    $display("");
    if (errors == 0) begin
      $display("RESULT: ALL CHECKS PASSED");
    end else begin
      $display("RESULT: %0d CHECK(S) FAILED", errors);
    end
    $finish;
  end

endmodule
