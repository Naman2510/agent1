#!/usr/bin/env python3
"""
prep_synth_rtl.py -- Phase 12: stage a synthesis-only COPY of rtl/ with
one mechanical transformation applied, needed because Yosys 0.33's
open-source Verilog/SystemVerilog frontend does not support
`import riscv_pkg::*;` in ANY form (module-header or module-body,
wildcard or explicit) -- verified directly against Yosys itself, not
assumed:

    $ yosys -p "read_verilog -sv <file with 'import pkg::*;'>"
    ERROR: syntax error, unexpected TOK_ID / TOK_PACKAGESEP, ...

but it DOES understand fully-qualified references like
`riscv_pkg::ALU_ADD`. This script never edits rtl/ in place -- it
writes a transformed copy to build/synth_src/, leaving every simulated,
tested, and committed source file under rtl/ completely untouched.
Only scripts/run_synthesis.sh reads from build/synth_src/; every other
script and testbench in this project continues to read rtl/ directly.

The transformation, applied only to the 8 files that import
riscv_pkg (`grep -rl "import riscv_pkg" rtl/`):
  1. Delete the `import riscv_pkg::*;` line.
  2. Replace every whole-word reference to one of riscv_pkg.sv's own
     exported parameter names (extracted directly from riscv_pkg.sv,
     not hardcoded here, so this script can't silently drift out of
     sync with the package) with its fully-qualified form
     (`riscv_pkg::NAME`), unless already qualified.

This is a syntactic transformation only -- per the SystemVerilog LRM, a
wildcard import and a fully-qualified reference to the same symbol
resolve to the identical declaration, so this does not change what the
design means. It is not just assumed equivalent, either:
scripts/run_synthesis.sh re-simulates a sample of the transformed files
against the SAME existing testbenches used throughout this project
(Icarus Verilog) and requires an exact pass before treating any
synthesis result as trustworthy -- see that script and
docs/synthesis.md for how.

Usage:
    python3 scripts/prep_synth_rtl.py
"""

import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RTL_DIR = os.path.join(ROOT, "rtl")
OUT_DIR = os.path.join(ROOT, "build", "synth_src")

PKG_FILE = os.path.join(RTL_DIR, "cpu", "riscv_pkg.sv")

IMPORT_LINE_RE = re.compile(r"^\s*import\s+riscv_pkg\s*::\s*\*\s*;\s*$", re.MULTILINE)
PARAM_DECL_RE = re.compile(
    r"parameter\s+(?:logic\s*\[[^\]]*\]\s+|int\s+)(\w+)\s*="
)


def extract_package_symbols(pkg_path):
    with open(pkg_path) as f:
        text = f.read()
    symbols = PARAM_DECL_RE.findall(text)
    if not symbols:
        raise RuntimeError(f"no exported parameters found in {pkg_path} -- "
                            "extraction regex may be out of sync with riscv_pkg.sv")
    return symbols


def qualify_references(text, symbols):
    for name in symbols:
        # Whole-word match, not already preceded by "::" (i.e. not
        # already qualified as pkg::NAME or accidentally matching part
        # of a longer identifier).
        pattern = re.compile(r"(?<!::)\b" + re.escape(name) + r"\b")
        text = pattern.sub(f"riscv_pkg::{name}", text)
    return text


def transform_file(src_path, symbols):
    with open(src_path) as f:
        text = f.read()
    text = IMPORT_LINE_RE.sub("", text)
    text = qualify_references(text, symbols)
    return text


def main():
    symbols = extract_package_symbols(PKG_FILE)
    print(f"Extracted {len(symbols)} exported symbols from riscv_pkg.sv")

    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)

    files_needing_transform = set()
    for dirpath, _dirs, files in os.walk(RTL_DIR):
        for fname in files:
            if not fname.endswith(".sv"):
                continue
            fpath = os.path.join(dirpath, fname)
            with open(fpath) as f:
                if "import riscv_pkg" in f.read():
                    files_needing_transform.add(fpath)

    copied, transformed = 0, 0
    for dirpath, _dirs, files in os.walk(RTL_DIR):
        rel_dir = os.path.relpath(dirpath, RTL_DIR)
        out_subdir = os.path.join(OUT_DIR, rel_dir) if rel_dir != "." else OUT_DIR
        os.makedirs(out_subdir, exist_ok=True)
        for fname in files:
            if not fname.endswith(".sv"):
                continue
            src_path = os.path.join(dirpath, fname)
            dst_path = os.path.join(out_subdir, fname)
            if src_path in files_needing_transform:
                text = transform_file(src_path, symbols)
                with open(dst_path, "w") as f:
                    f.write(text)
                transformed += 1
            else:
                shutil.copyfile(src_path, dst_path)
                copied += 1

    print(f"Staged {copied} file(s) unchanged, transformed {transformed} "
          f"file(s) (removed 'import riscv_pkg::*;', qualified package "
          f"references) into {OUT_DIR}")


if __name__ == "__main__":
    main()
