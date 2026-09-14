// tb_benchmark.sv
//
// Phase 7/11 generic benchmark harness: compiled once, run against any
// program via +HEXFILE=... +CYCLES=<n> +NAME=..., printing one
// machine-parseable line of every performance counter
// (rtl/cpu/perf_counters.sv) at the given cycle count, for
// scripts/run_benchmarks.py to collect into a report. Unlike
// sim/testbenches/tb_perf_counters.sv (which asserts exact expected
// values for one specific program as a directed test), this testbench
// makes no correctness assertions of its own -- it is a measurement
// tool, not a test. Correctness for every benchmark program here is
// established once by a directed test elsewhere before it's trusted as
// a benchmark (see docs/pipeline.md's Phase 7 section).

`timescale 1ns/1ps

module tb_benchmark;

  logic clk;
  logic rst_n = 0;

  logic [31:0] dbg_if_pc, dbg_if_instr, dbg_id_pc, dbg_id_instr, dbg_ex_pc, dbg_ex_instr;
  logic [31:0] dbg_mem_instr, dbg_wb_instr, dbg_rd_data;
  logic        dbg_reg_write, dbg_illegal, dbg_stall, dbg_flush;
  logic [4:0]  dbg_rd_addr;
  logic [31:0] perf_cycle_count, perf_instr_retired_count, perf_stall_count;
  logic [31:0] perf_branch_count, perf_branch_taken_count, perf_load_use_stall_count;
  logic [31:0] perf_forwarding_event_count, perf_flush_count;

  riscv_cpu_pipeline dut (
    .clk(clk), .rst_n(rst_n),
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

  initial begin
    string name;
    int cycles;
    if (!$value$plusargs("NAME=%s", name)) name = "(unnamed)";
    if (!$value$plusargs("CYCLES=%d", cycles)) cycles = 100;

    rst_n = 0;
    repeat (2) @(posedge clk);
    #1; // see sim/testbenches/tb_perf_counters.sv for why this delay matters
    rst_n = 1;

    repeat (cycles) @(posedge clk);
    #1;

    $display("BENCHMARK_RESULT: name=%s cycles=%0d retired=%0d stall=%0d branch=%0d branch_taken=%0d load_use_stall=%0d forwarding=%0d flush=%0d",
              name, perf_cycle_count, perf_instr_retired_count, perf_stall_count,
              perf_branch_count, perf_branch_taken_count, perf_load_use_stall_count,
              perf_forwarding_event_count, perf_flush_count);
    $finish;
  end

endmodule
