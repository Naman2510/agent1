// tb_mul.sv
//
// End-to-end check of the optional RV32M MUL instruction on the
// pipelined CPU inside the full SoC: the same program image
// (sim/programs/mul/mul_test.s) runs on two riscv_soc instances, one
// built with ENABLE_MUL=1 and one with the default ENABLE_MUL=0.
//
//   ENABLE_MUL=1: every product correct, including through EX->EX and
//                 MEM->EX forwarding, a load-use stall, rd=x0, and a
//                 branch on a mul result; `illegal` never raised.
//   ENABLE_MUL=0: every mul raises `illegal` and writes nothing -- each
//                 destination keeps its 0x5A5A sentinel or its reset
//                 value of 0, and the branch therefore takes the
//                 "mul didn't happen" path. This is the RV32I core every
//                 phase through 17 measured; before control_unit.sv
//                 validated funct7, this same image would instead have
//                 executed each mul as an ADD.
//
// Expected products computed in Python: (a * b) & 0xFFFFFFFF.

`timescale 1ns/1ps

module tb_mul;

  logic clk;
  logic rst_n = 0;

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  int errors = 0;

  task automatic check(string name, logic [31:0] actual, logic [31:0] expected);
    if (actual !== expected) begin
      $display("  [FAIL] %-30s expected=0x%08h actual=0x%08h", name, expected, actual);
      errors++;
    end else begin
      $display("  [PASS] %-30s = 0x%08h", name, actual);
    end
  endtask

  `define SOC_PORTS(gpio_out_sig, illegal_sig) \
    .clk(clk), .rst_n(rst_n), .gpio_in(32'b0), .gpio_out(gpio_out_sig), \
    .uart_tx_valid(), .uart_tx_byte(), \
    .dbg_if_pc(), .dbg_if_instr(), .dbg_id_pc(), .dbg_id_instr(), \
    .dbg_ex_pc(), .dbg_ex_instr(), .dbg_mem_instr(), .dbg_wb_instr(), \
    .dbg_reg_write(), .dbg_rd_addr(), .dbg_rd_data(), \
    .dbg_illegal(illegal_sig), .dbg_stall(), .dbg_flush(), \
    .perf_cycle_count(), .perf_instr_retired_count(), .perf_stall_count(), \
    .perf_branch_count(), .perf_branch_taken_count(), .perf_load_use_stall_count(), \
    .perf_forwarding_event_count(), .perf_flush_count()

  logic [31:0] gpio_m, gpio_r;
  logic        ill_m, ill_r;

  riscv_soc #(.IMEM_INIT_FILE("sim/programs/mul/mul_test.hex"), .ENABLE_MUL(1'b1))
    dut_mul (`SOC_PORTS(gpio_m, ill_m));
  riscv_soc #(.IMEM_INIT_FILE("sim/programs/mul/mul_test.hex"))
    dut_rv32i (`SOC_PORTS(gpio_r, ill_r));

  // Count real illegal instructions that reach EX. Two kinds of noise
  // have to be excluded, both pre-existing pipeline behavior:
  //   - dbg_illegal is an ID-stage signal, so it also fires on
  //     wrong-path instructions that are then flushed -- counting at EX
  //     (illegal_ex) drops those, since ID/EX's flush clears `illegal`;
  //   - pipeline bubbles (reset fill, flushes, load-use stalls) are the
  //     all-zero word, opcode 0000000, which the decoder also flags as
  //     illegal -- see tb_pipeline_directed_test.sv's note on exactly
  //     this. A bubble is precisely instr == 0, and every instruction
  //     this test needs to classify (the muls) is non-zero, so bubbles
  //     are excluded by their instruction word.
  int illegal_m = 0, illegal_r = 0;
  logic count_en = 1'b0;  // set once reset is released (a separate flag
                          // rather than rst_n itself, which Verilator
                          // rejects being both an async reset in the RTL
                          // and a synchronous enable here)
  always @(posedge clk) if (count_en) begin
    if (dut_mul.cpu_inst.illegal_ex   && dut_mul.dbg_ex_instr   != 32'b0) illegal_m <= illegal_m + 1;
    if (dut_rv32i.cpu_inst.illegal_ex && dut_rv32i.dbg_ex_instr != 32'b0) illegal_r <= illegal_r + 1;
  end

  `define RM(n) dut_mul.cpu_inst.regfile_inst.regs[n]
  `define RR(n) dut_rv32i.cpu_inst.regfile_inst.regs[n]

  initial begin
    $display("=== RV32M MUL end-to-end check (pipelined CPU in riscv_soc) ===");
    rst_n = 0;
    repeat (2) @(posedge clk);
    #1;
    rst_n = 1;
    count_en = 1;
    repeat (2000) @(posedge clk);
    #1;

    $display("");
    $display("--- ENABLE_MUL=1 ---");
    check("sentinel",                    gpio_m,  32'hDEADBEEF);
    check("x10 = 6*7",                   `RM(10), 32'd42);
    check("x11 = -3*5",                  `RM(11), 32'hFFFFFFF1);
    check("x12 = -4*-6",                 `RM(12), 32'd24);
    check("x13 = low32(0x12345678*0x9ABCDEF0)", `RM(13), 32'h242D2080);
    check("x15 = x14*x14 (EX->EX fwd)",  `RM(15), 32'd1764);
    check("x17 = x16*6 (MEM->EX fwd)",   `RM(17), 32'd294);
    check("x21 = 11*11 (load-use)",      `RM(21), 32'd121);
    check("x25 = x0 + 6 after mul x0",   `RM(25), 32'd6);
    check("x24 = 1 (branch on mul)",     `RM(24), 32'd1);
    check("illegal instrs reaching EX",  illegal_m, 32'd0);

    $display("");
    $display("--- ENABLE_MUL=0 (RV32I core): every mul illegal, no writes ---");
    check("sentinel",                    gpio_r,  32'hDEADBEEF);
    check("x10 untouched",               `RR(10), 32'h5A5A);
    check("x11 untouched",               `RR(11), 32'h5A5A);
    check("x12 untouched",               `RR(12), 32'h5A5A);
    check("x13 untouched",               `RR(13), 32'h5A5A);
    check("x14 untouched",               `RR(14), 32'h5A5A);
    check("x15 untouched",               `RR(15), 32'd0);
    check("x16 untouched",               `RR(16), 32'd0);
    check("x17 untouched",               `RR(17), 32'd0);
    check("x21 untouched",               `RR(21), 32'd0);
    check("x22 untouched",               `RR(22), 32'd0);
    check("x24 = 0x5A5A (branch saw no mul)", `RR(24), 32'h5A5A);
    check("x25 = x0 + 6",                `RR(25), 32'd6);
    check("illegal instrs reaching EX (= # of muls)", illegal_r, 32'd11);

    $display("");
    if (errors == 0) $display("RESULT: ALL CHECKS PASSED");
    else             $display("RESULT: %0d CHECK(S) FAILED", errors);
    $finish;
  end

endmodule
