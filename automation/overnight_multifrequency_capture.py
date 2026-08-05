# -*- coding: utf-8 -*-
from __future__ import print_function

"""Strictly serial overnight capture: 5 x 1 MHz, 5 x 2.5 MHz, 5 x 4 MHz.

SETUP / SAFETY
==============
1. Gel/phantom only.  Do not use this unattended sequence on a person.
2. TX7316 GUI, AFE58JD48 GUI and HSDC Pro must already be initialized,
   CONNECTED, and running at the same Windows administrator integrity level.
3. Normal HSDC capture must use TI's channel-mapping-fix profile
   AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1 at 120 MSPS.
4. CW and elastography modes must be off.  The finite B-mode pattern is written
   only while TX_BF_MODE is off and is read back bit-for-bit before capture.
5. Keep the phantom/probe fixed and wet-coupled.  Make sure the HV supplies,
   cables and load are suitable for unattended operation.

FAIL-CLOSED RULES
=================
- Runs one child capture at a time; no next run starts until the previous
  process exits and its manifest, 21 BIN files, exact file sizes, TX pattern
  readback, and ADC rail-code checks all pass.
- Any failure stops the entire night sequence.  TX child cleanup forces
  TX_BF_MODE off and restores the previous pattern before it exits.
- Every group is a separate capture_YYYYMMDD_HHMMSS folder below New2039.
"""

import argparse
import ctypes
import datetime
import json
import os
import subprocess
import sys
import time


PYTHON27 = r"C:\Python27\python.exe"
ROOT = r"E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture"
CAPTURE_SCRIPT = os.path.join(ROOT, "automation", "tx7316_hsdc_batch_capture.py")
OUTPUT_ROOT = os.path.join(ROOT, "auto_runs", "New2039")
REPORT_PATH = os.path.join(OUTPUT_ROOT, "overnight_batch_report.json")
ANGLES = "-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,0,1,2,3,4,5,6,7,8,9,10"
RX_SLOTS = "9,10,11,12,13,14,15,16"
DEFAULT_FREQUENCIES_MHZ = [1.0, 2.5, 4.0]
DEFAULT_GROUPS_PER_FREQUENCY = 5
EXPECTED_FILES = 21
SAMPLES_PER_CHANNEL = 1048576
EXPECTED_FILE_BYTES = SAMPLES_PER_CHANNEL * 16 * 2
MIN_FREE_BYTES = 12 * 1024 * 1024 * 1024
# A handful of exact ADC rail codes can be confined to the transmit-switching
# transient and does not imply that the delayed echo ROI is clipped.  Preserve
# the count in every manifest/report, but fail closed if more than 0.1% of a
# file is at either unsigned-16 rail.  For the 1.5 MHz check on 2026-07-24,
# every rail code was confined to nine 387-row clusters spaced by the measured
# PRF (120,076 rows); none occupied the delayed-echo intervals.  Delayed-region
# clipping is still a hard failure in reconstruction QA.
MAX_RAIL_FRACTION_PER_FILE = 1.0e-3


def parse_args():
    parser = argparse.ArgumentParser(
        description="Strict serial, readback-verified TX7316/HSDC frequency capture"
    )
    parser.add_argument(
        "--frequencies-mhz",
        default=",".join(str(value) for value in DEFAULT_FREQUENCIES_MHZ),
        help="comma-separated TX frequencies, for example 1.5,2.0,2.5",
    )
    parser.add_argument(
        "--groups-per-frequency",
        type=int,
        default=DEFAULT_GROUPS_PER_FREQUENCY,
        help="number of complete 21-angle captures at each frequency",
    )
    parser.add_argument(
        "--report-name",
        default=os.path.basename(REPORT_PATH),
        help="JSON report filename written below the New2039 output root",
    )
    return parser.parse_args()


def requested_frequencies(text):
    values = [float(item.strip()) for item in text.split(",") if item.strip()]
    if not values:
        raise ValueError("At least one frequency is required")
    if any(value <= 0.0 or value > 10.0 for value in values):
        raise ValueError("Frequencies must be in the range (0, 10] MHz")
    return values


def now_text():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def atomic_json(path, value):
    temp = path + ".tmp"
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    with open(temp, "wb") as handle:
        handle.write(payload.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    if os.path.exists(path):
        os.remove(path)
    os.rename(temp, path)


def free_bytes(path):
    value = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        unicode(path), ctypes.byref(value), None, None
    )
    if not ok:
        raise RuntimeError("Unable to query free disk space for " + path)
    return int(value.value)


