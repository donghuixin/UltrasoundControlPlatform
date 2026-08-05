import unittest

from tx_plan import TxPlan, validate_tx_plan


class TxPlanTests(unittest.TestCase):
    def test_two_mhz_tapered_plan(self):
        plan = validate_tx_plan("tapered-5level", 2.0, 4, 100.0, 50.0)
        self.assertIsInstance(plan, TxPlan)
        self.assertEqual(plan.cycles, 4)
        self.assertEqual(
            plan.level_sequence,
            ("+B", "0", "+A", "0", "+B", "0", "-B", "0", "-A", "0", "-B", "0"),
        )

    def test_bipolar_rejects_one_mhz(self):
        with self.assertRaisesRegex(ValueError, "只允許 1.5 MHz"):
            validate_tx_plan("bipolar-a", 1.0, 2, 100.0, 50.0)

    def test_external_rail_order_is_checked(self):
        with self.assertRaisesRegex(ValueError, "HV_A"):
            validate_tx_plan("tapered-5level", 2.0, 4, 50.0, 80.0)

    def test_bipolar_does_not_select_the_b_rail(self):
        plan = validate_tx_plan("bipolar-a", 1.5, 2, 50.0, 80.0)
        self.assertEqual(plan.level_sequence, ("+A", "-A"))


if __name__ == "__main__":
    unittest.main()
