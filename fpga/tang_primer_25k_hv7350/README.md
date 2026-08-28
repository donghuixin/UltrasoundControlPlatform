# Tang Primer 25K + HV7350 Final FPGA Control

This directory contains the final fixed transmit/damping build and the original
2 MHz rollback baseline for the eight-channel HV7350 transmitter.

## Final selected behavior

- Automatic startup after FPGA configuration; no button press is required.
- Carrier: **2.2 MHz** (`DEFAULT_FREQ_WORD = 0x0B439581` at 50 MHz).
- Main burst: **2 cycles**, positive-unipolar RTZ.
- Beam profile: fixed **0 degrees** in this build.
- PRF: **10 kHz** (100 us between bursts).
- J11: 200 ns trigger pulse, exactly 2 us before each burst.
- J10: rises with the burst and remains high for 50 us.
- After the main burst: 140 ns at RGND, then one 100 ns negative damping
  pulse on NIN. The design assumes VNN is fixed at -30 V.
- S1 is disconnected. S2 is retained only as an optional emergency
  stop/restart input.
- READY and DONE are steady high while transmission is running.
- UART cannot override the fixed carrier or cycle count.

The 2.2 MHz/140 ns setting produced the lowest measured CH1 post-T/R-switch
ringing among the 2.0, 2.2, and 2.4 MHz experiments. A second negative pulse is
not included because its cancellation phase was not measured, and the existing
high-resolution CH2 captures already showed approximately -46 to -51 V
instantaneous ceramic-terminal excursions with VNN fixed at -30 V.

## Final programming artifacts

- `artifacts/pmod_led_FINAL_2p2mhz_2cycles_pos_fixed140ns_neg30v_100ns_autostart.fs`
  - SHA-256: `f2021537d6facac767b4c1101f1ee417342aa0bed40c74f4fc81953e3e0397bc`
- `artifacts/pmod_led_FINAL_2p2mhz_2cycles_pos_fixed140ns_neg30v_100ns_autostart.bin`
  - SHA-256: `c7d5b6ca0e9d24e5ba1b1ad210566be2e377a625278d652b2fc32f18fc824086`

Use the `.fs` file with Gowin Programmer. The transmitter starts automatically
as soon as FPGA configuration completes, so keep the high-voltage rails off
during programming and logic-level verification.

## Timing and measurement documentation

- `docs/final_tx_rx_timing.md`: exact J11/PIN/NIN timing, 13-20 mm range-gate
  calculation, analog blanking, template subtraction, and Doppler processing
  order.
- `docs/final_control_2p2mhz.md`: final parameter decision and comparison of
  the three carrier-frequency experiments.
- `docs/ringing_damping_results_2mhz.md`: 2.0 MHz delay sweep.
- `docs/ringing_damping_results_2p2mhz.md`: 2.2 MHz delay sweep and peak-voltage
  caution.
- `docs/beamformer_control.md`: complete FPGA behavior and wiring summary.
- `docs/hv7350_wiring.md`: FPGA-to-HV7350 wiring details.

## Original rollback baseline

The earlier 2.0 MHz, 2-cycle, positive-only build remains available and is
preserved by tag `fpga-hv7350-2mhz-2cycles-positive-20260829`:

- `artifacts/pmod_led_2mhz_2cycles_positive_10khz.fs`
  - SHA-256: `2387ddf2f2f56a7190c81315636add51abffe9f930ac46348b9a820e5a73b36d`
- `artifacts/pmod_led_2mhz_2cycles_positive_10khz.bin`
  - SHA-256: `ea99941ec9fade86d59ef353f1b2fe90e84e793dab2931ea57777460628a8714`

That tagged baseline has no negative damping pulse and requires manual button
control. It is retained only for rollback and comparison.

## Rebuild and verify

From this directory:

```bash
python3 scripts/verify_scan_timing.py
python3 scripts/configure_beamformer.py \
  --dry-run \
  --frequency-mhz 2.2 \
  --cycles 2 \
  --angle-deg 0 \
  --pitch-mm 1.0
gw_sh scripts/build_fpga.tcl
```

The Gowin project targets `GW5A-LV25MG121NC1/I0`. Generated `impl/` output is
not versioned; only named programming artifacts are committed.

## Safety boundary

This is an experimental high-voltage ultrasound pulser and is not a medically
certified system. Validate all 3.3 V logic signals with VPP/VNN disabled. The
final bitstream transmits automatically, and VNN=-30 V must not be treated as a
clamp on instantaneous ceramic voltage.
