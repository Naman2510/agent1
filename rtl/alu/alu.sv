`timescale 1ns/1ps
// alu.sv
//
// RV32I arithmetic/logic unit. Combinational: given two 32-bit operands and
// a 4-bit operation select (rtl/cpu/riscv_pkg.sv ALU_*), produces the
// result for every R-type/I-type ALU instruction in docs/riscv.md section
// 3.1/3.2, plus the ADD used internally for LOAD/STORE address calculation
// and JALR/AUIPC, and a PASSB op used internally for LUI (see riscv_pkg.sv
// header comment: PASSB is not an ISA instruction, it is how this
// implementation reuses the ALU's output mux for LUI).
//
// Shift amount is rs2[4:0] (SLL/SRL/SRA) or the immediate's low 5 bits
// (SLLI/SRLI/SRAI) -- either way, by the time this module sees `b`, the
// caller has already put the shift amount in b[4:0], per RV32's "shifts
// are mod 32" rule (docs/riscv.md section 3.1 note).

module alu
  import riscv_pkg::*;
(
  input  logic [31:0] a,
  input  logic [31:0] b,
  input  logic [3:0]  alu_op,
  output logic [31:0] result,
  output logic        zero
);

  // Signed views of the operands, used for SLT/SRA.
  logic signed [31:0] a_signed, b_signed;
  assign a_signed = a;
  assign b_signed = b;

  always_comb begin
    case (alu_op)
      ALU_ADD:   result = a + b;
      ALU_SUB:   result = a - b;
      ALU_SLL:   result = a << b[4:0];
      ALU_SLT:   result = {31'b0, (a_signed < b_signed)};
      ALU_SLTU:  result = {31'b0, (a < b)};
      ALU_XOR:   result = a ^ b;
      ALU_SRL:   result = a >> b[4:0];
      ALU_SRA:   result = a_signed >>> b[4:0];
      ALU_OR:    result = a | b;
      ALU_AND:   result = a & b;
      ALU_PASSB: result = b;
      default:   result = 32'b0;
    endcase
  end

  assign zero = (result == 32'b0);

endmodule
