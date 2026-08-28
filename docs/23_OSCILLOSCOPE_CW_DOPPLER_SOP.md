# Oscilloscope-first CW Doppler SOP (no FPGA modification)

## Decision

The highest-feasibility path with the currently validated hardware is:

1. one dedicated TX element;
2. three independent RX elements;
3. Rigol CH1–CH3 record RX, CH4 records an isolated/attenuated copy of the real TX waveform;
4. save all four channels in one RG01 BIN file;
5. perform TX-referenced coherent I/Q demodulation offline.

This path does not depend on the currently unvalidated AFE demodulator import,
HSDC I/Q unpacking, auto-re-arm, or a TSW14J50 FPGA modification.  It is a
CW/bistatic measurement: it has no depth gate and is not PW Doppler.

## Safety boundary

- Do not connect a normal earth-ground oscilloscope probe directly to a TX7316
  high-voltage output.
- CH4 must receive the TX reference through a correctly rated differential HV
  probe, an isolated monitor, or a purpose-built attenuated pickoff.
- Verify the pickoff voltage with TX supplies off before applying high voltage.
- Do not use a common physical element for CW transmit and receive with an
  ordinary switched T/R path.  CW requires separate TX and RX elements.
- Do not connect a person during engineering validation.  Use water and a flow
  phantom first; verify electrical and acoustic safety separately.

## Recommended element assignment

The present board/GUI is the **TX7316 5LVL EVM**.  For this version the official
CW test path is different from B-mode:

- J7 pins 11–18 are the eight CW output pins (B1–B8); use **J7 pin 11 / B1**
  as the first dedicated TX output.
- J7 pins 3–10 are A1–A8.  Connect three independent receive patches to
  **J7 pins 3, 4, and 5 / A1–A3**.
- The corresponding protected receive-path outputs are **J5 pins 3, 4, and 5**.
  Route these through three identical receive-conditioning chains to Rigol
  CH1, CH2, and CH3.
- Route an isolated/attenuated copy of the actual waveform on J7 pin 11 to
  Rigol CH4.  CH4 is the coherent phase reference; SYNC is not a substitute.

Use the physical connector and pin numbers as the authority.  Harness labels
such as A1/B1 must be continuity-checked because a reversed connector view can
make them appear swapped.  The observed 3.125 MHz signal proves an output is
active, but does not by itself prove its logical channel name.

## Scope connections and input settings

1. Use equal-length RX cables and identical gain/filter settings.
2. Physically separate the TX cable/harness from the RX harness.
3. Fix the array and phantom so that neither can move during the five-second
   record.
4. Use 1 Mohm scope input for a bare high-impedance piezo/preamplifier output.
   Use 50 ohm only when the preceding source is designed to drive 50 ohm.
5. Start with the 20 MHz bandwidth limit on CH1–CH3.  Do not enable averaging,
   peak detect, or Roll acquisition.
6. Adjust each vertical range so the carrier/echo occupies roughly 30–70% of
   the display and has ample headroom.  No channel may clip.

## Rigol acquisition settings

- Acquisition type: Normal/Sample.
- Channels: CH1–CH4 enabled.
- Sample rate: 25 MSa/s.
- Memory depth: 125 Mpts per enabled channel if the scope reports that value
  after all four channels are enabled.  Some instruments share memory; verify
  the final on-screen point count instead of assuming it.
- Expected duration at 125 Mpts and 25 MSa/s: 5.0 s.
- Trigger source: CH4 TX reference.
- Trigger type: edge; level near 50% of the CH4 swing.
- Acquisition: Single.
- Horizontal position: 5–10% pre-trigger is sufficient for CW.
- Save format: BIN, Source/Range = Memory, Full Memory, or All Points.
- Save the scope setup and a screenshot next to each BIN.

If the scope has a separate external-trigger input, J7 pin 2 `TR_BF_SYNC` may
be connected to EXT trigger to make record starts repeatable while CH4 remains
the real TX phase reference.  This 1 kHz SYNC signal is optional for continuous
CW Doppler and must not be confused with the HSDC capture trigger.

Do not use CSV for full memory.  After saving, confirm that the BIN size and
RG01 header point count are consistent with four recorded channels.

## TX7316 starting state

Use the documented 5-level EVM CW procedure and the state already verified by
oscilloscope:

