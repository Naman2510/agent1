// tb_soc.sv
//
// Phase 8 testbench for the top-level SoC (rtl/cpu/riscv_soc.sv). Loads
// sim/programs/soc/soc_demo.s (assembled to hex) and verifies, through
// the real address-decoded bus, that:
//   - RAM at 0x00000000 still works exactly as every prior phase's test
//     assumed (backward compatibility with the pre-Phase-8 memory map).
//   - GPIO_OUT (0x20000000) is writable and reads back what was written.
//   - GPIO_IN (0x20000004) reflects this testbench's externally-driven
//     `gpio_in` value -- proving a real SoC-boundary input reaches
//     software through the bus, not just that gpio.sv works alone.
//   - UART TXDATA/STATUS (0x10000000/0x10000004) accept bytes and
//     report busy/idle correctly, observed two ways: the x31 pass/fail
//     check inside soc_demo.s itself, AND this testbench's own
//     uart_tx_valid/uart_tx_byte monitor, which prints every byte the
//     CPU actually transmitted -- real data captured from the
//     simulation, not asserted or fabricated.
//
// gpio_in is driven to a fixed constant BEFORE reset deasserts (see the
// initial block below) so soc_demo.s's read of it, which happens well
// after reset, sees a stable, already-settled value -- no race with
// reset the way the same-edge issues documented in CHANGELOG.md's
// Phase 7 entry required care around.

`timescale 1ns/1ps

module tb_soc;

  logic clk;
  logic rst_n = 0;

  logic [31:0] gpio_in;
  logic [31:0] gpio_out;
  logic         uart_tx_valid;
  logic [7:0]   uart_tx_byte;

  logic [31:0] dbg_if_pc, dbg_if_instr, dbg_id_pc, dbg_id_instr, dbg_ex_pc, dbg_ex_instr;
  logic [31:0] dbg_mem_instr, dbg_wb_instr, dbg_rd_data;
  logic         dbg_reg_write, dbg_illegal, dbg_stall, dbg_flush;
  logic [4:0]  dbg_rd_addr;
  logic [31:0] perf_cycle_count, perf_instr_retired_count, perf_stall_count;
  logic [31:0] perf_branch_count, perf_branch_taken_count, perf_load_use_stall_count;
  logic [31:0] perf_forwarding_event_count, perf_flush_count;

  riscv_soc #(
    .IMEM_INIT_FILE("sim/programs/soc/soc_demo.hex"),
    .UART_BUSY_CYCLES(4)
  ) dut (
    .clk(clk), .rst_n(rst_n),
    .gpio_in(gpio_in), .gpio_out(gpio_out),
    .uart_tx_valid(uart_tx_valid), .uart_tx_byte(uart_tx_byte),
    .dbg_if_pc(dbg_if_pc), .dbg_if_instr(dbg_if_instr),
    .dbg_id_pc(dbg_id_pc), .dbg_id_instr(dbg_id_instr),
    .dbg_ex_pc(dbg_ex_pc), .dbg_ex_instr(dbg_ex_instr),
    .dbg_mem_instr(dbg_mem_instr), .dbg_wb_instr(dbg_wb_instr),
    .dbg_reg_write(dbg_reg_write), .dbg_rd_addr(dbg_rd_addr), .dbg_rd_data(dbg_rd_data),
    .dbg_illegal(dbg_illegal), .dbg_stall(dbg_stall), .dbg_flush(dbg_flush),
    .perf_cycle_count(perf_cycle_count),
    .perf_instr_retired_count(perf_instr_retired_count),
    .perf_stall_count(perf_stall_count),
    .perf_branch_count(perf_branch_count),
    .perf_branch_taken_count(perf_branch_taken_count),
    .perf_load_use_stall_count(perf_load_use_stall_count),
    .perf_forwarding_event_count(perf_forwarding_event_count),
    .perf_flush_count(perf_flush_count)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // Fixed external GPIO input pattern, settled well before reset
  // deasserts -- see header comment.
  initial gpio_in = 32'hCAFEBABE;

  // Plain always (not always_ff): this block exists purely to observe
  // and $display simulation activity for a human reading the log, not
  // to describe synthesizable hardware -- always_ff is reserved for the
  // real datapath/peripheral registers elsewhere in this project.
  int uart_bytes_seen = 0;
  always @(posedge clk) begin
    if (uart_tx_valid) begin
      $display("  [UART TX] byte=0x%02x ('%c') @ t=%0t", uart_tx_byte, uart_tx_byte, $time);
      uart_bytes_seen <= uart_bytes_seen + 1;
    end
  end

  localparam int MAX_CYCLES = 500; // generous margin for the UART poll loops

  initial begin
    $display("=== Phase 8 SoC testbench ===");
    $display("  gpio_in driven to 0x%08x", gpio_in);

    rst_n = 0;
    repeat (2) @(posedge clk);
    // Same-edge race fix as every other testbench in this project --
    // see CHANGELOG.md's Phase 7 entry.
    #1;
    rst_n = 1;

    repeat (MAX_CYCLES) @(posedge clk);
    #1;

    $display("");
    $display("gpio_out final value = 0x%08x", gpio_out);
    $display("UART bytes actually transmitted this run: %0d", uart_bytes_seen);

    $display("");
    if (dut.cpu_inst.regfile_inst.regs[31] === 32'd1) begin
      $display("TEST_RESULT: PASS test=soc_demo");
    end else begin
      $display("TEST_RESULT: FAIL test=soc_demo x31=0x%08x",
                dut.cpu_inst.regfile_inst.regs[31]);
    end
    $finish;
  end

endmodule
