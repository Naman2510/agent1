`timescale 1ns/1ps
// forwarding_unit.sv
//
// EX-stage data-hazard forwarding for the pipelined CPU (Phase 6).
// Decides, for each ALU operand, whether to use the value the register
// file supplied back in ID (already sitting in id_ex_reg), or to
// substitute a more recent result still in flight from an instruction
// currently in EX/MEM or MEM/WB -- because that instruction's WB hasn't
// happened yet, so the register file itself doesn't have the right
// value yet even though the *pipeline* does.
//
// Priority: EX/MEM (the instruction one stage ahead, i.e. the most
// recently executed one) wins over MEM/WB (two stages ahead) when both
// happen to target the same register, since EX/MEM holds the more
// recent write.
//
// What this does NOT cover: a load whose result is needed by the very
// next instruction (the EX/MEM path above would forward the *address*
// alu_result computed for the load, not the loaded data, which isn't
// known until MEM completes) -- rtl/pipeline/hazard_unit.sv detects
// exactly that case and stalls one cycle instead, after which this
// forwarding unit's MEM/WB path (which carries the already-muxed,
// correct writeback value, load data included) supplies it.
//
// FWD_NONE/FWD_EX_MEM/FWD_MEM_WB are microarchitectural mux-select
// values, not ISA-visible state, so they live here rather than in
// riscv_pkg.sv.

module forwarding_unit (
  input  logic [4:0] id_ex_rs1_addr,
  input  logic [4:0] id_ex_rs2_addr,

  input  logic [4:0] ex_mem_rd_addr,
  input  logic       ex_mem_reg_write,

  input  logic [4:0] mem_wb_rd_addr,
  input  logic       mem_wb_reg_write,

  output logic [1:0] forward_a,
  output logic [1:0] forward_b
);

  localparam logic [1:0] FWD_NONE   = 2'b00; // use id_ex's own rs*_data
  localparam logic [1:0] FWD_EX_MEM = 2'b01; // use EX/MEM's alu_result
  localparam logic [1:0] FWD_MEM_WB = 2'b10; // use MEM/WB's writeback value

  always_comb begin
    if (ex_mem_reg_write && ex_mem_rd_addr != 5'd0 && ex_mem_rd_addr == id_ex_rs1_addr)
      forward_a = FWD_EX_MEM;
    else if (mem_wb_reg_write && mem_wb_rd_addr != 5'd0 && mem_wb_rd_addr == id_ex_rs1_addr)
      forward_a = FWD_MEM_WB;
    else
      forward_a = FWD_NONE;

    if (ex_mem_reg_write && ex_mem_rd_addr != 5'd0 && ex_mem_rd_addr == id_ex_rs2_addr)
      forward_b = FWD_EX_MEM;
    else if (mem_wb_reg_write && mem_wb_rd_addr != 5'd0 && mem_wb_rd_addr == id_ex_rs2_addr)
      forward_b = FWD_MEM_WB;
    else
      forward_b = FWD_NONE;
  end

endmodule
