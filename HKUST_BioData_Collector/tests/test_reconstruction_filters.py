from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reconstruct_ultrasound import (  # noqa: E402
    coherence_factor_from_accumulators,
    receive_apodization_weights,
    suppress_gated_common_mode,
    tukey_window,
)


class ReconstructionFilterTests(unittest.TestCase):
    def test_receive_windows_are_symmetric_and_select_physical_positions(self) -> None:
        physical = np.arange(1, 9)
        uniform = receive_apodization_weights("uniform", physical, 8)
        hann = receive_apodization_weights("hann", physical, 8)
        tukey = receive_apodization_weights("tukey", physical, 8, 0.5)
        np.testing.assert_allclose(uniform, np.ones(8))
        np.testing.assert_allclose(hann, hann[::-1])
        np.testing.assert_allclose(tukey, tukey[::-1])
        self.assertEqual(float(hann[0]), 0.0)
        self.assertGreater(float(tukey[1]), float(hann[1]))

        selected = receive_apodization_weights(
            "tukey", np.asarray([1, 3, 8]), 8, 0.5
        )
        np.testing.assert_allclose(selected, tukey[[0, 2, 7]])

    def test_tukey_limits_match_uniform_and_hann(self) -> None:
        np.testing.assert_allclose(tukey_window(8, 0.0), np.ones(8))
        np.testing.assert_allclose(tukey_window(8, 1.0), np.hanning(8))

    def test_coherence_factor_is_one_for_aligned_and_zero_for_cancellation(self) -> None:
        weights = np.asarray([1.0, 1.0])
        aligned = np.asarray([1.0 + 0.0j, 1.0 + 0.0j])
        aligned_sum = np.sum(weights * aligned)
        aligned_power = np.sum(weights * np.abs(aligned) ** 2)
        aligned_cf = coherence_factor_from_accumulators(
            np.asarray([aligned_sum]), np.asarray([aligned_power]), float(np.sum(weights))
        )
        self.assertAlmostEqual(float(aligned_cf[0]), 1.0)

        opposed = np.asarray([1.0 + 0.0j, -1.0 + 0.0j])
        opposed_sum = np.sum(weights * opposed)
        opposed_power = np.sum(weights * np.abs(opposed) ** 2)
        opposed_cf = coherence_factor_from_accumulators(
            np.asarray([opposed_sum]), np.asarray([opposed_power]), float(np.sum(weights))
        )
        self.assertAlmostEqual(float(opposed_cf[0]), 0.0)

    def test_common_mode_suppression_is_gated_and_reduces_common_ringing(self) -> None:
        samples = 1200
        phase = np.linspace(0.0, 20.0 * np.pi, samples)
        common = 100.0 * np.sin(phase)
        segment = np.stack(
            [common + 0.5 * channel * np.cos(phase * 0.37) for channel in range(4)],
            axis=1,
        ).astype(np.float32)
        filtered, removed_fraction = suppress_gated_common_mode(
            segment,
            tx_reference_sample=100,
            max_depth_mm=5.0,
            strength=0.75,
        )
        gate_stop = int(round(100 + 2.0 * 5e-3 * 120_000_000.0 / 1540.0))
        before = np.sqrt(np.mean(np.median(segment[100:gate_stop], axis=1) ** 2))
        after = np.sqrt(np.mean(np.median(filtered[100:gate_stop], axis=1) ** 2))
        self.assertLess(after, before)
        self.assertGreater(removed_fraction, 0.0)
        np.testing.assert_allclose(filtered[:100], segment[:100])
        np.testing.assert_allclose(filtered[gate_stop:], segment[gate_stop:])


if __name__ == "__main__":
    unittest.main()
