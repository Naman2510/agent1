# rtl/bus
Memory-mapped peripheral/accelerator bus and address decode logic: `soc_bus.sv` (address decoder routing the CPU's data-bus-master port to RAM/UART/GPIO/accelerator by `addr[31:28]`, Phase 8, with the accelerator port wired in Phase 9), `uart.sv`, `gpio.sv` (Phase 8). The accelerator itself lives in `rtl/accelerator/`. See `docs/soc.md` for the full memory map.
