#!/usr/bin/env python3
"""Static parameter checks and independent NCO calculation, NOT RTL simulation.

Run verify_probe_sequence.py as well to exercise the actual Verilog.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT / "src" / "pmod_led.v").read_text()
    clock_match = re.search(r"parameter integer CLK_FREQ_HZ = ([\d_]+)", source)
    freq_match = re.search(r"DEFAULT_FREQ_WORD = 32'h([0-9a-fA-F]+)", source)
    cycle_match = re.search(r"DEFAULT_BURST_CYCLES = 8'd(\d+)", source)
    delay_match = re.search(r"FIXED_DAMP_DELAY_TICKS = 16'd(\d+)", source)
    assert all((clock_match, freq_match, cycle_match, delay_match))
    clk = int(clock_match[1].replace("_", ""))
    word = int(freq_match[1], 16)
    cycles = int(cycle_match[1])
    delay = int(delay_match[1])
    assert clk == 50_000_000 and cycles == 2 and delay == 7
    assert abs(word * clk / (1 << 32) - 2_200_000) < 0.01
    for expression in (
        "PRF_PERIOD_TICKS = CLK_FREQ_HZ / 10_000",
        "PRF_HALF_TICKS = PRF_PERIOD_TICKS / 2",
        "PRETRIGGER_TICKS = CLK_FREQ_HZ / 500_000",
        "TRIGGER_PULSE_TICKS = CLK_FREQ_HZ / 5_000_000",
        "DAMP_PULSE_TICKS = CLK_FREQ_HZ / 10_000_000",
        "reg session_active = 1'b0;",
        "assign led_ready = ready_registered;",
        "assign led_done = done_registered;",
        "done_registered <= 1'b0;",
        "response_flags <= {7'd0, session_active};",
        "assign sync_prf_j11 = j11_registered;",
        "assign sync_prf_j10 = j10_registered;",
        "ready_registered <= channel_run_enable;",
        "pin_registered[selected_channel] <= ch_pin;",
        "nin_registered[selected_channel] <= ch_nin;",
        "assign pin_out = active && !phase_accumulator[31];",
        "assign nin_out = damp_active;",
    ):
        assert expression in source, expression
    assert "SESSION_TICKS" not in source
    assert "session_count" not in source

    # Reconstruct the retained two-cycle NCO waveform, one 20 ns tick at a time.
    phase = completed = tick = 0
    high_ticks = []
    while completed < cycles:
        if not phase & (1 << 31):
            high_ticks.append(tick)
        total = phase + word
        completed += total >> 32
        phase = total & 0xFFFFFFFF
        tick += 1
        assert tick < 1000
    assert high_ticks == list(range(12)) + list(range(23, 35))
    assert tick == 46
    pretrigger = clk // 500_000
    damping_start = pretrigger + tick + delay
    assert damping_start == 153  # J11 + 3060 ns.
    assert damping_start + clk // 10_000_000 == 158
    prf_ticks = clk // 10_000
    assert prf_ticks == 5000
    assert pretrigger + prf_ticks // 2 < prf_ticks

    for channel, pin, nin in (
        (1, "b2", "f2"), (2, "e1", "e3"),
        (3, "j1", "g4"), (4, "h1", "k7"),
    ):
        for kind, ball in (("pin", pin), ("nin", nin)):
            assignment = (f"assign tx{channel}_{kind}_{ball} = "
                          f"{kind}_registered[{channel - 1}];")
            assert assignment in source, assignment
    for name in ("tx5_pin_l7", "tx5_nin_l10", "tx6_pin_l9", "tx6_nin_j8",
                 "tx7_pin_f7", "tx7_nin_k8", "tx8_pin_l8", "tx8_nin_k10"):
        assert f"assign {name} = 1'b0;" in source

    print("PASS (static/model): fixed 2.2 MHz / 2 cycles / 140 ns wait / 100 ns negative tail")
    print("PASS (static/model): PIN at J11+[2000,2240), [2460,2700) ns; NIN at [3060,3160) ns")
    print("PASS (static/model): J11 200 ns / 10 kHz, burst/J10 start 2 us later")
    print("PASS (static/model): continuous 10 kHz PRF; former five-second expiry timer removed")
    print("PASS (static): power-up idle, one-of-four output mapping, HV5..HV8 disabled")
    print("Actual RTL behavior must also pass scripts/verify_probe_sequence.py.")


if __name__ == "__main__":
    main()
