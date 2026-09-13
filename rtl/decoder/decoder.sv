`timescale 1ns/1ps
// decoder.sv
//
// Instruction field decoder. Splits a raw 32-bit instruction word into its
// fixed-position fields per docs/riscv.md section 2. Real RISC-V hardware
// extracts these positionally regardless of format -- e.g. instr[24:20] is
// always read out as "rs2" even for instruction types that don't have an
// rs2 -- and lets the control unit (control_unit.sv) decide which fields
// are meaningful for the current opcode. This module does not interpret
// the fields; it only extracts them.

module decoder (
  input  logic [31:0] instr,
  output logic [6:0]  opcode,
  output logic [4:0]  rd,
  output logic [2:0]  funct3,
  output logic [4:0]  rs1,
  output logic [4:0]  rs2,
  output logic [6:0]  funct7
);

  assign opcode = instr[6:0];
  assign rd     = instr[11:7];
  assign funct3 = instr[14:12];
  assign rs1    = instr[19:15];
  assign rs2    = instr[24:20];
  assign funct7 = instr[31:25];

endmodule
