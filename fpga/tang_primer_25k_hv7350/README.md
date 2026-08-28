# Tang Primer 25K + HV7350 FPGA Baseline

This directory is the rollback baseline for the eight-channel HV7350 transmit
beamformer used with the Tang Primer 25K.

## Frozen behavior

- Carrier: **2.0 MHz** (`DEFAULT_FREQ_WORD = 0x0A3D70A4` at 50 MHz)
- Burst length: **2 carrier cycles** (approximately 1 us)
- Output mode: **positive-unipolar RTZ**
  - `PIN1..PIN8` carry the delayed transmit burst
  - `NIN1..NIN8` are permanently low
  - the intended high-voltage output is `0 V / +VPP`
- PRF: **10 kHz** (100 us frame period)
- J11: 200 ns trigger pulse, 2 us before each transmit burst
- J10: 10 kHz frame reference; burst starts with the J10 frame
- S2: master READY/transmit enable; disabling forces all outputs low
- S1: advances one fixed steering step through -10 to +10 degrees
- Steering: eight-channel true-time delay table, 1.00 mm default pitch,
  1540 m/s sound speed, 20 ns delay resolution
- No Barker/PRBS/chirp coding and no active-damping tail pulse in this baseline

## Rollback artifacts

- `artifacts/pmod_led_2mhz_2cycles_positive_10khz.fs`
  - SHA-256: `2387ddf2f2f56a7190c81315636add51abffe9f930ac46348b9a820e5a73b36d`
- `artifacts/pmod_led_2mhz_2cycles_positive_10khz.bin`
  - SHA-256: `ea99941ec9fade86d59ef353f1b2fe90e84e793dab2931ea57777460628a8714`

Use the `.fs` file with Gowin Programmer for the normal FPGA programming
workflow. Verify the checksum before programming when reproducing this exact
baseline.

## Rebuild and verify

From this directory:

```bash
python3 scripts/verify_scan_timing.py
python3 scripts/configure_beamformer.py \
  --dry-run \
  --frequency-mhz 2.0 \
  --cycles 2 \
  --angle-deg 10 \
  --pitch-mm 1.0
gw_sh scripts/build_fpga.tcl
```

The Gowin project targets `GW5A-LV25MG121NC1/I0`. Generated `impl/` output is
not versioned; only the named rollback artifacts above are committed.

## Safety boundary

This is an experimental high-voltage ultrasound pulser project. Validate the
3.3 V logic waveforms with the high-voltage rails disabled before connecting
the HV7350 outputs. It is not a medically certified system.
