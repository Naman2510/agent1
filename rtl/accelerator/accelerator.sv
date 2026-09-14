`timescale 1ns/1ps
// accelerator.sv
//
// Phase 9: memory-mapped hardware accelerator. Real sequential RTL (an
// explicit FSM with counters and an accumulator register -- not a
// combinational unrolled multiplier tree, and never a Python/software
// stand-in for hardware, per this project's own engineering rules),
// supporting three operations selected by a control register:
//
//   OP_VECADD (01): out[i]   = a[i] + b[i],                 i in [0,N)
//   OP_DOT    (10): result   = sum_i a[i] * b[i],            i in [0,N)
//   OP_MATMUL (11): out[i,j] = sum_k a[i,k] * b[k,j],  i,j,k in [0,N)
//                   (a, b, out all treated as flattened, row-major,
//                   N x N square matrices for this phase)
//
// This module is a pure MEMORY-MAPPED peripheral in Phase 9 -- a CPU
// drives it with ordinary LW/SW through rtl/bus/soc_bus.sv, exactly
// like rtl/bus/uart.sv or rtl/bus/gpio.sv. Phase 10 adds a *custom
// RISC-V instruction* as a faster/more ergonomic way to trigger it;
// that instruction will still ultimately control this same register
// interface, not a different accelerator.
//
// Register map (byte offsets within this peripheral's own window --
// see rtl/bus/soc_bus.sv for how the top-level SoC address 0x30000000
// routes a CPU access here in the first place):
//
//   0x0000  CTRL    (write-only): bit0 = START (self-clearing pulse,
//                    ignored while busy); bits[2:1] = OPCODE (see
//                    OP_* below). Latches OPCODE and begins the FSM
//                    using the LEN and data-memory contents already
//                    written.
//   0x0004  STATUS  (read-only): bit0 = BUSY, bit1 = DONE, bit2 = ERR
//                    (asserted, and the op skipped entirely, if LEN
//                    was 0 or exceeded this instance's bound at START
//                    time -- see MAX_LEN/MAX_DIM below).
//   0x0008  LEN     (read/write, write ignored while busy): vector
//                    length N for VECADD/DOT (0 < N <= MAX_LEN), or
//                    the matrix dimension N for MATMUL (0 < N <=
//                    MAX_DIM), so MATMUL reads/writes N*N elements
//                    from the same LEN value, not N directly as an
//                    element count. Sized to hold the larger of the
//                    two bounds (MAX_LEN), not just MAX_DIM -- an
//                    earlier draft of this module sized it for
//                    MAX_DIM only and silently truncated any
//                    VECADD/DOT length above 15; caught in review
//                    before this file was ever simulated (see
//                    CHANGELOG.md's Phase 9 entry).
//   0x000C  RESULT  (read-only): the scalar result of OP_DOT once
//                    DONE is asserted. Not meaningful for the other
//                    two ops (their output lives in VECOUT instead).
//   0x1000..         VECA:   input operand A, MAX_LEN 32-bit words,
//                    word-addressed (offset 0x1000 + 4*index).
//   0x2000..         VECB:   input operand B, same layout.
//   0x3000..         VECOUT: output, same layout (also the flattened
//                    row-major result matrix for OP_MATMUL).
//
// Multiplication is 32x32 -> 64, truncated to the low 32 bits and
// treated as signed -- the same "low bits of the product" semantics
// RV32M's MUL instruction uses, chosen so results compose predictably
// with ordinary RV32I arithmetic on the CPU side. This accelerator's
// existence does not depend on the CPU actually implementing the M
// extension; the multiply here is entirely internal to this module's
// own datapath.

module accelerator #(
  parameter int MAX_DIM = 8,               // matrix side bound (N <= MAX_DIM)
  parameter int MAX_LEN = MAX_DIM * MAX_DIM // scratchpad depth in words
) (
  input  logic        clk,
  input  logic        rst_n,
  input  logic [31:0] addr,
  input  logic [31:0] wdata,
  input  logic         mem_read,
  input  logic         mem_write,
  output logic [31:0] rdata
);

  localparam logic [1:0] OP_NONE   = 2'b00;
  localparam logic [1:0] OP_VECADD = 2'b01;
  localparam logic [1:0] OP_DOT    = 2'b10;
  localparam logic [1:0] OP_MATMUL = 2'b11;

  localparam logic [15:0] REG_CTRL    = 16'h0000;
  localparam logic [15:0] REG_STATUS  = 16'h0004;
  localparam logic [15:0] REG_LEN     = 16'h0008;
  localparam logic [15:0] REG_RESULT  = 16'h000C;
  localparam logic [15:0] VECA_BASE   = 16'h1000;
  localparam logic [15:0] VECB_BASE   = 16'h2000;
  localparam logic [15:0] VECOUT_BASE = 16'h3000;

  // Address-decode index width: just enough to select one of MAX_LEN
  // scratchpad words from an MMIO offset (6 bits for MAX_LEN=64).
  localparam int ADDR_IDX_BITS = $clog2(MAX_LEN);
  // FSM counter width: must hold the LARGER of the two LEN meanings
  // (up to MAX_LEN for VECADD/DOT, up to MAX_DIM for MATMUL) so a
  // full-length vector operation is never silently truncated (7 bits
  // for MAX_LEN=64, covering 0..64 inclusive).
  localparam int LEN_BITS = $clog2(MAX_LEN + 1);

  // -------------------------------------------------------------------
  // Address decode (this peripheral's own 16-bit window -- ample for
  // the 0x0000-0x30FC range this module actually uses; see header).
  // -------------------------------------------------------------------
  wire [15:0] off = addr[15:0];
  wire sel_ctrl   = (off == REG_CTRL);
  wire sel_status = (off == REG_STATUS);
  wire sel_len    = (off == REG_LEN);
  wire sel_result = (off == REG_RESULT);
  wire sel_veca   = (off >= VECA_BASE)   && (off < VECA_BASE   + 16'(MAX_LEN*4));
  wire sel_vecb   = (off >= VECB_BASE)   && (off < VECB_BASE   + 16'(MAX_LEN*4));
  wire sel_vecout = (off >= VECOUT_BASE) && (off < VECOUT_BASE + 16'(MAX_LEN*4));

  wire [15:0] veca_off   = off - VECA_BASE;
  wire [15:0] vecb_off   = off - VECB_BASE;
  wire [15:0] vecout_off = off - VECOUT_BASE;
  wire [ADDR_IDX_BITS-1:0] veca_idx   = veca_off[ADDR_IDX_BITS+1:2];
  wire [ADDR_IDX_BITS-1:0] vecb_idx   = vecb_off[ADDR_IDX_BITS+1:2];
  wire [ADDR_IDX_BITS-1:0] vecout_idx = vecout_off[ADDR_IDX_BITS+1:2];

  // -------------------------------------------------------------------
  // Data scratchpads
  // -------------------------------------------------------------------
  logic [31:0] veca   [0:MAX_LEN-1];
  logic [31:0] vecb   [0:MAX_LEN-1];
  logic [31:0] vecout [0:MAX_LEN-1];

  initial begin
    for (int i = 0; i < MAX_LEN; i++) begin
      veca[i]   = 32'b0;
      vecb[i]   = 32'b0;
      vecout[i] = 32'b0;
    end
  end

  // CPU-side writes into VECA/VECB (VECOUT is written only by the FSM,
  // never by the CPU -- it is a result, not an input).
  always_ff @(posedge clk) begin
    if (mem_write && sel_veca) veca[veca_idx] <= wdata;
    if (mem_write && sel_vecb) vecb[vecb_idx] <= wdata;
  end

  // -------------------------------------------------------------------
  // Control/status registers + FSM
  // -------------------------------------------------------------------
  typedef enum logic [1:0] {ST_IDLE, ST_RUN, ST_DONE} state_t;
  state_t state;

  logic [1:0]         op_r;
  logic [LEN_BITS-1:0] len_r;
  logic                busy, done, err;

  // VECADD/DOT: single running index. MATMUL: i/j/k triple. All share
  // LEN_BITS width so every comparison against len_r is apples-to-apples
  // (no truncation surprises like the ones this module's header comment
  // documents finding during review).
  logic [LEN_BITS-1:0] idx;          // VECADD/DOT element index
  logic [LEN_BITS-1:0] mi, mj, mk;   // MATMUL row/col/reduction indices
  logic [63:0]         acc;          // accumulator; only low 32 bits stored out
  logic [31:0]         result_r;

  // MATMUL operand addresses (a[mi,mk] = a[mi*N+mk], b[mk,mj] = b[mk*N+mj])
  // computed at a width wide enough (16 bits) that the multiply can't
  // truncate before reaching the scratchpad index, then sliced down to
  // ADDR_IDX_BITS for the actual array read -- values are always in
  // range because mi/mj/mk < len_r <= MAX_DIM and MAX_DIM*MAX_DIM ==
  // MAX_LEN by construction.
  wire [15:0] matmul_a_idx   = 16'(mi) * 16'(len_r) + 16'(mk);
  wire [15:0] matmul_b_idx   = 16'(mk) * 16'(len_r) + 16'(mj);
  wire [15:0] matmul_out_idx = 16'(mi) * 16'(len_r) + 16'(mj);

  wire [ADDR_IDX_BITS-1:0] a_idx = (op_r == OP_MATMUL)
    ? matmul_a_idx[ADDR_IDX_BITS-1:0] : idx[ADDR_IDX_BITS-1:0];
  wire [ADDR_IDX_BITS-1:0] b_idx = (op_r == OP_MATMUL)
    ? matmul_b_idx[ADDR_IDX_BITS-1:0] : idx[ADDR_IDX_BITS-1:0];

  wire signed [31:0] a_val = veca[a_idx];
  wire signed [31:0] b_val = vecb[b_idx];
  wire signed [63:0] product = a_val * b_val; // full 64-bit product; low 32 bits used
  // Named intermediate for "this cycle's running total including the
  // in-flight term" -- used both to update the 64-bit accumulator and,
  // truncated to its low 32 bits, as the final stored/reported result.
  // A plain identifier here (rather than slicing the `acc + product`
  // expression directly at each use site) is what makes the 32-bit
  // slice below acceptable to Icarus Verilog, which rejects a
  // part-select applied directly to a parenthesized arithmetic
  // expression; Verilator additionally wants the 64->32 truncation
  // spelled explicitly rather than left implicit in an assignment,
  // which this same named signal provides for free.
  wire signed [63:0] acc_next = acc + product;

  wire start_req = mem_write && sel_ctrl && wdata[0];
  wire [1:0] start_op = wdata[2:1];

  // Shared "begin a new operation" sequencing, used from both ST_IDLE
  // and ST_DONE (a new START is accepted the instant the previous
  // result has been observed, without forcing software to wait an
  // extra idle cycle).
  task automatic begin_op(logic [1:0] req_op);
    op_r <= req_op;
    idx  <= '0;
    mi <= '0; mj <= '0; mk <= '0;
    acc  <= '0;
    done <= 1'b0;
    if (len_r == 0 ||
        (req_op != OP_MATMUL && len_r > LEN_BITS'(MAX_LEN)) ||
        (req_op == OP_MATMUL && len_r > LEN_BITS'(MAX_DIM))) begin
      err   <= 1'b1;
      busy  <= 1'b0;
      done  <= 1'b1;
      state <= ST_DONE;
    end else begin
      err   <= 1'b0;
      busy  <= 1'b1;
      state <= ST_RUN;
    end
  endtask

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= ST_IDLE;
      op_r <= OP_NONE;
      len_r <= '0;
      busy <= 1'b0;
      done <= 1'b0;
      err <= 1'b0;
      idx <= '0;
      mi <= '0; mj <= '0; mk <= '0;
      acc <= '0;
      result_r <= 32'b0;
    end else begin
      // LEN register: writable only while idle (ignored mid-operation
      // so a software bug can't corrupt an operation already running).
      if (mem_write && sel_len && !busy) len_r <= wdata[LEN_BITS-1:0];

      unique case (state)
        ST_IDLE: if (start_req) begin_op(start_op);

        ST_RUN: begin
          unique case (op_r)
            OP_VECADD: begin
              vecout[a_idx] <= a_val + b_val;
              if (idx == len_r - 1'b1) begin
                busy <= 1'b0; done <= 1'b1; state <= ST_DONE;
              end else begin
                idx <= idx + 1'b1;
              end
            end

            OP_DOT: begin
              acc <= acc_next;
              if (idx == len_r - 1'b1) begin
                result_r <= acc_next[31:0];
                busy <= 1'b0; done <= 1'b1; state <= ST_DONE;
              end else begin
                idx <= idx + 1'b1;
              end
            end

            OP_MATMUL: begin
              acc <= acc_next;
              if (mk == len_r - 1'b1) begin
                // Last reduction term for this (mi, mj) output element.
                vecout[matmul_out_idx[ADDR_IDX_BITS-1:0]] <= acc_next[31:0];
                acc <= '0;
                mk  <= '0;
                if (mj == len_r - 1'b1) begin
                  mj <= '0;
                  if (mi == len_r - 1'b1) begin
                    busy <= 1'b0; done <= 1'b1; state <= ST_DONE;
                  end else begin
                    mi <= mi + 1'b1;
                  end
                end else begin
                  mj <= mj + 1'b1;
                end
              end else begin
                mk <= mk + 1'b1;
              end
            end

            default: begin
              // Unreachable (op_r is only ever latched from start_op
              // inside begin_op(), which itself is only called with a
              // START request's 2-bit opcode field) -- fail safe.
              busy <= 1'b0; done <= 1'b1; err <= 1'b1; state <= ST_DONE;
            end
          endcase
        end

        ST_DONE: begin
          if (start_req) begin_op(start_op);
          else state <= ST_IDLE;
        end

        default: state <= ST_IDLE;
      endcase
    end
  end

  // -------------------------------------------------------------------
  // Read mux (combinational, same convention as dmem.sv/uart.sv/gpio.sv)
  // -------------------------------------------------------------------
  assign rdata = !mem_read ? 32'b0 :
                 sel_status ? {29'b0, err, done, busy} :
                 sel_len    ? {{(32-LEN_BITS){1'b0}}, len_r} :
                 sel_result ? result_r :
                 sel_veca   ? veca[veca_idx] :
                 sel_vecb   ? vecb[vecb_idx] :
                 sel_vecout ? vecout[vecout_idx] :
                 32'b0;

endmodule
