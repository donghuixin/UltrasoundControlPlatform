# -*- coding: utf-8 -*-
from __future__ import print_function

"""Capture TI demod DDR windows for deterministic trigger-delay stitching.

Production capture uses 32-bit Python 2.7 because HSDCProAutomation.dll is
32-bit.  Dry-run also works on Python 3 for CI and planning.

This script does not control the signal generator, TX7316, or its trigger-delay
hardware.  It pauses before every block so the operator can reset the identical
replay and set the recorded EXT_TRIG delay.  It must never be used to describe
separate captures of live flow as a continuous recording.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import sys
import time

import tx7316_hsdc_batch_capture as base


MAX_RAW_ROWS_PER_LANE = 33554432
RAW_LANES = 8
BYTES_PER_SAMPLE = 2
RAW_ROWS_PER_SEPARATED_ROW = 64
VERIFIED_RAW_LANE_RATE_HZ = 60000000.0
CANDIDATE_RAW_LANE_RATE_HZ = 20000000.0


def utc_now_text():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def local_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def json_write_atomic(path, value):
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    if os.path.exists(path):
        os.remove(path)
    os.rename(temporary, path)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def read_persisted_hsdc_state():
    """Record the user's current HSDC selection without changing or approving it."""
    state = {
        "default_controls_ini": base.HSDC_DEFAULT_CONTROLS_INI,
        "board_name": None,
        "adc_dac_selected": None,
        "firmware_type": None,
    }
    path = base.HSDC_DEFAULT_CONTROLS_INI
    if not os.path.isfile(path):
        return state
    parser = base.ConfigParser.RawConfigParser()
    parser.read(path)
    for target, option in (
        ("board_name", "Board Name"),
        ("adc_dac_selected", "ADC/DAC selected"),
        ("firmware_type", "Firmware Type"),
    ):
        try:
            state[target] = parser.get("Board Parameters", option).strip().strip('"')
        except Exception:
            pass
    return state


def build_plan(desired_span_s, overlap_s, sample_rate_hz, samples_per_lane, prf_hz):
    if desired_span_s <= 0:
        raise ValueError("desired span must be positive")
    if sample_rate_hz <= 0 or samples_per_lane <= 0 or prf_hz <= 0:
        raise ValueError("sample rate, samples per lane, and PRF must be positive")
    if samples_per_lane > MAX_RAW_ROWS_PER_LANE:
        raise ValueError("samples per lane exceed TI's stated maximum capture depth")
    block_seconds = samples_per_lane / float(sample_rate_hz)
    if overlap_s < 0 or overlap_s >= block_seconds:
        raise ValueError("overlap must be non-negative and shorter than one block")
    step_seconds = block_seconds - overlap_s
    if desired_span_s <= block_seconds:
        block_count = 1
    else:
        block_count = int(math.ceil((desired_span_s - block_seconds) / step_seconds)) + 1
    offsets = [index * step_seconds for index in range(block_count)]
    file_bytes = samples_per_lane * RAW_LANES * BYTES_PER_SAMPLE
    supplied_separator_applies = abs(sample_rate_hz - VERIFIED_RAW_LANE_RATE_HZ) <= 0.5
    separated_rate_hz = (
        sample_rate_hz / float(RAW_ROWS_PER_SEPARATED_ROW)
        if supplied_separator_applies else None
    )
    return {
        "desired_virtual_span_s": desired_span_s,
        "block_duration_s": block_seconds,
        "step_s": step_seconds,
        "block_count": block_count,
        "virtual_span_s": block_seconds + (block_count - 1) * step_seconds,
        "trigger_offsets_s": offsets,
        "raw_lane_rate_hz": sample_rate_hz,
        "raw_rows_per_lane": samples_per_lane,
        "raw_lanes": RAW_LANES,
        "bytes_per_lane_sample": BYTES_PER_SAMPLE,
        "raw_file_bytes": file_bytes,
        "total_file_bytes": file_bytes * block_count,
        "raw_rows_per_separated_row": RAW_ROWS_PER_SEPARATED_ROW if supplied_separator_applies else None,
        "separated_rows_per_block": samples_per_lane // RAW_ROWS_PER_SEPARATED_ROW if supplied_separator_applies else None,
        "separated_row_rate_hz_inferred": separated_rate_hz,
        "overlap_raw_rows": int(round(overlap_s * sample_rate_hz)),
        "overlap_separated_rows": int(round(overlap_s * separated_rate_hz)) if separated_rate_hz else None,
        "prf_hz_metadata_only": prf_hz,
        "pulses_per_block_expected": block_seconds * prf_hz,
        "gap_free_live_recording": False,
        "deterministic_replay_stitch_only": True,
    }


