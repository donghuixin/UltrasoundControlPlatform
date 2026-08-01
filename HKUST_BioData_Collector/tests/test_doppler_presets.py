from __future__ import annotations

import sys
from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from config_audit import run_audit
from doppler_model import DopplerConfig, calculate_doppler
from doppler_presets import CAROTID_PHANTOM_PRESETS


class DopplerPresetTests(unittest.TestCase):
    def result_for(self, preset):
        return calculate_doppler(
            DopplerConfig(
                center_frequency_mhz=preset.center_frequency_mhz,
                prf_hz=preset.prf_hz,
                steering_angle_deg=preset.steering_angle_deg,
                flow_angle_deg=preset.flow_angle_deg,
                target_depth_mm=preset.target_depth_mm,
                expected_velocity_m_s=preset.expected_velocity_m_s,
                desired_duration_s=preset.desired_duration_s,
                ensemble_pulses=preset.ensemble_pulses,
                gate_length_mm=preset.gate_length_mm,
                wall_filter_hz=preset.wall_filter_hz,
                expected_heart_rate_bpm=preset.expected_heart_rate_bpm,
                block_samples_per_channel=preset.block_samples_per_channel,
                rx_channels=16,
                iq_channels=8,
                capture_mode=preset.capture_mode,
            )
        )

    def test_keys_and_labels_are_unique(self) -> None:
        self.assertEqual(len({item.key for item in CAROTID_PHANTOM_PRESETS}), len(CAROTID_PHANTOM_PRESETS))
        self.assertEqual(len({item.label for item in CAROTID_PHANTOM_PRESETS}), len(CAROTID_PHANTOM_PRESETS))

    def test_only_short_raw_preset_is_currently_executable(self) -> None:
        executable = [item for item in CAROTID_PHANTOM_PRESETS if item.current_backend_executable]
        self.assertEqual([item.key for item in executable], ["carotid_phantom_raw_low_flow"])
        result = self.result_for(executable[0])
        self.assertGreaterEqual(result.pulses_per_raw_block, executable[0].ensemble_pulses)
        self.assertFalse(result.cardiac_duration_requirement_met)

    def test_multi_cycle_presets_have_depth_and_velocity_margin(self) -> None:
        for preset in CAROTID_PHANTOM_PRESETS:
            result = self.result_for(preset)
            self.assertLessEqual(preset.flow_angle_deg, 60.0)
            self.assertLess(preset.target_depth_mm, 0.8 * result.max_unambiguous_depth_mm)
            self.assertLess(preset.expected_velocity_m_s, 0.8 * result.nyquist_velocity_m_s)
            if not preset.current_backend_executable:
                self.assertTrue(result.cardiac_duration_requirement_met)

    def test_repository_config_audit_has_no_errors(self) -> None:
        report = run_audit()
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["counts"]["error"], 0)


if __name__ == "__main__":
    unittest.main()
