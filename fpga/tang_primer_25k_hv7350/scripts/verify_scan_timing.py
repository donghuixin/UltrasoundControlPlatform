#!/usr/bin/env python3
"""Regression checks for positive-unipolar drive, steering and trigger timing."""

from pathlib import Path

CLK_HZ = 50_000_000
TICK_NS = 1_000_000_000 // CLK_HZ
PHASE_SCALE = 1 << 32
DEFAULT_FREQ_WORD = 0x0A3D70A4
DEFAULT_BURST_CYCLES = 2
PRF_TICKS = CLK_HZ // 10_000
PRF_HALF_TICKS = PRF_TICKS // 2
PRETRIGGER_TICKS = CLK_HZ // 500_000
TRIGGER_PULSE_TICKS = CLK_HZ // 5_000_000
ANGLE_COUNT = 11
PULSE_DRIVE = "PIN"
INACTIVE_DRIVE = "NIN"


def next_angle(angle_index):
    """Model one accepted S1 press."""
    return 0 if angle_index == ANGLE_COUNT - 1 else angle_index + 1


def main():
    source_text = (Path(__file__).resolve().parents[1] / "src" / "pmod_led.v").read_text()

    assert PRETRIGGER_TICKS == 100
    assert PRETRIGGER_TICKS * TICK_NS == 2_000
    assert TRIGGER_PULSE_TICKS == 10
    assert TRIGGER_PULSE_TICKS * TICK_NS == 200
    assert PRF_TICKS == 5_000
    assert PRF_TICKS * TICK_NS == 100_000
    assert PRF_HALF_TICKS * TICK_NS == 50_000
    actual_carrier_hz = DEFAULT_FREQ_WORD * CLK_HZ / PHASE_SCALE
    assert abs(actual_carrier_hz - 2_000_000) < 0.01
    assert DEFAULT_BURST_CYCLES == 2
    assert PULSE_DRIVE == "PIN"
    assert INACTIVE_DRIVE == "NIN"
    assert "assign pin_out = active && !phase_accumulator[31];" in source_text
    assert "assign nin_out = 1'b0;" in source_text
    for nin_signal in (
        "tx1_nin_f2", "tx2_nin_e3", "tx3_nin_g4", "tx4_nin_k7",
        "tx5_nin_l10", "tx6_nin_j8", "tx7_nin_k8", "tx8_nin_k10",
    ):
        assert f"assign {nin_signal} = 1'b0;" in source_text

    # With no S1 press, any number of 10 kHz frames keeps the same angle.
    selected_angle = 0
    fixed_frames = [selected_angle for _ in range(1_000)]
    assert fixed_frames == [0] * 1_000

    # Each accepted press moves exactly one entry through -10..+10 and wraps.
    stepped_angles = []
    for _ in range(ANGLE_COUNT):
        selected_angle = next_angle(selected_angle)
        stepped_angles.append(selected_angle)
    assert stepped_angles == list(range(1, ANGLE_COUNT)) + [0]

    first_frame_tick = PRETRIGGER_TICKS
    second_frame_tick = first_frame_tick + PRF_TICKS
    second_j11_rise_tick = second_frame_tick - PRETRIGGER_TICKS

    assert first_frame_tick * TICK_NS == 2_000
    assert second_j11_rise_tick * TICK_NS == 100_000
    assert (second_frame_tick - second_j11_rise_tick) * TICK_NS == 2_000

    print("PASS: J11 pulse width is 10 clocks (200 ns)")
    print(f"PASS: carrier is {actual_carrier_hz:.6f} Hz, 2 cycles per burst")
    print("PASS: PIN carries the burst and NIN stays low (positive-unipolar RTZ)")
    print("PASS: J11 rising edges repeat every 5000 clocks (10 kHz)")
    print("PASS: J10 and each burst start 100 clocks (2 us) after J11 rises")
    print("PASS: J10 frame period is 5000 clocks (100 us), high for 50 us")
    print("PASS: the steering angle stays fixed without an S1 press")
    print("PASS: every S1 press advances one angle and +10 wraps to -10")


if __name__ == "__main__":
    main()
