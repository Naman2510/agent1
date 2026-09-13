# RISC-V ISA Reference (Project Subset)

This document is the authoritative specification for the subset of the
RISC-V instruction set implemented by this project. Every hardware module
(decoder, ALU, branch unit, control unit) and every test in later phases
must conform exactly to what is written here. If an implementation and
this document ever disagree, this document wins unless it is itself
updated (with a changelog entry explaining why).

Source of truth: *The RISC-V Instruction Set Manual, Volume I: Unprivileged
ISA*. This project targets the **RV32I** base integer instruction set,
version 2.1 (as ratified), with no privileged architecture, no CSRs, and
no standard extensions (M, A, F, D, C) in the initial phases.

## 1. Programmer's Model

### 1.1 Registers

RV32I defines 32 general-purpose integer registers, `x0`–`x31`, each
32 bits wide, plus a separate 32-bit program counter (`PC`) that is not
part of the register file.

| Register | ABI name | Description                          | Saved by |
|----------|----------|---------------------------------------|----------|
| x0       | zero     | Hard-wired constant 0                 | —        |
| x1       | ra       | Return address                        | caller   |
| x2       | sp       | Stack pointer                         | callee   |
| x3       | gp       | Global pointer                        | —        |
| x4       | tp       | Thread pointer                        | —        |
| x5       | t0       | Temporary                             | caller   |
| x6       | t1       | Temporary                             | caller   |
| x7       | t2       | Temporary                             | caller   |
| x8       | s0/fp    | Saved register / frame pointer        | callee   |
| x9       | s1       | Saved register                        | callee   |
| x10      | a0       | Argument / return value               | caller   |
| x11      | a1       | Argument / return value               | caller   |
| x12–x17  | a2–a7    | Arguments                             | caller   |
| x18–x27  | s2–s11   | Saved registers                       | callee   |
| x28–x31  | t3–t6    | Temporaries                           | caller   |

**x0 is hard-wired to zero.** It always reads as `0x00000000` regardless
of what is written to it; writes to `x0` are legal and have no effect.
This project's register file enforces this in hardware (Phase 2), not
just by software convention.

### 1.2 Program Counter (PC)

A single 32-bit `PC` holds the byte address of the instruction currently
being fetched. RV32I instructions are always 4 bytes and word-aligned, so
`PC[1:0]` is always `00` for every instruction this project executes
(the base ISA requires `PC` to be a multiple of 2, but since we implement
no compressed extension, all instruction addresses here are multiples
of 4). On reset, `PC = 0x00000000`, which is the base address of
instruction memory.

### 1.3 Memory Model

Byte-addressable, little-endian, flat 32-bit address space (no virtual
memory, no privilege levels). Data accesses in the currently supported
subset are word-sized (`LW`/`SW`) and must be naturally aligned
(word address `[1:0] == 00`); misaligned access behavior is undefined
in this project until explicitly implemented.

## 2. Instruction Formats

RV32I encodes every instruction in a fixed 32-bit word using one of six
formats. Bit positions are `[31:0]`, bit 31 is the MSB.

```
 31        25 24     20 19     15 14  12 11      7 6      0
+------------+---------+---------+------+---------+--------+
| funct7     |   rs2   |   rs1   |funct3|   rd    | opcode | R-type
+------------+---------+---------+------+---------+--------+
|      imm[11:0]       |   rs1   |funct3|   rd    | opcode | I-type
+------------+---------+---------+------+---------+--------+
| imm[11:5]  |   rs2   |   rs1   |funct3| imm[4:0]| opcode | S-type
+------------+---------+---------+------+---------+--------+
|imm[12|10:5]|   rs2   |   rs1   |funct3|imm[4:1|11]|opcode| B-type
+------------+---------+---------+------+---------+--------+
|              imm[31:12]                |   rd    | opcode | U-type
+------------+---------+---------+------+---------+--------+
|         imm[20|10:1|11|19:12]          |   rd    | opcode | J-type
+------------+---------+---------+------+---------+--------+
```

Field meanings:

- `opcode` (bits 6:0) — selects the instruction format and broad
  operation class.
- `rd` (bits 11:7) — destination register.
- `funct3` (bits 14:12) — narrows the operation within an opcode class.
- `rs1`, `rs2` (bits 19:15, 24:20) — source registers.
- `funct7` (bits 31:25) — further narrows R-type operations (e.g.
  distinguishes `ADD` from `SUB`).
