# -*- coding: utf-8 -*-
from __future__ import print_function

"""Resume the four-frequency comparison after a completed 1 MHz folder."""

import datetime
import os
import sys

import overnight_multifrequency_capture as runner


runner.FREQUENCIES_MHZ = [1.5, 2.0, 2.5]
runner.GROUPS_PER_FREQUENCY = 1
runner.MIN_FREE_BYTES = 3 * 1024 * 1024 * 1024
runner.REPORT_PATH = os.path.join(
    runner.OUTPUT_ROOT,
    "frequency_comparison_remaining_%s.json" %
    datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
)


if __name__ == "__main__":
    sys.exit(runner.main())
