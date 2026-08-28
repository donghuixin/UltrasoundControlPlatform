# HV7350 Board Wiring Notes

> The active project is now the eight-channel beamformer. See
> `docs/beamformer_control.md` for its current pin map and control procedure.
> The one-channel sections below are retained only as legacy bring-up notes.

This note is based on:

- `Netlist_Schematic18_2026-07-02.tel`
- `BOM_HV7250AD9273TRUltraSound_Schematic18_2026-07-02.csv`
- the schematic screenshot shared on 2026-07-02

The board uses:

- U1: Microchip HV7350K6-G, 8-channel high-voltage pulser
- U3/U4: Microchip MD0101K6-G protection/switch devices for receive-side nodes
- H2: 3.3 V FPGA logic input connector
- H1: high-voltage TX output connector
- H3/H4: high-voltage supply connectors
- H5: protected receive-side connector

## Power-Up Safety

- Connect FPGA GPIOs only to H2 logic pins.
- Never connect H1 HV outputs to FPGA pins.
- Start with HVDC+ and HVDC- disabled, verify all H2 logic levels first, then bring
  high-voltage rails up slowly with current limits.
- Keep FPGA GND and this board GND common before driving logic signals.
- OEN, REN, CLK, PINx, and NINx are logic inputs referenced to VLL. On this
  board VLL is 3V3, so use 3.3 V logic, not 5 V.

## H2 FPGA Logic Connector

H2 is the control connector for U1. All logic pins are 3.3 V domain signals.

| H2 pin | Net / U1 pin | Function |
| --- | --- | --- |
| 1 | CLK / U1.54 | HV7350 logic clock or latch clock |
| 2 | PIN1 / U1.55 | Channel 1 positive control |
| 3 | GND | Logic ground |
| 4 | NIN1 / U1.56 | Channel 1 negative control |
| 5 | GND | Logic ground |
| 6 | PIN2 / U1.1 | Channel 2 positive control |
| 7 | 3V3 | 3.3 V logic power |
| 8 | NIN2 / U1.2 | Channel 2 negative control |
| 9 | 3V3 | 3.3 V logic power |
| 10 | PIN3 / U1.3 | Channel 3 positive control |
| 11 | 3V3 | 3.3 V logic power |
| 12 | NIN3 / U1.4 | Channel 3 negative control |
| 13 | GND | Logic ground |
| 14 | PIN4 / U1.5 | Channel 4 positive control |
| 15 | GND | Logic ground |
| 16 | NIN4 / U1.6 | Channel 4 negative control |
| 17 | 3V3 | 3.3 V logic power |
| 18 | PIN5 / U1.9 | Channel 5 positive control |
| 19 | 3V3 | 3.3 V logic power |
| 20 | NIN5 / U1.10 | Channel 5 negative control |
| 21 | 3V3 | 3.3 V logic power |
| 22 | PIN6 / U1.11 | Channel 6 positive control |
| 23 | GND | Logic ground |
| 24 | NIN6 / U1.12 | Channel 6 negative control |
| 25 | GND | Logic ground |
| 26 | PIN7 / U1.13 | Channel 7 positive control |
| 27 | GND | Logic ground |
| 28 | NIN7 / U1.14 | Channel 7 negative control |
| 29 | REN / U1.8 | Built-in positive/negative floating 5 V regulator enable |
| 30 | PIN8 / U1.15 | Channel 8 positive control |
| 31 | OEN / U1.7 | Output-enable control |
| 32 | NIN8 / U1.16 | Channel 8 negative control |

Basic channel logic:

- For a positive pulse on channel x, drive `PINx=1`, `NINx=0`.
- For a negative pulse on channel x, drive `PINx=0`, `NINx=1`.
- For idle, drive `PINx=0`, `NINx=0`.
- Avoid `PINx=1`, `NINx=1` unless the datasheet explicitly permits it.

## H1 High-Voltage Output Connector

H1 carries the HV7350 TX outputs and nearby return pins.

| H1 pin | Net | Function |
| --- | --- | --- |
| 1 | HV1 | U1 TX1 high-voltage output |
| 2 | GND | Return / shield |
| 3 | GND | Return / shield |
| 4 | GND | Return / shield |
| 5 | HV2 | U1 TX2 high-voltage output |
| 6 | GND | Return / shield |
| 7 | GND | Return / shield |
| 8 | GND | Return / shield |
| 9 | HV3 | U1 TX3 high-voltage output |
| 10 | GND | Return / shield |
| 11 | GND | Return / shield |
| 12 | GND | Return / shield |
| 13 | HV4 | U1 TX4 high-voltage output |
| 14 | GND | Return / shield |
| 15 | NC in exported netlist | Do not use unless PCB is verified |
| 16 | GND | Return / shield |
| 17 | HV5 | U1 TX5 high-voltage output |
| 18 | GND | Return / shield |
| 19 | GND | Return / shield |
| 20 | GND | Return / shield |
| 21 | HV6 | U1 TX6 high-voltage output |
| 22 | GND | Return / shield |
| 23 | GND | Return / shield |
| 24 | GND | Return / shield |
| 25 | HV7 | U1 TX7 high-voltage output |
| 26 | GND | Return / shield |
| 27 | GND | Return / shield |
| 28 | GND | Return / shield |
| 29 | HV8 | U1 TX8 high-voltage output |
| 30 | GND | Return / shield |
| 31 | GND | Return / shield |
| 32 | GND | Return / shield |

