# Final Fixed Transmit and Damping Control

> Historical eight-channel autostart build. The active project now uses the
> [four-probe / five-second controller](four_probe_control.md). Its per-burst
> waveform is retained, but the startup, button and LED behavior below is historical.

Selected from the 2.0, 2.2, and 2.4 MHz measurements on 2026-08-29.

## Fixed Parameters

- Carrier: 2.2 MHz (`0x0B439581` at a 50 MHz FPGA clock).
- Main burst: 2 cycles, positive-unipolar RTZ.
- PRF: 10 kHz.
- J11: 200 ns pulse; transmit begins 2 us after its rising edge.
- Beam profile: fixed 0 degrees in this build.
- After each channel finishes its main burst: 140 ns at RGND.
- Damping: one 100 ns negative pulse on NIN, with VNN fixed at -30 V.
- Return state: PIN=NIN=0 (HV7350 RGND path).

The FPGA starts this sequence automatically after configuration. S1 has no
effect. S2 is retained only as an optional emergency stop/restart input. READY
and DONE are steady high while transmission is running.

## Selection Evidence

| Carrier | Best tested damping delay | CH1 2-16 us ringing RMS |
| ---: | ---: | ---: |
| 2.0 MHz | 120 ns | 0.1882 V |
| 2.2 MHz | 140 ns | 0.1752 V |
| 2.4 MHz | 180 ns | 0.1904 V |

The 2.2 MHz/140 ns setting gave the lowest measured receive-side ringing. Its
2-16 us ringing energy was approximately 62.6% below the 2.2 MHz zero-delay
case, while the 13-20 mm receive interval was near the measured noise floor.

## Why There Is No Second Negative Pulse

The final sequence already includes one negative damping pulse. A second pulse
was not measured, and the delay sweeps showed that a negative pulse at the
wrong phase can reinforce rather than cancel ringing. High-resolution CH2
captures also showed instantaneous negative excursions around -46 to -51 V
with VNN fixed at -30 V. Adding an unverified second negative pulse would
increase both cancellation uncertainty and electrical stress, so it is not
included in the final build.
