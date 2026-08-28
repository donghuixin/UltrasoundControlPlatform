# 8-Channel HV7350 Beamformer

## Current FPGA Behavior

- The FPGA starts disabled. READY, DONE, J11, J10, and all 16 HV7350 logic
  outputs are low.
- Press S2 once to turn READY on. The first steering angle is -10 degrees and
  the FPGA keeps transmitting that same beam at 10 kHz; it does not scan
  automatically.
- While READY is on, each press of the board S1 button advances exactly one
  step: -10, -8, -6, -4, -2, 0, +2, +4, +6, +8, +10, then back to -10.
  The new angle is latched at the next J11 rising edge and remains fixed until
  S1 is pressed again.
- DONE alternates one second on and one second off while READY is on.
- J11 is a 200 ns-wide, 10 kHz trigger. J10 and each transmit burst start
  exactly 2 us after the J11 rising edge; the remaining 1.8 us after J11 falls
  is still part of the pretrigger delay. The first J11 pulse after S2 always
  identifies the first -10 degree burst. Every subsequent J11 pulse identifies
  a burst at the currently selected fixed angle.
- Pressing S2 again turns READY off and immediately forces J11, J10, DONE, and
  all 16 HV7350 PIN/NIN outputs low. Pressing S2 again always starts a fresh
  sequence at -10 degrees with a new J11 trigger at 10 kHz; the previous angle
  is not resumed.
- The default carrier is 2.0 MHz and every burst contains exactly 2 cycles.
- Transmission is positive-unipolar RTZ: PIN1..PIN8 generate positive pulses
  and every NIN output is permanently low. With OEN high, PIN=NIN=0 selects the
  HV7350 ground-return switch, so each channel alternates between +VPP and 0 V
  without enabling its negative high-voltage switch. Set VPP to +30 V to obtain
  a nominal +30 V/0 V output.
- UART configuration can change carrier frequency, burst cycles, element pitch,
  sound speed, and all eight channel delays. The host uploads all 11 scan-angle
  profiles for the selected pitch. Frequency and cycle updates take effect
  together at a 100 us frame boundary.

The built-in steering delays below assume 1.00 mm element pitch, 1540 m/s sound
speed, and a 50 MHz FPGA clock (one tick is 20 ns):

| Angle | CH1 | CH2 | CH3 | CH4 | CH5 | CH6 | CH7 | CH8 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| -10° | 39 | 34 | 28 | 23 | 17 | 11 | 6 | 0 |
| -8° | 32 | 27 | 23 | 18 | 14 | 9 | 5 | 0 |
| -6° | 24 | 20 | 17 | 14 | 10 | 7 | 3 | 0 |
| -4° | 16 | 14 | 11 | 9 | 7 | 5 | 2 | 0 |
| -2° | 8 | 7 | 6 | 5 | 3 | 2 | 1 | 0 |
| 0° | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| +2° | 0 | 1 | 2 | 3 | 5 | 6 | 7 | 8 |
| +4° | 0 | 2 | 5 | 7 | 9 | 11 | 14 | 16 |
| +6° | 0 | 3 | 7 | 10 | 14 | 17 | 20 | 24 |
| +8° | 0 | 5 | 9 | 14 | 18 | 23 | 27 | 32 |
| +10° | 0 | 6 | 11 | 17 | 23 | 28 | 34 | 39 |

These are true-time steering delays, so changing the carrier to 2.0 MHz does
not change the propagation delay required for a given angle. The
table was recalculated and quantized again at 20 ns resolution; its tick values
therefore remain the same, while the corresponding carrier phase changes.

## FPGA to HV7350 H2 Wiring

All signals in this table are 3.3 V logic. They do not carry high voltage.

| Channel | FPGA positive output | HV7350 board | FPGA negative output | HV7350 board |
| --- | --- | --- | --- | --- |
| CH1 | B2 / `tx1_pin_b2` | H2.2 PIN1 | F2 / `tx1_nin_f2` | H2.4 NIN1 |
| CH2 | E1 / `tx2_pin_e1` | H2.6 PIN2 | E3 / `tx2_nin_e3` | H2.8 NIN2 |
| CH3 | J1 / `tx3_pin_j1` | H2.10 PIN3 | G4 / `tx3_nin_g4` | H2.12 NIN3 |
| CH4 | H1 / `tx4_pin_h1` | H2.14 PIN4 | K7 / `tx4_nin_k7` | H2.16 NIN4 |
| CH5 | L7 / `tx5_pin_l7` | H2.18 PIN5 | L10 / `tx5_nin_l10` | H2.20 NIN5 |
| CH6 | L9 / `tx6_pin_l9` | H2.22 PIN6 | J8 / `tx6_nin_j8` | H2.24 NIN6 |
| CH7 | F7 / `tx7_pin_f7` | H2.26 PIN7 | K8 / `tx7_nin_k8` | H2.28 NIN7 |
| CH8 | L8 / `tx8_pin_l8` | H2.30 PIN8 | K10 / `tx8_nin_k10` | H2.32 NIN8 |

NIN1..NIN8 remain physically connected as listed above, but the FPGA drives all
eight pins permanently low in this build. PIN1..PIN8 carry the transmit burst.

