import unittest

from rapid_scan_model import (
    RapidScanConfig,
    build_rapid_scan_plan,
    contiguous_prf_block_samples,
    plan_as_dict,
)


class RapidScanModelTests(unittest.TestCase):
    def test_stock_cpld_32_prf_block(self):
        samples = contiguous_prf_block_samples(1000.0, 32)
        self.assertEqual(samples, 3_837_952)
        self.assertAlmostEqual(samples / 120_000_000.0 * 1000.0, 31.9829333333)

    def test_eleven_angles_fit_one_file(self):
        angles = tuple(float(value) for value in range(-10, 12, 2))
        plan = build_rapid_scan_plan(RapidScanConfig(angles_deg=angles))
        self.assertEqual(plan.bank_count, 1)
        self.assertEqual(plan.file_count, 1)
        self.assertEqual(plan.banks[0].samples_per_channel, 1_441_792)
        self.assertEqual(plan.banks[0].expected_bytes, 46_137_344)
        self.assertEqual([event.hardware_profile for event in plan.banks[0].events], list(range(11)))
        self.assertAlmostEqual(plan.banks[0].events[-1].time_ms, 10.0)

    def test_twenty_one_angles_split_sixteen_plus_five(self):
        angles = tuple(float(value) for value in range(-10, 11))
        plan = build_rapid_scan_plan(RapidScanConfig(angles_deg=angles))
        self.assertEqual(plan.bank_count, 2)
        self.assertEqual([len(bank.angles_deg) for bank in plan.banks], [16, 5])
        self.assertEqual([bank.samples_per_channel for bank in plan.banks], [2_043_904, 720_896])
        self.assertEqual(plan.banks[1].events[0].global_angle_index, 16)
        self.assertEqual(plan.banks[1].events[0].hardware_profile, 0)

    def test_multiple_frames_cycle_profiles_in_one_file(self):
        plan = build_rapid_scan_plan(
            RapidScanConfig(angles_deg=(-1.0, 0.0, 1.0), frames=2)
        )
        events = plan.banks[0].events
        self.assertEqual(len(events), 6)
        self.assertEqual([event.frame_index for event in events], [0, 0, 0, 1, 1, 1])
        self.assertEqual([event.hardware_profile for event in events], [0, 1, 2, 0, 1, 2])

    def test_plan_json_is_fail_closed(self):
        plan = build_rapid_scan_plan(RapidScanConfig(angles_deg=(0.0,)))
        payload = plan_as_dict(plan)
        self.assertEqual(payload["execution_state"], "blocked_until_verified_sequencer")
        self.assertTrue(payload["hardware_requirements"])


if __name__ == "__main__":
    unittest.main()