- TP19: about 200 MHz;
- TP21: about 50 MHz;
- TP18 SYNC and TP20 TREN: about 1 kHz in the validated cold-start state;
- J7 pins 11–18: about 3.125 MHz CW output when CW is enabled;
- for the official CW test, manually reduce the J1 positive and negative HV
  supplies to **+5 V and -5 V** and set the current limit of each +/-5 V supply
  to **500 mA** before enabling CW.  This voltage is set on the bench supplies,
  not selected in the GUI;
- keep `PDN_GBL`, `STNDBY_G1`, and `STNDBY_G2` clear;
- enable `CW_EN_MUX_SEL`, `CW_EN_1`, and `CW_EN_2`, select `Bipolar CW`, and
  enable CW from Quick Setup;
- `TR_SW_DIS_A1`, `TR_SW_DIS_A2`, and `TR_SW_DIS_A3` must be **clear** so the
  three A-side T/R receive paths are not powered down.  Unused paths may remain
  disabled;
- verify J7 pin 11 first with a correctly rated probe before connecting the TX
  patch, then verify J5 pins 3–5 with a small known injected/acoustic tone before
  recording flow.

Do not use continuous +/-30 V merely because that was the lowest convenient
setting on a previous supply.  It is not the user-guide CW starting condition
and raises transducer heating and acoustic-output risk.

## Capture matrix before any velocity claim

Record at least three repeats of each condition with exactly the same scope
settings:

1. TX off: electronics noise.
2. TX on with the acoustic path blocked/removed: electrical feedthrough.
3. TX on in air: cable and board coupling.
4. Still water: stationary acoustic clutter.
5. No-flow phantom: stationary phantom baseline.
6. Known-flow phantom at 0.2, 0.5, and 1.0 m/s.
7. Repeat known flow in the reverse direction.

Only proceed to non-diagnostic human measurements after the phantom criteria
below pass and electrical/acoustic safety has been reviewed.

## Offline coherent I/Q

Run from PowerShell with Python 3:

```powershell
python E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundControlPlatform_repo\tools\rigol_cw_doppler.py `
  --input "E:\path\to\four_channel_capture.bin" `
  --out-root "E:\Users\dxhui\Desktop\TI_AFE58jd48\Oscilloscope_CW_Analysis" `
  --rx-channels 1,2,3 `
  --tx-reference-channel 4 `
  --carrier-hz 3125000 `
  --target-iq-rate 25000 `
  --baseband-lowpass-hz 8000 `
  --wall-hz 100
```

The tool opens the BIN read-only and always creates a new timestamped result
directory.  It does not overwrite or delete the original capture.  Outputs are:

- `analysis_manifest.json`: source and parameter provenance;
- `qa.json`: carrier, common-mode, directionality, and per-channel metrics;
- `iq_downsampled.npz`: coherent raw and wall-filtered I/Q;
- `doppler_spectrogram.png`: signed Doppler spectrum versus time.

For an existing three-channel file without TX reference, add
`--no-tx-reference`.  Such output is useful for compatibility and artifact
inspection, but its Doppler sign and velocity are not validated.

## Velocity calibration

CW bistatic Doppler follows

`f_D = (f0/c) * v dot (e_TX + e_RX)`.

Do not use the monostatic factor of two unless TX and RX look directions are
actually identical.  The preferred calibration is a known-flow phantom.  Fit
one signed slope in Hz/(m/s) per RX channel and rerun with, for example:

```powershell
  --calibration-hz-per-mps 4050,3990,3920
```

Geometry-only velocity can be explored with `--tx-angle-deg`,
`--rx-angles-deg`, and `--flow-angle-deg`, but it is not a replacement for
known-flow calibration.

## Acceptance criteria

- no clipping or ADC range saturation;
- clear CH4 carrier and repeatable carrier frequency;
- known-flow Doppler frequency is linear with speed, R-squared >= 0.95;
- reverse flow reverses the signed spectral displacement;
- estimated speed error <= 10–15% over the calibrated range;
- no-flow spectral power is at least 20 dB below the useful flow band;
- motion/tapping moves all RX channels together and must not be called blood
  flow;
- three repeats agree before PSV, EDV, RI, or PI is reported.

High rank-1/common variance is reported as a warning.  The analyzer does not
blindly remove the first principal component because true blood signals may also
be common to adjacent RX elements.
