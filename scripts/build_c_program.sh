#!/usr/bin/env bash
# build_c_program.sh -- Phase 4 end-to-end build: real C source, through
# the real RISC-V GCC toolchain, to a memory image this project's
# simulated instruction memory can load.
#
#   C source (software/baremetal/*.c)
#     -> riscv64-unknown-elf-gcc (rv32i/ilp32, -O0, freestanding)
#     -> object files, linked against software/runtime/start.S via
#        software/runtime/link.ld
#     -> riscv64-unknown-elf-objcopy -O binary (raw memory image)
#     -> scripts/bin_to_hex.py ($readmemh-compatible hex)
#
# This uses the ACTUAL RISC-V cross-compiler and linker -- not this
# project's own scripts/asm_to_hex.py, which is only for this project's
# own hand-written directed test programs (Phase 2/3). Nothing about the
# C program is emulated in Python; every instruction the CPU executes was
# produced by GCC.
#
# Usage: scripts/build_c_program.sh <name>
#   Compiles software/baremetal/<name>.c, produces
#   software/baremetal/<name>.{elf,bin,hex} and prints the disassembly.

set -euo pipefail
cd "$(dirname "$0")/.."

NAME="${1:?usage: scripts/build_c_program.sh <name> (expects software/baremetal/<name>.c)}"
SRC="software/baremetal/${NAME}.c"
[ -f "$SRC" ] || { echo "not found: $SRC" >&2; exit 1; }

CC=riscv64-unknown-elf-gcc
OBJCOPY=riscv64-unknown-elf-objcopy
OBJDUMP=riscv64-unknown-elf-objdump

CFLAGS="-march=rv32i -mabi=ilp32 -nostdlib -nostartfiles -ffreestanding -O0"

BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"' EXIT

echo "== Compiling software/runtime/start.S =="
$CC $CFLAGS -c software/runtime/start.S -o "$BUILD_DIR/start.o"

echo "== Compiling $SRC =="
$CC $CFLAGS -c "$SRC" -o "$BUILD_DIR/${NAME}.o"

echo "== Linking (software/runtime/link.ld) =="
$CC $CFLAGS -nostdlib -Wl,-T,software/runtime/link.ld \
    -o "software/baremetal/${NAME}.elf" \
    "$BUILD_DIR/start.o" "$BUILD_DIR/${NAME}.o"

echo "== Disassembly =="
$OBJDUMP -d "software/baremetal/${NAME}.elf"

echo "== Extracting raw binary =="
$OBJCOPY -O binary "software/baremetal/${NAME}.elf" "software/baremetal/${NAME}.bin"

echo "== Converting to \$readmemh hex =="
python3 scripts/bin_to_hex.py "software/baremetal/${NAME}.bin" \
    -o "software/baremetal/${NAME}.hex" --words 1024

echo
echo "Built software/baremetal/${NAME}.{elf,bin,hex}"
