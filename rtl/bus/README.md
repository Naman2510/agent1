# rtl/bus
Memory-mapped peripheral/accelerator bus and address decode logic (Phase 8): `soc_bus.sv` (address decoder routing the CPU's data-bus-master port to RAM/UART/GPIO/accelerator by `addr[31:28]`), `uart.sv`, `gpio.sv`. See `docs/soc.md` for the full memory map.
