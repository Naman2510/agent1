// tb_control_unit_decode.sv
//
// Exhaustive decode check for rtl/cpu/control_unit.sv's two ALU opcode
// classes, OP (R-type) and OP-IMM: every funct3 x every funct7 value
// (8 x 128 = 1024 encodings per opcode), against an independent
// reference model written here from the RV32I spec (docs/riscv.md),
// for both values of the ENABLE_MUL parameter.
//
// What it checks per encoding: `illegal` exactly when the spec says the
// encoding is not an instruction this core implements; when legal,
// `reg_write` set and `alu_op` equal to the spec's operation; when
// illegal, `reg_write` clear (an illegal instruction must not write a
// register -- the same "diagnosed, not executed" contract
// docs/datapath.md gives unsupported opcodes).
//
// Why exhaustive: the bug this was written to catch was that OP decoded
// only funct3 and funct7[5], so any other funct7 value -- including
// every RV32M encoding -- silently executed as an RV32I ALU op instead
// of raising `illegal`. A handful of spot checks would not have shown
// which neighbouring encodings were affected.

`timescale 1ns/1ps

module tb_control_unit_decode;
  import riscv_pkg::*;

  logic [6:0] opcode;
  logic [2:0] funct3;
  logic [6:0] funct7;

  // one control unit per ENABLE_MUL setting, both driven by the same fields
  logic       rw0, rw1, ill0, ill1;
  logic [3:0] op0, op1;

  control_unit #(.ENABLE_MUL(0)) cu_nomul (
    .opcode(opcode), .funct3(funct3), .funct7(funct7),
    .reg_write(rw0), .alu_src_a(), .alu_src_b(), .imm_type(), .alu_op(op0),
    .mem_read(), .mem_write(), .result_src(), .branch(), .jal(), .jalr(),
    .illegal(ill0), .accel_sel()
  );
  control_unit #(.ENABLE_MUL(1)) cu_mul (
    .opcode(opcode), .funct3(funct3), .funct7(funct7),
    .reg_write(rw1), .alu_src_a(), .alu_src_b(), .imm_type(), .alu_op(op1),
    .mem_read(), .mem_write(), .result_src(), .branch(), .jal(), .jalr(),
    .illegal(ill1), .accel_sel()
  );

  int errors = 0;
  int checked = 0;

  // Reference decode, written from the spec, independent of control_unit.sv.
  // Returns {legal, alu_op}: legal=1 if (opc, f3, f7) is an instruction this
  // core implements with the given ENABLE_MUL, with alu_op its operation.
  // (Packed into one return value because Icarus doesn't support output
  // arguments on functions.)
  function automatic logic [4:0] ref_decode(input logic [6:0] opc, input logic [2:0] f3,
                                            input logic [6:0] f7, input bit mul_en);
    logic [3:0] op;
    op = ALU_ADD;
    if (opc == OP_R) begin
      if (f7 == 7'b0000000) begin
        case (f3)
          3'b000: op = ALU_ADD;  3'b001: op = ALU_SLL;
          3'b010: op = ALU_SLT;  3'b011: op = ALU_SLTU;
          3'b100: op = ALU_XOR;  3'b101: op = ALU_SRL;
          3'b110: op = ALU_OR;   3'b111: op = ALU_AND;
        endcase
        return {1'b1, op};
      end
      if (f7 == 7'b0100000 && f3 == 3'b000) return {1'b1, ALU_SUB};
      if (f7 == 7'b0100000 && f3 == 3'b101) return {1'b1, ALU_SRA};
      if (mul_en && f7 == 7'b0000001 && f3 == 3'b000) return {1'b1, ALU_MUL};
      return {1'b0, op};
    end
    // OP-IMM: funct7 is immediate bits [11:5], free for every funct3
    // except the two shift-immediate encodings, where it must be 0
    // (SLLI/SRLI) or 0100000 (SRAI).
    case (f3)
      3'b000: op = ALU_ADD;  3'b010: op = ALU_SLT;  3'b011: op = ALU_SLTU;
      3'b100: op = ALU_XOR;  3'b110: op = ALU_OR;   3'b111: op = ALU_AND;
      3'b001: begin
        if (f7 != 7'b0000000) return {1'b0, op};
        op = ALU_SLL;
      end
      3'b101: begin
        if (f7 == 7'b0000000) op = ALU_SRL;
        else if (f7 == 7'b0100000) op = ALU_SRA;
        else return {1'b0, op};
      end
    endcase
    return {1'b1, op};
  endfunction

  task automatic check_one(input string tag, input bit mul_en,
                           input logic rw, input logic ill, input logic [3:0] op);
    logic [4:0] ref_out;
    logic [3:0] exp_op;
    bit legal;
    ref_out = ref_decode(opcode, funct3, funct7, mul_en);
    legal = ref_out[4];
    exp_op = ref_out[3:0];
    checked++;
    if (ill !== !legal || rw !== legal || (legal && op !== exp_op)) begin
      if (errors < 20)
        $display("  [FAIL] %s opcode=%b f3=%b f7=%b: illegal=%b reg_write=%b alu_op=%0d, expected illegal=%b reg_write=%b alu_op=%0d",
                 tag, opcode, funct3, funct7, ill, rw, op, !legal, legal, exp_op);
      errors++;
    end
  endtask

  initial begin
    $display("=== control_unit OP / OP-IMM exhaustive decode check ===");
    #1;
    for (int k = 0; k < 2; k++) begin
      for (int f3 = 0; f3 < 8; f3++) begin
        for (int f7 = 0; f7 < 128; f7++) begin
          opcode = (k == 0) ? OP_R : OP_IMM;
          funct3 = f3[2:0];
          funct7 = f7[6:0];
          #1;
          check_one("ENABLE_MUL=0", 1'b0, rw0, ill0, op0);
          check_one("ENABLE_MUL=1", 1'b1, rw1, ill1, op1);
        end
      end
    end
    $display("  %0d decode checks", checked);
    if (errors == 0) $display("RESULT: ALL CHECKS PASSED");
    else             $display("RESULT: %0d CHECK(S) FAILED", errors);
    $finish;
  end

endmodule
