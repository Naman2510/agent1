`timescale 1ns/1ps
// riscv_cpu_pipeline.sv
//
// Phase 5: five-stage pipelined RV32I CPU (IF / ID / EX / MEM / WB).
// Reuses every submodule the single-cycle CPU (rtl/cpu/riscv_cpu.sv,
// Phase 2) already implemented and verified (decoder, control_unit,
// regfile, imm_gen, alu, branch_unit, imem, dmem) -- only the datapath
// wiring around them changes, split across four pipeline registers
// (rtl/pipeline/if_id_reg.sv, id_ex_reg.sv, ex_mem_reg.sv,
// mem_wb_reg.sv). The single-cycle CPU is left untouched so Phases 2-4
// keep passing against it unmodified; this is a new, separate top-level
// module, not a replacement, per the task's "replace/extend" wording.
//
// See docs/pipeline.md for the full stage-by-stage explanation,
// register contents, and -- importantly -- what this phase deliberately
// does NOT yet handle: data hazards (RAW hazards closer than 3
// instructions apart) and control hazards (branches/JAL/JALR do
// redirect the PC correctly, but the 2 instructions already fetched
// from the wrong path before that redirect are NOT flushed and will
// incorrectly execute). Both are Phase 6's job
// (forwarding/stalling/flush); Phase 5's own test suite
// (sim/programs/pipeline_tests/) is deliberately restricted to
// straight-line code with enough instruction spacing to avoid both, so
// that what Phase 5 verifies is the pipeline plumbing itself.

module riscv_cpu_pipeline
  import riscv_pkg::*;
#(
  parameter int IMEM_DEPTH_WORDS = 1024,
  parameter      IMEM_INIT_FILE  = "",
  parameter int DMEM_DEPTH_WORDS = 1024
) (
  input  logic        clk,
  input  logic        rst_n,

  // Debug/trace outputs: one (pc, instr) pair per stage, so a testbench
  // can show five different instructions occupying five different
  // stages in the same cycle -- the actual, observable point of
  // pipelining (see sim/testbenches/tb_pipeline.sv) -- plus the WB-stage
  // writeback bus and an illegal-opcode flag, matching the visibility
  // convention established in Phase 2 (rtl/cpu/riscv_cpu.sv).
  output logic [31:0] dbg_if_pc,    output logic [31:0] dbg_if_instr,
  output logic [31:0] dbg_id_pc,    output logic [31:0] dbg_id_instr,
  output logic [31:0] dbg_ex_pc,    output logic [31:0] dbg_ex_instr,
  output logic [31:0] dbg_mem_instr,
  output logic [31:0] dbg_wb_instr,
  output logic         dbg_reg_write,
  output logic [4:0]  dbg_rd_addr,
  output logic [31:0] dbg_rd_data,
  output logic        dbg_illegal
);

  // ===================================================================
  // IF stage
  // ===================================================================
  logic [31:0] pc = 32'b0; // explicit initializer: see rtl/cpu/riscv_cpu.sv
  logic [31:0] next_pc, pc_plus4_if, instr_if;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pc <= 32'b0;
    else        pc <= next_pc;
  end

  assign pc_plus4_if = pc + 32'd4;

  imem #(
    .DEPTH_WORDS(IMEM_DEPTH_WORDS),
    .INIT_FILE  (IMEM_INIT_FILE)
  ) imem_inst (
    .addr (pc),
    .instr(instr_if)
  );

  // ===================================================================
  // IF/ID
  // ===================================================================
  logic [31:0] pc_id, pc_plus4_id, instr_id;

  if_id_reg if_id_inst (
    .clk(clk), .rst_n(rst_n),
    .pc_in(pc), .pc_plus4_in(pc_plus4_if), .instr_in(instr_if),
    .pc_out(pc_id), .pc_plus4_out(pc_plus4_id), .instr_out(instr_id)
  );

  // ===================================================================
  // ID stage
  // ===================================================================
  logic [6:0] opcode_id;
  logic [4:0] rd_id, rs1_id, rs2_id;
  logic [2:0] funct3_id;
  logic [6:0] funct7_id;

  decoder decoder_inst (
    .instr (instr_id),
    .opcode(opcode_id), .rd(rd_id), .funct3(funct3_id),
    .rs1(rs1_id), .rs2(rs2_id), .funct7(funct7_id)
  );

  logic       reg_write_id, alu_src_a_id, alu_src_b_id, mem_read_id, mem_write_id;
  logic       branch_id, jal_id, jalr_id, illegal_id;
  logic [2:0] imm_type_id;
  logic [3:0] alu_op_id;
  logic [1:0] result_src_id;

  control_unit control_inst (
    .opcode(opcode_id), .funct3(funct3_id), .funct7(funct7_id),
    .reg_write(reg_write_id), .alu_src_a(alu_src_a_id), .alu_src_b(alu_src_b_id),
    .imm_type(imm_type_id), .alu_op(alu_op_id),
    .mem_read(mem_read_id), .mem_write(mem_write_id), .result_src(result_src_id),
    .branch(branch_id), .jal(jal_id), .jalr(jalr_id), .illegal(illegal_id)
  );

  logic [31:0] rs1_data_id, rs2_data_id;

  // Write port (rd_addr_wb/rd_wdata_wb/reg_write_wb) driven by the WB
  // stage below. This regfile's write (posedge clk, nonblocking) and
  // this ID stage's read feeding id_ex_reg's OWN posedge-clk capture
  // are two flip-flops racing on the same clock edge whenever the
  // producer's WB and this consumer's ID happen to land in the same
  // cycle -- Verilog resolves that race to the PRE-write value, not the
  // new one (nonblocking RHS evaluation for every block sensitive to an
  // edge uses pre-edge values, regardless of write-vs-read intent). So
  // this does NOT forward a value from an instruction 3 positions
  // behind its producer, only from 4 or more positions behind, where
  // the producer's WB has already fully committed and settled a whole
  // clock period earlier. See docs/pipeline.md for the cycle-by-cycle
  // account (verified empirically against simulation, not just
  // reasoned about) and what Phase 6's forwarding unit adds for
  // anything closer than that.
  logic [31:0] rd_wdata_wb;
  logic [4:0]  rd_addr_wb;
  logic        reg_write_wb;

  regfile regfile_inst (
    .clk(clk), .rst_n(rst_n),
    .rs1_addr(rs1_id), .rs2_addr(rs2_id),
    .rd_addr(rd_addr_wb), .rd_data(rd_wdata_wb), .reg_write(reg_write_wb),
    .rs1_data(rs1_data_id), .rs2_data(rs2_data_id)
  );

  logic [31:0] imm_out_id;

  imm_gen imm_gen_inst (
    .instr(instr_id), .imm_type(imm_type_id), .imm_out(imm_out_id)
  );

  // ===================================================================
  // ID/EX
  // ===================================================================
  logic [31:0] pc_ex, pc_plus4_ex, rs1_data_ex, rs2_data_ex, imm_out_ex, instr_ex;
  logic [4:0]  rd_ex, rs1_addr_ex, rs2_addr_ex;
  logic [2:0]  funct3_ex;
  logic        reg_write_ex, alu_src_a_ex, alu_src_b_ex, mem_read_ex, mem_write_ex;
  logic        branch_ex, jal_ex, jalr_ex, illegal_ex;
  logic [3:0]  alu_op_ex;
  logic [1:0]  result_src_ex;

  id_ex_reg id_ex_inst (
    .clk(clk), .rst_n(rst_n),
    .pc_in(pc_id), .pc_plus4_in(pc_plus4_id),
    .rs1_data_in(rs1_data_id), .rs2_data_in(rs2_data_id), .imm_out_in(imm_out_id),
    .rd_addr_in(rd_id), .rs1_addr_in(rs1_id), .rs2_addr_in(rs2_id),
    .funct3_in(funct3_id),
    .reg_write_in(reg_write_id), .alu_src_a_in(alu_src_a_id), .alu_src_b_in(alu_src_b_id),
    .alu_op_in(alu_op_id), .mem_read_in(mem_read_id), .mem_write_in(mem_write_id),
    .result_src_in(result_src_id), .branch_in(branch_id), .jal_in(jal_id),
    .jalr_in(jalr_id), .illegal_in(illegal_id), .instr_dbg_in(instr_id),

    .pc_out(pc_ex), .pc_plus4_out(pc_plus4_ex),
    .rs1_data_out(rs1_data_ex), .rs2_data_out(rs2_data_ex), .imm_out_out(imm_out_ex),
    .rd_addr_out(rd_ex), .rs1_addr_out(rs1_addr_ex), .rs2_addr_out(rs2_addr_ex),
    .funct3_out(funct3_ex),
    .reg_write_out(reg_write_ex), .alu_src_a_out(alu_src_a_ex), .alu_src_b_out(alu_src_b_ex),
    .alu_op_out(alu_op_ex), .mem_read_out(mem_read_ex), .mem_write_out(mem_write_ex),
    .result_src_out(result_src_ex), .branch_out(branch_ex), .jal_out(jal_ex),
    .jalr_out(jalr_ex), .illegal_out(illegal_ex), .instr_dbg_out(instr_ex)
  );

  // ===================================================================
  // EX stage
  // ===================================================================
  logic [31:0] alu_a_ex, alu_b_ex, alu_result_ex;
  logic        alu_zero_ex;

  assign alu_a_ex = alu_src_a_ex ? pc_ex      : rs1_data_ex;
  assign alu_b_ex = alu_src_b_ex ? imm_out_ex : rs2_data_ex;

  alu alu_inst (
    .a(alu_a_ex), .b(alu_b_ex), .alu_op(alu_op_ex),
    .result(alu_result_ex), .zero(alu_zero_ex)
  );

  logic branch_taken_ex;

  branch_unit branch_unit_inst (
    .rs1_data(rs1_data_ex), .rs2_data(rs2_data_ex), .funct3(funct3_ex),
    .branch_taken(branch_taken_ex)
  );

  logic [31:0] pc_target_ex;
  assign pc_target_ex = pc_ex + imm_out_ex;

  // Branch/jump resolution happens here, in EX -- and the redirect it
  // produces IS correctly computed and DOES change next_pc (below).
  // What Phase 5 does not do is flush the two instructions already
  // fetched from the sequential (wrong) path while this redirect was in
  // flight through ID and EX; those will incorrectly continue through
  // the pipeline. See the module header comment and docs/pipeline.md.
  logic        ex_redirect_valid;
  logic [31:0] ex_redirect_target;

  assign ex_redirect_valid  = jal_ex || jalr_ex || (branch_ex && branch_taken_ex);
  assign ex_redirect_target = jalr_ex ? {alu_result_ex[31:1], 1'b0} : pc_target_ex;

  assign next_pc = ex_redirect_valid ? ex_redirect_target : pc_plus4_if;

  // ===================================================================
  // EX/MEM
  // ===================================================================
  logic [31:0] pc_plus4_mem, alu_result_mem, rs2_data_mem, instr_mem;
  logic [4:0]  rd_mem;
  logic        reg_write_mem, mem_read_mem, mem_write_mem, illegal_mem;
  logic [1:0]  result_src_mem;

  ex_mem_reg ex_mem_inst (
    .clk(clk), .rst_n(rst_n),
    .pc_plus4_in(pc_plus4_ex), .alu_result_in(alu_result_ex), .rs2_data_in(rs2_data_ex),
    .rd_addr_in(rd_ex), .reg_write_in(reg_write_ex), .mem_read_in(mem_read_ex),
    .mem_write_in(mem_write_ex), .result_src_in(result_src_ex), .illegal_in(illegal_ex),
    .instr_dbg_in(instr_ex),

    .pc_plus4_out(pc_plus4_mem), .alu_result_out(alu_result_mem), .rs2_data_out(rs2_data_mem),
    .rd_addr_out(rd_mem), .reg_write_out(reg_write_mem), .mem_read_out(mem_read_mem),
    .mem_write_out(mem_write_mem), .result_src_out(result_src_mem), .illegal_out(illegal_mem),
    .instr_dbg_out(instr_mem)
  );

  // ===================================================================
  // MEM stage
  // ===================================================================
  logic [31:0] dmem_rdata_mem;

  dmem #(
    .DEPTH_WORDS(DMEM_DEPTH_WORDS)
  ) dmem_inst (
    .clk(clk), .addr(alu_result_mem), .wdata(rs2_data_mem),
    .mem_read(mem_read_mem), .mem_write(mem_write_mem), .rdata(dmem_rdata_mem)
  );

  // ===================================================================
  // MEM/WB
  // ===================================================================
  logic [31:0] pc_plus4_wb, alu_result_wb, mem_rdata_wb, instr_wb;
  logic        illegal_wb;
  logic [1:0]  result_src_wb;

  mem_wb_reg mem_wb_inst (
    .clk(clk), .rst_n(rst_n),
    .pc_plus4_in(pc_plus4_mem), .alu_result_in(alu_result_mem), .mem_rdata_in(dmem_rdata_mem),
    .rd_addr_in(rd_mem), .reg_write_in(reg_write_mem), .result_src_in(result_src_mem),
    .illegal_in(illegal_mem), .instr_dbg_in(instr_mem),

    .pc_plus4_out(pc_plus4_wb), .alu_result_out(alu_result_wb), .mem_rdata_out(mem_rdata_wb),
    .rd_addr_out(rd_addr_wb), .reg_write_out(reg_write_wb), .result_src_out(result_src_wb),
    .illegal_out(illegal_wb), .instr_dbg_out(instr_wb)
  );

  // ===================================================================
  // WB stage
  // ===================================================================
  always_comb begin
    case (result_src_wb)
      RESULT_ALU: rd_wdata_wb = alu_result_wb;
      RESULT_MEM: rd_wdata_wb = mem_rdata_wb;
      RESULT_PC4: rd_wdata_wb = pc_plus4_wb;
      default:    rd_wdata_wb = alu_result_wb;
    endcase
  end

  // ===================================================================
  // Debug/trace outputs
  // ===================================================================
  assign dbg_if_pc     = pc;
  assign dbg_if_instr  = instr_if;
  assign dbg_id_pc     = pc_id;
  assign dbg_id_instr  = instr_id;
  assign dbg_ex_pc     = pc_ex;
  assign dbg_ex_instr  = instr_ex;
  assign dbg_mem_instr = instr_mem;
  assign dbg_wb_instr  = instr_wb;

  assign dbg_reg_write = reg_write_wb;
  assign dbg_rd_addr   = rd_addr_wb;
  assign dbg_rd_data   = rd_wdata_wb;
  assign dbg_illegal   = illegal_id; // this cycle's freshly-decoded instruction

endmodule
