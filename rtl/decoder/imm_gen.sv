`timescale 1ns/1ps
// imm_gen.sv
//
// Immediate generator. Reassembles the sign-extended 32-bit immediate for
// whichever format the current instruction uses, per the bit-level mapping
// in docs/riscv.md section 2.1. The caller (control_unit.sv) tells this
// module which format applies via imm_type; this module does not look at
// the opcode itself.

module imm_gen
  import riscv_pkg::*;
(
  input  logic [31:0] instr,
  input  logic [2:0]  imm_type,
  output logic [31:0] imm_out
);

  always_comb begin
    case (imm_type)
      // I-type: imm[11:0] = instr[31:20], sign-extended.
      IMM_I: imm_out = {{20{instr[31]}}, instr[31:20]};

      // S-type: imm[11:0] = instr[31:25]:instr[11:7], sign-extended.
      IMM_S: imm_out = {{20{instr[31]}}, instr[31:25], instr[11:7]};

      // B-type: imm[12:0] = instr[31]:instr[7]:instr[30:25]:instr[11:8]:0,
      // sign-extended. Bit 0 is always 0 (branch targets are word-pair
      // aligned; this project has no compressed extension so in practice
      // they are always word-aligned as well).
      IMM_B: imm_out = {{19{instr[31]}}, instr[31], instr[7], instr[30:25],
                        instr[11:8], 1'b0};

      // U-type: imm[31:12] = instr[31:12], low 12 bits are zero. Not
      // sign-extended separately -- instr[31] already carries the sign
      // into the top of the result because it lines up with imm_out[31].
      IMM_U: imm_out = {instr[31:12], 12'b0};

      // J-type: imm[20:0] = instr[31]:instr[19:12]:instr[20]:instr[30:21]:0,
      // sign-extended.
      IMM_J: imm_out = {{11{instr[31]}}, instr[31], instr[19:12], instr[20],
                        instr[30:21], 1'b0};

      default: imm_out = 32'b0;
    endcase
  end

endmodule
