# Configuration snapshots

- `hsdc/AFE58JD48_120M_8L_M16_FIXED.ini`: HSDC Pro 5.31 / TSW14J50RX 16-channel, 120-MSPS, 8-lane profile with JESD converter count corrected to M=16. Do not use the legacy MANUAL/M=5 file.
- `tx7316/1MHz_5pulses.cfg`: 1-MHz internal quick-start preset copied from the installed TX7316 EVM software package. Despite the TI filename, `REPEAT_COUNT=3` produces four acoustic cycles; SBOU224A also labels this preset `Internal: 1 MHz, 4 pulses`.

Treat these as versioned baselines, not proof of the live hardware state. After loading, read back the registers/JESD status and verify the acoustic spectrum from a real capture.
