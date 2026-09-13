#!/usr/bin/env python3
"""
asm_to_hex.py -- a small, purpose-built assembler for this project's RV32I
subset (docs/riscv.md).

This is NOT a general RISC-V assembler. It supports exactly the
instructions this project has documented and implemented, so that a typo'd
mnemonic or operand is a hard error rather than silently producing wrong
machine code. It exists so hand-written directed test programs (Phase 3)
and CPU bring-up programs (Phase 2) don't have to be hex-encoded by hand.

Output: one 32-bit instruction per line, as plain hex digits (no "0x"
prefix), suitable for Verilog/SystemVerilog $readmemh().

Design note on pseudo-instructions: a couple of convenience pseudo-ops
(`li`, `mv`, `j`, `ret`) are supported, expanded into real instructions.
`li` with a value that doesn't fit in 12 bits expands to *two* real
instructions (LUI+ADDI). Because of that, this assembler fully expands
all pseudo-ops into real instructions *before* assigning addresses and
resolving labels -- assigning addresses per source line first and
expanding afterwards would silently corrupt every label address that
comes after a two-word `li`. See `expand_pseudo()` / `assemble()`.

Usage:
    python3 scripts/asm_to_hex.py program.s -o program.hex
"""

import argparse
import re
import sys

# ---------------------------------------------------------------------
# Register names -> number
# ---------------------------------------------------------------------
ABI_NAMES = {
    "zero": 0, "ra": 1, "sp": 2, "gp": 3, "tp": 4,
    "t0": 5, "t1": 6, "t2": 7,
    "s0": 8, "fp": 8, "s1": 9,
    "a0": 10, "a1": 11, "a2": 12, "a3": 13, "a4": 14, "a5": 15, "a6": 16, "a7": 17,
    "s2": 18, "s3": 19, "s4": 20, "s5": 21, "s6": 22, "s7": 23, "s8": 24, "s9": 25,
    "s10": 26, "s11": 27,
    "t3": 28, "t4": 29, "t5": 30, "t6": 31,
}
for _i in range(32):
    ABI_NAMES[f"x{_i}"] = _i


def reg(tok):
    tok = tok.strip().rstrip(",")
    if tok not in ABI_NAMES:
        raise ValueError(f"unknown register '{tok}'")
    return ABI_NAMES[tok]


def fit_imm(val, bits, signed=True):
    lo = -(1 << (bits - 1)) if signed else 0
    hi = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
    if not (lo <= val <= hi):
        raise ValueError(f"immediate {val} out of range [{lo},{hi}] for {bits}-bit field")
    return val & ((1 << bits) - 1)


def imm_tok(tok, bits, signed=True):
    return fit_imm(int(tok.strip().rstrip(","), 0), bits, signed)


