// tb_scheduler_v2_heldout_correctness.sv
//
// Post-Phase-17 improvement: correctness check for the 4 round-2
// held-out workloads (vecadd/dot N=6, N=12 -- see
// scheduler/benchmarks/gen_scheduler_programs.py's
// HELDOUT_V2_VECADD_DOT_SIZES). These exist so
// scheduler/training/train_scheduler_v2.py's retrained model (fit on
// ALL 20 of Phase 13/14's original workloads, once their old held-out
// set stops being held-out) can still be scored against genuinely
// unseen data -- same "verify correctness before trusting timing"
// discipline as every prior phase.
//
// Expected values computed in Python, not by hand:
//
//   python3 -c "
//   def vecadd(n): return [2*i+3 for i in range(n)]
//   def dot(n): return sum((i+1)*(i+2) for i in range(n))
//   for n in [6, 12]:
//       print(n, vecadd(n)[0], vecadd(n)[-1], dot(n))
//   "

`timescale 1ns/1ps

module tb_scheduler_v2_heldout_correctness;

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

  task automatic check_sentinel(string name, logic [31:0] gpio_out);
    check({name, " sentinel"}, gpio_out, 32'hDEADBEEF);
  endtask

  `define SOC_PORTS(gpio_out_sig) \
    .clk(clk), .rst_n(rst_n), .gpio_in(32'b0), .gpio_out(gpio_out_sig), \
    .uart_tx_valid(), .uart_tx_byte(), \
    .dbg_if_pc(), .dbg_if_instr(), .dbg_id_pc(), .dbg_id_instr(), \
    .dbg_ex_pc(), .dbg_ex_instr(), .dbg_mem_instr(), .dbg_wb_instr(), \
    .dbg_reg_write(), .dbg_rd_addr(), .dbg_rd_data(), \
    .dbg_illegal(), .dbg_stall(), .dbg_flush(), \
    .perf_cycle_count(), .perf_instr_retired_count(), .perf_stall_count(), \
    .perf_branch_count(), .perf_branch_taken_count(), .perf_load_use_stall_count(), \
    .perf_forwarding_event_count(), .perf_flush_count()

  logic [31:0] cpu_va6_gpio, cpu_va12_gpio, cpu_dot6_gpio, cpu_dot12_gpio;
  logic [31:0] acc_va6_gpio, acc_va12_gpio, acc_dot6_gpio, acc_dot12_gpio;

  riscv_soc #(.IMEM_INIT_FILE("sim/programs/scheduler/cpu_vecadd_n6.hex"), .RAM_DEPTH_WORDS(4096))
    dut_cpu_va6 (`SOC_PORTS(cpu_va6_gpio));
  riscv_soc #(.IMEM_INIT_FILE("sim/programs/scheduler/cpu_vecadd_n12.hex"), .RAM_DEPTH_WORDS(4096))
    dut_cpu_va12 (`SOC_PORTS(cpu_va12_gpio));
  riscv_soc #(.IMEM_INIT_FILE("sim/programs/scheduler/cpu_dot_n6.hex"), .RAM_DEPTH_WORDS(4096))
    dut_cpu_dot6 (`SOC_PORTS(cpu_dot6_gpio));
  riscv_soc #(.IMEM_INIT_FILE("sim/programs/scheduler/cpu_dot_n12.hex"), .RAM_DEPTH_WORDS(4096))
    dut_cpu_dot12 (`SOC_PORTS(cpu_dot12_gpio));

  riscv_soc #(.IMEM_INIT_FILE("sim/programs/scheduler/accel_vecadd_n6.hex"))
    dut_acc_va6 (`SOC_PORTS(acc_va6_gpio));
  riscv_soc #(.IMEM_INIT_FILE("sim/programs/scheduler/accel_vecadd_n12.hex"))
    dut_acc_va12 (`SOC_PORTS(acc_va12_gpio));
  riscv_soc #(.IMEM_INIT_FILE("sim/programs/scheduler/accel_dot_n6.hex"))
    dut_acc_dot6 (`SOC_PORTS(acc_dot6_gpio));
  riscv_soc #(.IMEM_INIT_FILE("sim/programs/scheduler/accel_dot_n12.hex"))
    dut_acc_dot12 (`SOC_PORTS(acc_dot12_gpio));

  localparam int MAX_CYCLES = 10000;

  initial begin
    $display("=== Round-2 held-out scheduler-workload correctness check ===");

    rst_n = 0;
    repeat (2) @(posedge clk);
    #1;
    rst_n = 1;

    repeat (MAX_CYCLES) @(posedge clk);
    #1;

    $display("");
    $display("--- cpu_vecadd N=6, N=12 ---");
    check_sentinel("cpu_vecadd_n6", cpu_va6_gpio);
    check("va6 out[0]", dut_cpu_va6.ram_inst.mem[16'h0C00+0], 32'd3);
    check("va6 out[5]", dut_cpu_va6.ram_inst.mem[16'h0C00+5], 32'd13);
    check_sentinel("cpu_vecadd_n12", cpu_va12_gpio);
    check("va12 out[0]",  dut_cpu_va12.ram_inst.mem[16'h0C00+0],  32'd3);
    check("va12 out[11]", dut_cpu_va12.ram_inst.mem[16'h0C00+11], 32'd25);

    $display("");
    $display("--- cpu_dot N=6, N=12 ---");
    check_sentinel("cpu_dot_n6", cpu_dot6_gpio);
    check("dot6 (x20)", dut_cpu_dot6.cpu_inst.regfile_inst.regs[20], 32'd112);
    check_sentinel("cpu_dot_n12", cpu_dot12_gpio);
    check("dot12 (x20)", dut_cpu_dot12.cpu_inst.regfile_inst.regs[20], 32'd728);

    $display("");
    $display("--- accel_vecadd N=6, N=12 ---");
    check_sentinel("accel_vecadd_n6", acc_va6_gpio);
    check("va6 vecout[0]", dut_acc_va6.accel_inst.vecout[0], 32'd3);
    check("va6 vecout[5]", dut_acc_va6.accel_inst.vecout[5], 32'd13);
    check_sentinel("accel_vecadd_n12", acc_va12_gpio);
    check("va12 vecout[0]",  dut_acc_va12.accel_inst.vecout[0],  32'd3);
    check("va12 vecout[11]", dut_acc_va12.accel_inst.vecout[11], 32'd25);

    $display("");
    $display("--- accel_dot N=6, N=12 ---");
    check_sentinel("accel_dot_n6", acc_dot6_gpio);
    check("dot6 result_r", dut_acc_dot6.accel_inst.result_r, 32'd112);
    check_sentinel("accel_dot_n12", acc_dot12_gpio);
    check("dot12 result_r", dut_acc_dot12.accel_inst.result_r, 32'd728);

    $display("");
    if (errors == 0) begin
      $display("RESULT: ALL CHECKS PASSED");
    end else begin
      $display("RESULT: %0d CHECK(S) FAILED", errors);
    end
    $finish;
  end

endmodule
