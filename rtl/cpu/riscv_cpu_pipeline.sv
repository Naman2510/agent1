`timescale 1ns/1ps
// riscv_cpu_pipeline.sv
//
// Five-stage pipelined RV32I CPU (IF / ID / EX / MEM / WB). Reuses every
// submodule the single-cycle CPU (rtl/cpu/riscv_cpu.sv, Phase 2) already
// implemented and verified (decoder, control_unit, regfile, imm_gen,
// alu, branch_unit, imem, dmem) -- only the datapath wiring around them
// changes, split across four pipeline registers (rtl/pipeline/
// if_id_reg.sv, id_ex_reg.sv, ex_mem_reg.sv, mem_wb_reg.sv). The
// single-cycle CPU is left untouched so Phases 2-4 keep passing against
// it unmodified; this pipelined CPU is a separate top-level module, not
// a replacement, per the task's "replace/extend" wording.
//
// This module is built up across three phases:
//   Phase 5 built the five stages and pipeline registers with NO hazard
//     handling (see CHANGELOG.md and git history for that milestone).
//   Phase 6 added data-hazard forwarding (rtl/pipeline/
//     forwarding_unit.sv), the load-use stall, and the branch/JAL/JALR
//     flush (both from rtl/pipeline/hazard_unit.sv).
//   Phase 7 (this version) adds free-running performance counters
//     (rtl/cpu/perf_counters.sv) -- purely observational, no feedback
//     into the datapath -- and a `valid` bit threaded through every
//     pipeline register (see id_ex_reg.sv's header comment) so
//     "instructions retired" can be counted without miscounting
//     bubbles.
// Unlike Phase 2 -> Phase 5 (a genuinely different microarchitecture
// kept side by side for comparison), Phases 6 and 7 evolve THIS SAME
// pipeline in place, because the task frames both as completing this
// pipeline, not building another one -- and Phase 5's own straight-line,
// branch-free test program (sim/programs/pipeline_straightline.s)
// continues to pass unchanged here, since it was constructed to have no
// hazards for forwarding/stalling/flushing to ever engage on. See
// docs/pipeline.md for the full explanation of all three phases,
// including a same-clock-edge race found and fixed during Phase 5's own
// verification and the hazard-by-hazard account of Phase 6.

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
  // convention established in Phase 2 (rtl/cpu/riscv_cpu.sv), and the
  // Phase 6 hazard signals so a testbench can show exactly when a stall
  // or flush fires.
  output logic [31:0] dbg_if_pc,    output logic [31:0] dbg_if_instr,
  output logic [31:0] dbg_id_pc,    output logic [31:0] dbg_id_instr,
  output logic [31:0] dbg_ex_pc,    output logic [31:0] dbg_ex_instr,
  output logic [31:0] dbg_mem_instr,
  output logic [31:0] dbg_wb_instr,
  output logic        dbg_reg_write,
  output logic [4:0]  dbg_rd_addr,
  output logic [31:0] dbg_rd_data,
  output logic        dbg_illegal,
  output logic        dbg_stall,
  output logic        dbg_flush,

  // Phase 7 performance counters (rtl/cpu/perf_counters.sv) -- see
  // docs/pipeline.md's Phase 7 section for what each one measures and
  // how CPI is derived from them in software.
  output logic [31:0] perf_cycle_count,
  output logic [31:0] perf_instr_retired_count,
  output logic [31:0] perf_stall_count,
  output logic [31:0] perf_branch_count,
  output logic [31:0] perf_branch_taken_count,
  output logic [31:0] perf_load_use_stall_count,
  output logic [31:0] perf_forwarding_event_count,
  output logic [31:0] perf_flush_count
);

  // ===================================================================
  // Hazard control (computed here at the top so every stage below can
  // reference it; see rtl/pipeline/hazard_unit.sv for what each signal
  // means and why load-use and branch-flush can never collide)
  // ===================================================================
  logic pc_stall, if_id_stall, if_id_flush, id_ex_flush;
  logic ex_redirect_valid; // driven by the EX stage further down

  // ===================================================================
  // IF stage
  // ===================================================================
  logic [31:0] pc = 32'b0; // explicit initializer: see rtl/cpu/riscv_cpu.sv
  logic [31:0] next_pc, pc_plus4_if, instr_if;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)          pc <= 32'b0;
    else if (pc_stall)   ; // hold: load-use hazard, wait for it to clear
    else                 pc <= next_pc;
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
    .clk(clk), .rst_n(rst_n), .stall(if_id_stall), .flush(if_id_flush),
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
  // stage below. BYPASS_WRITE_TO_READ=1 here is what makes a RAW
  // dependency exactly 2 instructions apart correct: without it, this
  // regfile's write (posedge clk, nonblocking) and this ID stage's read
  // feeding id_ex_reg's OWN posedge-clk capture are two flip-flops
  // racing on the same clock edge for that exact gap, which Verilog
  // resolves to the pre-write value -- found and explained in full,
  // including why it's specifically gap=2 and not some other distance,
  // in regfile.sv's header comment and docs/pipeline.md. A gap of 0 or
  // 1 is handled by the EX-stage forwarding_unit below instead (the
  // producer's value isn't in the register file yet at all in those
  // cases); a gap of 3 or more needs neither mechanism, since the
  // write has then settled a full clock period before this read, with
  // no same-edge ambiguity.
  logic [31:0] rd_wdata_wb;
  logic [4:0]  rd_addr_wb;
  logic        reg_write_wb;

  regfile #(
    .BYPASS_WRITE_TO_READ(1'b1)
  ) regfile_inst (
    .clk(clk), .rst_n(rst_n),
    .rs1_addr(rs1_id), .rs2_addr(rs2_id),
    .rd_addr(rd_addr_wb), .rd_data(rd_wdata_wb), .reg_write(reg_write_wb),
    .rs1_data(rs1_data_id), .rs2_data(rs2_data_id)
  );

  logic [31:0] imm_out_id;

  imm_gen imm_gen_inst (
    .instr(instr_id), .imm_type(imm_type_id), .imm_out(imm_out_id)
  );

  // Phase 7: true iff this is a real instruction, not a bubble. Every
  // supported opcode (docs/riscv.md section 3.8) sets at least one of
  // these five signals, and a bubble's control signals are all zero by
  // construction -- see id_ex_reg.sv's header comment for the full
  // reasoning and why this is computed once here and threaded through
  // rather than re-derived at each stage.
  logic valid_id;
  assign valid_id = reg_write_id | mem_write_id | branch_id | jal_id | jalr_id;

  // ===================================================================
  // ID/EX
  // ===================================================================
  logic [31:0] pc_ex, pc_plus4_ex, rs1_data_ex, rs2_data_ex, imm_out_ex, instr_ex;
  logic [4:0]  rd_ex, rs1_addr_ex, rs2_addr_ex;
  logic [2:0]  funct3_ex;
  logic        reg_write_ex, alu_src_a_ex, alu_src_b_ex, mem_read_ex, mem_write_ex;
  logic        branch_ex, jal_ex, jalr_ex, illegal_ex, valid_ex;
  logic [3:0]  alu_op_ex;
  logic [1:0]  result_src_ex;

  id_ex_reg id_ex_inst (
    .clk(clk), .rst_n(rst_n), .flush(id_ex_flush),
    .pc_in(pc_id), .pc_plus4_in(pc_plus4_id),
    .rs1_data_in(rs1_data_id), .rs2_data_in(rs2_data_id), .imm_out_in(imm_out_id),
    .rd_addr_in(rd_id), .rs1_addr_in(rs1_id), .rs2_addr_in(rs2_id),
    .funct3_in(funct3_id),
    .reg_write_in(reg_write_id), .alu_src_a_in(alu_src_a_id), .alu_src_b_in(alu_src_b_id),
    .alu_op_in(alu_op_id), .mem_read_in(mem_read_id), .mem_write_in(mem_write_id),
    .result_src_in(result_src_id), .branch_in(branch_id), .jal_in(jal_id),
    .jalr_in(jalr_id), .illegal_in(illegal_id), .instr_dbg_in(instr_id), .valid_in(valid_id),

    .pc_out(pc_ex), .pc_plus4_out(pc_plus4_ex),
    .rs1_data_out(rs1_data_ex), .rs2_data_out(rs2_data_ex), .imm_out_out(imm_out_ex),
    .rd_addr_out(rd_ex), .rs1_addr_out(rs1_addr_ex), .rs2_addr_out(rs2_addr_ex),
    .funct3_out(funct3_ex),
    .reg_write_out(reg_write_ex), .alu_src_a_out(alu_src_a_ex), .alu_src_b_out(alu_src_b_ex),
    .alu_op_out(alu_op_ex), .mem_read_out(mem_read_ex), .mem_write_out(mem_write_ex),
    .result_src_out(result_src_ex), .branch_out(branch_ex), .jal_out(jal_ex),
    .jalr_out(jalr_ex), .illegal_out(illegal_ex), .instr_dbg_out(instr_ex), .valid_out(valid_ex)
  );

  // ===================================================================
  // Hazard unit (Phase 6) -- driven by ID and EX state, consumed by IF,
  // IF/ID, ID/EX above and referenced by name only here for locality.
  // ===================================================================
  hazard_unit hazard_unit_inst (
    .id_ex_mem_read(mem_read_ex),
    .id_ex_rd_addr (rd_ex),
    .id_rs1_addr   (rs1_id),
    .id_rs2_addr   (rs2_id),
    .branch_flush  (ex_redirect_valid),
    .pc_stall      (pc_stall),
    .if_id_stall   (if_id_stall),
    .if_id_flush   (if_id_flush),
    .id_ex_flush   (id_ex_flush)
  );

  // ===================================================================
  // EX stage
  // ===================================================================

  // --- Forwarding (Phase 6) ---------------------------------------
  // EX/MEM and MEM/WB rd_addr/reg_write come from further down this
  // file (ex_mem_reg / mem_wb_reg outputs); declared here via forward
  // reference through the module's flat scope, matching how `pc_stall`
  // etc. are used above before their producing instance. rd_wdata_wb is
  // the WB stage's already-muxed writeback value (ALU result, memory
  // data, or PC+4 -- whichever this instruction's result_src selects),
  // exactly what MEM/WB-path forwarding needs to supply, including for
  // a load (see forwarding_unit.sv header for why EX/MEM's plain
  // alu_result is the wrong thing to forward for a load one stage
  // earlier -- that case is handled by the load-use stall instead).
  logic [1:0] forward_a, forward_b;

  forwarding_unit forwarding_unit_inst (
    .id_ex_rs1_addr  (rs1_addr_ex),
    .id_ex_rs2_addr  (rs2_addr_ex),
    .ex_mem_rd_addr  (rd_mem),
    .ex_mem_reg_write(reg_write_mem),
    .mem_wb_rd_addr  (rd_addr_wb),
    .mem_wb_reg_write(reg_write_wb),
    .forward_a       (forward_a),
    .forward_b       (forward_b)
  );

  logic [31:0] rs1_data_fwd, rs2_data_fwd;

  always_comb begin
    case (forward_a)
      2'b01:   rs1_data_fwd = alu_result_mem; // EX/MEM
      2'b10:   rs1_data_fwd = rd_wdata_wb;    // MEM/WB
      default: rs1_data_fwd = rs1_data_ex;    // no hazard
    endcase
  end

  always_comb begin
    case (forward_b)
      2'b01:   rs2_data_fwd = alu_result_mem; // EX/MEM
      2'b10:   rs2_data_fwd = rd_wdata_wb;    // MEM/WB
      default: rs2_data_fwd = rs2_data_ex;    // no hazard
    endcase
  end

  // --- ALU ---------------------------------------------------------
  // Both ALU inputs use the FORWARDED operands, not the raw id_ex_reg
  // outputs -- rs1_data_fwd/rs2_data_fwd already fall back to
  // rs1_data_ex/rs2_data_ex when forwarding isn't needed (forward_a/b
  // == 2'b00), so this is correct for every instruction, hazard or not.
  logic [31:0] alu_a_ex, alu_b_ex, alu_result_ex;
  logic        alu_zero_ex;

  assign alu_a_ex = alu_src_a_ex ? pc_ex      : rs1_data_fwd;
  assign alu_b_ex = alu_src_b_ex ? imm_out_ex : rs2_data_fwd;

  alu alu_inst (
    .a(alu_a_ex), .b(alu_b_ex), .alu_op(alu_op_ex),
    .result(alu_result_ex), .zero(alu_zero_ex)
  );

  // --- Branch condition ---------------------------------------------
  // Also uses the forwarded operands: a branch comparing against a
  // value produced 1-2 instructions earlier needs the same forwarding
  // the ALU gets, or it would compare against a stale pre-forwarding
  // value and reach the wrong taken/not-taken decision.
  logic branch_taken_ex;

  branch_unit branch_unit_inst (
    .rs1_data(rs1_data_fwd), .rs2_data(rs2_data_fwd), .funct3(funct3_ex),
    .branch_taken(branch_taken_ex)
  );

  logic [31:0] pc_target_ex;
  assign pc_target_ex = pc_ex + imm_out_ex;

  // Branch/jump resolution: correctly computed AND, as of Phase 6,
  // correctly flushed -- hazard_unit's if_id_flush/id_ex_flush above
  // discard the 2 wrong-path instructions the cycle this fires.
  logic [31:0] ex_redirect_target;

  assign ex_redirect_valid  = jal_ex || jalr_ex || (branch_ex && branch_taken_ex);
  assign ex_redirect_target = jalr_ex ? {alu_result_ex[31:1], 1'b0} : pc_target_ex;

  assign next_pc = ex_redirect_valid ? ex_redirect_target : pc_plus4_if;

  // ===================================================================
  // EX/MEM
  // ===================================================================
  logic [31:0] pc_plus4_mem, alu_result_mem, rs2_data_mem, instr_mem;
  logic [4:0]  rd_mem;
  logic        reg_write_mem, mem_read_mem, mem_write_mem, illegal_mem, valid_mem;
  logic [1:0]  result_src_mem;

  // rs2_data_fwd (not the raw rs2_data_ex) is what SW's store data must
  // carry forward -- a store whose data operand was itself just
  // computed 1-2 instructions earlier needs that value forwarded here
  // exactly like an ALU operand would.
  ex_mem_reg ex_mem_inst (
    .clk(clk), .rst_n(rst_n),
    .pc_plus4_in(pc_plus4_ex), .alu_result_in(alu_result_ex), .rs2_data_in(rs2_data_fwd),
    .rd_addr_in(rd_ex), .reg_write_in(reg_write_ex), .mem_read_in(mem_read_ex),
    .mem_write_in(mem_write_ex), .result_src_in(result_src_ex), .illegal_in(illegal_ex),
    .instr_dbg_in(instr_ex), .valid_in(valid_ex),

    .pc_plus4_out(pc_plus4_mem), .alu_result_out(alu_result_mem), .rs2_data_out(rs2_data_mem),
    .rd_addr_out(rd_mem), .reg_write_out(reg_write_mem), .mem_read_out(mem_read_mem),
    .mem_write_out(mem_write_mem), .result_src_out(result_src_mem), .illegal_out(illegal_mem),
    .instr_dbg_out(instr_mem), .valid_out(valid_mem)
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
  logic        illegal_wb, valid_wb;
  logic [1:0]  result_src_wb;

  mem_wb_reg mem_wb_inst (
    .clk(clk), .rst_n(rst_n),
    .pc_plus4_in(pc_plus4_mem), .alu_result_in(alu_result_mem), .mem_rdata_in(dmem_rdata_mem),
    .rd_addr_in(rd_mem), .reg_write_in(reg_write_mem), .result_src_in(result_src_mem),
    .illegal_in(illegal_mem), .instr_dbg_in(instr_mem), .valid_in(valid_mem),

    .pc_plus4_out(pc_plus4_wb), .alu_result_out(alu_result_wb), .mem_rdata_out(mem_rdata_wb),
    .rd_addr_out(rd_addr_wb), .reg_write_out(reg_write_wb), .result_src_out(result_src_wb),
    .illegal_out(illegal_wb), .instr_dbg_out(instr_wb), .valid_out(valid_wb)
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
  // Performance counters (Phase 7)
  // ===================================================================
  perf_counters perf_counters_inst (
    .clk(clk), .rst_n(rst_n),
    .instr_retired  (valid_wb),
    .stall          (pc_stall),
    .branch_resolved(branch_ex && valid_ex),
    .branch_taken   (branch_taken_ex),
    .forward_a_active(forward_a != 2'b00),
    .forward_b_active(forward_b != 2'b00),
    .flush          (if_id_flush),

    .cycle_count           (perf_cycle_count),
    .instr_retired_count   (perf_instr_retired_count),
    .stall_count            (perf_stall_count),
    .branch_count            (perf_branch_count),
    .branch_taken_count      (perf_branch_taken_count),
    .load_use_stall_count    (perf_load_use_stall_count),
    .forwarding_event_count  (perf_forwarding_event_count),
    .flush_count             (perf_flush_count)
  );

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
  assign dbg_stall     = pc_stall;
  assign dbg_flush     = if_id_flush;

endmodule
