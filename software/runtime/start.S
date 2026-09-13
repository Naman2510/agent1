/* start.S -- minimal bare-metal entry point for Phase 4.
 *
 * There is no OS, no C runtime, and no trap/exception architecture
 * (docs/riscv.md section 4), so this is the entire "runtime": set up a
 * stack pointer, call main(), and park in an infinite loop when main()
 * returns (there is nowhere else to return to). This is real RISC-V
 * assembly, assembled by the actual riscv64-unknown-elf toolchain --
 * not this project's own scripts/asm_to_hex.py, which exists only for
 * this project's own hand-written directed test programs.
 *
 * Stack pointer value: 0xFF0, near the top of the 4096-byte (1024-word)
 * simulated data memory (rtl/memory/dmem.sv default DEPTH_WORDS=1024)
 * with headroom below 0x1000 so a stack that grows downward never runs
 * into an out-of-range address for this small memory.
 */

    .section .text.start
    .global _start
_start:
    li   sp, 0xFF0
    jal  ra, main
halt:
    j    halt
