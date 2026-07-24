# Configuration snapshots

- `hsdc/AFE58JD48_120M_8L_M16_FIXED.ini`: experimental HSDC Pro 5.31 / TSW14J50RX 16-column, 120-MSPS, 8-lane profile using a literal M=16 field. It has **not** passed the 16/16 unique-code transport gate.
- `afe58jd48/AFE58JD48_120M_8L_S1_K8.cfg`: minimal AFE overlay that pairs the TI Subclass-1 8-lane quick-start with the K=8 HSDC profile.
- `afe58jd48/AFE58JD48_120M_8L_S1_K16_ROLLBACK.cfg`: restores the original TI quick-start K=16 value.
- `afe58jd48/ADC_UNIQUE_CODES_16CH.cfg` and `ADC_ANALOG_RESTORE.cfg`: non-acoustic 16-channel transport mapping test and its rollback.
- Files containing `S2_K8_EXPERIMENTAL` form a matched AFE/HSDC Subclass-2 pair. Use them only as the second-stage experiment described in `docs/09_CHANNEL_JESD_REPAIR_FOR_CODEX.md`.
- `tx7316/1MHz_5pulses.cfg`: 1-MHz internal quick-start preset copied from the installed TX7316 EVM software package. Despite the TI filename, `REPEAT_COUNT=3` produces four acoustic cycles; SBOU224A also labels this preset `Internal: 1 MHz, 4 pulses`.

Treat these as versioned baselines, not proof of the live hardware state. After loading, read back the registers/JESD status and verify the acoustic spectrum from a real capture.

As of 2026-07-25, matched S1/K8, matched S2/K8 and the TI-installed original
S1 profile all produced the same deterministic duplicate mapping
`[3,5] [4,6] [9,15] [10,16]`. The TI-original profile's private
`JESD IP Core_M=5` field and the repository's literal `M=16` field therefore
cannot be interpreted by name alone. Do not promote or overwrite any installed
profile until a candidate passes `automation/jesd_transport_qa.py` with 16/16
distinct stable codes. See `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md`.