- `imm` — an immediate value, assembled from non-contiguous bit fields
  as shown; always sign-extended to 32 bits except where noted.

### 2.1 Immediate assembly

| Format | Immediate bits, MSB → LSB (source positions in the instruction word) | Notes |
|--------|---------------------------------------------------------------------|-------|
| I-type | `inst[31:20]` → `imm[11:0]`                                          | Sign-extend from bit 31 (=`inst[31]`) |
| S-type | `inst[31:25]:inst[11:7]` → `imm[11:0]`                               | Sign-extend from bit 31 |
| B-type | `inst[31]:inst[7]:inst[30:25]:inst[11:8]:1'b0` → `imm[12:0]`         | Bit 0 is always 0 (branch targets are 2-byte, effectively 4-byte, aligned); sign-extend from bit 31 |
| U-type | `inst[31:12]:12'b0` → `imm[31:0]`                                    | Immediate occupies the upper 20 bits, lower 12 bits are zero |
| J-type | `inst[31]:inst[19:12]:inst[20]:inst[30:21]:1'b0` → `imm[20:0]`       | Bit 0 is always 0; sign-extend from bit 31 |

This scrambled bit layout is not arbitrary — it is chosen upstream by the
RISC-V spec authors so that as many immediate bits as possible line up
with the same instruction-word bit position across formats (e.g. the sign
bit is always `inst[31]`), which simplifies the immediate-generator
hardware. Phase 2's immediate generator implements exactly this table.

## 3. Supported Instructions (Phase 1 subset)

All instructions below are standard, unmodified RV32I encodings — no
custom encodings are introduced yet (that happens in Phase 10, in an
opcode space reserved by the spec for custom extensions, so it cannot
collide with anything in this table).

### 3.1 R-type — Register-Register ALU ops

opcode = `0110011` (`OP`)

| Mnemonic | funct3 | funct7    | Operation                          |
|----------|--------|-----------|-------------------------------------|
| ADD      | 000    | 0000000   | rd = rs1 + rs2                     |
| SUB      | 000    | 0100000   | rd = rs1 - rs2                     |
| SLL      | 001    | 0000000   | rd = rs1 << rs2[4:0]               |
| SLT      | 010    | 0000000   | rd = (rs1 <s rs2) ? 1 : 0 (signed) |
| SLTU     | 011    | 0000000   | rd = (rs1 <u rs2) ? 1 : 0 (unsigned) — *implemented for completeness, not in the minimum list but required for a correct SLTIU-consistent ALU* |
| XOR      | 100    | 0000000   | rd = rs1 ^ rs2                     |
| SRL      | 101    | 0000000   | rd = rs1 >> rs2[4:0] (logical)     |
| SRA      | 101    | 0100000   | rd = rs1 >>> rs2[4:0] (arithmetic) |
| OR       | 110    | 0000000   | rd = rs1 \| rs2                    |
| AND      | 111    | 0000000   | rd = rs1 & rs2                     |

Note: only the low 5 bits of the shift amount (`rs2[4:0]`) are used,
since RV32 shifts are defined modulo 32.

### 3.2 I-type — Register-Immediate ALU ops

opcode = `0010011` (`OP-IMM`)

| Mnemonic | funct3 | imm[11:5] (shift ops only) | Operation                              |
|----------|--------|------------------------------|-----------------------------------------|
| ADDI     | 000    | —                             | rd = rs1 + sext(imm)                    |
| SLTI     | 010    | —                             | rd = (rs1 <s sext(imm)) ? 1 : 0         |
| SLTIU    | 011    | —                             | rd = (rs1 <u sext(imm)) ? 1 : 0         |
| XORI     | 100    | —                             | rd = rs1 ^ sext(imm)                    |
| ORI      | 110    | —                             | rd = rs1 \| sext(imm)                   |
| ANDI     | 111    | —                             | rd = rs1 & sext(imm)                    |
| SLLI     | 001    | 0000000                       | rd = rs1 << shamt (shamt = imm[4:0])    |
| SRLI     | 101    | 0000000                       | rd = rs1 >> shamt (logical)             |
| SRAI     | 101    | 0100000                       | rd = rs1 >>> shamt (arithmetic)         |

For `SLLI`/`SRLI`/`SRAI`, the immediate field is reinterpreted: bits
`[24:20]` are the 5-bit shift amount, and bits `[31:25]` behave like a
mini funct7 (`0000000` vs `0100000`) selecting logical vs arithmetic
right shift, mirroring the R-type `SRL`/`SRA` split.

