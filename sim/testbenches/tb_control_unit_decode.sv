// tb_control_unit_decode.sv
//
// Exhaustive decode check for rtl/cpu/control_unit.sv: EVERY combination
// of opcode x funct3 x funct7 (2^17 = 131,072 encodings), for both values
// of the ENABLE_MUL parameter, against an independent reference model
// written here from the spec (docs/riscv.md, docs/custom_extension.md).
// rd/rs1/rs2 never affect decode, so this is the complete decode space.
//
// Per encoding:
//   - `illegal` exactly when the encoding is not an instruction this core
//     implements;
//   - an illegal encoding must have NO side effect: reg_write, mem_read,
//     mem_write, branch, jal and jalr all clear, accel_sel = NONE (the
//     "diagnosed, not executed" contract docs/datapath.md gives illegal
//     instructions);
//   - a legal encoding must drive exactly the side-effect signals its
//     instruction needs, and the right alu_op wherever the ALU result is
//     used (OP, OP-IMM, LOAD/STORE address, LUI, AUIPC, JALR target).
//
// History: the first version swept only OP and OP-IMM and found that
// funct7 was never validated there (any RV32M encoding executed as an
// RV32I op). Widening it to the full space found the same gap in four
// more opcodes -- LOAD and STORE never checked funct3, so LB/LH/LBU/LHU
// executed as LW and SB/SH as a full-word SW; BRANCH funct3 010/011
// decoded as a never-taken branch; JALR never checked funct3. See
// docs/rv32m_mul.md.

