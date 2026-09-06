from __future__ import annotations

import sys
from pathlib import Path
import unittest


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from long_capture_model import (  # noqa: E402
    TI_CANDIDATE_RAW_LANE_RATE_HZ,
    TiReplayCaptureConfig,
    calculate_ti_replay_capture,
    ti_replay_plan_as_dict,
)


class TiReplayCaptureModelTests(unittest.TestCase):
    def test_ti_60m_five_second_plan(self) -> None:
        result = calculate_ti_replay_capture(TiReplayCaptureConfig())
        self.assertAlmostEqual(result.block_duration_s, 0.5592405333333333)
        self.assertEqual(result.block_count, 10)
        self.assertGreaterEqual(result.virtual_span_s, 5.0)
        self.assertEqual(result.raw_file_bytes, 512 * 1024 * 1024)
        self.assertEqual(result.total_file_bytes, 5 * 1024 * 1024 * 1024)
        self.assertEqual(result.separated_rows_per_block, 524_288)
        self.assertEqual(result.separated_row_rate_hz, 937_500.0)
        self.assertEqual(result.overlap_separated_rows, 46_875)
        self.assertTrue(result.capture_ready)

    def test_twenty_megasample_candidate_is_planning_only(self) -> None:
        result = calculate_ti_replay_capture(
            TiReplayCaptureConfig(
                desired_span_s=5.0,
                overlap_s=0.05,
                raw_lane_rate_hz=TI_CANDIDATE_RAW_LANE_RATE_HZ,
            )
        )
        self.assertAlmostEqual(result.block_duration_s, 1.6777216)
        self.assertEqual(result.block_count, 4)
        self.assertFalse(result.capture_ready)
        self.assertIsNone(result.separated_row_rate_hz)
        self.assertIsNone(result.overlap_separated_rows)

    def test_overlap_must_be_shorter_than_block(self) -> None:
        with self.assertRaisesRegex(ValueError, "shorter"):
            calculate_ti_replay_capture(TiReplayCaptureConfig(overlap_s=0.6))

    def test_plan_forbids_live_continuity_claim(self) -> None:
        config = TiReplayCaptureConfig()
        plan = ti_replay_plan_as_dict(config, calculate_ti_replay_capture(config))
        self.assertFalse(plan["continuity_contract"]["gap_free_live_recording"])
        self.assertFalse(plan["continuity_contract"]["cardiac_cycle_claim_allowed"])


if __name__ == "__main__":
    unittest.main()