## H3 / H4 High-Voltage Supplies

H3 and H4 are duplicate 3-pin high-voltage supply connectors.

| Pin | Net | Function |
| --- | --- | --- |
| 1 | HVDC+ | Positive high-voltage supply for VPP |
| 2 | GND | Supply return |
| 3 | HVDC- | Negative high-voltage supply for VNN |

Use an isolated/current-limited bench supply during bring-up. Do not power these
rails from the FPGA board.

## H5 Protected Receive Connector

H5 routes through U3/U4 MD0101 devices. Use this for receive-side analog signals,
not for FPGA digital GPIO.

| H5 pin | Net | Related TX channel |
| --- | --- | --- |
| 1 | RX1 via U3 | HV1 |
| 2 | GND | Return |
| 3 | RX2 via U3 | HV2 |
| 4 | GND | Return |
| 5 | RX3 via U3 | HV3 |
| 6 | GND | Return |
| 7 | RX4 via U3 | HV4 |
| 8 | GND | Return |
| 9 | RX5 via U4 | HV5 |
| 10 | GND | Return |
| 11 | RX6 via U4 | HV6 |
| 12 | GND | Return |
| 13 | RX7 via U4 | HV7 |
| 14 | GND | Return |
| 15 | RX8 via U4 | HV8 |
| 16 | GND | Return |

## Minimal One-Channel Bring-Up Wiring

Recommended wiring for the current burned bitstream is asynchronous mode:
tie HV7350 `CLK` high and do not use the FPGA `hv_clk` output. In this mode,
the HV7350 output follows `PIN1` and `NIN1` directly, which also guarantees the
idle zero state is applied when the FPGA drives both logic pins low.

| Existing FPGA pin / signal | Board connection |
| --- | --- |
| J11 / `hv_pin1` | H2.2 PIN1 |
| F7 / `hv_nin1` | H2.4 NIN1 |
| Board 3V3 | H2.1 CLK |
| Board 3V3 | H2.31 OEN |
| Board 3V3 | H2.29 REN |
| Board 3V3 | one or more H2 3V3 pins |
| Board GND | one or more H2 GND pins |
| Board GND | unused PIN2..PIN8/NIN2..NIN8 inputs, preferably through pulldown resistors |

Do not leave unused `PINx` or `NINx` inputs floating.
Do not connect OEN or REN to 5 V on this board.

## Optional Synchronous Wiring

With `src/hv7350_single_channel_example.v`, assign and wire:

| FPGA signal | Connect to board |
| --- | --- |
| `hv_pin1` | H2.2 PIN1 |
| `hv_nin1` | H2.4 NIN1 |
| `hv_clk` | H2.1 CLK |
| `hv_oen` | H2.31 OEN |
| `hv_ren` | H2.29 REN |
| FPGA 3V3 | one or more H2 3V3 pins |
| FPGA GND | one or more H2 GND pins |

If only the three already-used external FPGA pins are available, the synchronous
test wiring is:

| Existing FPGA pin / signal | Board connection |
| --- | --- |
| J11 / `hv_pin1` | H2.2 PIN1 |
| F7 / `hv_nin1` | H2.4 NIN1 |
| J8 / `hv_clk` | H2.1 CLK |
| Board 3V3 | H2.31 OEN, H2.29 REN |
| Board 3V3 | one or more H2 3V3 pins |
| Board GND | one or more H2 GND pins |

Example CST fragment for the three FPGA-driven lines:

```tcl
IO_LOC "hv_pin1" J11;
IO_PORT "hv_pin1" IO_TYPE=LVCMOS33 PULL_MODE=NONE DRIVE=8 BANK_VCCIO=3.3;

IO_LOC "hv_nin1" F7;
IO_PORT "hv_nin1" IO_TYPE=LVCMOS33 PULL_MODE=NONE DRIVE=8 BANK_VCCIO=3.3;

IO_LOC "hv_clk" J8;
IO_PORT "hv_clk" IO_TYPE=LVCMOS33 PULL_MODE=NONE DRIVE=8 BANK_VCCIO=3.3;
```

For first power-up, leave HVDC+ and HVDC- off and check H2 with an oscilloscope
or logic analyzer. After the H2 waveform is correct, connect the high-voltage
supply to H3 or H4 and observe H1.1 relative to nearby H1 GND.