`timescale 1ns/1ps

module tb_control_unit_decode;
  import riscv_pkg::*;

  logic [6:0] opcode;
  logic [2:0] funct3;
  logic [6:0] funct7;

  logic       rw0, mr0, mw0, br0, jal0, jalr0, ill0;
  logic       rw1, mr1, mw1, br1, jal1, jalr1, ill1;
  logic [3:0] op0, op1;
  logic [2:0] acc0, acc1;

  control_unit #(.ENABLE_MUL(0)) cu_nomul (
    .opcode(opcode), .funct3(funct3), .funct7(funct7),
    .reg_write(rw0), .alu_src_a(), .alu_src_b(), .imm_type(), .alu_op(op0),
    .mem_read(mr0), .mem_write(mw0), .result_src(), .branch(br0), .jal(jal0), .jalr(jalr0),
    .illegal(ill0), .accel_sel(acc0)
  );
  control_unit #(.ENABLE_MUL(1)) cu_mul (
    .opcode(opcode), .funct3(funct3), .funct7(funct7),
    .reg_write(rw1), .alu_src_a(), .alu_src_b(), .imm_type(), .alu_op(op1),
    .mem_read(mr1), .mem_write(mw1), .result_src(), .branch(br1), .jal(jal1), .jalr(jalr1),
    .illegal(ill1), .accel_sel(acc1)
  );

  int errors = 0;
  int checked = 0;
  int legal_nomul = 0, legal_mul = 0;

  // Packed expectation (Icarus has no function output args):
  // [15] legal  [14] check_alu_op  [13] reg_write  [12] mem_read  [11] mem_write
  // [10] branch [9] jal  [8] jalr  [7:4] alu_op  [3:1] accel_sel  [0] unused
  function automatic logic [15:0] pack(input bit legal, input bit chk_op, input bit rw,
                                       input bit mr, input bit mw, input bit br,
                                       input bit jl, input bit jr, input logic [3:0] op,
                                       input logic [2:0] acc);
    return {legal, chk_op, rw, mr, mw, br, jl, jr, op, acc, 1'b0};
  endfunction

  function automatic logic [3:0] arith_op(input logic [2:0] f3);
    case (f3)
      3'b000: return ALU_ADD;  3'b001: return ALU_SLL;
      3'b010: return ALU_SLT;  3'b011: return ALU_SLTU;
      3'b100: return ALU_XOR;  3'b101: return ALU_SRL;
      3'b110: return ALU_OR;   default: return ALU_AND;
    endcase
  endfunction

  localparam logic [15:0] ILLEGAL = 16'h0000;  // legal=0, every side effect 0, accel NONE

  // Reference decode, written from the spec, independent of control_unit.sv.
  function automatic logic [15:0] ref_decode(input logic [6:0] opc, input logic [2:0] f3,
                                             input logic [6:0] f7, input bit mul_en);
    case (opc)
      OP_R: begin
        if (f7 == 7'b0000000)                   return pack(1,1, 1,0,0,0,0,0, arith_op(f3), ACCEL_SEL_NONE);
        if (f7 == 7'b0100000 && f3 == 3'b000)    return pack(1,1, 1,0,0,0,0,0, ALU_SUB,      ACCEL_SEL_NONE);
        if (f7 == 7'b0100000 && f3 == 3'b101)    return pack(1,1, 1,0,0,0,0,0, ALU_SRA,      ACCEL_SEL_NONE);
        if (mul_en && f7 == 7'b0000001 && f3 == 3'b000)
                                                 return pack(1,1, 1,0,0,0,0,0, ALU_MUL,      ACCEL_SEL_NONE);
        return ILLEGAL;
      end
      OP_IMM: begin  // funct7 is immediate data except for the shift-immediates
        if (f3 == 3'b001) return (f7 == 7'b0000000) ? pack(1,1, 1,0,0,0,0,0, ALU_SLL, ACCEL_SEL_NONE) : ILLEGAL;
        if (f3 == 3'b101) begin
          if (f7 == 7'b0000000) return pack(1,1, 1,0,0,0,0,0, ALU_SRL, ACCEL_SEL_NONE);
          if (f7 == 7'b0100000) return pack(1,1, 1,0,0,0,0,0, ALU_SRA, ACCEL_SEL_NONE);
          return ILLEGAL;
        end
        return pack(1,1, 1,0,0,0,0,0, arith_op(f3), ACCEL_SEL_NONE);
      end
      OP_LOAD:   return (f3 == 3'b010) ? pack(1,1, 1,1,0,0,0,0, ALU_ADD, ACCEL_SEL_NONE) : ILLEGAL; // LW only
      OP_STORE:  return (f3 == 3'b010) ? pack(1,1, 0,0,1,0,0,0, ALU_ADD, ACCEL_SEL_NONE) : ILLEGAL; // SW only
      OP_BRANCH: return (f3 == 3'b010 || f3 == 3'b011) ? ILLEGAL
                                                        : pack(1,0, 0,0,0,1,0,0, ALU_ADD, ACCEL_SEL_NONE);
      OP_LUI:    return pack(1,1, 1,0,0,0,0,0, ALU_PASSB, ACCEL_SEL_NONE);
      OP_AUIPC:  return pack(1,1, 1,0,0,0,0,0, ALU_ADD,   ACCEL_SEL_NONE);
      OP_JAL:    return pack(1,0, 1,0,0,0,1,0, ALU_ADD,   ACCEL_SEL_NONE);
      OP_JALR:   return (f3 == 3'b000) ? pack(1,1, 1,0,0,0,0,1, ALU_ADD, ACCEL_SEL_NONE) : ILLEGAL;
      OP_CUSTOM0: begin
        case (f3)
          F3_ACCEL_VECADD: return pack(1,0, 0,0,1,0,0,0, ALU_ADD, ACCEL_SEL_VECADD);
          F3_ACCEL_DOT:    return pack(1,0, 0,0,1,0,0,0, ALU_ADD, ACCEL_SEL_DOT);
          F3_ACCEL_MATMUL: return pack(1,0, 0,0,1,0,0,0, ALU_ADD, ACCEL_SEL_MATMUL);
          F3_ACCEL_STAT:   return pack(1,0, 1,1,0,0,0,0, ALU_ADD, ACCEL_SEL_STAT);
          default:         return ILLEGAL;
        endcase
      end
      default: return ILLEGAL;
    endcase
  endfunction

  task automatic check_one(input string tag, input bit mul_en,
                           input logic rw, input logic mr, input logic mw, input logic br,
                           input logic jl, input logic jr, input logic ill,
                           input logic [3:0] op, input logic [2:0] acc);
    logic [15:0] e;
    bit bad;
    e = ref_decode(opcode, funct3, funct7, mul_en);
    checked++;
    if (e[15]) begin
      if (mul_en) legal_mul++; else legal_nomul++;
    end
    bad = (ill !== !e[15]) || (rw !== e[13]) || (mr !== e[12]) || (mw !== e[11])
       || (br !== e[10]) || (jl !== e[9]) || (jr !== e[8]) || (acc !== e[3:1])
       || (e[15] && e[14] && op !== e[7:4]);
    if (bad) begin
      if (errors < 25)
        $display("  [FAIL] %s opcode=%b f3=%b f7=%b: got ill=%b rw=%b mr=%b mw=%b br=%b jal=%b jalr=%b op=%0d acc=%0d; expected ill=%b rw=%b mr=%b mw=%b br=%b jal=%b jalr=%b op=%0d acc=%0d",
                 tag, opcode, funct3, funct7, ill, rw, mr, mw, br, jl, jr, op, acc,
                 !e[15], e[13], e[12], e[11], e[10], e[9], e[8], e[7:4], e[3:1]);
      errors++;
    end
  endtask

  initial begin
    $display("=== control_unit exhaustive decode check: every opcode x funct3 x funct7 ===");
    #1;
    for (int opc = 0; opc < 128; opc++) begin
      for (int f3 = 0; f3 < 8; f3++) begin
        for (int f7 = 0; f7 < 128; f7++) begin
          opcode = opc[6:0];
          funct3 = f3[2:0];
          funct7 = f7[6:0];
          #1;
          check_one("ENABLE_MUL=0", 1'b0, rw0, mr0, mw0, br0, jal0, jalr0, ill0, op0, acc0);
          check_one("ENABLE_MUL=1", 1'b1, rw1, mr1, mw1, br1, jal1, jalr1, ill1, op1, acc1);
        end
      end
    end
    $display("  %0d decode checks; legal encodings: %0d (ENABLE_MUL=0), %0d (ENABLE_MUL=1)",
             checked, legal_nomul, legal_mul);
    if (errors == 0) $display("RESULT: ALL CHECKS PASSED");
    else             $display("RESULT: %0d CHECK(S) FAILED", errors);
    $finish;
  end

endmodule
