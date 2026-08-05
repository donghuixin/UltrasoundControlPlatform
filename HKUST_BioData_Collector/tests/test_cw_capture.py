from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from cw_capture_ui import DDR_BYTES, _capture_geometry
from cw_iq_analysis import analyze_iq_capture


class Var:
    def __init__(self, value):
        self.value = str(value)

    def get(self):
        return self.value


class CwCaptureTests(unittest.TestCase):
    def test_five_msps_caps_to_full_512_mib_ddr(self):
        app = SimpleNamespace(cw_iq_rate_var=Var(5), cw_duration_var=Var(10))
        rate, frames, actual_s, expected_bytes = _capture_geometry(app)
        self.assertEqual(rate, 5_000_000.0)
        self.assertEqual(expected_bytes, DDR_BYTES)
        self.assertAlmostEqual(actual_s, 3.3554432)
        self.assertEqual(frames % 4096, 0)

    def test_iq_preview_recovers_signed_frequency(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = 65536
            rate = 5_000_000.0
            index = np.arange(frames)
            words = np.empty((frames, 16), dtype="<u2")
            for channel in range(8):
                frequency = 1000.0 * (channel + 1)
                i_data = (1200 * np.cos(2 * np.pi * frequency * index / rate)).astype("<i2")
                q_data = (1200 * np.sin(2 * np.pi * frequency * index / rate)).astype("<i2")
                words[:, 2 * channel] = i_data.view("<u2") ^ 0x8000
                words[:, 2 * channel + 1] = q_data.view("<u2") ^ 0x8000
            bin_path = root / "input.bin"
            words.tofile(bin_path)
            result = analyze_iq_capture(bin_path, rate, root / "analysis", (1, 2, 3))
            peaks = [item["peak_baseband_hz"] for item in result["channels"]]
            for actual, expected in zip(peaks, (1000.0, 2000.0, 3000.0)):
                self.assertAlmostEqual(actual, expected, delta=80.0)
            self.assertTrue((root / "analysis" / "cw_iq_preview.png").is_file())


if __name__ == "__main__":
    unittest.main()
