`timescale 1ns/1ps
// riscv_soc.sv
//
// Phase 8/9: top-level System-on-Chip. Instantiates the pipelined CPU
// (rtl/cpu/riscv_cpu_pipeline.sv, unmodified from Phase 7's
// architecture except for Phase 8's data-bus externalization -- see its
// own header comment) and connects its data-bus-master port through the
// address decoder (rtl/bus/soc_bus.sv) to four memory-mapped
// peripherals: RAM (rtl/memory/dmem.sv, reused as-is -- a behavioral
// memory model, not synthesizable SRAM, same caveat as every prior
// phase), UART (rtl/bus/uart.sv), GPIO (rtl/bus/gpio.sv), and, since
// Phase 9, the hardware accelerator (rtl/accelerator/accelerator.sv).
// See docs/soc.md for the full memory map and how this module is
// verified.
//
// Instruction memory (ROM) is NOT part of this new data bus: it stays on
// riscv_cpu_pipeline's own dedicated fetch-only port, internal to that
// module, exactly as in every prior phase -- there was never a
// requirement (or a mechanism in a real Harvard-ish RISC-V core) for the
// CPU to write program memory over the data bus, so it is not modeled
// here. IMEM_INIT_FILE is forwarded through so this SoC can run any
// existing test/benchmark program unchanged.

module riscv_soc #(
  parameter int IMEM_DEPTH_WORDS = 1024,
  parameter      IMEM_INIT_FILE  = "",
  parameter int RAM_DEPTH_WORDS  = 1024,
  parameter int UART_BUSY_CYCLES = 4,
  parameter int ACCEL_MAX_DIM    = 8
) (
  input  logic clk,
  input  logic rst_n,

  // GPIO pins, exposed at the SoC boundary for a testbench to drive
  // (gpio_in) and observe (gpio_out) -- see rtl/bus/gpio.sv.
  input  logic [31:0] gpio_in,
  output logic [31:0] gpio_out,

  // UART "transmitted byte" observation port -- see rtl/bus/uart.sv's
  // header comment for why this is the honest simulation-level
  // substitute for a physical serial line.
  output logic         uart_tx_valid,
  output logic [7:0]   uart_tx_byte,

  // Debug/observability passthrough from the CPU core, unchanged from
  // Phase 7 (see riscv_cpu_pipeline.sv) -- kept here so an SoC-level
  // testbench has the same visibility earlier testbenches had.
  output logic [31:0] dbg_if_pc, dbg_if_instr,
  output logic [31:0] dbg_id_pc, dbg_id_instr,
  output logic [31:0] dbg_ex_pc, dbg_ex_instr,
  output logic [31:0] dbg_mem_instr,
  output logic [31:0] dbg_wb_instr,
  output logic         dbg_reg_write,
  output logic [4:0]  dbg_rd_addr,
  output logic [31:0] dbg_rd_data,
  output logic         dbg_illegal,
  output logic         dbg_stall, dbg_flush,

  output logic [31:0] perf_cycle_count,
  output logic [31:0] perf_instr_retired_count,
  output logic [31:0] perf_stall_count,
  output logic [31:0] perf_branch_count,
  output logic [31:0] perf_branch_taken_count,
  output logic [31:0] perf_load_use_stall_count,
  output logic [31:0] perf_forwarding_event_count,
  output logic [31:0] perf_flush_count
);

  // -------------------------------------------------------------------
  // CPU <-> bus wires
  // -------------------------------------------------------------------
  logic [31:0] dbus_addr, dbus_wdata, dbus_rdata;
  logic         dbus_mem_read, dbus_mem_write;

  riscv_cpu_pipeline #(
    .IMEM_DEPTH_WORDS(IMEM_DEPTH_WORDS),
    .IMEM_INIT_FILE  (IMEM_INIT_FILE)
  ) cpu_inst (
    .clk(clk), .rst_n(rst_n),
    .dbus_addr(dbus_addr), .dbus_wdata(dbus_wdata),
    .dbus_mem_read(dbus_mem_read), .dbus_mem_write(dbus_mem_write),
    .dbus_rdata(dbus_rdata),
    .dbg_if_pc(dbg_if_pc), .dbg_if_instr(dbg_if_instr),
    .dbg_id_pc(dbg_id_pc), .dbg_id_instr(dbg_id_instr),
    .dbg_ex_pc(dbg_ex_pc), .dbg_ex_instr(dbg_ex_instr),
    .dbg_mem_instr(dbg_mem_instr),
    .dbg_wb_instr(dbg_wb_instr),
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

  // -------------------------------------------------------------------
  // Bus <-> peripheral wires
  // -------------------------------------------------------------------
  logic [31:0] ram_addr, ram_wdata, ram_rdata;
  logic         ram_mem_read, ram_mem_write;

  logic [31:0] uart_addr, uart_wdata, uart_rdata;
  logic         uart_mem_read, uart_mem_write;

  logic [31:0] gpio_addr, gpio_wdata, gpio_rdata;
  logic         gpio_mem_read, gpio_mem_write;

  logic [31:0] accel_addr, accel_wdata, accel_rdata;
  logic         accel_mem_read, accel_mem_write;

  soc_bus bus_inst (
    .cpu_addr(dbus_addr), .cpu_wdata(dbus_wdata),
    .cpu_mem_read(dbus_mem_read), .cpu_mem_write(dbus_mem_write),
    .cpu_rdata(dbus_rdata),

    .ram_addr(ram_addr), .ram_wdata(ram_wdata),
    .ram_mem_read(ram_mem_read), .ram_mem_write(ram_mem_write),
    .ram_rdata(ram_rdata),

    .uart_addr(uart_addr), .uart_wdata(uart_wdata),
    .uart_mem_read(uart_mem_read), .uart_mem_write(uart_mem_write),
    .uart_rdata(uart_rdata),

    .gpio_addr(gpio_addr), .gpio_wdata(gpio_wdata),
    .gpio_mem_read(gpio_mem_read), .gpio_mem_write(gpio_mem_write),
    .gpio_rdata(gpio_rdata),

    .accel_addr(accel_addr), .accel_wdata(accel_wdata),
    .accel_mem_read(accel_mem_read), .accel_mem_write(accel_mem_write),
    .accel_rdata(accel_rdata)
  );

  // -------------------------------------------------------------------
  // Peripherals
  // -------------------------------------------------------------------
  dmem #(
    .DEPTH_WORDS(RAM_DEPTH_WORDS)
  ) ram_inst (
    .clk(clk), .addr(ram_addr), .wdata(ram_wdata),
    .mem_read(ram_mem_read), .mem_write(ram_mem_write), .rdata(ram_rdata)
  );

  uart #(
    .BUSY_CYCLES(UART_BUSY_CYCLES)
  ) uart_inst (
    .clk(clk), .rst_n(rst_n),
    .addr(uart_addr), .wdata(uart_wdata),
    .mem_read(uart_mem_read), .mem_write(uart_mem_write), .rdata(uart_rdata),
    .tx_valid(uart_tx_valid), .tx_byte(uart_tx_byte)
  );

  gpio gpio_inst (
    .clk(clk), .rst_n(rst_n),
    .addr(gpio_addr), .wdata(gpio_wdata),
    .mem_read(gpio_mem_read), .mem_write(gpio_mem_write), .rdata(gpio_rdata),
    .gpio_out(gpio_out), .gpio_in(gpio_in)
  );

  accelerator #(
    .MAX_DIM(ACCEL_MAX_DIM), .MAX_LEN(ACCEL_MAX_DIM * ACCEL_MAX_DIM)
  ) accel_inst (
    .clk(clk), .rst_n(rst_n),
    .addr(accel_addr), .wdata(accel_wdata),
    .mem_read(accel_mem_read), .mem_write(accel_mem_write), .rdata(accel_rdata)
  );

endmodule
