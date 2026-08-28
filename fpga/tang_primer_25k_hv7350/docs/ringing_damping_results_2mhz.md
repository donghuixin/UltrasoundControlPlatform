# 2 MHz Negative-Tail Damping Measurement Record

Measurement date: 2026-08-29

## Setup

- Main burst: 2.0 MHz, 2 cycles, positive-unipolar drive.
- Negative damping tail: 100 ns, with VNN fixed at -30 V.
- PRF: 10 kHz.
- Oscilloscope: 25 MSa/s, 40 ns per sample, two transmit events per file.
- CH2: reference waveform measured directly across the piezoelectric ceramic.
- CH1: receive-side waveform measured after the T/R switch.
- Files: `/Volumes/RIGOL/RigolDS1.bin` through `RigolDS11.bin`.
- File mapping: DS1 is 0 S1 presses; DS2..DS11 are 1..10 presses. Each press
  adds 20 ns to the negative-tail delay.

## Analysis Method

CH2 was used only to align the transmit start and characterize the actual
voltage across the ceramic. CH1 was band-limited around the observed residual
ringing mode (1.5 to 2.5 MHz), and the RMS and energy were evaluated after the
transmit event. The two events in each file were averaged.

The observed CH1 ringing peak was approximately 1.976 MHz. Its principal
spectral lobe in this capture was approximately 1.895 to 2.055 MHz.

## Result

| File | S1 presses | Added tail delay | CH1 RMS, 2-16 us | Relative CH1 ringing energy |
| --- | ---: | ---: | ---: | ---: |
| DS1 | 0 | 0 ns | 0.2726 V | 100.0% |
| DS2 | 1 | 20 ns | 0.2498 V | 84.0% |
| DS3 | 2 | 40 ns | 0.2254 V | 68.4% |
| DS4 | 3 | 60 ns | 0.2063 V | 57.3% |
| DS5 | 4 | 80 ns | 0.1946 V | 51.0% |
| DS6 | 5 | 100 ns | 0.1899 V | 48.5% |
| DS7 | 6 | 120 ns | 0.1882 V | 47.7% |
| DS8 | 7 | 140 ns | 0.2005 V | 54.1% |
| DS9 | 8 | 160 ns | 0.2231 V | 67.0% |
| DS10 | 9 | 180 ns | 0.2496 V | 83.8% |
| DS11 | 10 | 200 ns | 0.2854 V | 109.6% |

After normalization by the measured CH2 transmit RMS, DS6 and DS7 differed by
less than one percentage point. The reliable optimum is therefore a broad
100-120 ns interval rather than a precisely resolved 20 ns point. DS7 is the
preferred 2 MHz setting because it gave the lowest absolute CH1 ringing and
its measured CH2 negative excursion was about -30.1 V; DS6 showed a much larger
negative excursion of about -46.8 V.

For a 13-20 mm two-way path in tissue (approximately 16.9-26.0 us), the DS7
2 MHz residual was already near the measured receive noise floor. CH1 includes
both ceramic ringing and T/R-switch feedthrough/recovery, so this is a
system-level receive-interference result rather than an isolated mechanical-Q
measurement.

## Next Experiment

Test 2.2 MHz with the same 2-cycle positive burst and 100 ns negative tail.
Rescan the tail delay from 0 through 240 ns in 20 ns steps because the 2 MHz
100-120 ns optimum must not be assumed to remain optimal after changing the
carrier frequency.
