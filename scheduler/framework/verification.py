"""
verification.py -- expected output words for a generated program, and the
expect-file format sim/testbenches/tb_coschedule_check.sv reads
(one 64-bit hex word per line: {ram_word_index[31:0], value[31:0]}).
"""

from . import operations as ops
from .rv32_codegen import layout


def expected_words(stream):
    """[(ram_word_index, value)] for every output word of every task."""
    out = []
    for (op, n), base in zip(stream, layout(stream)):
        for i, v in enumerate(ops.reference(op, n)):
            out.append((base // 4 + i, v))
    return out


def write_expect_file(stream, path):
    words = expected_words(stream)
    with open(path, "w") as f:
        for idx, v in words:
            f.write(f"{idx:08x}{v:08x}\n")
    return len(words)
