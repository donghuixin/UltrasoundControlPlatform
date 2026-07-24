# -*- coding: utf-8 -*-
from __future__ import print_function

"""Backfill loadable TX7316 CFG batch files from a completed capture manifest."""

import argparse
import imp
import json
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURE_MODULE = os.path.join(HERE, "tx7316_hsdc_batch_capture.py")


def load_json(path):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_folder")
    args = parser.parse_args()
    folder = os.path.abspath(args.capture_folder)
    manifest_path = os.path.join(folder, "capture_manifest.json")
    manifest = load_json(manifest_path)
    if manifest.get("status") != "complete":
        raise RuntimeError("CFG export requires a complete capture manifest")

    module = imp.load_source("tx7316_capture_cfg_export", CAPTURE_MODULE)
    profiles = manifest["array"]["profiles"]
    batch_numbers = sorted(set(int(item["profile_batch_number"]) for item in profiles))
    batches = [
        [item for item in profiles if int(item["profile_batch_number"]) == number]
        for number in batch_numbers
    ]
    original = manifest["tx_original"]
    readback = manifest["tx_waveform_readback"]
    frequency_mhz = float(manifest["arguments"]["center_frequency_mhz"])
    artifacts = module.save_verified_tx_cfg_files(
        folder,
        manifest["array"],
        batches,
        int(original["register22"], 16),
        int(readback["register24"], 16),
        int(readback["register25"], 16),
        readback,
        frequency_mhz,
    )
    manifest["tx_cfg_files"] = artifacts
    module.json_write_atomic(manifest_path, manifest)
    print("Saved %d CFG files in %s" % (len(artifacts), folder))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ERROR: %s" % exc)
        sys.exit(1)
