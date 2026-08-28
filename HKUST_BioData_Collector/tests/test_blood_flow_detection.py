from __future__ import annotations

import sys
from pathlib import Path
import unittest

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from blood_flow_detection import (  # noqa: E402
    FlowDetectionConfig,
    locate_blood_flow_gate,
    select_longest_contiguous_run,
)


def synthetic_depth_cube(include_flow: bool, common_comb: bool = False) -> tuple[np.ndarray, np.ndarray]:
    prf_hz = 2000.0
    pulses = 4096
    depths_mm = np.arange(18.0, 30.01, 0.5)
    time_s = np.arange(pulses) / prf_hz
    generator = np.random.default_rng(17 if include_flow else 19)
    cube = 0.06 * (
        generator.normal(size=(pulses, depths_mm.size, 2))
        + 1j * generator.normal(size=(pulses, depths_mm.size, 2))
    )
    if common_comb:
        common = 0.8 * np.exp(2j * np.pi * 220.0 * time_s)
        cube += common[:, None, None]
    if include_flow:
        gate = np.abs(depths_mm - 24.0) <= 0.75
        cardiac = 1.0 + 0.25 * np.sin(2.0 * np.pi * 1.2 * time_s)
        flow = cardiac * np.exp(2j * np.pi * 360.0 * time_s)
        channel_phase = np.exp(1j * np.asarray([0.0, 0.45]))
        cube[:, gate, :] += flow[:, None, None] * channel_phase[None, None, :]
    return cube.astype(np.complex64), depths_mm


class BloodFlowDetectionTests(unittest.TestCase):
    def test_localises_flow_and_accepts_against_static_reference(self) -> None:
        candidate, depths = synthetic_depth_cube(include_flow=True)
        reference, _ = synthetic_depth_cube(include_flow=False)
        result = locate_blood_flow_gate(
            candidate,
            depths,
            prf_hz=2000.0,
            center_frequency_hz=1.5e6,
            config=FlowDetectionConfig(
                wall_filter_hz=50.0,
                flow_max_hz=800.0,
                sample_volume_mm=2.0,
                welch_pulses=1024,
            ),
            reference_iq=reference,
        )
        self.assertTrue(result["blood_flow_candidate"])
        self.assertTrue(result["accepted_blood_flow"])
        self.assertAlmostEqual(result["selected_gate"]["center_mm"], 24.0, delta=0.75)
        self.assertGreater(result["selected_gate"]["reference_excess_db"], 3.0)

    def test_depth_wide_comb_is_not_blood(self) -> None:
        candidate, depths = synthetic_depth_cube(include_flow=False, common_comb=True)
        reference, _ = synthetic_depth_cube(include_flow=False)
        result = locate_blood_flow_gate(
            candidate,
            depths,
            prf_hz=2000.0,
            center_frequency_hz=1.5e6,
            config=FlowDetectionConfig(
                wall_filter_hz=50.0,
                flow_max_hz=800.0,
                sample_volume_mm=2.0,
                welch_pulses=1024,
                comb_base_hz=220.0,
                comb_half_width_hz=20.0,
            ),
            reference_iq=reference,
        )
        self.assertFalse(result["accepted_blood_flow"])
        self.assertEqual(result["classification"], "rejected")

    def test_gap_handling_keeps_only_longest_contiguous_run(self) -> None:
        iq = np.ones((10, 2), dtype=np.complex64)
        pulse_index = np.asarray([0, 1, 2, 3, 9, 10, 11, 12, 13, 14])
        selected, diagnostics = select_longest_contiguous_run(
            iq, prf_hz=1000.0, pulse_index=pulse_index
        )
        self.assertEqual(selected.shape[0], 6)
        self.assertEqual(diagnostics["gap_count"], 1)
        self.assertEqual(diagnostics["discarded_pulse_count"], 4)


if __name__ == "__main__":
    unittest.main()
