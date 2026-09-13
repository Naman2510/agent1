`timescale 1ns/1ps
// control_unit.sv
//
// Main control unit for the single-cycle RV32I CPU. Combinational: takes
// the fields decoder.sv extracted (opcode/funct3/funct7) and produces every
// control signal the rest of the datapath needs. See docs/datapath.md for
// how each signal wires into the datapath and why it is shaped this way.
//
// alu_op derivation note: for both R-type (OP) and I-type ALU ops
// (OP-IMM), instr[31:25] sits in the same bit position whether the ISA
// calls it "funct7" (R-type) or the top bits of a shift immediate
// (SLLI/SRLI/SRAI). Because of that, a single case on funct3 -- checking
// funct7[5] only for funct3=000 (ADD/SUB) and funct3=101 (SRL/SRA) -- gives
// the right ALU op for both R-type and I-type instructions without the
// control unit needing to special-case OP vs OP-IMM for that decision:
// funct7[5] is only ever "real" (non-immediate) hardware state for
// R-type and for the two shift-immediate encodings, and in exactly those
// cases it means what this case statement assumes.

module control_unit
  import riscv_pkg::*;
(
  input  logic [6:0] opcode,
  input  logic [2:0] funct3,
  input  logic [6:0] funct7,

  output logic       reg_write,
  output logic       alu_src_a,   // 0 = rs1, 1 = PC        (AUIPC only)
  output logic       alu_src_b,   // 0 = rs2, 1 = immediate
  output logic [2:0] imm_type,
  output logic [3:0] alu_op,
  output logic       mem_read,
  output logic       mem_write,
  output logic [1:0] result_src,
  output logic       branch,
  output logic       jal,
  output logic       jalr,
  output logic       illegal
);

  // ALU op is shared by OP and OP-IMM; see header comment.
  logic [3:0] alu_op_rtype_or_itype;
  always_comb begin
    case (funct3)
      3'b000:  alu_op_rtype_or_itype = (opcode == OP_R && funct7[5]) ? ALU_SUB : ALU_ADD;
      3'b001:  alu_op_rtype_or_itype = ALU_SLL;
      3'b010:  alu_op_rtype_or_itype = ALU_SLT;
      3'b011:  alu_op_rtype_or_itype = ALU_SLTU;
      3'b100:  alu_op_rtype_or_itype = ALU_XOR;
      3'b101:  alu_op_rtype_or_itype = funct7[5] ? ALU_SRA : ALU_SRL;
      3'b110:  alu_op_rtype_or_itype = ALU_OR;
      3'b111:  alu_op_rtype_or_itype = ALU_AND;
      default: alu_op_rtype_or_itype = ALU_ADD;
    endcase
  end

  always_comb begin
    // Safe defaults: no state-changing effect, ADD on the ALU.
    reg_write  = 1'b0;
    alu_src_a  = 1'b0;
    alu_src_b  = 1'b0;
    imm_type   = IMM_I;
    alu_op     = ALU_ADD;
    mem_read   = 1'b0;
    mem_write  = 1'b0;
    result_src = RESULT_ALU;
    branch     = 1'b0;
    jal        = 1'b0;
    jalr       = 1'b0;
    illegal    = 1'b0;

    case (opcode)
      OP_R: begin
        reg_write = 1'b1;
        alu_src_a = 1'b0;
        alu_src_b = 1'b0; // rs2
        alu_op    = alu_op_rtype_or_itype;
        result_src = RESULT_ALU;
      end

      OP_IMM: begin
        reg_write = 1'b1;
        alu_src_a = 1'b0;
        alu_src_b = 1'b1; // immediate
        imm_type  = IMM_I;
        alu_op    = alu_op_rtype_or_itype;
        result_src = RESULT_ALU;
      end

      OP_LOAD: begin // LW
        reg_write  = 1'b1;
        alu_src_a  = 1'b0;
        alu_src_b  = 1'b1;
        imm_type   = IMM_I;
        alu_op     = ALU_ADD;
        mem_read   = 1'b1;
        result_src = RESULT_MEM;
      end

      OP_STORE: begin // SW
        alu_src_a = 1'b0;
        alu_src_b = 1'b1;
        imm_type  = IMM_S;
        alu_op    = ALU_ADD;
        mem_write = 1'b1;
      end

      OP_BRANCH: begin // BEQ/BNE/BLT/BGE/BLTU/BGEU
        imm_type = IMM_B;
        branch   = 1'b1;
        // alu_op/alu_src_* left at defaults: the branch unit evaluates
        // rs1/rs2 directly and does not use the main ALU.
      end

      OP_LUI: begin
        reg_write  = 1'b1;
        alu_src_b  = 1'b1;   // immediate
        imm_type   = IMM_U;
        alu_op     = ALU_PASSB; // result = imm (see riscv_pkg.sv note)
        result_src = RESULT_ALU;
      end

      OP_AUIPC: begin
        reg_write  = 1'b1;
        alu_src_a  = 1'b1;   // PC
        alu_src_b  = 1'b1;   // immediate
        imm_type   = IMM_U;
        alu_op     = ALU_ADD;
        result_src = RESULT_ALU;
      end

      OP_JAL: begin
        reg_write  = 1'b1;
        imm_type   = IMM_J;
        jal        = 1'b1;
        result_src = RESULT_PC4;
      end

      OP_JALR: begin
        reg_write  = 1'b1;
        alu_src_a  = 1'b0;   // rs1
        alu_src_b  = 1'b1;   // immediate
        imm_type   = IMM_I;
        alu_op     = ALU_ADD; // ALU computes rs1 + imm; top level masks bit0
        jalr       = 1'b1;
        result_src = RESULT_PC4;
      end

      default: begin
        // Opcode not in docs/riscv.md section 3.8: diagnose, don't
        // silently execute garbage. See CHANGELOG.md Phase 1 entry on
        // illegal-opcode handling (no trap architecture exists yet).
        illegal = 1'b1;
      end
    endcase
  end

endmodule
