`timescale 1ns/1ps
// if_id_reg.sv
//
// IF/ID pipeline register. Captures what the IF stage produced this
// cycle so the ID stage can consume it next cycle.
//
// Contents and why each field is here:
//   pc         - address of the fetched instruction. Needed in ID (and
//                passed further, to EX) to compute branch/JAL targets
//                (pc + imm) and for AUIPC (pc + imm<<12).
//   pc_plus4   - pc+4, needed all the way to WB for JAL/JALR's return
//                value and passed through so EX/MEM/WB don't need their
//                own adder recomputing it from a stale pc.
//   instr      - the raw 32-bit instruction word. ID needs the whole
//                word for both the decoder (field extraction) and the
//                immediate generator.
//
// Reset clears both to 0. On reset (or the first few cycles as the
// pipeline fills), instr=0 decodes to opcode=0000000, which is not any
// of this project's supported opcodes (docs/riscv.md section 3.8) --
// control_unit.sv's default case makes that a safe, inert bubble
// (reg_write=0, mem_read=0, mem_write=0, branch/jal/jalr=0), not a
// silently-wrong instruction. See docs/pipeline.md for the full
// register-by-register account of what Phase 5 does and does not
// handle (in particular: no flush support yet -- that's Phase 6).

module if_id_reg (
  input  logic        clk,
  input  logic        rst_n,

  input  logic [31:0] pc_in,
  input  logic [31:0] pc_plus4_in,
  input  logic [31:0] instr_in,

  output logic [31:0] pc_out,
  output logic [31:0] pc_plus4_out,
  output logic [31:0] instr_out
);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pc_out       <= 32'b0;
      pc_plus4_out <= 32'b0;
      instr_out    <= 32'b0;
    end else begin
      pc_out       <= pc_in;
      pc_plus4_out <= pc_plus4_in;
      instr_out    <= instr_in;
    end
  end

endmodule
