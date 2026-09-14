// tb_bench_cpu_correctness.sv
//
// Phase 11: correctness check for the three CPU-only benchmark kernels
// (cpu_vecadd_bench.s, cpu_dot_bench.s, cpu_matmul_bench.s), run at
// their ACTUAL benchmark sizes (N=16 for vecadd/dot, 4x4 for matmul --
// not a separately-written "small" variant) against expected values
// computed in Python (see this file's own header derivation below),
// not hand arithmetic -- this project's own history (CHANGELOG.md,
// repeatedly) is that hand-derived expected values for anything beyond
// the most trivial case tend to be wrong, so Python computed them
// here instead of a human doing it by hand.
//
// Reference computation (reproduce with:
// `python3 -c "N=16; A=[i+1 for i in range(N)]; B=[i+2 for i in
// range(N)]; print([A[i]+B[i] for i in range(N)]);
// print(sum(A[i]*B[i] for i in range(N)))"` for vecadd/dot, and the
// equivalent nested-loop reference for matmul -- see
// cpu_matmul_bench.s's header comment for A/B's definition):
//   vecadd (N=16): out = [3,5,7,...,33]  (i.e. out[i] = 2i+3)
//   dot    (N=16): 1632
//   matmul (4x4):  C = [40,50,60,70, 54,68,82,96, 68,86,104,122,
//                        82,104,126,148]  (row-major)
//
// Three separate riscv_soc instances run in parallel (same pattern as
// Phase 7's tb_perf_counters.sv), each loaded with one benchmark
// program, checked once each has had time to reach its GPIO_OUT
// sentinel write (see tb_benchmark_soc.sv's header comment for why
// that convention exists) -- generous fixed cycle budgets are used
// here (this is a correctness check, not itself a benchmark, so
// measurement precision doesn't matter).

