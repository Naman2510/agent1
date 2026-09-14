`timescale 1ns/1ps
// regfile.sv
//
// RV32I register file: 32 x 32-bit registers, two asynchronous read
// ports (rs1/rs2, read every cycle for the current instruction) and one
// synchronous write port (rd, written on the clock edge that retires an
// instruction).
//
// x0 is hard-wired to zero (docs/riscv.md section 1.1): reads of x0 always
// return 0 regardless of what was ever "written" to it, and writes to x0
// are accepted (rd_addr == 0 is legal to encode) but silently discarded.
// This is enforced here in hardware, not left to software convention.
//
// BYPASS_WRITE_TO_READ (Phase 6, default OFF): when set, a read whose
// address matches rd_addr on a cycle reg_write is asserted returns
// rd_data directly (the value being written this same cycle) instead of
// the stored array content, which the plain array read would only see
// starting the following cycle. This is needed by the pipelined CPU
// (rtl/cpu/riscv_cpu_pipeline.sv), which enables it: a RAW dependency
// exactly 2 instructions apart lands the producer's WB and the
// consumer's ID-stage capture into id_ex_reg on the very same clock
// edge, and relying on Verilog's nonblocking-assignment scheduling
// order there resolves to the OLD (pre-write) value, not the new one --
// found and explained in detail in docs/pipeline.md. A 0- or
// 1-instruction gap is handled by rtl/pipeline/forwarding_unit.sv
// instead (the value isn't in the register file yet at all in those
// cases); a 3-or-more-instruction gap needs neither, since by then the
// producer's write has settled a full clock period earlier with no
// same-edge ambiguity. This bypass is exactly the missing piece for the
// one gap distance (2) that neither of those other two mechanisms
// reaches.
//
// This must stay OFF (the default) for the single-cycle CPU
// (rtl/cpu/riscv_cpu.sv): there, rs1_addr/rs2_addr and rd_addr/rd_data
// belong to the SAME instruction in the SAME cycle (e.g. `add x1,x1,x2`
// reads x1 to compute a new x1), and rd_data is itself combinationally
// derived from rs1_data/rs2_data via that cycle's ALU. Bypassing there
// would close rs1_data -> ALU -> rd_data -> rs1_data into a zero-delay
// combinational loop. In the pipeline, the read (ID stage) and the
// write (WB stage) always belong to two DIFFERENT, independent
// instructions, and rd_data there comes from mem_wb_reg -- a value
// already latched in a previous cycle -- so no such loop can form.

module regfile #(
  parameter bit BYPASS_WRITE_TO_READ = 1'b0
) (
  input  logic        clk,
  input  logic         rst_n,
  input  logic [4:0]  rs1_addr,
  input  logic [4:0]  rs2_addr,
  input  logic [4:0]  rd_addr,
  input  logic [31:0] rd_data,
  input  logic        reg_write,
  output logic [31:0] rs1_data,
  output logic [31:0] rs2_data
);

  logic [31:0] regs [1:31]; // x0 deliberately excluded: it is not storage

  integer i;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (i = 1; i <= 31; i = i + 1) regs[i] <= 32'b0;
    end else if (reg_write && rd_addr != 5'd0) begin
      regs[rd_addr] <= rd_data;
    end
  end

  // Plain asynchronous (combinational) reads, with x0 forced to zero.
  logic [31:0] rs1_raw, rs2_raw;
  assign rs1_raw = (rs1_addr == 5'd0) ? 32'b0 : regs[rs1_addr];
  assign rs2_raw = (rs2_addr == 5'd0) ? 32'b0 : regs[rs2_addr];

  generate
    if (BYPASS_WRITE_TO_READ) begin : gen_bypass
      assign rs1_data = (rs1_addr != 5'd0 && reg_write && rd_addr == rs1_addr) ? rd_data : rs1_raw;
      assign rs2_data = (rs2_addr != 5'd0 && reg_write && rd_addr == rs2_addr) ? rd_data : rs2_raw;
    end else begin : gen_no_bypass
      assign rs1_data = rs1_raw;
      assign rs2_data = rs2_raw;
    end
  endgenerate

endmodule
