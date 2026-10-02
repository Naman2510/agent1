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
// cases it means what this case statement assumes. The full funct7 value
// of those encodings is validated separately in the OP_R / OP_IMM
// branches below, so an encoding outside RV32I raises `illegal` instead
// of being decoded by funct7[5] alone. Likewise LOAD/STORE/BRANCH/JALR
// validate funct3. Every opcode x funct3 x funct7 combination is checked
// against a spec-derived reference by sim/testbenches/tb_control_unit_decode.sv.
//
// ENABLE_MUL (default 0): when set, OP_R funct7=0000001 funct3=000
// decodes as RV32M MUL (ALU_MUL). The rest of RV32M (MULH*, DIV*, REM*)
// is not implemented and stays illegal either way. Default-off keeps the
// RV32I core -- and every result measured on it -- unchanged.

module control_unit
  import riscv_pkg::*;
#(
  parameter bit ENABLE_MUL = 1'b0
)
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
  output logic       illegal,
  output logic [2:0] accel_sel   // Phase 10: see riscv_pkg.sv's ACCEL_SEL_*
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
    accel_sel  = ACCEL_SEL_NONE;

    case (opcode)
      OP_R: begin
        // funct7 must be validated, not just funct7[5]: RV32I defines only
        // 0000000 (all funct3) and 0100000 (SUB, SRA). Anything else --
        // including every RV32M encoding -- is illegal here unless it is
        // MUL with ENABLE_MUL set. Before this check existed, those
        // encodings silently executed as the RV32I op their funct3/funct7[5]
        // happened to select (e.g. MUL ran as ADD); caught by
        // sim/testbenches/tb_control_unit_decode.sv's exhaustive sweep.
        if (funct7 == 7'b0000000 ||
            (funct7 == 7'b0100000 && (funct3 == 3'b000 || funct3 == 3'b101))) begin
          reg_write  = 1'b1;
          alu_src_a  = 1'b0;
          alu_src_b  = 1'b0; // rs2
          alu_op     = alu_op_rtype_or_itype;
          result_src = RESULT_ALU;
        end else if (ENABLE_MUL && funct7 == 7'b0000001 && funct3 == 3'b000) begin
          reg_write  = 1'b1; // MUL: low 32 bits of rs1 * rs2
          alu_src_a  = 1'b0;
          alu_src_b  = 1'b0;
          alu_op     = ALU_MUL;
          result_src = RESULT_ALU;
        end else begin
          illegal = 1'b1;
        end
      end

      OP_IMM: begin
        // instr[31:25] is immediate data for every OP-IMM funct3 except the
        // two shift-immediates, where it must be 0000000 (SLLI/SRLI) or
        // 0100000 (SRAI) -- same validation gap and same fix as OP_R above.
        if ((funct3 == 3'b001 && funct7 != 7'b0000000) ||
            (funct3 == 3'b101 && funct7 != 7'b0000000 && funct7 != 7'b0100000)) begin
          illegal = 1'b1;
        end else begin
          reg_write  = 1'b1;
          alu_src_a  = 1'b0;
          alu_src_b  = 1'b1; // immediate
          imm_type   = IMM_I;
          alu_op     = alu_op_rtype_or_itype;
          result_src = RESULT_ALU;
        end
      end

      OP_LOAD: begin // LW only -- LB/LH/LBU/LHU (funct3 != 010) are not
                     // implemented and must not execute as LW
        if (funct3 == 3'b010) begin
          reg_write  = 1'b1;
          alu_src_a  = 1'b0;
          alu_src_b  = 1'b1;
          imm_type   = IMM_I;
          alu_op     = ALU_ADD;
          mem_read   = 1'b1;
          result_src = RESULT_MEM;
        end else begin
          illegal = 1'b1;
        end
      end

      OP_STORE: begin // SW only -- SB/SH (funct3 != 010) are not implemented;
                      // executing them as SW would write a full word and
                      // clobber the neighbouring bytes
        if (funct3 == 3'b010) begin
          alu_src_a = 1'b0;
          alu_src_b = 1'b1;
          imm_type  = IMM_S;
          alu_op    = ALU_ADD;
          mem_write = 1'b1;
        end else begin
          illegal = 1'b1;
        end
      end

      OP_BRANCH: begin // BEQ/BNE/BLT/BGE/BLTU/BGEU -- funct3 010/011 are
                       // undefined (branch_unit.sv would just never take them)
        if (funct3 == 3'b010 || funct3 == 3'b011) begin
          illegal = 1'b1;
        end else begin
          imm_type = IMM_B;
          branch   = 1'b1;
          // alu_op/alu_src_* left at defaults: the branch unit evaluates
          // rs1/rs2 directly and does not use the main ALU.
        end
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

      OP_JALR: begin // JALR requires funct3 = 000
        if (funct3 == 3'b000) begin
          reg_write  = 1'b1;
          alu_src_a  = 1'b0;   // rs1
          alu_src_b  = 1'b1;   // immediate
          imm_type   = IMM_I;
          alu_op     = ALU_ADD; // ALU computes rs1 + imm; top level masks bit0
          jalr       = 1'b1;
          result_src = RESULT_PC4;
        end else begin
          illegal = 1'b1;
        end
      end

      OP_CUSTOM0: begin
        // Phase 10: ACCEL.* custom accelerator-control instructions.
        // See docs/custom_extension.md for the encoding and
        // rtl/cpu/riscv_cpu_pipeline.sv's MEM stage for how accel_sel
        // is consumed -- this instruction's real destination address
        // and (for the START variants) its data are both HARDWIRED,
        // not computed by the ALU or read from rs2, so alu_src_a/
        // alu_src_b/alu_op/imm_type are simply left at their harmless
        // defaults above (their result is never observed for this
        // opcode -- see the MEM-stage override).
        case (funct3)
          F3_ACCEL_VECADD: begin
            mem_write = 1'b1;
            accel_sel = ACCEL_SEL_VECADD;
          end
          F3_ACCEL_DOT: begin
            mem_write = 1'b1;
            accel_sel = ACCEL_SEL_DOT;
          end
          F3_ACCEL_MATMUL: begin
            mem_write = 1'b1;
            accel_sel = ACCEL_SEL_MATMUL;
          end
          F3_ACCEL_STAT: begin
            // Reads the accelerator's STATUS register into rd, reusing
            // the existing RESULT_MEM writeback path -- functionally
            // identical to a LW's timing (including the load-use
            // hazard the hazard_unit already detects via mem_read),
            // just with a hardwired address instead of rs1+imm.
            reg_write  = 1'b1;
            mem_read   = 1'b1;
            result_src = RESULT_MEM;
            accel_sel  = ACCEL_SEL_STAT;
          end
          default: begin
            // funct3 values 100-111 are not defined for this custom-0
            // extension: diagnose rather than silently do nothing.
            illegal = 1'b1;
          end
        endcase
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
