from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT / "automation" / "tx7316_hsdc_batch_capture.py"
SPEC = importlib.util.spec_from_file_location("tx7316_hsdc_batch_capture", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def decode_profile_bytes(registers: list[int]) -> tuple[list[int], list[int]]:
    levels: list[int] = []
    periods: list[int] = []
    for value in registers:
        for byte_index in range(4):
            encoded = (value >> (8 * byte_index)) & 0xFF
            level = encoded & 0x7
            if level == 7:
                return levels, periods
            levels.append(level)
            periods.append((encoded >> 3) & 0x1F)
    return levels, periods


class TxPatternDefaultTests(unittest.TestCase):
    def test_one_mhz_profile_has_twelve_transitions(self) -> None:
        profile = MODULE.pattern_profile_with_cycles(
            MODULE.KNOWN_PATTERN_PROFILES[1.0], 4
        )
        levels, periods = decode_profile_bytes(profile["registers"])
        self.assertEqual(levels, [6, 3, 2, 3, 6, 3, 5, 3, 1, 3, 5, 3])
        self.assertEqual(periods, [13, 16, 19, 16, 13, 16, 13, 16, 19, 16, 13, 16])
        self.assertEqual(profile["register25"] & 0x7FE, 0x246)

    def test_program_only_is_an_explicit_mode(self) -> None:
        args = MODULE.make_parser().parse_args(["--program-tx-only"])
        self.assertTrue(args.program_tx_only)
        self.assertFalse(args.capture)
        self.assertFalse(args.dry_run)
        self.assertEqual(args.center_frequency_mhz, 1.0)
        self.assertEqual(args.waveform_mode, "tapered-5level")
        self.assertEqual(args.tx_cycles, 4)

    def test_full_setup_reselects_legacy_g128off_profile(self) -> None:
        selected = MODULE.resolve_hsdc_capture_device(
            "AFE58JD48_S1_K8_G128OFF", "normal", allow_reselect=True
        )
        self.assertEqual(selected, MODULE.HSDC_AFE_RX_NORMAL_DEVICE)

    def test_reuse_refuses_legacy_g128off_profile(self) -> None:
        with self.assertRaises(MODULE.AutomationError):
            MODULE.resolve_hsdc_capture_device(
                "AFE58JD48_S1_K8_G128OFF", "normal", allow_reselect=False
            )

    def test_full_setup_selects_trigger_profile_for_j13(self) -> None:
        selected = MODULE.resolve_hsdc_capture_device(
            MODULE.HSDC_AFE_RX_DEVICE, "hardware", allow_reselect=True
        )
        self.assertEqual(selected, MODULE.HSDC_AFE_RX_TRIGGER_DEVICE)

    def test_full_setup_replaces_historical_m16_with_ti_fix(self) -> None:
        selected = MODULE.resolve_hsdc_capture_device(
            MODULE.HSDC_AFE_RX_DEVICE, "normal", allow_reselect=True
        )
        self.assertEqual(selected, MODULE.HSDC_AFE_RX_TI_VENDOR_DEVICE)


if __name__ == "__main__":
    unittest.main()
