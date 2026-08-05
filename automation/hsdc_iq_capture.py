#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Capture one finite AFE58JD48 demodulated I/Q DDR block with HSDC Pro."""

from __future__ import print_function

import argparse
import json
import os
import sys
import time


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tx7316_hsdc_batch_capture as capture  # noqa: E402


WORDS_PER_FRAME = 16  # I1,Q1,...,I8,Q8
DEFAULT_DEVICE = "AFE58JD48_Custom_PLL_MODE_40x_Demod_SubClass1"


def write_manifest(path, value):
    capture.json_write_atomic(path, value)


def main():
    parser = argparse.ArgumentParser(description="Finite TSW14J50 DDR capture of AFE digital I/Q")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output-rate-hz", type=float, required=True)
    parser.add_argument("--samples", type=int, required=True)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--board", default=capture.HSDC_BOARD_SERIAL)
    parser.add_argument("--trigger", choices=("normal", "software"), default="normal")
    parser.add_argument("--timeout-ms", type=int, default=capture.HSDC_DEFAULT_TIMEOUT_MS)
    parser.add_argument("--reuse-current-hsdc", action="store_true")
    args = parser.parse_args()
    if args.output_rate_hz <= 0:
        raise capture.AutomationError("Output rate must be positive")
    if args.samples <= 0 or args.samples % 4096:
        raise capture.AutomationError("Samples must be a positive multiple of 4096")
    expected_bytes = int(args.samples) * WORDS_PER_FRAME * 2
    print("HSDC I/Q device:", args.device)
    print("I/Q rate: %.6f MSPS" % (args.output_rate_hz / 1000000.0))
    print("Samples/slot:", args.samples)
    print("Expected BIN: %.2f MiB" % (expected_bytes / float(1024 ** 2)))
    print("Mapping: I1,Q1,I2,Q2,...,I8,Q8")
    if args.dry_run:
        print("DRY RUN COMPLETE: no board connection and no capture")
        return 0

    capture.require_32bit_python()
    if not capture.is_windows_admin():
        raise capture.AutomationError("Run the collector, HSDC Pro and this script as Administrator")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.abspath(os.path.join(args.output_root, "cw_capture_" + stamp))
    if not os.path.isdir(run_dir):
        os.makedirs(run_dir)
    manifest_path = os.path.join(run_dir, "cw_capture_manifest.json")
    bin_path = os.path.join(run_dir, "cw_iq.bin")
    manifest = {
        "schema": "hkust-cw-iq-capture/v1",
        "status": "initializing",
        "created": stamp,
        "device": args.device,
        "board": args.board,
        "output_rate_hz": args.output_rate_hz,
        "samples_per_slot": args.samples,
        "word_layout": "I1,Q1,I2,Q2,...,I8,Q8",
        "expected_bytes": expected_bytes,
        "file": bin_path,
        "trigger": args.trigger,
    }
    write_manifest(manifest_path, manifest)
    hsdc = None
    try:
        # HSDC's displayed/output rate is the post-decimation I/Q word rate,
        # not the 120-MSPS physical ADC clock.
        capture.ADC_SAMPLE_RATE_HZ = float(args.output_rate_hz)
        hsdc = capture.HSDCController(args.timeout_ms)
        manifest["status"] = "configuring_hsdc"
        write_manifest(manifest_path, manifest)
        hsdc.configure(
            args.samples,
            args.trigger,
            not args.reuse_current_hsdc,
            args.board,
            args.device,
        )
        manifest["status"] = "capturing_ddr"
        write_manifest(manifest_path, manifest)
        hsdc.capture(args.trigger)
        manifest["status"] = "saving_bin"
        write_manifest(manifest_path, manifest)
        save_result = hsdc.save_binary(bin_path, expected_bytes=expected_bytes)
        actual_bytes = os.path.getsize(bin_path)
        if actual_bytes != expected_bytes:
            raise capture.AutomationError(
                "Saved BIN size %d does not match expected %d" % (actual_bytes, expected_bytes)
            )
        manifest.update({
            "status": "complete",
            "actual_bytes": actual_bytes,
            "duration_s": args.samples / float(args.output_rate_hz),
            "save_result": save_result,
        })
        write_manifest(manifest_path, manifest)
        print("CW I/Q CAPTURE COMPLETE:", run_dir)
        return 0
    except Exception as exc:
        manifest["status"] = "error"
        manifest["error"] = repr(exc)
        write_manifest(manifest_path, manifest)
        raise
    finally:
        if hsdc is not None:
            try:
                hsdc.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ERROR:", repr(exc))
        sys.exit(1)
