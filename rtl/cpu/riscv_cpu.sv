`timescale 1ns/1ps
// riscv_cpu.sv
//
// Top-level single-cycle RV32I CPU. See docs/datapath.md for the full
// block diagram and an explanation of every mux. One instruction
// fetches, decodes, executes, accesses memory, and writes back within a
// single clock cycle -- there is exactly one instruction in flight at any
// time, so no hazard logic exists or is needed yet (that is Phase 5/6's
// job, once this design is proven correct and replaced/extended with a
// pipeline).
//
// Debug output ports (pc, instr, illegal, and the writeback bus) are
// exposed so testbenches can trace fetch/decode/execute/writeback and PC
// progression without relying on simulator-specific hierarchical
// references into internal state, per the Phase 2 requirement to show
// instruction fetch, decode, register values, ALU operation, PC
// progression, and the final result.

module riscv_cpu
  import riscv_pkg::*;
#(
  parameter int IMEM_DEPTH_WORDS = 1024,
  parameter      IMEM_INIT_FILE  = "",
  parameter int DMEM_DEPTH_WORDS = 1024
) (
  input  logic        clk,
  input  logic        rst_n,

  // Debug/trace outputs (Phase 2 visibility requirement; not part of the
  // architectural state a real program can read).
  output logic [31:0] dbg_pc,
  output logic [31:0] dbg_instr,
  output logic        dbg_reg_write,
  output logic [4:0]  dbg_rd_addr,
  output logic [31:0] dbg_rd_data,
  output logic [31:0] dbg_alu_result,
  output logic        dbg_illegal
);

  // -----------------------------------------------------------------
  // Program counter
  // -----------------------------------------------------------------
  // `pc` is given an explicit initial value (rather than relying solely
  // on the synchronous reset below) so that instruction fetch has a
  // well-defined address from time 0, not an X that only resolves at
  // the first posedge of clk. Without this, `pc` is X for the brief
  // window between simulation start and the first clock edge; that X
  // propagates through imem's address decode into `instr`/`opcode`,
  // and the control unit's `case (opcode)` correctly (but misleadingly)
  // falls through to its `illegal` default for an X opcode. Two
  // simulators can order that transient differently relative to
  // anything sampling `illegal` on the very first clock edge, which is
  // exactly the kind of simulator-dependent race a testbench should
  // never be able to observe. The synchronous reset (`if (!rst_n)`
  // below) remains the real, synthesizable reset behavior; this
  // initializer only removes an artificial pre-reset X window that
  // exists purely because this is a simulation, not real silicon.
  logic [31:0] pc = 32'b0;
  logic [31:0] next_pc, pc_plus4, pc_target;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pc <= 32'b0;
    else        pc <= next_pc;
  end

  assign pc_plus4 = pc + 32'd4;

  // -----------------------------------------------------------------
  // Fetch
  // -----------------------------------------------------------------
  logic [31:0] instr;

  imem #(
    .DEPTH_WORDS(IMEM_DEPTH_WORDS),
    .INIT_FILE  (IMEM_INIT_FILE)
  ) imem_inst (
    .addr (pc),
    .instr(instr)
  );

  // -----------------------------------------------------------------
  // Decode (field extraction)
  // -----------------------------------------------------------------
  logic [6:0] opcode;
  logic [4:0] rd_addr, rs1_addr, rs2_addr;
  logic [2:0] funct3;
  logic [6:0] funct7;

  decoder decoder_inst (
    .instr (instr),
    .opcode(opcode),
    .rd    (rd_addr),
    .funct3(funct3),
    .rs1   (rs1_addr),
    .rs2   (rs2_addr),
    .funct7(funct7)
  );

  // -----------------------------------------------------------------
  // Control unit
  // -----------------------------------------------------------------
  logic       reg_write, alu_src_a, alu_src_b, mem_read, mem_write;
  logic       branch, jal, jalr, illegal;
  logic [2:0] imm_type;
  logic [3:0] alu_op;
  logic [1:0] result_src;

  control_unit control_inst (
    .opcode    (opcode),
    .funct3    (funct3),
    .funct7    (funct7),
    .reg_write (reg_write),
    .alu_src_a (alu_src_a),
    .alu_src_b (alu_src_b),
    .imm_type  (imm_type),
    .alu_op    (alu_op),
    .mem_read  (mem_read),
    .mem_write (mem_write),
    .result_src(result_src),
    .branch    (branch),
    .jal       (jal),
    .jalr      (jalr),
    .illegal   (illegal)
  );

  // -----------------------------------------------------------------
  // Register file
  // -----------------------------------------------------------------
  logic [31:0] rs1_data, rs2_data, rd_wdata;

  regfile regfile_inst (
    .clk      (clk),
    .rst_n    (rst_n),
    .rs1_addr (rs1_addr),
    .rs2_addr (rs2_addr),
    .rd_addr  (rd_addr),
    .rd_data  (rd_wdata),
    .reg_write(reg_write),
    .rs1_data (rs1_data),
    .rs2_data (rs2_data)
  );

  // -----------------------------------------------------------------
  // Immediate generator
  // -----------------------------------------------------------------
  logic [31:0] imm_out;

  imm_gen imm_gen_inst (
    .instr   (instr),
    .imm_type(imm_type),
    .imm_out (imm_out)
  );

  assign pc_target = pc + imm_out; // branch / JAL target

  // -----------------------------------------------------------------
  // ALU
  // -----------------------------------------------------------------
  logic [31:0] alu_a, alu_b, alu_result;
  logic        alu_zero;

  assign alu_a = alu_src_a ? pc       : rs1_data;
  assign alu_b = alu_src_b ? imm_out  : rs2_data;

  alu alu_inst (
    .a     (alu_a),
    .b     (alu_b),
    .alu_op(alu_op),
    .result(alu_result),
    .zero  (alu_zero)
  );

  // -----------------------------------------------------------------
  // Branch resolution
  // -----------------------------------------------------------------
  logic branch_taken;

  branch_unit branch_unit_inst (
    .rs1_data    (rs1_data),
    .rs2_data    (rs2_data),
    .funct3      (funct3),
    .branch_taken(branch_taken)
  );

  // -----------------------------------------------------------------
  // Data memory
  // -----------------------------------------------------------------
  logic [31:0] dmem_rdata;

  dmem #(
    .DEPTH_WORDS(DMEM_DEPTH_WORDS)
  ) dmem_inst (
    .clk      (clk),
    .addr     (alu_result),
    .wdata    (rs2_data),
    .mem_read (mem_read),
    .mem_write(mem_write),
    .rdata    (dmem_rdata)
  );

  // -----------------------------------------------------------------
  // Writeback mux
  // -----------------------------------------------------------------
  always_comb begin
    case (result_src)
      RESULT_ALU: rd_wdata = alu_result;
      RESULT_MEM: rd_wdata = dmem_rdata;
      RESULT_PC4: rd_wdata = pc_plus4;
      default:    rd_wdata = alu_result;
    endcase
  end

  // -----------------------------------------------------------------
  // Next-PC selection
  //   JALR   -> (rs1 + imm) & ~1   (alu_result already computes rs1+imm
  //                                  for the JALR opcode; see control_unit)
  //   JAL, or taken branch -> PC + imm (pc_target)
  //   otherwise -> PC + 4
  // -----------------------------------------------------------------
  always_comb begin
    if (jalr)
      next_pc = {alu_result[31:1], 1'b0};
    else if (jal || (branch && branch_taken))
      next_pc = pc_target;
    else
      next_pc = pc_plus4;
  end

  // -----------------------------------------------------------------
  // Debug/trace outputs
  // -----------------------------------------------------------------
  assign dbg_pc         = pc;
  assign dbg_instr      = instr;
  assign dbg_reg_write  = reg_write;
  assign dbg_rd_addr    = rd_addr;
  assign dbg_rd_data    = rd_wdata;
  assign dbg_alu_result = alu_result;
  assign dbg_illegal    = illegal;

endmodule
