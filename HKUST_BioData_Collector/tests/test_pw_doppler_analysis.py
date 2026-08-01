from __future__ import annotations

import sys
from pathlib import Path
import json
import tempfile
import unittest

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from pw_doppler_analysis import analyze_capture, analyze_slow_time_iq


def synthetic_pulsatile_iq(duration_s: float, heart_rate_bpm: float = 72.0) -> np.ndarray:
    prf_hz = 1000.0
    center_frequency_hz = 1.5e6
    sound_speed_m_s = 1540.0
    flow_angle_deg = 60.0
    slow_time = np.arange(int(round(duration_s * prf_hz))) / prf_hz
    heart_hz = heart_rate_bpm / 60.0
    velocity = 0.24 + 0.11 * (0.5 + 0.5 * np.sin(2.0 * np.pi * heart_hz * slow_time))
    doppler_hz = (
        2.0
        * center_frequency_hz
        * velocity
        * np.cos(np.deg2rad(flow_angle_deg))
        / sound_speed_m_s
    )
    phase = np.cumsum(2.0 * np.pi * doppler_hz / prf_hz)
    spatial_phase = np.exp(1j * np.linspace(-0.8, 0.8, 8))
    generator = np.random.default_rng(7)
    noise = 0.08 * (
        generator.normal(size=(slow_time.size, 8))
        + 1j * generator.normal(size=(slow_time.size, 8))
    )
    return (np.exp(1j * phase)[:, None] * spatial_phase[None, :] + noise).astype(np.complex64)


class PwDopplerAnalysisTests(unittest.TestCase):
    def analyze(self, iq: np.ndarray) -> dict:
        return analyze_slow_time_iq(
            iq,
            prf_hz=1000.0,
            center_frequency_hz=1.5e6,
            flow_angle_deg=60.0,
            wall_filter_hz=30.0,
            ensemble_pulses=128,
            expected_heart_rate_bpm=72.0,
        )

    def test_eight_second_pulsatile_record_exposes_heart_period(self) -> None:
        result = self.analyze(synthetic_pulsatile_iq(8.0))
        self.assertTrue(result["cardiac_cycle_visible"])
        self.assertAlmostEqual(
            result["cardiac_periodicity"]["heart_rate_bpm"], 72.0, delta=2.0
        )
        self.assertGreater(result["expected_heart_cycles"], 9.0)

    def test_short_record_never_claims_cardiac_periodicity(self) -> None:
        result = self.analyze(synthetic_pulsatile_iq(0.14))
        self.assertFalse(result["cardiac_cycle_visible"])
        self.assertIn(
            result["cardiac_periodicity"]["reason"],
            {"too few spectrogram time bins", "continuous record is shorter than 3 seconds"},
        )

    def test_continuous_iq_capture_writes_spectrogram_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "capture_synthetic"
            capture.mkdir()
            np.savez_compressed(
                capture / "pw_doppler_input_iq.npz",
                iq=synthetic_pulsatile_iq(4.0),
                prf_hz=np.asarray([1000.0]),
            )
            plan = {
                "configuration": {
                    "center_frequency_mhz": 1.5,
                    "prf_hz": 1000.0,
                    "steering_angle_deg": 0.0,
                    "flow_angle_deg": 60.0,
                    "target_depth_mm": 25.0,
                    "gate_length_mm": 2.0,
                    "wall_filter_hz": 30.0,
                    "expected_heart_rate_bpm": 72.0,
                    "ensemble_pulses": 128,
                    "sound_speed_m_s": 1540.0,
                }
            }
            (capture / "doppler_session_plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )
            summary = analyze_capture(capture, force=True)
            output = capture / "analysis" / "pw_doppler"
            self.assertTrue(summary["result"]["cardiac_cycle_visible"])
            self.assertTrue((output / "pw_doppler_spectrogram.png").is_file())
            self.assertTrue((output / "pw_doppler_velocity.csv").is_file())
            self.assertTrue((output / "pw_doppler_summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
