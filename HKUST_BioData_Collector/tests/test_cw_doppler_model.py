import math
import sys
from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from cw_doppler_model import (
    CwDopplerConfig,
    calculate_cw_doppler,
    estimate_dbud_velocity,
    refracted_angle_deg,
)


class CwDopplerModelTests(unittest.TestCase):
    def test_paper_row_refraction_angles(self):
        actual = [refracted_angle_deg(value) for value in (17.0, 20.0, 23.0)]
        expected = (26.76, 31.78, 36.99)
        for value, target in zip(actual, expected):
            self.assertAlmostEqual(value, target, places=2)

    def test_default_is_four_mhz_and_fifteen_msps(self):
        result = calculate_cw_doppler(CwDopplerConfig())
        self.assertAlmostEqual(result.iq_output_rate_hz, 15_000_000.0)
        self.assertEqual(result.nco_word, 2185)
        self.assertAlmostEqual(result.nco_actual_hz, 4_000_854.4921875)
        self.assertAlmostEqual(result.hsdc_16slot_bytes_per_s, 480_000_000.0)
        self.assertAlmostEqual(result.hsdc_8slot_bytes_per_s, 240_000_000.0)
        self.assertGreater(result.hsdc_16slot_duration_s, 1.0)
        self.assertEqual(result.external_iq_bytes, 2_000_000)
        self.assertTrue(result.preset_fir_supported)

    def test_five_msps_is_hardware_decimation_12(self):
        result = calculate_cw_doppler(CwDopplerConfig(decimation=12))
        self.assertAlmostEqual(result.iq_output_rate_hz, 5_000_000.0)
        self.assertTrue(result.preset_fir_supported)
        self.assertFalse(result.full_chain_write_ready)

    def test_eight_channel_topology_covers_each_patch_once(self):
        config = CwDopplerConfig()
        patches = [patch for row in config.rows for patch in row.tx_patch_ids + (row.rx_patch_id,)]
        self.assertEqual(sorted(patches), list(range(1, 9)))

    def test_only_selectable_center_frequency_choices_are_accepted(self):
        for frequency_hz in (1_000_000.0, 2_000_000.0, 3_125_000.0, 4_000_000.0):
            calculate_cw_doppler(CwDopplerConfig(center_frequency_hz=frequency_hz))
        with self.assertRaises(ValueError):
            calculate_cw_doppler(CwDopplerConfig(center_frequency_hz=3_000_000.0))

    def test_dbud_recovers_synthetic_speed_and_angle(self):
        config = CwDopplerConfig()
        result = calculate_cw_doppler(config)
        true_speed = 0.62
        true_angle = 5.0
        scale = 2.0 * config.center_frequency_hz / config.tissue_sound_speed_m_s
        measured = [
            scale * true_speed * math.sin(math.radians(beta - true_angle))
            for beta in result.refracted_angles_deg
        ]
        estimate = estimate_dbud_velocity(
            measured,
            result.refracted_angles_deg,
            config.center_frequency_hz,
            config.tissue_sound_speed_m_s,
        )
        self.assertAlmostEqual(estimate.signed_speed_m_s, true_speed, places=9)
        self.assertAlmostEqual(estimate.flow_angle_deg, true_angle, places=9)
        self.assertLess(estimate.residual_rms_hz, 1e-8)

    def test_invalid_duplicate_angles_are_rejected(self):
        rows = tuple(
            type(row)(row.row_number, 20.0, row.tx_patch_ids, row.rx_patch_id, row.afe_rx_slot)
            for row in CwDopplerConfig().rows
        )
        with self.assertRaises(ValueError):
            calculate_cw_doppler(CwDopplerConfig(rows=rows))

    def test_analysis_filter_must_be_below_nyquist(self):
        with self.assertRaises(ValueError):
            calculate_cw_doppler(CwDopplerConfig(analysis_rate_hz=50_000.0, lowpass_hz=25_000.0))


if __name__ == "__main__":
    unittest.main()
