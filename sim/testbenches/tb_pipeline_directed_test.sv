// tb_pipeline_directed_test.sv
//
// Phase 6 directed-test harness for the pipelined CPU
// (rtl/cpu/riscv_cpu_pipeline.sv). Same generic, compile-once/run-many
// pattern as sim/testbenches/tb_directed_test.sv (Phase 3): a runtime
// +HEXFILE=... plusarg selects the test program, and the reserved x31
// (t6) pass/fail convention from docs/testing.md applies unchanged --
// the pipeline is still the same ISA underneath.
//
// MAX_CYCLES is larger than Phase 3's single-cycle directed-test budget
// (300) to comfortably cover pipeline fill/drain latency (4 extra
// cycles) and the occasional 1-cycle load-use stall these tests
// specifically exercise.

`timescale 1ns/1ps

module tb_pipeline_directed_test;

  logic clk;
  logic rst_n = 0;

  logic [31:0] dbg_if_pc, dbg_if_instr;
  logic [31:0] dbg_id_pc, dbg_id_instr;
  logic [31:0] dbg_ex_pc, dbg_ex_instr;
  logic [31:0] dbg_mem_instr;
  logic [31:0] dbg_wb_instr;
  logic        dbg_reg_write;
  logic [4:0]  dbg_rd_addr;
  logic [31:0] dbg_rd_data;
  logic        dbg_illegal;
  logic        dbg_stall, dbg_flush;

  riscv_cpu_pipeline dut (
    .clk(clk), .rst_n(rst_n),
    .dbg_if_pc(dbg_if_pc), .dbg_if_instr(dbg_if_instr),
    .dbg_id_pc(dbg_id_pc), .dbg_id_instr(dbg_id_instr),
    .dbg_ex_pc(dbg_ex_pc), .dbg_ex_instr(dbg_ex_instr),
    .dbg_mem_instr(dbg_mem_instr),
    .dbg_wb_instr(dbg_wb_instr),
    .dbg_reg_write(dbg_reg_write), .dbg_rd_addr(dbg_rd_addr), .dbg_rd_data(dbg_rd_data),
    .dbg_illegal(dbg_illegal), .dbg_stall(dbg_stall), .dbg_flush(dbg_flush)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // Unlike Phase 3's single-cycle directed-test harness
  // (tb_directed_test.sv), this testbench does NOT track "illegal ever
  // seen" as a pass/fail condition. In a pipeline, a bubble -- an
  // all-zero pipeline-register state from reset fill, a hazard_unit
  // flush, or a load-use stall -- is a completely normal, constant
  // feature of ordinary operation, and instr=0 decodes to opcode
  // 0000000, which control_unit.sv correctly (and, for this purpose,
  // misleadingly) flags as `illegal` since it isn't one of this
  // project's supported opcodes. Every single directed test in this
  // suite produces bubbles during pipeline fill alone, so a sticky
  // "illegal ever seen" check would fail on 100% of runs regardless of
  // correctness -- this was tried and immediately produced exactly
  // that false failure on all 3 initial hazard tests (see
  // CHANGELOG.md's Phase 6 entry). Distinguishing a real illegal
  // opcode from an empty bubble correctly would need an explicit
  // `valid` bit threaded through every pipeline register, which
  // doesn't exist yet; verification here relies solely on the x31
  // pass/fail convention below, same as Phase 5's tb_pipeline.sv.
  localparam int MAX_CYCLES = 300;

  // Optional waveform dump for GTKWave, gated behind a plusarg so
  // ordinary pass/fail runs (scripts/run_pipeline_hazard_tests.py)
  // don't pay the cost of writing one every time. See
  // scripts/generate_waveforms.sh and docs/hazards.md for how this is
  // used to produce the .vcd files those docs walk through.
  initial begin
    string vcd_path;
    if ($value$plusargs("DUMP_VCD=%s", vcd_path)) begin
      $dumpfile(vcd_path);
      $dumpvars(0, tb_pipeline_directed_test);
    end
  end

  initial begin
    string testname;
    if (!$value$plusargs("TESTNAME=%s", testname)) testname = "(unnamed)";

    rst_n = 0;
    repeat (2) @(posedge clk);
    rst_n = 1;

    repeat (MAX_CYCLES) @(posedge clk);
    #1;

    if (dut.regfile_inst.regs[31] === 32'd1) begin
      $display("TEST_RESULT: PASS test=%s", testname);
    end else begin
      $display("TEST_RESULT: FAIL test=%s x31=0x%08x", testname, dut.regfile_inst.regs[31]);
    end
    $finish;
  end

endmodule
