# -*- coding: utf-8 -*-
from __future__ import print_function

"""Complete the frequency comparison with 2.0 and 2.5 MHz groups."""

import datetime
import os
import sys

import overnight_multifrequency_capture as runner


runner.FREQUENCIES_MHZ = [2.0, 2.5]
runner.GROUPS_PER_FREQUENCY = 1
runner.MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
runner.REPORT_PATH = os.path.join(
    runner.OUTPUT_ROOT,
    "frequency_comparison_last_two_%s.json" %
    datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
)


if __name__ == "__main__":
    sys.exit(runner.main())
