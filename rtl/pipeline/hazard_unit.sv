`timescale 1ns/1ps
// hazard_unit.sv
//
// Generates the stall/flush controls for Phase 6's two remaining hazard
// types (data forwarding itself is rtl/pipeline/forwarding_unit.sv):
//
//   1. Load-use hazard: the instruction currently in EX is a load, and
//      the instruction currently in ID needs the loaded value as one of
//      its own operands. Forwarding alone can't fix this -- EX/MEM would
//      only have the load's *address*, not its data, which isn't ready
//      until MEM completes -- so this stalls the pipeline for exactly
//      one cycle: freeze PC and IF/ID, insert a bubble into ID/EX. After
//      that one cycle, the load has moved into MEM/WB and
//      forwarding_unit's MEM/WB path supplies the correct value when the
//      stalled instruction reaches EX.
//
//   2. Control hazard (branch/JAL/JALR flush): asserted whenever EX
//      resolves a taken branch or any JAL/JALR (i.e. whenever the top
//      level is about to redirect the PC). The 2 instructions already
//      fetched from the sequential (now known wrong) path -- one
//      sitting in IF/ID, one about to be captured from IF -- must be
//      discarded rather than allowed to execute. See
//      docs/pipeline.md for why this couldn't be deferred any longer
//      once forwarding/stalling were in place: unlike Phase 5, Phase 6's
//      own directed tests use real branches, which would otherwise
//      corrupt architectural state exactly as documented as a known
//      Phase 5 limitation.
//
// Conservative simplification, documented rather than hidden: the
// load-use check compares raw rs1/rs2 *field* values (which decoder.sv
// extracts positionally for every instruction, per docs/riscv.md
// section 2) against the in-flight load's rd, without checking whether
// the ID-stage instruction's opcode actually uses rs1/rs2 as register
// operands. For an instruction where that field is actually part of an
// immediate (LUI, AUIPC, JAL), a numeric coincidence can trigger an
// unnecessary stall. This never produces an incorrect result -- a
// spurious stall costs a cycle, never correctness -- so it is an
// accepted, standard simplification (the same one made in most
// textbook 5-stage designs), not a bug.
//
// load_use_hazard and branch_flush can never both be true in the same
// cycle: both are properties of the single instruction currently in EX,
// and an instruction cannot simultaneously be a load (OP_LOAD) and a
// branch/JAL/JALR -- the opcodes are mutually exclusive.

module hazard_unit (
  input  logic       id_ex_mem_read,
  input  logic [4:0] id_ex_rd_addr,

  input  logic [4:0] id_rs1_addr, // freshly decoded, straight from decoder.sv
  input  logic [4:0] id_rs2_addr,

  input  logic       branch_flush, // ex_redirect_valid from the top level

  output logic       pc_stall,
  output logic       if_id_stall,
  output logic       if_id_flush,
  output logic       id_ex_flush
);

  logic load_use_hazard;

  assign load_use_hazard = id_ex_mem_read && (id_ex_rd_addr != 5'd0) &&
                            ((id_ex_rd_addr == id_rs1_addr) || (id_ex_rd_addr == id_rs2_addr));

  assign pc_stall    = load_use_hazard;
  assign if_id_stall = load_use_hazard;
  assign if_id_flush = branch_flush;
  assign id_ex_flush = branch_flush || load_use_hazard;

endmodule
