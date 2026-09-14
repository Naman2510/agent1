// tb_perf_counters.sv
//
// Phase 7 testbench: runs both benchmark programs
// (sim/programs/benchmarks/sum_loop.s and array_sum.s -- real,
// branch-driven loops, not synthetic NOP-padded code) and checks both
// the computed result AND every performance counter against values
// verified empirically against these exact programs (see
// CHANGELOG.md's Phase 7 entry for hand-derivations that turned out
// wrong before this was captured from an actual simulation run)
// rather than hand-derived and trusted blindly. Two independent DUT
// instances (one per program) run in the same simulation so this one
// file establishes the correctness of both benchmarks
// scripts/run_benchmarks.py's report is built from.
//
// Snapshot points: chosen as the earliest cycle each program's
// instr_retired_count reaches its final real-instruction total (34 for
// both programs, coincidentally) -- i.e. after the loop's own exit
// branch has retired but before the terminal `done: j done` loop
// starts contributing retirements/flushes of its own forever.
//
// A genuinely interesting artifact ended up baked into both expected
// flush_counts (one more than the real taken-branch count): flush is
// counted when EX resolves a redirect, but instr_retired is counted 3
// pipeline stages later at WB. By each snapshot cycle, the loop's real
// taken branches have all both resolved AND retired, but the halt
// loop's first `j done` has already resolved in EX (incrementing
// flush_count) despite not yet reaching WB (so it is correctly NOT yet
// counted in instr_retired_count). This is not a bug -- it's exactly
// what two counters measuring different pipeline stages at one instant
// should show -- and is called out here rather than picking a
// snapshot cycle that would hide it.

