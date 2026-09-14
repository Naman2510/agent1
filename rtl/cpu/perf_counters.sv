`timescale 1ns/1ps
// perf_counters.sv
//
// Phase 7: free-running performance counters for the pipelined CPU.
// Purely observational -- every input here is a signal the pipeline
// already computes for its own functional correctness; this module adds
// no datapath feedback of any kind, only counts what already happened.
//
// Counters (all free-running 32-bit, wrap on overflow, cleared on
// reset):
//   cycle_count            - clock cycles since reset (one per posedge
//                             clk while rst_n is high).
//   instr_retired_count    - instructions that reached WB and were not
//                             a bubble (gated on `valid`, threaded
//                             through the pipeline registers -- see
//                             rtl/pipeline/id_ex_reg.sv's header
//                             comment for why a bubble can't be
//                             recognized by its control signals alone
//                             downstream, and why this dedicated signal
//                             exists instead).
//   stall_count             - cycles hazard_unit held the pipeline for
//                             a load-use hazard (pc_stall).
//   branch_count            - real BRANCH instructions resolved in EX
//                             (taken or not).
//   branch_taken_count      - the subset of those that were taken.
//   load_use_stall_count    - cycles stalled specifically because of a
//                             load-use hazard. Currently always equal
//                             to stall_count, since that is the only
//                             stall source this CPU has; kept as a
//                             separate counter (rather than an alias)
//                             because the task specification asks for
//                             both by name, and because a future stall
//                             source (e.g. a structural hazard added in
//                             a later phase) would make them diverge.
//   forwarding_event_count  - total number of EX-stage operands
//                             (summed over both A and B, so a cycle
//                             forwarding both operands counts as 2)
//                             supplied by forwarding_unit instead of
//                             the plain register-file read.
//   flush_count             - cycles hazard_unit flushed the pipeline
//                             for a taken branch or JAL/JALR. Not in
//                             the task's named counter list, but cheap
//                             and directly useful alongside branch
//                             counts, so included.
//
// CPI (cycles per instruction = cycle_count / instr_retired_count) is
// deliberately NOT computed in hardware here: it's a derived ratio, not
// a piece of state the CPU needs, and computing it correctly in
// hardware would need a divider for no functional benefit. It's
// computed in software from these raw counters -- see
// scripts/run_benchmarks.py and docs/pipeline.md's Phase 7 section.

module perf_counters (
  input  logic clk,
  input  logic rst_n,

  input  logic instr_retired,   // WB stage: valid (non-bubble) this cycle
  input  logic stall,           // pc_stall
  input  logic branch_resolved, // EX stage: a real BRANCH instruction
  input  logic branch_taken,    // that branch's outcome (only meaningful
                                 // when branch_resolved is also true)
  input  logic forward_a_active,
  input  logic forward_b_active,
  input  logic flush,

  output logic [31:0] cycle_count,
  output logic [31:0] instr_retired_count,
  output logic [31:0] stall_count,
  output logic [31:0] branch_count,
  output logic [31:0] branch_taken_count,
  output logic [31:0] load_use_stall_count,
  output logic [31:0] forwarding_event_count,
  output logic [31:0] flush_count
);

  logic [1:0] forward_inc;
  assign forward_inc = {1'b0, forward_a_active} + {1'b0, forward_b_active};

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cycle_count            <= 32'b0;
      instr_retired_count    <= 32'b0;
      stall_count             <= 32'b0;
      branch_count            <= 32'b0;
      branch_taken_count      <= 32'b0;
      load_use_stall_count    <= 32'b0;
      forwarding_event_count  <= 32'b0;
      flush_count             <= 32'b0;
    end else begin
      cycle_count <= cycle_count + 32'd1;

      if (instr_retired) instr_retired_count <= instr_retired_count + 32'd1;
      if (stall)          stall_count          <= stall_count + 32'd1;
      if (stall)          load_use_stall_count <= load_use_stall_count + 32'd1;
      if (branch_resolved) branch_count <= branch_count + 32'd1;
      if (branch_resolved && branch_taken)
        branch_taken_count <= branch_taken_count + 32'd1;
      if (flush) flush_count <= flush_count + 32'd1;

      forwarding_event_count <= forwarding_event_count + {30'b0, forward_inc};
    end
  end

endmodule
