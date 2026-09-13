`timescale 1ns/1ps
// branch_unit.sv
//
// Evaluates whether a BRANCH instruction is taken, per docs/riscv.md
// section 3.5. Operates directly on rs1/rs2 (not through the main ALU --
// see control_unit.sv header comment) so that branch resolution doesn't
// contend with, e.g., an in-flight ALU computation for AUIPC's PC+imm.

module branch_unit (
  input  logic [31:0] rs1_data,
  input  logic [31:0] rs2_data,
  input  logic [2:0]  funct3,
  output logic        branch_taken
);

  logic signed [31:0] rs1_signed, rs2_signed;
  assign rs1_signed = rs1_data;
  assign rs2_signed = rs2_data;

  always_comb begin
    case (funct3)
      3'b000:  branch_taken = (rs1_data == rs2_data);              // BEQ
      3'b001:  branch_taken = (rs1_data != rs2_data);              // BNE
      3'b100:  branch_taken = (rs1_signed <  rs2_signed);          // BLT
      3'b101:  branch_taken = (rs1_signed >= rs2_signed);          // BGE
      3'b110:  branch_taken = (rs1_data   <  rs2_data);            // BLTU
      3'b111:  branch_taken = (rs1_data   >= rs2_data);            // BGEU
      default: branch_taken = 1'b0;
    endcase
  end

endmodule