`timescale 1ns/1ps

module tb_perf_counters;

  logic clk;
  logic rst_n = 0;

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  int errors = 0;
  real array_sum_cpi;

  task automatic check(string name, logic [31:0] actual, logic [31:0] expected);
    if (actual !== expected) begin
      $display("  [FAIL] %-28s expected=%0d actual=%0d", name, expected, actual);
      errors++;
    end else begin
      $display("  [PASS] %-28s = %0d", name, actual);
    end
  endtask

  // ===================================================================
  // sum_loop.s: pure-ALU loop, zero load-use stalls.
  // ===================================================================
  logic [31:0] sl_if_pc, sl_if_instr, sl_id_pc, sl_id_instr, sl_ex_pc, sl_ex_instr;
  logic [31:0] sl_mem_instr, sl_wb_instr, sl_rd_data;
  logic        sl_reg_write, sl_illegal, sl_stall, sl_flush;
  logic [4:0]  sl_rd_addr;
  logic [31:0] sl_cycle, sl_retired, sl_stall_cnt, sl_branch, sl_branch_taken;
  logic [31:0] sl_load_use, sl_fwd, sl_flush_cnt;
  // Phase 8: see tb_pipeline.sv's header comment -- each riscv_cpu_pipeline
  // instance is now a data-bus master and needs its own dmem wired up.
  logic [31:0] sl_dbus_addr, sl_dbus_wdata, sl_dbus_rdata;
  logic        sl_dbus_mem_read, sl_dbus_mem_write;

  riscv_cpu_pipeline #(
    .IMEM_INIT_FILE("sim/programs/benchmarks/sum_loop.hex")
  ) dut_sum_loop (
    .clk(clk), .rst_n(rst_n),
    .dbus_addr(sl_dbus_addr), .dbus_wdata(sl_dbus_wdata),
    .dbus_mem_read(sl_dbus_mem_read), .dbus_mem_write(sl_dbus_mem_write),
    .dbus_rdata(sl_dbus_rdata),
    .dbg_if_pc(sl_if_pc), .dbg_if_instr(sl_if_instr),
    .dbg_id_pc(sl_id_pc), .dbg_id_instr(sl_id_instr),
    .dbg_ex_pc(sl_ex_pc), .dbg_ex_instr(sl_ex_instr),
    .dbg_mem_instr(sl_mem_instr), .dbg_wb_instr(sl_wb_instr),
    .dbg_reg_write(sl_reg_write), .dbg_rd_addr(sl_rd_addr), .dbg_rd_data(sl_rd_data),
    .dbg_illegal(sl_illegal), .dbg_stall(sl_stall), .dbg_flush(sl_flush),
    .perf_cycle_count(sl_cycle), .perf_instr_retired_count(sl_retired),
    .perf_stall_count(sl_stall_cnt), .perf_branch_count(sl_branch),
    .perf_branch_taken_count(sl_branch_taken), .perf_load_use_stall_count(sl_load_use),
    .perf_forwarding_event_count(sl_fwd), .perf_flush_count(sl_flush_cnt)
  );

  dmem sl_dmem_inst (
    .clk(clk), .addr(sl_dbus_addr), .wdata(sl_dbus_wdata),
    .mem_read(sl_dbus_mem_read), .mem_write(sl_dbus_mem_write), .rdata(sl_dbus_rdata)
  );

  // ===================================================================
  // array_sum.s: load-heavy loop, 1 load-use stall per iteration.
  // ===================================================================
  logic [31:0] as_if_pc, as_if_instr, as_id_pc, as_id_instr, as_ex_pc, as_ex_instr;
  logic [31:0] as_mem_instr, as_wb_instr, as_rd_data;
  logic        as_reg_write, as_illegal, as_stall, as_flush;
  logic [4:0]  as_rd_addr;
  logic [31:0] as_cycle, as_retired, as_stall_cnt, as_branch, as_branch_taken;
  logic [31:0] as_load_use, as_fwd, as_flush_cnt;
  logic [31:0] as_dbus_addr, as_dbus_wdata, as_dbus_rdata;
  logic        as_dbus_mem_read, as_dbus_mem_write;

  riscv_cpu_pipeline #(
    .IMEM_INIT_FILE("sim/programs/benchmarks/array_sum.hex")
  ) dut_array_sum (
    .clk(clk), .rst_n(rst_n),
    .dbus_addr(as_dbus_addr), .dbus_wdata(as_dbus_wdata),
    .dbus_mem_read(as_dbus_mem_read), .dbus_mem_write(as_dbus_mem_write),
    .dbus_rdata(as_dbus_rdata),
    .dbg_if_pc(as_if_pc), .dbg_if_instr(as_if_instr),
    .dbg_id_pc(as_id_pc), .dbg_id_instr(as_id_instr),
    .dbg_ex_pc(as_ex_pc), .dbg_ex_instr(as_ex_instr),
    .dbg_mem_instr(as_mem_instr), .dbg_wb_instr(as_wb_instr),
    .dbg_reg_write(as_reg_write), .dbg_rd_addr(as_rd_addr), .dbg_rd_data(as_rd_data),
    .dbg_illegal(as_illegal), .dbg_stall(as_stall), .dbg_flush(as_flush),
    .perf_cycle_count(as_cycle), .perf_instr_retired_count(as_retired),
    .perf_stall_count(as_stall_cnt), .perf_branch_count(as_branch),
    .perf_branch_taken_count(as_branch_taken), .perf_load_use_stall_count(as_load_use),
    .perf_forwarding_event_count(as_fwd), .perf_flush_count(as_flush_cnt)
  );

  dmem as_dmem_inst (
    .clk(clk), .addr(as_dbus_addr), .wdata(as_dbus_wdata),
    .mem_read(as_dbus_mem_read), .mem_write(as_dbus_mem_write), .rdata(as_dbus_rdata)
  );

  initial begin
    $display("=== Phase 7 performance counter testbench ===");

    rst_n = 0;
    repeat (2) @(posedge clk);
    // A small delay (not the bare next statement) before deasserting
    // reset: driving rst_n=1 exactly on the same active clock edge
    // every always_ff(posedge clk or negedge rst_n) block also samples
    // it on is a same-edge race whose outcome is simulator-defined --
    // found when Icarus Verilog and Verilator disagreed by exactly one
    // cycle on these exact free-running counters. This #1 delay is the
    // standard fix and costs nothing (rst_n is not sampled at that
    // instant by anything else). See CHANGELOG.md's Phase 7 entry.
    #1;
    rst_n = 1;

    // Both DUT instances run in parallel on this same clock, so each
    // program's counters must be checked (using LIVE signal values,
    // via the `check` task) at the moment the simulation reaches ITS
    // OWN snapshot cycle, before advancing further -- checking them out
    // of order would read a later, already-moved-on set of values.
    // array_sum.s's snapshot (cycle 51) comes first.
    repeat (51) @(posedge clk);
    #1;

    $display("");
    $display("--- array_sum.s @ cycle 51 ---");
    check("array_sum x2 (sum=150)",      dut_array_sum.regfile_inst.regs[2], 32'd150);
    check("array_sum cycle_count",       as_cycle,          32'd51);
    check("array_sum instr_retired",     as_retired,        32'd34);
    check("array_sum stall_count",       as_stall_cnt,      32'd5);
    check("array_sum branch_count",      as_branch,         32'd5);
    check("array_sum branch_taken_count",as_branch_taken,   32'd4);
    check("array_sum load_use_stall",    as_load_use,       32'd5);
    check("array_sum forwarding_events", as_fwd,            32'd17);
    check("array_sum flush_count",       as_flush_cnt,      32'd5); // see header comment
    // Captured NOW, not re-read later: both DUTs keep running after
    // this point, and array_sum's own counters (cycle_count included)
    // move past this snapshot well before the testbench finishes -- a
    // display line reading `as_cycle`/`as_retired` live at the very end
    // would silently show stale-wrong numbers despite every check()
    // above (which does read live values, but AT this correct instant)
    // having passed.
    array_sum_cpi = real'(as_cycle) / real'(as_retired);

    $display("");
    $display("--- sum_loop.s @ cycle 56 ---");
    repeat (5) @(posedge clk); #1; // reach cycle 56 for sum_loop specifically
    check("sum_loop x2 (sum 1..10)",     dut_sum_loop.regfile_inst.regs[2], 32'd55);
    check("sum_loop cycle_count",        sl_cycle,          32'd56);
    check("sum_loop instr_retired",      sl_retired,        32'd34);
    check("sum_loop stall_count",        sl_stall_cnt,      32'd0);
    check("sum_loop branch_count",       sl_branch,         32'd10);
    check("sum_loop branch_taken_count", sl_branch_taken,   32'd9);
    check("sum_loop load_use_stall",     sl_load_use,       32'd0);
    check("sum_loop forwarding_events",  sl_fwd,            32'd12);
    check("sum_loop flush_count",        sl_flush_cnt,      32'd10); // see header comment

    $display("");
    $display("sum_loop  CPI = %0d / %0d = %0f", sl_cycle, sl_retired,
              real'(sl_cycle) / real'(sl_retired));
    $display("array_sum CPI = 51 / 34 = %0f", array_sum_cpi);

    $display("");
    if (errors == 0) begin
      $display("RESULT: ALL CHECKS PASSED");
    end else begin
      $display("RESULT: %0d CHECK(S) FAILED", errors);
    end
    $finish;
  end

endmodule