`timescale 1ns/1ps

module tb_bench_cpu_correctness;

  logic clk;
  logic rst_n = 0;

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  int errors = 0;

  task automatic check(string name, logic [31:0] actual, logic [31:0] expected);
    if (actual !== expected) begin
      $display("  [FAIL] %-28s expected=%0d actual=%0d", name, expected, actual);
      errors++;
    end else begin
      $display("  [PASS] %-28s = %0d", name, actual);
    end
  endtask

  // -------------------------------------------------------------------
  // VECADD instance
  // -------------------------------------------------------------------
  logic [31:0] va_gpio_out;
  riscv_soc #(
    .IMEM_INIT_FILE("sim/programs/benchmarks/cpu_vecadd_bench.hex"),
    .RAM_DEPTH_WORDS(4096) // see this file's header note on the
                            // 0x1000/0x2000/0x3000 addressing scheme
  ) dut_vecadd (
    .clk(clk), .rst_n(rst_n), .gpio_in(32'b0), .gpio_out(va_gpio_out),
    .uart_tx_valid(), .uart_tx_byte(),
    .dbg_if_pc(), .dbg_if_instr(), .dbg_id_pc(), .dbg_id_instr(),
    .dbg_ex_pc(), .dbg_ex_instr(), .dbg_mem_instr(), .dbg_wb_instr(),
    .dbg_reg_write(), .dbg_rd_addr(), .dbg_rd_data(),
    .dbg_illegal(), .dbg_stall(), .dbg_flush(),
    .perf_cycle_count(), .perf_instr_retired_count(), .perf_stall_count(),
    .perf_branch_count(), .perf_branch_taken_count(), .perf_load_use_stall_count(),
    .perf_forwarding_event_count(), .perf_flush_count()
  );

  // -------------------------------------------------------------------
  // DOT instance
  // -------------------------------------------------------------------
  logic [31:0] dot_gpio_out;
  riscv_soc #(
    .IMEM_INIT_FILE("sim/programs/benchmarks/cpu_dot_bench.hex"),
    .RAM_DEPTH_WORDS(4096)
  ) dut_dot (
    .clk(clk), .rst_n(rst_n), .gpio_in(32'b0), .gpio_out(dot_gpio_out),
    .uart_tx_valid(), .uart_tx_byte(),
    .dbg_if_pc(), .dbg_if_instr(), .dbg_id_pc(), .dbg_id_instr(),
    .dbg_ex_pc(), .dbg_ex_instr(), .dbg_mem_instr(), .dbg_wb_instr(),
    .dbg_reg_write(), .dbg_rd_addr(), .dbg_rd_data(),
    .dbg_illegal(), .dbg_stall(), .dbg_flush(),
    .perf_cycle_count(), .perf_instr_retired_count(), .perf_stall_count(),
    .perf_branch_count(), .perf_branch_taken_count(), .perf_load_use_stall_count(),
    .perf_forwarding_event_count(), .perf_flush_count()
  );

  // -------------------------------------------------------------------
  // MATMUL instance
  // -------------------------------------------------------------------
  logic [31:0] mm_gpio_out;
  riscv_soc #(
    .IMEM_INIT_FILE("sim/programs/benchmarks/cpu_matmul_bench.hex"),
    .RAM_DEPTH_WORDS(4096)
  ) dut_matmul (
    .clk(clk), .rst_n(rst_n), .gpio_in(32'b0), .gpio_out(mm_gpio_out),
    .uart_tx_valid(), .uart_tx_byte(),
    .dbg_if_pc(), .dbg_if_instr(), .dbg_id_pc(), .dbg_id_instr(),
    .dbg_ex_pc(), .dbg_ex_instr(), .dbg_mem_instr(), .dbg_wb_instr(),
    .dbg_reg_write(), .dbg_rd_addr(), .dbg_rd_data(),
    .dbg_illegal(), .dbg_stall(), .dbg_flush(),
    .perf_cycle_count(), .perf_instr_retired_count(), .perf_stall_count(),
    .perf_branch_count(), .perf_branch_taken_count(), .perf_load_use_stall_count(),
    .perf_forwarding_event_count(), .perf_flush_count()
  );

  localparam int MAX_CYCLES = 20000;

  initial begin
    $display("=== Phase 11 CPU-only benchmark kernel correctness check ===");

    rst_n = 0;
    repeat (2) @(posedge clk);
    #1;
    rst_n = 1;

    repeat (MAX_CYCLES) @(posedge clk);
    #1;

    $display("");
    $display("--- vecadd (N=16): out[i] = 2i+3 ---");
    if (va_gpio_out !== 32'hDEADBEEF) begin
      $display("  [FAIL] sentinel not observed (gpio_out=0x%08x)", va_gpio_out);
      errors++;
    end
    for (int i = 0; i < 16; i++) begin
      check($sformatf("out[%0d]", i), dut_vecadd.ram_inst.mem[32'h0C00 + 32'(i)], 32'(2*i + 3));
    end
    // 0x3000 (VECOUT-style convention reused here purely as a layout
    // choice for this program, not accelerator MMIO) as a word index
    // into dmem's `mem` array: 0x3000 >> 2 = 0xC00.

    $display("");
    $display("--- dot (N=16): sum (i+1)(i+2) ---");
    if (dot_gpio_out !== 32'hDEADBEEF) begin
      $display("  [FAIL] sentinel not observed (gpio_out=0x%08x)", dot_gpio_out);
      errors++;
    end
    check("dot result (x20)", dut_dot.cpu_inst.regfile_inst.regs[20], 32'd1632);

    $display("");
    $display("--- matmul (4x4) ---");
    if (mm_gpio_out !== 32'hDEADBEEF) begin
      $display("  [FAIL] sentinel not observed (gpio_out=0x%08x)", mm_gpio_out);
      errors++;
    end
    begin
      // Icarus Verilog doesn't support an explicit `automatic`
      // lifetime override in this context (see
      // sim/testbenches/tb_accelerator.sv's header comment on the
      // same limitation) -- individual element assignment instead.
      int expected[0:15];
      expected[0]=40;  expected[1]=50;  expected[2]=60;  expected[3]=70;
      expected[4]=54;  expected[5]=68;  expected[6]=82;  expected[7]=96;
      expected[8]=68;  expected[9]=86;  expected[10]=104; expected[11]=122;
      expected[12]=82; expected[13]=104; expected[14]=126; expected[15]=148;
      for (int i = 0; i < 16; i++) begin
        check($sformatf("C[%0d]", i), dut_matmul.ram_inst.mem[32'h0C00 + 32'(i)], expected[i][31:0]);
      end
    end

    $display("");
    if (errors == 0) begin
      $display("RESULT: ALL CHECKS PASSED");
    end else begin
      $display("RESULT: %0d CHECK(S) FAILED", errors);
    end
    $finish;
  end

endmodule
