# -*- coding: utf-8 -*-
from __future__ import print_function

"""One strictly serial comparison group at 1.0, 1.5, 2.0 and 2.5 MHz.

This is a deliberately small wrapper around overnight_multifrequency_capture.
It inherits the same fail-closed rules: one 21-angle folder per frequency,
bit-for-bit TX pattern readback, exact HSDC file-size checks, no ADC rail codes,
and no next frequency until the previous folder is verified complete.
"""

import datetime
import os
import sys

import overnight_multifrequency_capture as runner


runner.FREQUENCIES_MHZ = [1.0, 1.5, 2.0, 2.5]
runner.GROUPS_PER_FREQUENCY = 1
runner.MIN_FREE_BYTES = 4 * 1024 * 1024 * 1024
runner.REPORT_PATH = os.path.join(
    runner.OUTPUT_ROOT,
    "frequency_comparison_%s.json" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
)


if __name__ == "__main__":
    sys.exit(runner.main())
