`timescale 1ns/1ps
// ex_mem_reg.sv
//
// EX/MEM pipeline register. Captures what EX computed this cycle so MEM
// can consume it next cycle.
//
// Contents and why each field is here:
//   pc_plus4    - passed through untouched for JAL/JALR's return value
//                 (result_src = RESULT_PC4), selected in WB.
//   alu_result  - the ALU's output: the arithmetic/logical result for
//                 R-type/I-type ops, or the memory address for LW/SW
//                 (computed in EX as rs1+imm, same as the single-cycle
//                 design in rtl/cpu/riscv_cpu.sv).
//   rs2_data    - carried through as SW's store data (the ALU only
//                 computed the *address* from rs1+imm; the value being
//                 stored is rs2, untouched by EX).
//   rd_addr     - destination register, needed by MEM/WB and WB.
//   reg_write, mem_read, mem_write, result_src, illegal - control
//   signals MEM and WB still need to act on this instruction.
//
// branch/jal/jalr and funct3 stop here: EX is where they were consumed
// (to decide whether to redirect the PC -- see riscv_cpu_pipeline.sv),
// and nothing downstream of EX needs them again.
//
//   instr_dbg   - raw instruction word, carried through for simulation
//                 trace visibility only (see id_ex_reg.sv's header
//                 comment); not read by any functional logic.
//   valid       - Phase 7: threaded straight through from id_ex_reg
//                 unchanged (see its header comment for how it's
//                 derived); this register never flushes on its own, so
//                 there's no separate "force to 0" case here beyond
//                 the reset default.

module ex_mem_reg
  import riscv_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,

  input  logic [31:0] pc_plus4_in,
  input  logic [31:0] alu_result_in,
  input  logic [31:0] rs2_data_in,
  input  logic [4:0]  rd_addr_in,
  input  logic        reg_write_in,
  input  logic        mem_read_in,
  input  logic        mem_write_in,
  input  logic [1:0]  result_src_in,
  input  logic        illegal_in,
  input  logic [31:0] instr_dbg_in,
  input  logic        valid_in,

  output logic [31:0] pc_plus4_out,
  output logic [31:0] alu_result_out,
  output logic [31:0] rs2_data_out,
  output logic [4:0]  rd_addr_out,
  output logic        reg_write_out,
  output logic        mem_read_out,
  output logic        mem_write_out,
  output logic [1:0]  result_src_out,
  output logic        illegal_out,
  output logic [31:0] instr_dbg_out,
  output logic        valid_out
);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pc_plus4_out   <= 32'b0;
      alu_result_out <= 32'b0;
      rs2_data_out   <= 32'b0;
      rd_addr_out    <= 5'b0;
      reg_write_out  <= 1'b0;
      mem_read_out   <= 1'b0;
      mem_write_out  <= 1'b0;
      result_src_out <= RESULT_ALU;
      illegal_out    <= 1'b0;
      instr_dbg_out  <= 32'b0;
      valid_out      <= 1'b0;
    end else begin
      pc_plus4_out   <= pc_plus4_in;
      alu_result_out <= alu_result_in;
      rs2_data_out   <= rs2_data_in;
      rd_addr_out    <= rd_addr_in;
      reg_write_out  <= reg_write_in;
      mem_read_out   <= mem_read_in;
      mem_write_out  <= mem_write_in;
      result_src_out <= result_src_in;
      illegal_out    <= illegal_in;
      instr_dbg_out  <= instr_dbg_in;
      valid_out      <= valid_in;
    end
  end

endmodule
