import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[2] / "automation" / "tx7316_cw_control.py"
SPEC = importlib.util.spec_from_file_location("tx7316_cw_control_tested", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cw)


class FakeTx:
    def __init__(self):
        self.registers = {
            ("GLOBAL", 0x18): 0x00000001,
            ("GLOBAL", 0x19): 0x12345678,
        }

    def read(self, block, address):
        return self.registers.get((block, address), 0)

    def write_verified(self, block, address, value):
        self.registers[(block, address)] = value & 0xFFFFFFFF


class Tx7316CwControlTests(unittest.TestCase):
    def setUp(self):
        self.tx = FakeTx()
        self.vendor_reg24 = cw.CW_ENABLE_MASK | 0x00000020
        self.entries = [
            ("GLOBAL", 0x18, self.vendor_reg24),
            ("GLOBAL", 0x19, 0xCAFEBABE),
        ]

    def test_stage_never_enables_cw_or_tx_bf(self):
        original, readback = cw.apply_vendor_cfg(self.tx, self.entries, enable_cw=False)
        self.assertEqual(readback & (cw.CW_ENABLE_MASK | cw.TX_BF_MODE_MASK), 0)
        self.assertEqual(original[("GLOBAL", 0x18)], 0x00000001)

    def test_timed_enable_can_be_restored_to_safe_off(self):
        original, enabled = cw.apply_vendor_cfg(self.tx, self.entries, enable_cw=True)
        self.assertEqual(enabled & cw.CW_ENABLE_MASK, cw.CW_ENABLE_MASK)
        final = cw.restore_original(self.tx, original)
        self.assertEqual(final & (cw.CW_ENABLE_MASK | cw.TX_BF_MODE_MASK), 0)


if __name__ == "__main__":
    unittest.main()
