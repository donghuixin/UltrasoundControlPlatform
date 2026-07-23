from __future__ import annotations

import sys
from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from delay_model import ArrayConfig, build_angle_list, calculate_delay_profile, calculate_profiles


class DelayModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ArrayConfig(
            elements=8,
            pitch_mm=1.59,
            element_width_mm=1.0,
            center_frequency_mhz=2.5,
            sound_speed_m_s=1540.0,
            delay_quantum_ns=5.0,
        )

    def test_zero_degree_profile(self) -> None:
        profile = calculate_delay_profile(0.0, self.config)
        self.assertEqual(profile.counts_a1_to_a8, (0, 0, 0, 0, 0, 0, 0, 0))
        self.assertAlmostEqual(profile.realized_angle_deg, 0.0, places=6)

    def test_known_ten_degree_profile(self) -> None:
        profile = calculate_delay_profile(10.0, self.config)
        self.assertEqual(profile.counts_a1_to_a8, (0, 36, 72, 108, 143, 179, 215, 251))
        self.assertAlmostEqual(profile.realized_angle_deg, 9.98656, places=4)

    def test_negative_profile(self) -> None:
        profile = calculate_delay_profile(-10.0, self.config)
        self.assertEqual(profile.counts_a1_to_a8, (251, 215, 179, 143, 108, 72, 36, 0))

    def test_smaller_active_aperture_is_padded(self) -> None:
        config = ArrayConfig(elements=4, pitch_mm=0.30, element_width_mm=0.25)
        profile = calculate_delay_profile(8.0, config)
        self.assertEqual(len(profile.active_counts), 4)
        self.assertEqual(profile.counts_a1_to_a8[4:], (0, 0, 0, 0))

    def test_angle_sweep_safety_limit(self) -> None:
        with self.assertRaises(ValueError):
            build_angle_list(-40.0, 40.0, 1.0)

    def test_one_degree_sweep_uses_twenty_one_software_profiles(self) -> None:
        angles = build_angle_list(-10.0, 10.0, 1.0)
        profiles = calculate_profiles(angles, self.config)
        self.assertEqual(len(angles), 21)
        self.assertEqual(len(profiles), 21)
        self.assertEqual(angles[10], 0.0)

    def test_default_sweep(self) -> None:
        angles = build_angle_list(-10.0, 10.0, 2.0)
        self.assertEqual(angles, [-10.0, -8.0, -6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0, 10.0])
        self.assertEqual(len(calculate_profiles(angles, self.config)), 11)


if __name__ == "__main__":
    unittest.main()
