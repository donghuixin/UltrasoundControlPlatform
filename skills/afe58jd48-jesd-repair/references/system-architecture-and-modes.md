# System Architecture and Modes

## Signal chain

```text
TX7316 pattern/delay -> high-voltage T/R node -> probe/phantom
echo -> TX7316 internal T/R switch -> AFE58JD48 -> JESD204B
     -> TSW14J50 FPGA/DDR -> HSDC Pro -> raw BIN + manifest
```

Do not connect J5 RX outputs to the probe. J5 is the protected low-voltage receive output to the AFE.
Do not treat SYNCP as an external TX input; on the stock EVM it is a CPLD-derived output/observation point.

## Keep three timing domains separate

- The JESD device/reference clocks establish and maintain the high-speed data link.
- PRF identifies each ultrasound transmit/receive event.
- HSDC capture trigger arms one DDR acquisition. It does not create one record per PRF pulse.

Do not connect unrelated clock or sync SMA ports merely because their names contain `SYNC`.
Use a fan-out/buffer and verified logic levels when one timing source must reach multiple boards.

## Capture modes

- B-mode: capture RF per steering event, preserve exact angle/profile mapping, then receive-DAS and compound.
- PW Doppler: hold angle and range gate fixed, acquire a coherent slow-time ensemble, then demodulate/filter/estimate.
- HSDC DDR: finite capture followed by transfer/save; use blocks with timestamps for long recordings.
- Custom streaming: requires a suitable TSW14J50 FPGA design and host transport; the standard GUI is not proof of this mode.

