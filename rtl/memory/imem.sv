`timescale 1ns/1ps
// imem.sv
//
// Simulated instruction memory. Word-addressed, initialized from a
// $readmemh hex file (one 32-bit instruction word per line, as produced
// by scripts/asm_to_hex.py or by objcopy in later phases). Read is
// combinational: in a single-cycle CPU the fetched instruction must be
// available within the same cycle the new PC is presented, with no
// clock-edge latency, exactly like a fast SRAM/ROM being read
// asynchronously would behave in this simulation-only model. This is a
// behavioral simulation model, not a synthesizable ROM -- see
// docs/soc.md (Phase 8) for how instruction storage is treated once this
// becomes a real SoC memory map.
//
// Which file to load: a runtime `+HEXFILE=path` plusarg takes priority
// over the INIT_FILE parameter. This lets Phase 3's directed-test suite
// compile the testbench once and re-run it against dozens of different
// test programs (`vvp sim.vvp +HEXFILE=sim/programs/tests/add.hex`)
// instead of recompiling per test; Phase 2's testbench, which never
// passes +HEXFILE, is unaffected and keeps using INIT_FILE.

module imem #(
  parameter int DEPTH_WORDS = 1024,
  parameter      INIT_FILE  = ""
) (
  input  logic [31:0] addr, // byte address (must be word-aligned)
  output logic [31:0] instr
);

  localparam int WORD_ADDR_BITS = $clog2(DEPTH_WORDS);

  logic [31:0] mem [0:DEPTH_WORDS-1];

  initial begin
    string runtime_hexfile;
    for (int i = 0; i < DEPTH_WORDS; i++) mem[i] = 32'b0;
    if ($value$plusargs("HEXFILE=%s", runtime_hexfile))
      $readmemh(runtime_hexfile, mem);
    else if (INIT_FILE != "")
      $readmemh(INIT_FILE, mem);
  end

  // Only the bits that actually index the array are used; addr's upper
  // bits are simply not part of this memory's address decode (a real SoC
  // address map, Phase 8, is what turns "upper bits select which device"
  // into an actual decoder).
  assign instr = mem[addr[WORD_ADDR_BITS+1:2]];

endmodule
