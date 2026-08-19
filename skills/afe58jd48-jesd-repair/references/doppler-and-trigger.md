# Doppler and Trigger

## Acquisition requirement

Keep the steering angle and sample volume fixed. Each valid PRF event contributes one slow-time sample.
Record the actual PRF, center frequency, steering angle, range gate, sound speed, wall filter, and assumed
flow angle in the manifest.

Use:

```text
RF -> complex demodulation -> range gate -> wall/clutter filter
   -> Kasai autocorrelation or short-time FFT -> alias/quality checks -> velocity/power
```

Nyquist velocity magnitude before angle correction is approximately `c*PRF/(4*fc)`. Increasing burst
cycles narrows bandwidth and may improve SNR, but does not raise the slow-time Nyquist limit.

## Multi-heart-cycle recording

The standard HSDC Pro path captures a finite DDR block and saves after acquisition. External trigger
defines the block start; it does not make HSDC automatically save a short record after every PRF pulse.

For several seconds:

1. Use the largest verified DDR block that fits the selected channel/sample format.
2. Segment pulses from the continuous RF block using verified PRF markers.
3. For longer duration, acquire sequential blocks with overlap and monotonic timestamps.
4. Detect missing or duplicated pulse indices at block boundaries.
5. Develop custom FPGA/host streaming only after finite-block Doppler passes.

Do not alternate steering angles inside a PW ensemble. Angle sweeps belong to B-mode or vector-flow
sequences and require an explicit pulse-index schedule.