def capture_dirs():
    if not os.path.isdir(OUTPUT_ROOT):
        return set()
    return set(
        os.path.join(OUTPUT_ROOT, name)
        for name in os.listdir(OUTPUT_ROOT)
        if name.startswith("capture_") and os.path.isdir(os.path.join(OUTPUT_ROOT, name))
    )


def load_json(path):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def validate_capture(folder, requested_frequency_mhz):
    manifest_path = os.path.join(folder, "capture_manifest.json")
    if not os.path.isfile(manifest_path):
        raise RuntimeError("Missing manifest: " + manifest_path)
    manifest = load_json(manifest_path)
    if manifest.get("status") != "complete":
        raise RuntimeError("Manifest status is not complete: %r" % manifest.get("status"))

    arguments = manifest.get("arguments", {})
    actual_frequency = float(arguments.get("center_frequency_mhz", -1))
    if abs(actual_frequency - requested_frequency_mhz) > 1e-9:
        raise RuntimeError(
            "Manifest frequency mismatch: requested %.3f got %.3f" % (
                requested_frequency_mhz, actual_frequency
            )
        )
    waveform = manifest.get("tx_waveform_readback", {})
    if waveform.get("reference_matches") is not True:
        raise RuntimeError("TX pattern readback did not match the frequency reference")
    programming = manifest.get("tx_pattern_programming", {})
    if programming.get("requested") is not True:
        raise RuntimeError("Manifest does not prove that TX pattern programming was requested")

    captures = manifest.get("captures", [])
    if len(captures) != EXPECTED_FILES:
        raise RuntimeError(
            "Expected %d capture records, got %d" % (EXPECTED_FILES, len(captures))
        )
    names = set()
    for entry in captures:
        filename = entry.get("filename")
        if not filename or filename in names:
            raise RuntimeError("Missing or duplicate capture filename in manifest")
        names.add(filename)
        path = os.path.join(folder, filename)
        if not os.path.isfile(path):
            raise RuntimeError("Missing BIN file: " + path)
        size = os.path.getsize(path)
        if size != EXPECTED_FILE_BYTES or int(entry.get("file_bytes", -1)) != size:
            raise RuntimeError(
                "BIN size mismatch for %s: got %d expected %d" % (
                    filename, size, EXPECTED_FILE_BYTES
                )
            )
        qa = entry.get("file_qa") or {}
        rail_count = int(qa.get("rail_sample_count", 0))
        total_samples = size // 2
        rail_fraction = rail_count / float(total_samples)
        if rail_fraction > MAX_RAIL_FRACTION_PER_FILE:
            raise RuntimeError(
                "ADC rail-code fraction %.6g exceeds %.6g in %s" % (
                    rail_fraction, MAX_RAIL_FRACTION_PER_FILE, filename
                )
            )
    bin_names = set(name for name in os.listdir(folder) if name.lower().endswith(".bin"))
    if bin_names != names:
        raise RuntimeError(
            "Folder BIN set does not exactly match manifest (%d vs %d)" % (
                len(bin_names), len(names)
            )
        )
    cfg_entries = manifest.get("tx_cfg_files", [])
    expected_cfg_count = (len(captures) + 15) // 16
    if len(cfg_entries) != expected_cfg_count:
        raise RuntimeError(
            "Expected %d verified TX CFG batch files, got %d" % (
                expected_cfg_count, len(cfg_entries)
            )
        )
    for entry in cfg_entries:
        cfg_name = entry.get("filename")
        cfg_path = os.path.join(folder, cfg_name or "")
        if not cfg_name or not os.path.isfile(cfg_path):
            raise RuntimeError("Missing verified TX CFG file: %r" % cfg_name)
        with open(cfg_path, "rb") as handle:
            digest = __import__("hashlib").sha256(handle.read()).hexdigest()
        if digest != entry.get("sha256"):
            raise RuntimeError("TX CFG SHA-256 mismatch: " + cfg_name)
    return manifest


def child_command(frequency_mhz):
    return [
        PYTHON27,
        CAPTURE_SCRIPT,
        "--capture",
        "--program-known-pattern",
        "--enable-internal-bf",
        "--center-frequency-mhz", str(frequency_mhz),
        "--angles=" + ANGLES,
        "--tx-elements", "8",
        "--rx-channels", RX_SLOTS,
        "--pitch-mm", "1.59",
        "--element-width-mm", "1.0",
        "--samples", str(SAMPLES_PER_CHANNEL),
        "--repeats", "1",
        "--settle-seconds", "0.25",
        "--timeout-ms", "180000",
        "--trigger", "normal",
        "--output-root", OUTPUT_ROOT,
    ]


