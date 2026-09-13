#!/usr/bin/env python3
"""
bin_to_hex.py -- convert a flat little-endian binary (as produced by
`riscv64-unknown-elf-objcopy -O binary`) into a $readmemh-compatible hex
file: one 32-bit word per line, plain hex digits, no "0x" prefix. This is
the same output format scripts/asm_to_hex.py produces, so every memory
image in this project -- whether from this project's own toy assembler or
from the real RISC-V GCC toolchain -- loads into rtl/memory/imem.sv the
same way.

Usage:
    python3 scripts/bin_to_hex.py program.bin -o program.hex --words 1024
"""

import argparse
import struct
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--words", type=int, required=True,
                     help="total words to emit, zero-padded if the binary is shorter")
    args = ap.parse_args()

    with open(args.input, "rb") as f:
        data = f.read()

    if len(data) % 4 != 0:
        pad = 4 - (len(data) % 4)
        data += b"\x00" * pad

    words = list(struct.unpack(f"<{len(data)//4}I", data))

    if len(words) > args.words:
        print(f"error: binary has {len(words)} words, exceeds --words {args.words}",
              file=sys.stderr)
        sys.exit(1)
    words += [0] * (args.words - len(words))

    with open(args.output, "w") as f:
        for w in words:
            f.write(f"{w:08x}\n")

    print(f"converted {args.input} -> {args.output} ({len(words)} words)")


if __name__ == "__main__":
    main()
