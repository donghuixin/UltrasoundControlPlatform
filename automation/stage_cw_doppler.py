#!/usr/bin/env python2
"""Stage the CW Doppler TX test frequency without enabling continuous TX.

This script intentionally performs only the part that has a verified register
encoding in this repository: write and read back the selected 1/2/4 MHz TX7316
pattern while CW_EN_1, CW_EN_2, and TX_BF_MODE remain off.  The selected AFE
digital-I/Q decimation and its matching HSDC JESD unpack transport remain
hardware gates, not settings that may be guessed by automation.
"""

from __future__ import print_function

import argparse
import json
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tx7316_hsdc_batch_capture as capture  # noqa: E402


def load_plan(path):
    with open(path, "rb") as handle:
        plan = json.loads(handle.read().decode("utf-8"))
    if plan.get("schema") not in ("hkust-cw-doppler-plan/v1", "hkust-cw-doppler-plan/v2"):
        raise capture.AutomationError("Unsupported CW plan schema")
    frequency_hz = float(plan["configuration"]["center_frequency_hz"])
    frequency_mhz = frequency_hz / 1000000.0
    if frequency_mhz not in (1.0, 2.0, 4.0):
        raise capture.AutomationError(
            "Only the qualified 1/2/4 MHz standby patterns may be staged; requested %.3f Hz"
            % frequency_hz
        )
    return plan, frequency_mhz


def main():
    parser = argparse.ArgumentParser(
        description="Stage a qualified TX7316 1/2/4 MHz pattern with CW kept OFF"
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan, frequency_mhz = load_plan(args.plan)
    print("CW Doppler plan:", os.path.abspath(args.plan))
    print("Active hardware channels: 8; adapted topology RX slots:", [
        row["afe_rx_slot"] for row in plan["configuration"]["rows"]
    ])
    print("TX action: qualified %.1f MHz finite pattern, CW OFF, TX_BF_MODE OFF" % frequency_mhz)
    print("AFE/HSDC action: blocked until a matching demod/decimation CFG and TSW unpack profile pass channel QA")
    if not args.apply:
        print("DRY RUN COMPLETE: no GUI connection and no register write")
        return 0

    capture.require_32bit_python()
    if not capture.is_windows_admin():
        raise capture.AutomationError("Run the collector as Administrator")
    tx = capture.TX7316Controller()
    tx.check_cw_disabled()
    result = tx.program_known_pattern_profile0(capture.KNOWN_PATTERN_PROFILES[frequency_mhz])
    tx.set_internal_bf(False)
    readback = tx.snapshot_pattern_profile(
        0,
        tx.read("GLOBAL", 0x18),
        tx.read("GLOBAL", 0x19),
    )
    if int(readback["register24"], 16) & ((1 << 14) | (1 << 13) | 1):
        raise capture.AutomationError("Safety readback failed: CW or TX_BF_MODE is enabled")
    result_path = os.path.splitext(os.path.abspath(args.plan))[0] + ".tx_standby_readback.json"
    capture.json_write_atomic(result_path, {
        "status": "complete",
        "tx_gui_application": tx.application_name,
        "cw_enabled": False,
        "tx_bf_mode_enabled": False,
        "requested_frequency_mhz": frequency_mhz,
        "nominal_pattern_hz": readback["nominal_base_pattern_hz"],
        "afe_register_write": "blocked_unqualified_profile",
        "hsdc_profile_write": "blocked_unqualified_profile",
        "configuration_plan": os.path.abspath(args.plan),
        "register24": readback["register24"],
        "register25": readback["register25"],
        "readback": readback,
    })
    print("TX SAFE-STANDBY STAGE COMPLETE")
    print("Readback:", result_path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ERROR:", repr(exc))
        sys.exit(1)
