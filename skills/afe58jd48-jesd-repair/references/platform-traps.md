# Previously encountered platform traps

Use the failure signature before changing hardware or JESD settings.

| Symptom | Meaning and first action |
|---|---|
| TX7316 `FTDI I/O error` / Error 4 | Usually a stale or multiply owned FTDI handle. Turn TX high voltage off, close every TX automation client, power-cycle the TX USB/control rail, and start one administrator GUI. Do not continue from an unknown register state. |
| HSDC Automation `Connect_Board` code 66 | The process may be open while the Automation session is dead or another client owns it. Stop all acquisition processes, restart HSDC Pro, select the intended device once, then retry with one client. |
| HSDC `JTAG_CHAIN_BROKEN` or firmware version `0.0` | FPGA firmware did not load. Recover board power/USB/JTAG and download the matching firmware before any converter mapping test. |
| HSDC `DATA_READ_FAILED` / DDR timeout | No valid packet reached DDR. Check AFE initialization, sample/JESD clocks, firmware/profile match, and external-trigger arrival. This is not the same signature as stable duplicated columns. |
| Console pauses during `ADC_Save_Raw_Data_As_Binary_File` | TI's save API is blocking and can take tens of seconds for a large file. Use the acquisition heartbeat and file-size verification; do not press Ctrl+C unless the timeout expires. |
| TX pattern readback mismatch | Fail closed. Do not capture until the programmed pattern matches a whitelisted reference and the readback is saved with the run. |
| Reconstruction crashes on `float(None)` for `expected_prf_hz` | A historical manifest bug, fixed by safe fallback. It does not alter raw samples and is unrelated to JESD converter duplication. |
| `SYNCP` exists while `TX_BF_MODE=0` | Normal for the stock CPLD: SYNCP is a free-running event output, not proof of high-voltage transmit and not an external 20 kHz input. Use a validated buffer to TSW J13 only for capture start. Never connect it to an LMK clock input. |
| Acoustic channels have high correlation or low SVD rank | Not sufficient to diagnose JESD. Plane reflectors and common transmit feedthrough can be coherent. Repeat the internal distinct-code transport gate. |
| Bit-exact duplicate columns survive 65,536 samples and cold starts | Deterministic transport/deformatter failure. Do not blame PDMS, FPC, transducer crosstalk, gain, or beamforming. |

Repository details are in `docs/07_TROUBLESHOOTING.md`, `docs/09_RECENT_SOFTWARE_UPDATES.md`, `docs/05_TRIGGER_AND_SYNC.md`, and `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md`.
