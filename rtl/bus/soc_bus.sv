`timescale 1ns/1ps
// soc_bus.sv
//
// Phase 8: address decoder / router connecting riscv_cpu_pipeline's
// single data-bus-master port (dbus_addr/dbus_wdata/dbus_mem_read/
// dbus_mem_write/dbus_rdata -- see rtl/cpu/riscv_cpu_pipeline.sv's
// header comment) to the SoC's memory-mapped peripherals. See
// docs/soc.md for the full memory map; summarized here:
//
//   addr[31:28] == 4'h0  ->  RAM   (0x00000000 - 0x0FFFFFFF)
//   addr[31:28] == 4'h1  ->  UART  (0x10000000 - 0x1FFFFFFF)
//   addr[31:28] == 4'h2  ->  GPIO  (0x20000000 - 0x2FFFFFFF)
//   addr[31:28] == 4'h3  ->  Accelerator (0x30000000 - 0x3FFFFFFF,
//                             rtl/accelerator/accelerator.sv, Phase 9)
//   anything else         ->  unmapped: reads as 0, writes dropped
//
// RAM is deliberately kept at address 0x00000000 (not, say, moved to
// make room for a "device 0"): every existing test program from Phases
// 2-7 was assembled assuming LW/SW addresses starting at 0, and this
// decoder exists specifically so that assumption keeps holding when
// those same programs run through the full SoC instead of a bare dmem
// (see docs/soc.md's regression section for how this was verified).
//
// Decode is purely combinational, exactly like dmem.sv's own
// combinational read: for a given addr held stable during a read, the
// selected peripheral's rdata is muxed back out the same cycle,
// matching every prior memory model's timing so the CPU pipeline's
// existing MEM-stage timing assumptions don't need to change.
//
// Address forwarding: addr/wdata are broadcast to all peripheral ports,
// but mem_read/mem_write are only asserted to the ONE selected
// peripheral -- so an access to UART cannot accidentally also assert a
// write strobe into RAM or GPIO just because they all see the same
// wires.

module soc_bus (
  // CPU-facing (bus-master) side
  input  logic [31:0] cpu_addr,
  input  logic [31:0] cpu_wdata,
  input  logic         cpu_mem_read,
  input  logic         cpu_mem_write,
  output logic [31:0] cpu_rdata,

  // RAM port
  output logic [31:0] ram_addr,
  output logic [31:0] ram_wdata,
  output logic         ram_mem_read,
  output logic         ram_mem_write,
  input  logic [31:0] ram_rdata,

  // UART port
  output logic [31:0] uart_addr,
  output logic [31:0] uart_wdata,
  output logic         uart_mem_read,
  output logic         uart_mem_write,
  input  logic [31:0] uart_rdata,

  // GPIO port
  output logic [31:0] gpio_addr,
  output logic [31:0] gpio_wdata,
  output logic         gpio_mem_read,
  output logic         gpio_mem_write,
  input  logic [31:0] gpio_rdata,

  // Accelerator port (Phase 9)
  output logic [31:0] accel_addr,
  output logic [31:0] accel_wdata,
  output logic         accel_mem_read,
  output logic         accel_mem_write,
  input  logic [31:0] accel_rdata
);

  localparam logic [3:0] SEL_RAM   = 4'h0;
  localparam logic [3:0] SEL_UART  = 4'h1;
  localparam logic [3:0] SEL_GPIO  = 4'h2;
  localparam logic [3:0] SEL_ACCEL = 4'h3; // reserved for Phase 9

  wire [3:0] sel = cpu_addr[31:28];

  wire is_ram   = (sel == SEL_RAM);
  wire is_uart  = (sel == SEL_UART);
  wire is_gpio  = (sel == SEL_GPIO);
  wire is_accel = (sel == SEL_ACCEL);

  // Broadcast addr/wdata; each peripheral only sees the low bits it
  // actually decodes internally (its own register-offset window), same
  // pattern as imem/dmem already use for their word-index slice.
  assign ram_addr   = cpu_addr;
  assign ram_wdata  = cpu_wdata;
  assign ram_mem_read  = cpu_mem_read  && is_ram;
  assign ram_mem_write = cpu_mem_write && is_ram;

  assign uart_addr  = cpu_addr;
  assign uart_wdata = cpu_wdata;
  assign uart_mem_read  = cpu_mem_read  && is_uart;
  assign uart_mem_write = cpu_mem_write && is_uart;

  assign gpio_addr  = cpu_addr;
  assign gpio_wdata = cpu_wdata;
  assign gpio_mem_read  = cpu_mem_read  && is_gpio;
  assign gpio_mem_write = cpu_mem_write && is_gpio;

  assign accel_addr  = cpu_addr;
  assign accel_wdata = cpu_wdata;
  assign accel_mem_read  = cpu_mem_read  && is_accel;
  assign accel_mem_write = cpu_mem_write && is_accel;

  assign cpu_rdata = is_ram   ? ram_rdata   :
                      is_uart  ? uart_rdata  :
                      is_gpio  ? gpio_rdata  :
                      is_accel ? accel_rdata :
                      32'b0; // unmapped reads as 0

endmodule
