`timescale 1ns/1ps
// riscv_pkg.sv
//
// Shared constants for the RV32I datapath: instruction opcodes (exactly as
// specified in docs/riscv.md §3.8), internal ALU operation codes, and the
// mux-select encodings used to wire the single-cycle datapath in
// rtl/cpu/riscv_cpu.sv. Keeping these in one package means every module
// (decoder, control unit, ALU, immediate generator, CPU top level) agrees
// on the same encoding instead of repeating magic numbers.
//
// NOTE: ALU_PASSB and the mux-select parameters below are *microarchitectural*
// choices of this implementation, not part of the RISC-V ISA. Only the
// OP_* opcode values are architectural (they come directly from
// docs/riscv.md).

package riscv_pkg;

  // ---------------------------------------------------------------------
  // RV32I opcodes (instr[6:0]) -- see docs/riscv.md section 3.8
  // ---------------------------------------------------------------------
  parameter logic [6:0] OP_R      = 7'b0110011; // R-type ALU ops
  parameter logic [6:0] OP_IMM    = 7'b0010011; // I-type ALU ops
  parameter logic [6:0] OP_LOAD   = 7'b0000011; // LW
  parameter logic [6:0] OP_STORE  = 7'b0100011; // SW
  parameter logic [6:0] OP_BRANCH = 7'b1100011; // BEQ/BNE/BLT/BGE/BLTU/BGEU
  parameter logic [6:0] OP_LUI    = 7'b0110111; // LUI
  parameter logic [6:0] OP_AUIPC  = 7'b0010111; // AUIPC
  parameter logic [6:0] OP_JAL    = 7'b1101111; // JAL
  parameter logic [6:0] OP_JALR   = 7'b1100111; // JALR

  // ---------------------------------------------------------------------
  // Internal ALU operation codes (microarchitectural, not ISA-visible)
  // ---------------------------------------------------------------------
  parameter logic [3:0] ALU_ADD   = 4'b0000;
  parameter logic [3:0] ALU_SUB   = 4'b0001;
  parameter logic [3:0] ALU_SLL   = 4'b0010;
  parameter logic [3:0] ALU_SLT   = 4'b0011;
  parameter logic [3:0] ALU_SLTU  = 4'b0100;
  parameter logic [3:0] ALU_XOR   = 4'b0101;
  parameter logic [3:0] ALU_SRL   = 4'b0110;
  parameter logic [3:0] ALU_SRA   = 4'b0111;
  parameter logic [3:0] ALU_OR    = 4'b1000;
  parameter logic [3:0] ALU_AND   = 4'b1001;
  parameter logic [3:0] ALU_PASSB = 4'b1010; // result = b input, used for LUI

  // ---------------------------------------------------------------------
  // Immediate-format selector for imm_gen (see docs/riscv.md section 2.1)
  // ---------------------------------------------------------------------
  parameter logic [2:0] IMM_I = 3'b000;
  parameter logic [2:0] IMM_S = 3'b001;
  parameter logic [2:0] IMM_B = 3'b010;
  parameter logic [2:0] IMM_U = 3'b011;
  parameter logic [2:0] IMM_J = 3'b100;

  // ---------------------------------------------------------------------
  // Writeback source select (which value gets written back to rd)
  // ---------------------------------------------------------------------
  parameter logic [1:0] RESULT_ALU = 2'b00; // ALU output
  parameter logic [1:0] RESULT_MEM = 2'b01; // data memory read value (LW)
  parameter logic [1:0] RESULT_PC4 = 2'b10; // PC+4 (JAL/JALR return address)

endpackage