# ---------------------------------------------------------------------
# Encoders for each format (bit layouts per docs/riscv.md section 2)
# ---------------------------------------------------------------------
def enc_r(funct7, rs2, rs1, funct3, rd, opcode):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def enc_i(imm12, rs1, funct3, rd, opcode):
    return ((imm12 & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def enc_s(imm12, rs2, rs1, funct3, opcode):
    imm12 &= 0xFFF
    return ((imm12 >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | ((imm12 & 0x1F) << 7) | opcode


def enc_b(imm13, rs2, rs1, funct3, opcode):
    imm13 &= 0x1FFF
    bit12 = (imm13 >> 12) & 1
    bit11 = (imm13 >> 11) & 1
    bits10_5 = (imm13 >> 5) & 0x3F
    bits4_1 = (imm13 >> 1) & 0xF
    return (bit12 << 31) | (bits10_5 << 25) | (rs2 << 20) | (rs1 << 15) | \
           (funct3 << 12) | (bits4_1 << 8) | (bit11 << 7) | opcode


def enc_u(imm20, rd, opcode):
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | opcode


def enc_j(imm21, rd, opcode):
    imm21 &= 0x1FFFFF
    bit20 = (imm21 >> 20) & 1
    bits19_12 = (imm21 >> 12) & 0xFF
    bit11 = (imm21 >> 11) & 1
    bits10_1 = (imm21 >> 1) & 0x3FF
    return (bit20 << 31) | (bits10_1 << 21) | (bit11 << 20) | (bits19_12 << 12) | (rd << 7) | opcode


OPCODES = {
    "R": 0b0110011, "I": 0b0010011, "LOAD": 0b0000011, "STORE": 0b0100011,
    "BRANCH": 0b1100011, "LUI": 0b0110111, "AUIPC": 0b0010111,
    "JAL": 0b1101111, "JALR": 0b1100111,
}

R_OPS = {  # mnemonic -> (funct3, funct7)
    "add": (0b000, 0b0000000), "sub": (0b000, 0b0100000),
    "sll": (0b001, 0b0000000), "slt": (0b010, 0b0000000),
    "sltu": (0b011, 0b0000000), "xor": (0b100, 0b0000000),
    "srl": (0b101, 0b0000000), "sra": (0b101, 0b0100000),
    "or": (0b110, 0b0000000), "and": (0b111, 0b0000000),
}

I_ARITH_OPS = {  # mnemonic -> funct3 (no shift-amount funct7 distinction)
    "addi": 0b000, "slti": 0b010, "sltiu": 0b011,
    "xori": 0b100, "ori": 0b110, "andi": 0b111,
}

I_SHIFT_OPS = {  # mnemonic -> (funct3, funct7)
    "slli": (0b001, 0b0000000), "srli": (0b101, 0b0000000), "srai": (0b101, 0b0100000),
}

BRANCH_OPS = {
    "beq": 0b000, "bne": 0b001, "blt": 0b100, "bge": 0b101, "bltu": 0b110, "bgeu": 0b111,
}

LABEL_TARGET_OPS = set(BRANCH_OPS) | {"jal", "j"}

MEM_RE = re.compile(r"^(-?\w+)\((\w+)\)$")


def split_ops(s):
    return [t.strip() for t in s.split(",") if t.strip() != ""]


def parse_mem_operand(tok):
    """Parse 'imm(rs1)' -> (imm_str, rs1_num)."""
    m = MEM_RE.match(tok.strip())
    if not m:
        raise ValueError(f"expected 'imm(reg)' operand, got '{tok}'")
    return m.group(1), reg(m.group(2))


# ---------------------------------------------------------------------
# Pass 1: read source into a flat list of (labels_here, mnemonic, ops)
# ---------------------------------------------------------------------
def parse_source(lines):
    items = []          # list of (mnem, ops:list[str])
    pending_labels = []  # labels seen since the last real item
    label_targets = {}   # item_index -> [label names] (index into `items`
                          # BEFORE pseudo-expansion; remapped after)

    for raw in lines:
        line = re.split(r"[#;]", raw, maxsplit=1)[0].strip()
        if not line:
            continue
        while ":" in line:
            label, _, rest = line.partition(":")
            pending_labels.append(label.strip())
            line = rest.strip()
            if not line:
                break
        if not line:
            continue
        parts = line.split(None, 1)
        mnem = parts[0].lower()
        ops = split_ops(parts[1]) if len(parts) > 1 else []
        if pending_labels:
            label_targets[len(items)] = list(pending_labels)
            pending_labels = []
        items.append((mnem, ops))

    if pending_labels:
        raise ValueError(f"label(s) {pending_labels} at end of file with no following instruction")

    return items, label_targets


# ---------------------------------------------------------------------
# Pass 2: expand pseudo-instructions into real ones, preserving which
# real instruction each original label now points at.
# ---------------------------------------------------------------------
def expand_pseudo(mnem, ops):
    """Return a list of (mnem, ops) real instructions for one source item."""
    if mnem == "nop":
        return [("addi", ["x0", "x0", "0"])]
    if mnem == "li":
        rd, val_tok = ops[0], ops[1]
        val = int(val_tok, 0)
        if -2048 <= val <= 2047:
            return [("addi", [rd, "x0", str(val)])]
        upper = (val + 0x800) >> 12
        lower = val - (upper << 12)
        return [("lui", [rd, str(upper & 0xFFFFF)]),
                ("addi", [rd, rd, str(lower)])]
    if mnem == "mv":
        return [("addi", [ops[0], ops[1], "0"])]
    if mnem == "j":
        return [("jal", ["x0", ops[0]])]
    if mnem == "ret":
        return [("jalr", ["x0", "ra", "0"])]
    return [(mnem, ops)]


def assemble(lines):
    items, label_targets = parse_source(lines)

    # Expand pseudo-ops first, tracking where each original label now
    # points (the address of the FIRST real instruction it expanded to).
    real_items = []
    labels = {}
    for idx, (mnem, ops) in enumerate(items):
        expanded = expand_pseudo(mnem, ops)
        if idx in label_targets:
            for name in label_targets[idx]:
                labels[name] = len(real_items) * 4
        real_items.extend(expanded)

    words = []
    for addr, (mnem, ops) in zip(range(0, len(real_items) * 4, 4), real_items):
        def resolve_branch_target(tok, bits):
            tok = tok.strip()
            if tok in labels:
                return fit_imm(labels[tok] - addr, bits, signed=True)
            return imm_tok(tok, bits, signed=True)

        if mnem in R_OPS:
            f3, f7 = R_OPS[mnem]
            rd, rs1, rs2 = reg(ops[0]), reg(ops[1]), reg(ops[2])
            words.append(enc_r(f7, rs2, rs1, f3, rd, OPCODES["R"]))
        elif mnem in I_ARITH_OPS:
            f3 = I_ARITH_OPS[mnem]
            rd, rs1 = reg(ops[0]), reg(ops[1])
            val = imm_tok(ops[2], 12, signed=True)
            words.append(enc_i(val, rs1, f3, rd, OPCODES["I"]))
        elif mnem in I_SHIFT_OPS:
            f3, f7 = I_SHIFT_OPS[mnem]
            rd, rs1 = reg(ops[0]), reg(ops[1])
            shamt = imm_tok(ops[2], 5, signed=False)
            words.append(enc_i((f7 << 5) | shamt, rs1, f3, rd, OPCODES["I"]))
        elif mnem == "lw":
            rd = reg(ops[0])
            off_tok, rs1 = parse_mem_operand(ops[1])
            words.append(enc_i(imm_tok(off_tok, 12, signed=True), rs1, 0b010, rd, OPCODES["LOAD"]))
        elif mnem == "sw":
            rs2 = reg(ops[0])
            off_tok, rs1 = parse_mem_operand(ops[1])
            words.append(enc_s(imm_tok(off_tok, 12, signed=True), rs2, rs1, 0b010, OPCODES["STORE"]))
        elif mnem in BRANCH_OPS:
            f3 = BRANCH_OPS[mnem]
            rs1, rs2 = reg(ops[0]), reg(ops[1])
            off = resolve_branch_target(ops[2], 13)
            words.append(enc_b(off, rs2, rs1, f3, OPCODES["BRANCH"]))
        elif mnem == "lui":
            rd = reg(ops[0])
            val = imm_tok(ops[1], 20, signed=False)
            words.append(enc_u(val, rd, OPCODES["LUI"]))
        elif mnem == "auipc":
            rd = reg(ops[0])
            val = imm_tok(ops[1], 20, signed=False)
            words.append(enc_u(val, rd, OPCODES["AUIPC"]))
        elif mnem == "jal":
            rd = reg(ops[0])
            target = resolve_branch_target(ops[1], 21)
            words.append(enc_j(target, rd, OPCODES["JAL"]))
        elif mnem == "jalr":
            rd = reg(ops[0])
            if len(ops) == 3:
                rs1, off_tok = reg(ops[1]), ops[2]
            else:
                off_tok, rs1 = parse_mem_operand(ops[1])
            words.append(enc_i(imm_tok(off_tok, 12, signed=True), rs1, 0b000, rd, OPCODES["JALR"]))
        else:
            raise ValueError(f"unsupported mnemonic '{mnem}' (not in docs/riscv.md subset)")

    return words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--words", type=int, default=None,
                     help="pad output with zero words up to this many total")
    args = ap.parse_args()

    with open(args.input) as f:
        lines = f.readlines()

    try:
        words = assemble(lines)
    except ValueError as e:
        print(f"assemble error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.words is not None:
        if len(words) > args.words:
            print(f"error: program has {len(words)} words, exceeds --words {args.words}", file=sys.stderr)
            sys.exit(1)
        words += [0] * (args.words - len(words))

    with open(args.output, "w") as f:
        for w in words:
            f.write(f"{w & 0xFFFFFFFF:08x}\n")

    print(f"assembled {args.input} -> {args.output} ({len(words)} words)")


if __name__ == "__main__":
    main()
