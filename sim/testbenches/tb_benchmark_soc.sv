// tb_benchmark_soc.sv
//
// Phase 11 generic benchmark harness for the full SoC (riscv_soc):
// compiled once, run against any program via +HEXFILE=... +NAME=...,
// watching GPIO_OUT for a fixed sentinel value the program writes the
// instant its measured work is done (see each benchmark program's own
// header comment for why), then printing the performance counters
// AT THAT EXACT CYCLE.
//
// This is deliberately NOT the same technique as
// sim/testbenches/tb_benchmark.sv (Phase 7), which takes a runtime
// +CYCLES=... and snapshots at a cycle chosen by the caller: Phase
// 7's benchmarks were short, hand-verified loops where a human could
// determine the exact completion cycle once and hardcode it. Phase
// 11 compares six different programs (three operations, CPU-only vs.
// accelerator-driven) of different lengths, and mis-hardcoding even
// one completion cycle would silently make the comparison unfair
// (measuring one program's real completion against another's
// idle-loop padding). Detecting completion automatically via a
// sentinel write removes that entire class of human error -- the
// same reasoning that has already caught real bugs earlier in this
// project (see CHANGELOG.md's repeated "trust the simulator, not
// hand math" lesson).
//
// Like tb_benchmark.sv, this testbench makes NO correctness assertion
// of its own -- it is a measurement tool. Correctness for the
// CPU-only kernels is established by sim/testbenches/tb_bench_cpu_correctness.sv;
// correctness for the accelerator-driven kernels was already
// established in Phase 9/10 (sim/testbenches/tb_accelerator.sv,
// tb_soc_accel.sv, tb_soc_accel_custom.sv) -- these benchmark programs
// reuse that same, already-verified code path at a different problem
// size, per docs/benchmarking.md.

`timescale 1ns/1ps

module tb_benchmark_soc;

  localparam logic [31:0] SENTINEL = 32'hDEADBEEF;
  localparam int MAX_CYCLES = 20000;

  logic clk;
  logic rst_n = 0;

  logic [31:0] gpio_in = 32'b0;
  logic [31:0] gpio_out;
  logic         uart_tx_valid;
  logic [7:0]   uart_tx_byte;

  logic [31:0] dbg_if_pc, dbg_if_instr, dbg_id_pc, dbg_id_instr, dbg_ex_pc, dbg_ex_instr;
  logic [31:0] dbg_mem_instr, dbg_wb_instr, dbg_rd_data;
  logic         dbg_reg_write, dbg_illegal, dbg_stall, dbg_flush;
  logic [4:0]  dbg_rd_addr;
  logic [31:0] perf_cycle_count, perf_instr_retired_count, perf_stall_count;
  logic [31:0] perf_branch_count, perf_branch_taken_count, perf_load_use_stall_count;
  logic [31:0] perf_forwarding_event_count, perf_flush_count;

  riscv_soc #(
    .UART_BUSY_CYCLES(4),
    .ACCEL_MAX_DIM(8),
    // 4096 words (16KB) so the CPU-only kernels' 0x1000/0x2000/0x3000
    // scratch addresses don't alias against RAM's own 1024-word
    // default depth (dmem.sv only decodes as many low address bits as
    // its DEPTH_WORDS needs -- see this project's own bug writeup in
    // CHANGELOG.md's Phase 11 entry for exactly what aliasing at the
    // default depth looked like before this was caught).
    .RAM_DEPTH_WORDS(4096)
  ) dut (
    .clk(clk), .rst_n(rst_n),
    .gpio_in(gpio_in), .gpio_out(gpio_out),
    .uart_tx_valid(uart_tx_valid), .uart_tx_byte(uart_tx_byte),
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
    string hexfile;
    int    cyc;
    bit    got_sentinel;

    if (!$value$plusargs("NAME=%s", name)) name = "(unnamed)";
    if (!$value$plusargs("HEXFILE=%s", hexfile)) begin
      $display("ERROR: +HEXFILE=... required"); $finish;
    end
    // $readmemh inside imem.sv also honors +HEXFILE directly (see its
    // own header comment) -- this local copy is read here only to
    // echo it into the BENCHMARK_RESULT line for the report script.

    rst_n = 0;
    repeat (2) @(posedge clk);
    #1; // same-edge reset race fix, see CHANGELOG.md's Phase 7 entry
    rst_n = 1;

    got_sentinel = 1'b0;
    cyc = 0;
    while (cyc < MAX_CYCLES && !got_sentinel) begin
      @(posedge clk);
      #1;
      if (gpio_out == SENTINEL) got_sentinel = 1'b1;
      cyc++;
    end

    if (!got_sentinel) begin
      $display("BENCHMARK_ERROR: name=%s sentinel never observed within %0d cycles",
                name, MAX_CYCLES);
      $finish;
    end

    $display("BENCHMARK_RESULT: name=%s cycles=%0d retired=%0d stall=%0d branch=%0d branch_taken=%0d load_use_stall=%0d forwarding=%0d flush=%0d",
              name, perf_cycle_count, perf_instr_retired_count, perf_stall_count,
              perf_branch_count, perf_branch_taken_count, perf_load_use_stall_count,
              perf_forwarding_event_count, perf_flush_count);
    $finish;
  end

endmodule
