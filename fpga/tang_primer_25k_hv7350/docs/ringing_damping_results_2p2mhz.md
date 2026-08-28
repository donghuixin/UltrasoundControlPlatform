# 2.2 MHz Negative-Tail Damping Measurement Record

Measurement date: 2026-08-29

## Setup

- Main burst: 2.2 MHz, 2 cycles, positive-unipolar drive.
- Negative damping tail: 100 ns, with VNN fixed at -30 V.
- PRF: 10 kHz.
- Oscilloscope: approximately 2.5 GSa/s, 0.4 ns per sample, two transmit
  events per file.
- CH2: reference waveform measured directly across the piezoelectric ceramic.
- CH1: receive-side waveform measured after the T/R switch.
- File mapping: DS0 is 0 S1 presses; DS1..DS10 are 1..10 presses. Each press
  adds 20 ns to the negative-tail delay.

## Analysis Method

CH2 was used to align each transmit event and verify that transmit amplitude
remained stable. CH1 was band-limited to 1.5-2.5 MHz around the residual mode,
and its RMS and energy were evaluated from 2 to 16 us after transmit. The two
events in every file were averaged.

The post-transmit CH1 ringing remained centered at approximately 2.003 MHz;
changing the burst carrier to 2.2 MHz did not move the ceramic/system natural
ringing mode to 2.2 MHz.

## Result

| File | S1 presses | Added tail delay | CH1 RMS, 2-16 us | Relative CH1 ringing energy |
| --- | ---: | ---: | ---: | ---: |
| DS0 | 0 | 0 ns | 0.2864 V | 100.0% |
| DS1 | 1 | 20 ns | 0.2792 V | 95.0% |
| DS2 | 2 | 40 ns | 0.2635 V | 84.7% |
| DS3 | 3 | 60 ns | 0.2397 V | 70.1% |
| DS4 | 4 | 80 ns | 0.2158 V | 56.8% |
| DS5 | 5 | 100 ns | 0.1945 V | 46.1% |
| DS6 | 6 | 120 ns | 0.1804 V | 39.7% |
| DS7 | 7 | 140 ns | 0.1752 V | 37.4% |
| DS8 | 8 | 160 ns | 0.1875 V | 42.8% |
| DS9 | 9 | 180 ns | 0.2160 V | 56.9% |
| DS10 | 10 | 200 ns | 0.3670 V | 164.2% |

The preferred 2.2 MHz setting is therefore 140 ns (seven S1 presses). It
reduced the 2-16 us CH1 ringing RMS by approximately 38.8% and energy by
approximately 62.6% relative to 0 ns. The 200 ns setting reinforced the
ringing and must not be treated as a damping setting.

CH2 transmit RMS stayed near 21.7 V across all delay settings, so the CH1
improvement was not caused by reduced main-burst voltage. The 17-26 us CH1
residual at 140 ns was close to the receive noise floor.

## Peak-Voltage Caution

The high-resolution captures showed CH2 negative excursions between roughly
-46 V and -50.5 V even though VNN was fixed at -30 V. The earlier 25 MSa/s
2 MHz captures could miss these narrow peaks; their approximately -30 V
sampled minimum must not be interpreted as a safe bound on the instantaneous
ceramic voltage.

## Next Experiment

Test 2.4 MHz with the same two-cycle positive burst, 100 ns negative tail, and
0-240 ns manual delay scan in 20 ns steps. Because the 2.2 MHz 200 ns setting
strongly reinforced ringing, begin high-voltage measurements at reduced energy
or current limit and inspect CH2 while stepping the delay.
