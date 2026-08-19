# Calibration and Imaging

## Frequency evidence

Track three values independently:

1. TX pattern frequency decoded from TX7316 registers.
2. Electrical burst frequency measured at the dummy load with a differential high-voltage probe.
3. Acoustic or delayed-echo response peak measured outside the direct-coupling/ring-down window.

Never use HSDC `ADC Input Target Frequency` as TX evidence. Never label an early crosstalk peak as the
probe center frequency.

The operator measured the current probe/system best response near `1.6–1.7 MHz`; use `1.65 MHz` only as
a provisional calibration center until the electrical and acoustic measurements are saved with conditions.

## Geometry limit

At `c=1540 m/s` and `fc=1.65 MHz`, wavelength is approximately `0.933 mm`; a `1.59 mm` pitch is about
`1.70λ`. Expect grating lobes and false arcs. Start at `-4°/0°/+4°`. Software super-resolution cannot
recover spatial samples that the physical aperture never measured.

## Calibration gates

1. Verify TX burst shape, period, amplitude, symmetry, return to AVSS, and T/R recovery on a dummy load.
2. Use one element and a planar reflector at a known depth.
3. Verify echo delay moves with reflector depth and repeats across PRF events.
4. Measure every channel's delay, gain, polarity, noise, clipping, and physical position.
5. Reconstruct a 0-degree planar reflector before steering or compounding.
6. Add three angles, then expand only if the reflector remains fixed and focused.

Reject a B-mode result when echo SNR is below zero, ADC rails occur, event timing hits search boundaries,
or the image is dominated by periodic horizontal bands and common-mode ring-down.

