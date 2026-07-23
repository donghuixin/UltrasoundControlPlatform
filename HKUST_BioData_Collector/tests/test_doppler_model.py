from __future__ import annotations

import sys
from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from doppler_model import DopplerConfig, calculate_doppler, round_up_samples


class DopplerModelTests(unittest.TestCase):
    def test_one_mhz_one_khz_sixty_degree_nyquist(self) -> None:
        result = calculate_doppler(DopplerConfig(prf_hz=1000.0))
        self.assertAlmostEqual(result.nyquist_velocity_m_s, 0.77, places=2)
        self.assertAlmostEqual(result.max_unambiguous_depth_mm, 770.0, places=2)

    def test_default_block_contains_more_than_128_pulses(self) -> None:
        result = calculate_doppler(DopplerConfig())
        self.assertGreater(result.pulses_per_raw_block, 170)
        self.assertLess(result.pulses_per_raw_block, 180)
        self.assertAlmostEqual(result.raw_block_gib, 0.125, places=3)

    def test_multi_second_raw_capture_is_flagged(self) -> None:
        result = calculate_doppler(DopplerConfig(desired_duration_s=6.0))
        self.assertGreater(result.full_duration_raw_gib, 20.0)
        self.assertTrue(any("not gap-free" in warning for warning in result.warnings))
        self.assertTrue(any("range gating" in warning for warning in result.warnings))

    def test_range_gated_volume_is_small(self) -> None:
        result = calculate_doppler(DopplerConfig(desired_duration_s=6.0, prf_hz=5000.0))
        self.assertLess(result.range_gated_iq_mib, 2.0)

    def test_sample_rounding(self) -> None:
        self.assertEqual(round_up_samples(4097), 8192)

    def test_invalid_flow_angle(self) -> None:
        with self.assertRaises(ValueError):
            calculate_doppler(DopplerConfig(flow_angle_deg=89.5))


if __name__ == "__main__":
    unittest.main()
