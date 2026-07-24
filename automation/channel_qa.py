#!/usr/bin/env python3
"""Compatibility entry point for channel_health_qa.py.

Accepts either the requested positional form:
    python automation/channel_qa.py <capture_dir>

or the original explicit form:
    python automation/channel_qa.py --capture-dir <capture_dir>
"""

from __future__ import annotations

import sys

from channel_health_qa import main


if len(sys.argv) >= 2 and not sys.argv[1].startswith("-"):
    sys.argv[1:1] = ["--capture-dir"]

raise SystemExit(main())