def main():
    args = parse_args()
    frequencies_mhz = requested_frequencies(args.frequencies_mhz)
    groups_per_frequency = int(args.groups_per_frequency)
    if groups_per_frequency < 1:
        print("ERROR: groups-per-frequency must be at least 1.")
        return 2
    report_name = os.path.basename(args.report_name)
    if not report_name.lower().endswith(".json"):
        print("ERROR: report-name must end in .json")
        return 2
    report_path = os.path.join(OUTPUT_ROOT, report_name)
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("ERROR: run this orchestrator as Windows administrator.")
        return 2
    for required in [PYTHON27, CAPTURE_SCRIPT]:
        if not os.path.isfile(required):
            print("ERROR: missing required file: " + required)
            return 2
    if not os.path.isdir(OUTPUT_ROOT):
        os.makedirs(OUTPUT_ROOT)
    available = free_bytes(OUTPUT_ROOT)
    if available < MIN_FREE_BYTES:
        print("ERROR: less than 12 GiB free at output root: %d bytes" % available)
        return 2

    report = {
        "status": "running",
        "started_local": now_text(),
        "output_root": OUTPUT_ROOT,
        "plan": [
            {"frequency_mhz": value, "groups": groups_per_frequency}
            for value in frequencies_mhz
        ],
        "completed_groups": [],
    }
    atomic_json(report_path, report)
    ordinal = 0
    total = len(frequencies_mhz) * groups_per_frequency
    try:
        for frequency in frequencies_mhz:
            for group_index in range(1, groups_per_frequency + 1):
                ordinal += 1
                print("\n" + "=" * 78)
                print("OVERNIGHT GROUP %d/%d: %.3f MHz, replicate %d/%d" % (
                    ordinal, total, frequency, group_index, groups_per_frequency
                ))
                print("Start: " + now_text())
                print("=" * 78)
                before = capture_dirs()
                code = subprocess.call(child_command(frequency))
                after = capture_dirs()
                created = sorted(after - before, key=lambda path: os.path.getmtime(path))
                if code != 0:
                    raise RuntimeError(
                        "Child capture exited with code %d at %.3f MHz group %d" % (
                            code, frequency, group_index
                        )
                    )
                if len(created) != 1:
                    raise RuntimeError(
                        "Expected exactly one new capture folder, found %d: %r" % (
                            len(created), created
                        )
                    )
                folder = created[0]
                manifest = validate_capture(folder, frequency)
                record = {
                    "ordinal": ordinal,
                    "frequency_mhz": frequency,
                    "replicate": group_index,
                    "folder": folder,
                    "completed_local": now_text(),
                    "files": len(manifest.get("captures", [])),
                    "pattern_reference": manifest.get(
                        "tx_waveform_readback", {}
                    ).get("reference_name"),
                    "pattern_nominal_mhz": (
                        manifest.get("tx_waveform_readback", {}).get(
                            "nominal_base_pattern_hz", 0.0
                        ) / 1e6
                    ),
                    "max_rail_samples_per_file": max(
                        int((entry.get("file_qa") or {}).get("rail_sample_count", 0))
                        for entry in manifest.get("captures", [])
                    ),
                    "max_rail_fraction_per_file": max(
                        int((entry.get("file_qa") or {}).get("rail_sample_count", 0)) /
                        float(int(entry.get("file_bytes", EXPECTED_FILE_BYTES)) // 2)
                        for entry in manifest.get("captures", [])
                    ),
                }
                report["completed_groups"].append(record)
                report["last_verified_folder"] = folder
                atomic_json(report_path, report)
                print("VERIFIED COMPLETE: " + folder)
                # Ensure timestamp folders cannot collide and give hardware a
                # quiet period with TX_BF_MODE already forced off.
                time.sleep(5.0)
        report["status"] = "complete"
        report["completed_local"] = now_text()
        atomic_json(report_path, report)
        print("\nALL %d GROUPS VERIFIED COMPLETE." % total)
        return 0
    except Exception as exc:
        report["status"] = "error"
        report["failed_local"] = now_text()
        report["error"] = repr(exc)
        atomic_json(report_path, report)
        print("\nFAIL-CLOSED: %s" % exc)
        print("No later frequency/group will be started.")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted; child cleanup should force TX_BF_MODE off.")
        sys.exit(130)
