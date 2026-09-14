`timescale 1ns/1ps
// mem_wb_reg.sv
//
// MEM/WB pipeline register. Captures what MEM produced this cycle so WB
// can consume it next cycle -- the last handoff in the pipeline.
//
// Contents and why each field is here:
//   pc_plus4    - one of the three writeback-mux inputs (JAL/JALR).
//   alu_result  - another writeback-mux input (everything except loads
//                 and JAL/JALR).
//   mem_rdata   - data memory's read output for this instruction (only
//                 meaningful when result_src selects it, i.e. LW).
//   rd_addr     - destination register for WB's regfile write port.
//   reg_write, result_src, illegal - reg_write and result_src drive WB's
//   writeback mux and regfile write enable; illegal is carried through
//   only for debug visibility (see riscv_cpu_pipeline.sv's dbg_illegal).
//   instr_dbg   - raw instruction word, carried through for simulation
//                 trace visibility only (see id_ex_reg.sv's header
//                 comment); not read by any functional logic.
//   valid       - Phase 7: threaded straight through from ex_mem_reg
//                 unchanged (see id_ex_reg.sv's header comment for how
//                 it's derived). This is what
//                 rtl/cpu/perf_counters.sv gates "instruction retired"
//                 on -- a bubble reaching WB (pipeline fill, a
//                 load-use bubble, or a flushed instruction) must never
//                 count as a retired instruction.

module mem_wb_reg
  import riscv_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,

  input  logic [31:0] pc_plus4_in,
  input  logic [31:0] alu_result_in,
  input  logic [31:0] mem_rdata_in,
  input  logic [4:0]  rd_addr_in,
  input  logic        reg_write_in,
  input  logic [1:0]  result_src_in,
  input  logic        illegal_in,
  input  logic [31:0] instr_dbg_in,
  input  logic        valid_in,

  output logic [31:0] pc_plus4_out,
  output logic [31:0] alu_result_out,
  output logic [31:0] mem_rdata_out,
  output logic [4:0]  rd_addr_out,
  output logic        reg_write_out,
  output logic [1:0]  result_src_out,
  output logic        illegal_out,
  output logic [31:0] instr_dbg_out,
  output logic        valid_out
);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pc_plus4_out   <= 32'b0;
      alu_result_out <= 32'b0;
      mem_rdata_out  <= 32'b0;
      rd_addr_out    <= 5'b0;
      reg_write_out  <= 1'b0;
      result_src_out <= RESULT_ALU;
      illegal_out    <= 1'b0;
      instr_dbg_out  <= 32'b0;
      valid_out      <= 1'b0;
    end else begin
      pc_plus4_out   <= pc_plus4_in;
      alu_result_out <= alu_result_in;
      mem_rdata_out  <= mem_rdata_in;
      rd_addr_out    <= rd_addr_in;
      reg_write_out  <= reg_write_in;
      result_src_out <= result_src_in;
      illegal_out    <= illegal_in;
      instr_dbg_out  <= instr_dbg_in;
      valid_out      <= valid_in;
    end
  end

endmodule
