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
// Phase 6 hazard control (rtl/pipeline/hazard_unit.sv drives both):
//   stall - hold the current contents instead of capturing pc_in/
//           instr_in. Asserted for exactly one cycle on a load-use
//           hazard, so the instruction already in ID gets re-decoded
//           next cycle instead of the one behind it advancing into it.
//   flush - force the OUTPUT to a bubble (all zero) regardless of
//           pc_in/instr_in or `stall`. Asserted the cycle EX resolves a
//           taken branch or any JAL/JALR, discarding the
//           wrong-path instruction IF just fetched using the
//           pre-redirect PC. flush takes priority over stall (the two
//           can't actually co-occur in the same cycle -- the EX-stage
//           instruction can't simultaneously be a load, which drives
//           the stall this register would be asked to hold for, and a
//           branch/JAL/JALR, which drives the flush -- but flush wins
//           if both were ever asserted, since discarding wrong-path
//           work is always safe to do unconditionally).
//
// Reset clears everything to 0, same bubble-safe rationale as flush:
// instr=0 decodes to opcode=0000000, not any supported opcode
// (docs/riscv.md section 3.8), so control_unit.sv's default case makes
// it an inert no-op rather than a silently-wrong instruction.

module if_id_reg (
  input  logic        clk,
  input  logic        rst_n,
  input  logic        stall,
  input  logic        flush,

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
    end else if (flush) begin
      pc_out       <= 32'b0;
      pc_plus4_out <= 32'b0;
      instr_out    <= 32'b0;
    end else if (stall) begin
      // Hold: intentionally no assignment, keeps current values.
    end else begin
      pc_out       <= pc_in;
      pc_plus4_out <= pc_plus4_in;
      instr_out    <= instr_in;
    end
  end

endmodule