def make_parser():
    parser = argparse.ArgumentParser(
        description="HSDC Pro deterministic replay capture orchestrator (not live continuous recording)."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--capture", action="store_true")
    parser.add_argument("--output-root", default=base.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--desired-span-s", type=float, default=5.0)
    parser.add_argument("--overlap-s", type=float, default=0.05)
    parser.add_argument("--sample-rate-hz", type=float, default=VERIFIED_RAW_LANE_RATE_HZ)
    parser.add_argument("--samples-per-lane", type=int, default=MAX_RAW_ROWS_PER_LANE)
    parser.add_argument("--prf-hz", type=float, default=1000.0)
    parser.add_argument("--timeout-ms", type=int, default=base.HSDC_DEFAULT_TIMEOUT_MS)
    parser.add_argument("--skip-sha256", action="store_true")
    parser.add_argument("--acknowledge-deterministic-replay-only", action="store_true")
    parser.add_argument("--acknowledge-phase-lock", action="store_true")
    return parser


def print_plan(plan):
    print("TI EXT_TRIG deterministic replay plan")
    print("  NOT a gap-free live recording")
    print("  block duration: %.9f s" % plan["block_duration_s"])
    print("  virtual span:   %.9f s" % plan["virtual_span_s"])
    print("  blocks:         %d" % plan["block_count"])
    print("  one BIN:        %.1f MiB" % (plan["raw_file_bytes"] / float(1024 ** 2)))
    print("  total:          %.3f GiB" % (plan["total_file_bytes"] / float(1024 ** 3)))
    if plan["separated_row_rate_hz_inferred"] is None:
        print("  separated rate: UNKNOWN (no matching frame mapping/separator supplied)")
    else:
        print("  separated rate: %.1f complex rows/s (inferred from 64 raw rows/output row)" %
              plan["separated_row_rate_hz_inferred"])
    print("  offsets (s):    %s" % ", ".join("%.9f" % value for value in plan["trigger_offsets_s"]))


def require_capture_acknowledgements(args):
    if abs(args.sample_rate_hz - VERIFIED_RAW_LANE_RATE_HZ) > 0.5:
        if abs(args.sample_rate_hz - CANDIDATE_RAW_LANE_RATE_HZ) <= 0.5:
            reason = "20 MSPS / 160x was suggested by TI, but no matching CFG/separator was supplied"
        else:
            reason = "the selected sample rate has no qualified TI package"
        raise base.AutomationError(reason + "; this script permits planning only")
    if not args.acknowledge_deterministic_replay_only:
        raise base.AutomationError("missing --acknowledge-deterministic-replay-only")
    if not args.acknowledge_phase_lock:
        raise base.AutomationError("missing --acknowledge-phase-lock")
    base.require_32bit_python()
    if not base.is_windows_admin():
        raise base.AutomationError(
            "Capture requires Administrator; HSDC Pro and this console must use the same elevation."
        )


def prompt_for_block(block_index, block_count, offset_s):
    prompt = (
        "\nBLOCK %02d/%02d - operator action required\n"
        "1. Reset the deterministic input sequence to the identical t=0.\n"
        "2. Set EXT_TRIG rising-edge delay to %.9f s relative to that t=0.\n"
        "3. Confirm input generation, ADC clock, and EXT_TRIG remain phase locked.\n"
        "4. Type READY and press Enter; HSDC will arm and wait for exactly one trigger edge.\n> "
    ) % (block_index + 1, block_count, offset_s)
    try:
        response = raw_input(prompt)
    except NameError:
        response = input(prompt)
    if response.strip().upper() != "READY":
        raise base.AutomationError("operator did not confirm READY for block %d" % block_index)


def run_capture(args, plan):
    require_capture_acknowledgements(args)
    output_root = os.path.abspath(args.output_root)
    run_dir = os.path.join(output_root, "capture_ti_replay_" + local_stamp())
    if os.path.exists(run_dir):
        raise base.AutomationError("refusing to reuse existing run directory: " + run_dir)
    os.makedirs(run_dir)
    manifest_path = os.path.join(run_dir, "capture_manifest.json")
    log_path = os.path.join(run_dir, "run.log")
    base.LOG_HANDLE = open(log_path, "ab")
    persisted_hsdc_state = read_persisted_hsdc_state()
    manifest = {
        "schema_version": 1,
        "status": "initializing",
        "created_utc": utc_now_text(),
        "script": os.path.abspath(__file__),
        "python": sys.executable,
        "method": "ti_external_trigger_deterministic_replay_stitch",
        "planned_captures": plan["block_count"],
        "arguments": vars(args),
        "plan": plan,
        "continuity_contract": {
            "gap_free_live_recording": False,
            "deterministic_replay_stitch_only": True,
            "cardiac_cycle_claim_allowed": False,
        },
        "hsdc": {
            "reuse_current_gui_configuration": False,
            "full_setup_or_profile_selection_by_script": True,
            "selection_policy": "reconnect and reload the operator's persisted HSDC device selection",
            "persisted_state_before_capture": persisted_hsdc_state,
            "trigger": "hardware",
            "capture_to_file_streaming_enabled": False,
        },
        "captures": [],
    }
    json_write_atomic(manifest_path, manifest)
    base.log("Run directory: " + run_dir)
    base.log("NOT CONTINUOUS: deterministic replay stitching only.")
    hsdc = None
    try:
        free_bytes = base.free_bytes_for_path(run_dir)
        if free_bytes is not None and free_bytes < plan["total_file_bytes"] + 1024 ** 3:
            raise base.AutomationError("not enough disk space with 1 GiB safety margin")
        board_name = persisted_hsdc_state.get("board_name")
        device_name = persisted_hsdc_state.get("adc_dac_selected")
        if not board_name or not device_name:
            raise base.AutomationError(
                "HSDC persisted Board Name / ADC-DAC selection is missing; configure and close/reopen HSDC Pro first"
            )
        base.log("HSDC persisted selection: board=%s device=%s" % (board_name, device_name))
        hsdc = base.HSDCController(args.timeout_ms)
        hsdc.configure(
            samples=args.samples_per_lane,
            trigger_mode="hardware",
            full_setup=True,
            board_serial=board_name,
            device_name=device_name,
            enable_capture_to_file_streaming=False,
            sample_rate_hz=args.sample_rate_hz,
        )
        manifest["status"] = "waiting_for_operator"
        json_write_atomic(manifest_path, manifest)
        previous_saved_utc = None
        previous_saved_epoch_s = None
        for index, offset_s in enumerate(plan["trigger_offsets_s"]):
            prompt_for_block(index, plan["block_count"], offset_s)
            operator_ready_epoch_s = time.time()
            entry = {
                "block_index": index,
                "trigger_offset_s": offset_s,
                "operator_ready_utc": utc_now_text(),
                "operator_ready_epoch_s": operator_ready_epoch_s,
                "host_gap_since_previous_save_s": (
                    None if previous_saved_epoch_s is None
                    else operator_ready_epoch_s - previous_saved_epoch_s
                ),
                "status": "armed",
            }
            manifest["active_block"] = entry
            manifest["status"] = "armed_waiting_for_ext_trig"
            json_write_atomic(manifest_path, manifest)
            capture_started_epoch_s = time.time()
            hsdc.capture("hardware")
            capture_finished_epoch_s = time.time()
            filename = "replay_block_%03d_offset_%013.9fs.bin" % (index, offset_s)
            path = os.path.join(run_dir, filename)
            manifest["status"] = "saving"
            json_write_atomic(manifest_path, manifest)
            save_started_epoch_s = time.time()
            save_result = hsdc.save_binary(path, expected_bytes=plan["raw_file_bytes"])
            save_finished_epoch_s = time.time()
            actual_bytes = os.path.getsize(path)
            if actual_bytes != plan["raw_file_bytes"]:
                raise base.AutomationError(
                    "saved file size mismatch: expected %d got %d" %
                    (plan["raw_file_bytes"], actual_bytes)
                )
            saved_utc = utc_now_text()
            entry.update({
                "status": "complete",
                "filename": filename,
                "bytes": actual_bytes,
                "sha256": None if args.skip_sha256 else sha256_file(path),
                "saved_utc": saved_utc,
                "previous_file_saved_utc": previous_saved_utc,
                "capture_call_elapsed_s": capture_finished_epoch_s - capture_started_epoch_s,
                "save_call_elapsed_s": save_finished_epoch_s - save_started_epoch_s,
                "hsdc_save": save_result,
            })
            previous_saved_utc = saved_utc
            previous_saved_epoch_s = save_finished_epoch_s
            manifest["captures"].append(entry)
            manifest.pop("active_block", None)
            manifest["status"] = "waiting_for_operator"
            json_write_atomic(manifest_path, manifest)
            base.log("Completed block %d/%d: %s" % (index + 1, plan["block_count"], filename))
        manifest["status"] = "complete"
        manifest["completed_utc"] = utc_now_text()
        json_write_atomic(manifest_path, manifest)
        base.log("CAPTURE COMPLETE: %d finite DDR blocks saved." % plan["block_count"])
        return 0
    except Exception as exc:
        manifest["status"] = "error"
        manifest["error"] = repr(exc)
        manifest["failed_utc"] = utc_now_text()
        json_write_atomic(manifest_path, manifest)
        base.log("ERROR: %r" % exc)
        raise
    finally:
        if hsdc is not None:
            try:
                hsdc.set_trigger("normal")
            except Exception as exc:
                base.log("WARNING: unable to disarm HSDC trigger: %r" % exc)
            try:
                hsdc.disconnect()
            except Exception as exc:
                base.log("WARNING: HSDC disconnect failed: %r" % exc)
        if base.LOG_HANDLE is not None:
            base.LOG_HANDLE.close()
            base.LOG_HANDLE = None


def main(argv=None):
    args = make_parser().parse_args(argv)
    try:
        plan = build_plan(
            args.desired_span_s,
            args.overlap_s,
            args.sample_rate_hz,
            args.samples_per_lane,
            args.prf_hz,
        )
        print_plan(plan)
        if args.dry_run:
            if abs(args.sample_rate_hz - VERIFIED_RAW_LANE_RATE_HZ) > 0.5:
                print("PLANNING ONLY: no supplied, qualified configuration for this rate.")
            print("DRY RUN COMPLETE: no HSDC connection, no trigger arm, no file creation.")
            return 0
        return run_capture(args, plan)
    except Exception as exc:
        print("ERROR: %r" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
