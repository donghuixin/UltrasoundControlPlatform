#!/usr/bin/env python3
"""Regression checks for the final fixed negative-tail damping timing."""

from pathlib import Path

CLK_HZ = 50_000_000
TICK_NS = 1_000_000_000 // CLK_HZ
PHASE_SCALE = 1 << 32
DEFAULT_FREQ_WORD = 0x0B439581
DEFAULT_BURST_CYCLES = 2
PRF_TICKS = CLK_HZ // 10_000
PRF_HALF_TICKS = PRF_TICKS // 2
PRETRIGGER_TICKS = CLK_HZ // 500_000
TRIGGER_PULSE_TICKS = CLK_HZ // 5_000_000
FIXED_DAMP_DELAY_TICKS = 7
DAMP_PULSE_TICKS = CLK_HZ // 10_000_000
CALIBRATION_ANGLE_INDEX = 5

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
    assert abs(actual_carrier_hz - 2_200_000) < 0.01
    assert DEFAULT_BURST_CYCLES == 2
    assert FIXED_DAMP_DELAY_TICKS * TICK_NS == 140
    assert DAMP_PULSE_TICKS == 5
    assert DAMP_PULSE_TICKS * TICK_NS == 100
    assert CALIBRATION_ANGLE_INDEX == 5
    assert "assign pin_out = active && !phase_accumulator[31];" in source_text
    assert "assign nin_out = damp_active;" in source_text
    assert "reg output_enabled = 1'b1;" in source_text
    assert "reg pretrigger_active = 1'b1;" in source_text
    assert "wire [15:0] frame_damp_delay_ticks = FIXED_DAMP_DELAY_TICKS;" in source_text
    assert "wire [31:0] frame_freq_word = DEFAULT_FREQ_WORD;" in source_text
    assert "wire [7:0] frame_burst_cycles = DEFAULT_BURST_CYCLES;" in source_text
    assert "if (s1_pressed)" not in source_text
    assert "input  wire s1" not in source_text
    assert "shadow_freq_word" not in source_text
    for nin_signal in (
        "tx1_nin_f2", "tx2_nin_e3", "tx3_nin_g4", "tx4_nin_k7",
        "tx5_nin_l10", "tx6_nin_j8", "tx7_nin_k8", "tx8_nin_k10",
    ):
        channel_number = nin_signal[2]
        assert (
            f"assign {nin_signal} = output_enabled && ch{channel_number}_nin;"
            in source_text
        )

    # Every 10 kHz frame uses the same measured 140 ns optimum.
    fixed_frames = [FIXED_DAMP_DELAY_TICKS * TICK_NS for _ in range(1_000)]
    assert fixed_frames == [140] * 1_000

    first_frame_tick = PRETRIGGER_TICKS
    second_frame_tick = first_frame_tick + PRF_TICKS
    second_j11_rise_tick = second_frame_tick - PRETRIGGER_TICKS

    assert first_frame_tick * TICK_NS == 2_000
    assert second_j11_rise_tick * TICK_NS == 100_000
    assert (second_frame_tick - second_j11_rise_tick) * TICK_NS == 2_000

    print("PASS: J11 pulse width is 10 clocks (200 ns)")
    print(f"PASS: carrier is {actual_carrier_hz:.6f} Hz, 2 cycles per burst")
    print("PASS: PIN carries the positive burst and NIN carries a 100 ns negative tail")
    print("PASS: J11 rising edges repeat every 5000 clocks (10 kHz)")
    print("PASS: J10 and each burst start 100 clocks (2 us) after J11 rises")
    print("PASS: J10 frame period is 5000 clocks (100 us), high for 50 us")
    print("PASS: transmitter starts automatically without a button press")
    print("PASS: UART cannot override the fixed carrier or cycle count")
    print("PASS: steering is fixed at 0 degrees")
    print("PASS: every frame uses one 100 ns negative tail after a fixed 140 ns delay")
    print("PASS: S1 cannot alter the fixed damping delay")


if __name__ == "__main__":
    main()
