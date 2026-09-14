`timescale 1ns/1ps
// id_ex_reg.sv
//
// ID/EX pipeline register. Captures everything ID computed this cycle --
// decoded operands, the immediate, and every control signal -- so EX can
// consume it next cycle.
//
// Contents and why each field is here:
//   pc, pc_plus4  - pc for branch/JAL target math (pc+imm) in EX;
//                   pc_plus4 passed through to EX/MEM/WB for JAL/JALR's
//                   return value.
//   rs1_data,
//   rs2_data      - register operands read by ID's regfile port. EX uses
//                   these for the ALU inputs and the branch comparison;
//                   MEM (via EX/MEM) uses rs2_data as SW's store data.
//   imm_out       - the assembled immediate from ID's imm_gen, used as
//                   an ALU input and in the branch/JAL target adder.
//   rd_addr       - destination register, needed all the way to WB.
//   rs1_addr,
//   rs2_addr      - source register *numbers* (not their values). Not
//                   used by anything in Phase 5's datapath; carried
//                   forward now because Phase 6's forwarding unit needs
//                   to compare EX/MEM's and MEM/WB's rd_addr against
//                   ID/EX's rs1_addr/rs2_addr, and plumbing them through
//                   now avoids re-touching this register's port list
//                   later.
//   funct3        - selects the branch condition in EX's branch_unit.
//   Control signals (reg_write, alu_src_a, alu_src_b, alu_op, mem_read,
//   mem_write, result_src, branch, jal, jalr, illegal) - produced by
//   ID's control_unit, needed by EX/MEM/WB as this instruction moves
//   through the rest of the pipeline. See docs/pipeline.md for how each
//   is used stage by stage.
//   instr_dbg    - the raw instruction word, carried through purely for
//                  simulation trace/debug visibility (so a testbench can
//                  show which instruction occupies every stage in the
//                  same cycle, demonstrating real pipelined concurrency
//                  -- see sim/testbenches/tb_pipeline.sv). Not read by
//                  any functional logic.
//   valid        - Phase 7: true iff this slot holds a real instruction,
//                  not a bubble. Computed once in riscv_cpu_pipeline.sv's
//                  ID stage as the OR of every control signal that some
//                  real opcode sets (reg_write | mem_write | branch |
//                  jal | jalr -- every supported opcode sets at least
//                  one, see rtl/cpu/control_unit.sv), then threaded
//                  through unchanged rather than re-derived at each
//                  stage, since a bubble's control signals are all zero
//                  by construction (reset/flush) and downstream stages
//                  don't have enough of the original signals left (e.g.
//                  branch/jal/jalr stop at EX) to recompute it. Used by
//                  rtl/cpu/perf_counters.sv to count retired
//                  instructions without miscounting bubbles.
//
// Reset clears every control signal to its inactive value (0), which is
// what makes a bubble a bubble (see if_id_reg.sv's header comment) --
// the data fields (pc, operands, etc.) don't need a defined reset value
// beyond that, since no control signal will ever act on them while they
// hold reset garbage, but they are cleared to 0 anyway for clean,
// glitch-free waveforms and simulation traces.
//
// Phase 6 hazard control: `flush` (driven by rtl/pipeline/hazard_unit.sv)
// forces the output to the same all-zero bubble as reset, regardless of
// the *_in values, for two distinct reasons: (1) a load-use hazard --
// the instruction that would otherwise enter EX must wait, so EX gets a
// bubble instead this cycle while IF/ID holds; (2) the cycle after EX
// resolves a taken branch/JAL/JALR, discarding the wrong-path
// instruction that was sitting in ID (about to become the new EX
// instruction) when the redirect fired. Unlike if_id_reg, this register
// never needs a plain `stall` (hold) -- when ID can't yet issue, EX
// simply gets an empty bubble, not a repeat of an old instruction.

module id_ex_reg
  import riscv_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,
  input  logic        flush,

  input  logic [31:0] pc_in,
  input  logic [31:0] pc_plus4_in,
  input  logic [31:0] rs1_data_in,
  input  logic [31:0] rs2_data_in,
  input  logic [31:0] imm_out_in,
  input  logic [4:0]  rd_addr_in,
  input  logic [4:0]  rs1_addr_in,
  input  logic [4:0]  rs2_addr_in,
  input  logic [2:0]  funct3_in,
  input  logic        reg_write_in,
  input  logic        alu_src_a_in,
  input  logic        alu_src_b_in,
  input  logic [3:0]  alu_op_in,
  input  logic        mem_read_in,
  input  logic        mem_write_in,
  input  logic [1:0]  result_src_in,
  input  logic        branch_in,
  input  logic        jal_in,
  input  logic        jalr_in,
  input  logic        illegal_in,
  input  logic [2:0]  accel_sel_in,  // Phase 10: see riscv_pkg.sv's ACCEL_SEL_*
  input  logic [31:0] instr_dbg_in,
  input  logic        valid_in,

  output logic [31:0] pc_out,
  output logic [31:0] pc_plus4_out,
  output logic [31:0] rs1_data_out,
  output logic [31:0] rs2_data_out,
  output logic [31:0] imm_out_out,
  output logic [4:0]  rd_addr_out,
  output logic [4:0]  rs1_addr_out,
  output logic [4:0]  rs2_addr_out,
  output logic [2:0]  funct3_out,
  output logic        reg_write_out,
  output logic        alu_src_a_out,
  output logic        alu_src_b_out,
  output logic [3:0]  alu_op_out,
  output logic        mem_read_out,
  output logic        mem_write_out,
  output logic [1:0]  result_src_out,
  output logic        branch_out,
  output logic        jal_out,
  output logic        jalr_out,
  output logic        illegal_out,
  output logic [2:0]  accel_sel_out,
  output logic [31:0] instr_dbg_out,
  output logic        valid_out
);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pc_out         <= 32'b0;
      pc_plus4_out   <= 32'b0;
      rs1_data_out   <= 32'b0;
      rs2_data_out   <= 32'b0;
      imm_out_out    <= 32'b0;
      rd_addr_out    <= 5'b0;
      rs1_addr_out   <= 5'b0;
      rs2_addr_out   <= 5'b0;
      funct3_out     <= 3'b0;
      reg_write_out  <= 1'b0;
      alu_src_a_out  <= 1'b0;
      alu_src_b_out  <= 1'b0;
      alu_op_out     <= ALU_ADD;
      mem_read_out   <= 1'b0;
      mem_write_out  <= 1'b0;
      result_src_out <= RESULT_ALU;
      branch_out     <= 1'b0;
      jal_out        <= 1'b0;
      jalr_out       <= 1'b0;
      illegal_out    <= 1'b0;
      accel_sel_out  <= ACCEL_SEL_NONE;
      instr_dbg_out  <= 32'b0;
      valid_out      <= 1'b0;
    end else if (flush) begin
      pc_out         <= 32'b0;
      pc_plus4_out   <= 32'b0;
      rs1_data_out   <= 32'b0;
      rs2_data_out   <= 32'b0;
      imm_out_out    <= 32'b0;
      rd_addr_out    <= 5'b0;
      rs1_addr_out   <= 5'b0;
      rs2_addr_out   <= 5'b0;
      funct3_out     <= 3'b0;
      reg_write_out  <= 1'b0;
      alu_src_a_out  <= 1'b0;
      alu_src_b_out  <= 1'b0;
      alu_op_out     <= ALU_ADD;
      mem_read_out   <= 1'b0;
      mem_write_out  <= 1'b0;
      result_src_out <= RESULT_ALU;
      branch_out     <= 1'b0;
      jal_out        <= 1'b0;
      jalr_out       <= 1'b0;
      illegal_out    <= 1'b0;
      accel_sel_out  <= ACCEL_SEL_NONE;
      instr_dbg_out  <= 32'b0;
      valid_out      <= 1'b0;
    end else begin
      pc_out         <= pc_in;
      pc_plus4_out   <= pc_plus4_in;
      rs1_data_out   <= rs1_data_in;
      rs2_data_out   <= rs2_data_in;
      imm_out_out    <= imm_out_in;
      rd_addr_out    <= rd_addr_in;
      rs1_addr_out   <= rs1_addr_in;
      rs2_addr_out   <= rs2_addr_in;
      funct3_out     <= funct3_in;
      reg_write_out  <= reg_write_in;
      alu_src_a_out  <= alu_src_a_in;
      alu_src_b_out  <= alu_src_b_in;
      alu_op_out     <= alu_op_in;
      mem_read_out   <= mem_read_in;
      mem_write_out  <= mem_write_in;
      result_src_out <= result_src_in;
      branch_out     <= branch_in;
      jal_out        <= jal_in;
      jalr_out       <= jalr_in;
      illegal_out    <= illegal_in;
      accel_sel_out  <= accel_sel_in;
      instr_dbg_out  <= instr_dbg_in;
      valid_out      <= valid_in;
    end
  end

endmodule