Required common control and power wiring:

| Source | HV7350 board connection | Purpose |
| --- | --- | --- |
| FPGA/board 3V3 | H2.1 CLK | High selects direct/asynchronous PIN/NIN control |
| FPGA/board 3V3 | H2.31 OEN | Enable high-voltage output stages |
| FPGA/board 3V3 | H2.29 REN | Enable the internal floating regulator |
| FPGA/board 3V3 | H2 3V3 pins | HV7350 VLL logic supply |
| FPGA GND | H2 GND pins | Common logic reference |
| HV supply + | H3/H4.1 HVDC+ | Positive high-voltage rail |
| HV supply return | H3/H4.2 GND | High-voltage supply return |
| HV supply - | H3/H4.3 HVDC- | Negative high-voltage rail |

The actual high-voltage channel outputs are H1.1, H1.5, H1.9, H1.13,
H1.17, H1.21, H1.25, and H1.29. Never connect an H1 pin to the FPGA.

## UART Configuration Wiring

Use a 3.3 V USB-UART adapter, not a 5 V adapter:

| USB-UART | FPGA |
| --- | --- |
| TX | B3 / `uart_rx_b3` |
| GND | FPGA GND |

Baud rate is 115200, format is 8-N-1. C3 is reserved as TX but is idle-high in
this version; configuration is one-way and has no acknowledgement.

Example for the default 2.0 MHz carrier, 1.00 mm element pitch, and 2-cycle
burst (the script uploads all scan angles):

```bash
python3 scripts/configure_beamformer.py \
  --port /dev/cu.usbserial-0001 \
  --frequency-mhz 2.0 \
  --angle-deg 10 \
  --pitch-mm 1.00 \
  --cycles 2
```

Inspect the calculated delays without opening a serial port:

```bash
python3 scripts/configure_beamformer.py \
  --dry-run \
  --frequency-mhz 2.0 \
  --angle-deg 10 \
  --pitch-mm 1.00
```

If CH1..CH8 are wired in the opposite physical order, add `--reverse-array`.
The default sound speed is 1540 m/s for soft tissue and can be changed with
`--sound-speed`.

`--pitch-mm` is therefore a run-time configuration value. Every invocation of
the script regenerates and uploads the complete -10 to +10 degree scan table. The
uploaded table is held in FPGA registers; after FPGA power loss or reprogramming,
it returns to the built-in 1.00 mm table until the script is run again.

## Timing and Accuracy

For a linear array, the host computes the transmit delays from:

```text
x[i] = (i - 3.5) * pitch
raw_delay[i] = x[i] * sin(angle) / sound_speed
delay[i] = raw_delay[i] - min(raw_delay)
```

The 50 MHz FPGA clock gives 20 ns delay resolution. The 32-bit NCO provides an
accurate average carrier frequency over the 1-4 MHz range, but an individual
edge can move by one 20 ns clock when the requested period is not an integer
number of clocks. At 2 MHz, 20 ns is 14.4 degrees of carrier phase, so this
implementation is suitable for functional steering tests but is not the final
choice for precision 2 MHz beamforming. A later hardware revision should expose
a clean 100-200 MHz clock or a device PLL.

The built-in fallback scan table assumes 1.00 mm element pitch and 1540 m/s sound
speed. Running the configuration script replaces it with the requested
`--pitch-mm` and `--sound-speed` values.

## Bring-Up Order

1. Keep HVDC+ and HVDC- off.
2. Program the FPGA and check K9 is high, all PIN/NIN outputs are low while S2
   is disabled, and J11/J10 are low.
3. Press S2 once and verify that READY and J11 rise together. Verify J11 stays
   high for 200 ns, and that J10 plus the first -10 degree burst start 2 us
   after the J11 rising edge. J11 must repeat every 100 us. Check all 16 H2
   logic signals and their relative delays with a logic analyzer or
   oscilloscope. Press S1 once and verify that the next J11 selects -8 degrees,
   then confirm that the -8 degree delay pattern remains unchanged until the
   next S1 press.
4. Confirm that all eight NINx signals remain low continuously. PINx should
   contain two nominal 250 ns high-logic pulses commanding the positive output,
   separated by nominal 250 ns return-to-zero intervals at the selected delays.
5. Connect the HV7350 board controls and 3.3 V logic power.
6. Set VPP to +30 V, apply the required rails with current limiting, and inspect
   H1 with a correctly rated high-voltage probe. The expected channel output is
   nominally +30 V/0 V and must not contain a commanded negative level.

The FPGA prevents the N-channel pulser FET from turning on, but it does not set
the high-voltage amplitude: the positive level follows the external VPP rail.
Do not omit or change the HV7350 VNN supply/decoupling merely because NIN is
low; HV7350 specifies VNN as an operating supply. Eliminating the negative rail
entirely requires a separately validated power circuit or a unipolar pulser.

The selected FPGA pins overlap the dock-board SDRAM interface. This design fixes
K9/SDRAM_CS_N high, so the onboard SDRAM is unavailable while beamforming. Do
not add an SDRAM controller to this project.
