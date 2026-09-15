# 8-Channel HV7350 Beamformer

> Historical eight-channel autostart build, not the active firmware. See
> [four-probe continuous control](four_probe_control.md) for current S2/USB,
> startup and LED behavior. The old angle-configuration protocol below does
> not control the current firmware.

## Historical FPGA Behavior

- Transmission starts automatically as soon as FPGA configuration completes;
  no button press is required. READY and DONE remain steadily on while output
  is running.
- The final build fixes the beam at 0 degrees and fixes the negative-tail delay
  at 140 ns on every channel and every frame.
- S1 is reserved and has no effect.
- S2 is optional: pressing it stops all synchronization and PIN/NIN outputs;
  pressing it again restarts with a new J11 pulse and the same fixed settings.
- J11 is a 200 ns-wide, 10 kHz trigger. J10 and each transmit burst start
  exactly 2 us after the J11 rising edge; the remaining 1.8 us after J11 falls
  is still part of the pretrigger delay. The first automatic J11 pulse and all
  subsequent J11 pulses identify fixed 0-degree bursts.
- The carrier is fixed at 2.2 MHz and every burst contains exactly 2 cycles.
- Each channel first transmits a positive-unipolar RTZ main burst on PINx. After
  the fixed 140 ns delay, NINx emits one 100 ns negative damping pulse. PINx and
  NINx are never high together, and PIN=NIN=0 selects the HV7350 ground-return
  switch between them. With VPP=+30 V and the fixed VNN=-30 V, the sequence is
  a +30 V/0 V main burst, a 140 ns RGND interval, one 0 V/-30 V damping
  pulse, and then continuous RGND.
- UART packets may update the stored steering-delay profiles, but this final
  build ignores UART frequency and cycle fields. The carrier remains 2.2 MHz,
  the burst remains 2 cycles, and the active profile remains 0 degrees.

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

These are true-time steering delays, so changing the carrier to 2.2 MHz does
not change the propagation delay required for a given angle. The
table was recalculated and quantized again at 20 ns resolution; its tick values
therefore remain the same, while the corresponding carrier phase changes.

> The active project is now the [four-probe controller](four_probe_control.md).
> The wiring table below remains valid; historical beam/angle control is not active.

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

PIN1..PIN8 carry the positive main burst. NIN1..NIN8 carry only the 100 ns
negative damping tail. The logic guarantees that PINx and NINx are not high at
the same time.

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

Example for the fixed 2.2 MHz carrier, 1.00 mm element pitch, and 2-cycle
burst (the script uploads all scan angles):

```bash
python3 scripts/configure_beamformer.py \
  --port /dev/cu.usbserial-0001 \
  --frequency-mhz 2.2 \
  --angle-deg 10 \
  --pitch-mm 1.00 \
  --cycles 2
```

Inspect the calculated delays without opening a serial port:

```bash
python3 scripts/configure_beamformer.py \
  --dry-run \
  --frequency-mhz 2.2 \
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
accurate average 2.2 MHz carrier, but an individual edge can move by one 20 ns
clock because the requested period is not an integer number of clocks. At
2.2 MHz, 20 ns is 15.84 degrees of carrier phase. A later hardware revision
should expose a clean 100-200 MHz clock or a device PLL for finer beam timing.

The built-in fallback scan table assumes 1.00 mm element pitch and 1540 m/s sound
speed. Running the configuration script replaces it with the requested
`--pitch-mm` and `--sound-speed` values.

## Bring-Up Order

1. Keep HVDC+ and HVDC- off.
2. Program the FPGA. READY and DONE should turn on automatically, J11 should
   immediately produce a 200 ns pulse and repeat every 100 us, and J10 plus the
   first 0-degree burst should start 2 us after the first J11 rising edge.
3. Check all 16 H2 logic signals with a logic analyzer or oscilloscope before
   enabling the high-voltage rails. PINx should contain two 2.2 MHz positive
   RTZ cycles. After the full burst completes, NINx should start 140 ns later,
   remain high for exactly 100 ns, and then return low. S1 must have no effect.
4. Optionally press S2 once to confirm READY, DONE, J11, J10, PIN, and NIN all
   stop; press it again to confirm automatic restart with the same timing.
5. Connect the HV7350 board controls and 3.3 V logic power.
6. With VPP=+30 V and VNN=-30 V, apply the required rails with current limiting
   and inspect H1 with a correctly rated high-voltage probe. Confirm the main
   burst is +30 V/0 V, the damping tail is one 100 ns 0 V/-30 V pulse, and the
   output otherwise returns to RGND.

The FPGA controls timing only: the positive main amplitude follows VPP and the
negative damping amplitude follows VNN. This final setting assumes VNN is fixed
at -30 V. High-resolution measurements observed approximately -46 to -51 V
instantaneous CH2 excursions, so VNN=-30 V must not be treated as a clamp on
the ceramic voltage. Start with current limiting and first confirm on the logic
pins that PIN and NIN never overlap.

The selected FPGA pins overlap the dock-board SDRAM interface. This design fixes
K9/SDRAM_CS_N high, so the onboard SDRAM is unavailable while beamforming. Do
not add an SDRAM controller to this project.