### 3.3 Loads

opcode = `0000011` (`LOAD`), I-type

| Mnemonic | funct3 | Operation                                  |
|----------|--------|---------------------------------------------|
| LW       | 010    | rd = sext(Mem32[rs1 + sext(imm)])            |

(`LB`, `LH`, `LBU`, `LHU` are part of RV32I but are **not implemented**
in this project's initial subset per the project scope; only word loads
are required. This is documented here explicitly rather than left
ambiguous, per the project's engineering rules.)

### 3.4 Stores

opcode = `0100011` (`STORE`), S-type

| Mnemonic | funct3 | Operation                            |
|----------|--------|----------------------------------------|
| SW       | 010    | Mem32[rs1 + sext(imm)] = rs2[31:0]      |

(`SB`, `SH` not implemented in this subset, same rationale as loads.)

### 3.5 Branches

opcode = `1100011` (`BRANCH`), B-type. Target = `PC + sext(imm)`.

| Mnemonic | funct3 | Taken condition                  |
|----------|--------|------------------------------------|
| BEQ      | 000    | rs1 == rs2                         |
| BNE      | 001    | rs1 != rs2                         |
| BLT      | 100    | rs1 <s rs2 (signed)                |
| BGE      | 101    | rs1 >=s rs2 (signed)               |
| BLTU     | 110    | rs1 <u rs2 (unsigned) — *for ALU/branch-unit completeness* |
| BGEU     | 111    | rs1 >=u rs2 (unsigned) — *for ALU/branch-unit completeness* |

### 3.6 Upper-immediate

U-type.

| Mnemonic | opcode    | Operation                          |
|----------|-----------|--------------------------------------|
| LUI      | 0110111   | rd = imm[31:12] << 12 (imm[11:0]=0)  |
| AUIPC    | 0010111   | rd = PC + (imm[31:12] << 12)         |

### 3.7 Jumps

| Mnemonic | opcode    | Format | Operation                                        |
|----------|-----------|--------|---------------------------------------------------|
| JAL      | 1101111   | J-type | rd = PC + 4; PC = PC + sext(imm)                   |
| JALR     | 1100111   | I-type | rd = PC + 4; PC = (rs1 + sext(imm)) & ~1 (funct3=000) |

### 3.8 Full opcode map (this subset)

| opcode (bin) | opcode (hex) | Format | Mnemonics |
|--------------|--------------|--------|-----------|
| 0110011      | 0x33         | R      | ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND |
| 0010011      | 0x13         | I      | ADDI, SLTI, SLTIU, XORI, ORI, ANDI, SLLI, SRLI, SRAI |
| 0000011      | 0x03         | I      | LW |
| 0100011      | 0x23         | S      | SW |
| 1100011      | 0x63         | B      | BEQ, BNE, BLT, BGE, BLTU, BGEU |
| 0110111      | 0x37         | U      | LUI |
| 0010111      | 0x17         | U      | AUIPC |
| 1101111      | 0x6F         | J      | JAL |
| 1100111      | 0x67         | I      | JALR |

Every opcode value not in this table is undefined behavior in this
project (the control unit will treat it as an illegal instruction; Phase
2 defines the exact fallback: PC does not retire and a diagnostic is
asserted in simulation, since there is no trap/exception handling yet).

## 4. Explicitly Out of Scope (for now)

To keep each phase honest about what is and is not implemented:

- Compressed instructions (RVC / "C" extension) — not implemented.
- Multiply/divide (M extension) — not implemented until a phase explicitly adds it.
- Atomics (A), floating point (F/D) — not implemented.
- CSRs, traps, interrupts, privilege modes (M/S/U) — not implemented.
- Byte/halfword loads and stores (`LB`, `LH`, `LBU`, `LHU`, `SB`, `SH`) — not implemented; only `LW`/`SW`.
- Misaligned memory access handling — undefined until implemented.
- `FENCE`, `ECALL`, `EBREAK` — not implemented.

Later phases (Phase 10) add exactly one custom, non-conflicting
extension for accelerator control; that encoding is documented in
`docs/custom_extension.md` when it is introduced, not here.

## 5. References

- RISC-V Instruction Set Manual, Volume I: Unprivileged ISA (riscv.org)
- RISC-V ELF psABI specification (for the ABI register names in §1.1)
