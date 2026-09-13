/* link.ld -- linker script for Phase 4 bare-metal programs.
 *
 * Places code and data starting at address 0, matching this project's
 * simulated instruction/data memory (rtl/memory/imem.sv, dmem.sv), which
 * have no real address decode yet (that's Phase 8's SoC memory map).
 * .text.start (start.S's _start) is placed first so the CPU's PC, which
 * resets to 0 (docs/riscv.md section 1.2), begins execution at _start
 * rather than at an arbitrary point inside main()'s object code.
 */

ENTRY(_start)

MEMORY {
  RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 4096
}

SECTIONS {
  . = 0x00000000;

  .text : {
    *(.text.start)
    *(.text*)
  } > RAM

  .rodata : {
    *(.rodata*)
  } > RAM

  .data : {
    *(.data*)
  } > RAM

  .bss : {
    *(.bss*)
    *(COMMON)
  } > RAM

  /DISCARD/ : { *(.riscv.attributes) *(.comment) }
}
