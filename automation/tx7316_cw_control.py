#!/usr/bin/env python2
"""Safely stage or run the vendor-qualified TX7316EVM CW quick setup.

The installed TI 5-level EVM quick-start file is used as the source of truth.
This module never embeds or exports the vendor register sequence.  CW testing
is limited to the stock 200-MHz BF_CLK / 3.125-MHz output, a maximum of five
seconds, and an explicit operator acknowledgement that the CW supply rails
have been reduced to +/-5 V as required by the EVM user guide.
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import sys
import time


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tx7316_hsdc_batch_capture as capture  # noqa: E402


VENDOR_CW_CFG_SHA256 = "B74B50CFC0432B10E19F12A737AD4B43FAE73B8BEC16FC8E5ABD40FBB08B2FCA"
CW_ENABLE_MASK = (1 << 14) | (1 << 13)
TX_BF_MODE_MASK = 1
MAX_CW_SECONDS = 5.0


def vendor_cfg_candidates():
    relative = os.path.join(
        "Texas Instruments", "TX7316 EVM", "Config Files", "TX7316 5LVL",
        "TX7316 5LVLvE3", "Scripts", "Quick Start", "CW", "CW_mode.cfg",
    )
    candidates = [
        os.path.join(r"E:\Program Files (x86)", relative),
        os.path.join(r"C:\Program Files (x86)", relative),
    ]
    program_files = os.environ.get("ProgramFiles(x86)")
    if program_files:
        candidates.append(os.path.join(program_files, relative))
    return candidates


def find_vendor_cfg():
    for path in vendor_cfg_candidates():
        if os.path.isfile(path):
            return path
    raise capture.AutomationError(
        "TI TX7316 5-level CW quick-start file was not found in the installed GUI package"
    )


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def load_vendor_cfg(path):
    actual_hash = sha256_file(path)
    if actual_hash != VENDOR_CW_CFG_SHA256:
        raise capture.AutomationError(
            "Installed TX7316 CW quick-start hash is not qualified: %s" % actual_hash
        )
    allowed_blocks = set(("GLOBAL", "PATTERN-PROFILE", "DELAY-PROFILE", "CHANNEL-PDN"))
    entries = []
    block = None
    with open(path, "rb") as handle:
        for line_number, raw in enumerate(handle.read().decode("ascii").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                block_text, line = line.split("|", 1)
                block = block_text.strip()
            elif line in allowed_blocks:
                block = line
                continue
            if block not in allowed_blocks:
                raise capture.AutomationError("Malformed vendor CW cfg at line %d" % line_number)
            fields = line.replace(",", " ").split()
            if len(fields) != 2:
                raise capture.AutomationError("Malformed vendor CW cfg at line %d" % line_number)
            entries.append((block, int(fields[0], 0), int(fields[1], 0) & 0xffffffff))
    if not entries or len(entries) > 64:
        raise capture.AutomationError("Unexpected vendor CW cfg entry count: %d" % len(entries))
    if not any(block == "GLOBAL" and address == 0x18 for block, address, _value in entries):
        raise capture.AutomationError("Vendor CW cfg does not contain the CW control register")
    return entries, actual_hash


def force_cw_off(tx):
    failures = []
    for attempt in range(1, 4):
        try:
            current = tx.read("GLOBAL", 0x18)
            safe = current & ~(CW_ENABLE_MASK | TX_BF_MODE_MASK)
            tx.write_verified("GLOBAL", 0x18, safe)
            readback = tx.read("GLOBAL", 0x18)
            if readback & (CW_ENABLE_MASK | TX_BF_MODE_MASK):
                raise capture.AutomationError("CW/TX_BF readback remained enabled")
            return readback
        except Exception as exc:
            failures.append(repr(exc))
            time.sleep(0.1)
    raise capture.AutomationError("Unable to force CW OFF: %s" % " | ".join(failures))


def apply_vendor_cfg(tx, entries, enable_cw):
    original = {}
    vendor_reg24 = None
    for block, address, value in entries:
        key = (block, address)
        if key not in original:
            original[key] = tx.read(block, address)
        if block == "GLOBAL" and address == 0x18:
            vendor_reg24 = value
    if vendor_reg24 is None:
        raise capture.AutomationError("Vendor CW control value is missing")

    force_cw_off(tx)
    staged_reg24 = vendor_reg24 & ~(CW_ENABLE_MASK | TX_BF_MODE_MASK)
    tx.write_verified("GLOBAL", 0x18, staged_reg24)
    for block, address, value in entries:
        if block == "GLOBAL" and address == 0x18:
            continue
        tx.write_verified(block, address, value)

    final_reg24 = staged_reg24
    if enable_cw:
        final_reg24 = vendor_reg24 & ~TX_BF_MODE_MASK
        if (final_reg24 & CW_ENABLE_MASK) != CW_ENABLE_MASK:
            raise capture.AutomationError("Qualified vendor cfg does not enable both CW die groups")
        tx.write_verified("GLOBAL", 0x18, final_reg24)
        readback = tx.read("GLOBAL", 0x18)
        if (readback & CW_ENABLE_MASK) != CW_ENABLE_MASK or (readback & TX_BF_MODE_MASK):
            raise capture.AutomationError("CW enable readback failed")
    else:
        readback = tx.read("GLOBAL", 0x18)
        if readback & (CW_ENABLE_MASK | TX_BF_MODE_MASK):
            raise capture.AutomationError("CW/TX_BF became enabled while staging")
    return original, readback


def restore_original(tx, original):
    force_cw_off(tx)
    for (block, address), value in reversed(list(original.items())):
        if block == "GLOBAL" and address == 0x18:
            continue
        tx.write_verified(block, address, value)
    original_reg24 = original.get(("GLOBAL", 0x18), tx.read("GLOBAL", 0x18))
    safe_original = original_reg24 & ~(CW_ENABLE_MASK | TX_BF_MODE_MASK)
    tx.write_verified("GLOBAL", 0x18, safe_original)
    return tx.read("GLOBAL", 0x18)


def write_result(path, payload):
    if not path:
        return
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "wb") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Safe TX7316EVM stock-CW control")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--stage", action="store_true", help="apply vendor CW setup with CW_EN kept off")
    action.add_argument("--run-seconds", type=float, help="enable CW temporarily and always turn it off")
    action.add_argument("--stop", action="store_true", help="force CW and TX_BF_MODE off")
    parser.add_argument("--acknowledge-5v-supply", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    capture.require_32bit_python()
    if not capture.is_windows_admin():
        raise capture.AutomationError("Run the collector as Administrator")
    tx = capture.TX7316Controller()

    if args.stop:
        readback = force_cw_off(tx)
        write_result(args.output, {"status": "stopped", "cw_enabled": False, "register24": "0x%08X" % readback})
        print("TX7316 CW OFF verified")
        return 0

    cfg_path = find_vendor_cfg()
    entries, cfg_hash = load_vendor_cfg(cfg_path)
    if args.stage:
        _original, readback = apply_vendor_cfg(tx, entries, enable_cw=False)
        write_result(args.output, {
            "status": "staged", "cw_enabled": False, "tx_bf_mode_enabled": False,
            "stock_bf_clock_hz": 200000000, "stock_cw_frequency_hz": 3125000,
            "vendor_cfg_sha256": cfg_hash, "register24": "0x%08X" % readback,
        })
        print("TX7316 stock 3.125-MHz CW configuration staged; CW remains OFF")
        return 0

    duration = float(args.run_seconds)
    if not args.acknowledge_5v_supply:
        raise capture.AutomationError("CW run requires explicit acknowledgement of the measured +/-5-V supply")
    if not 0.05 <= duration <= MAX_CW_SECONDS:
        raise capture.AutomationError("CW duration must be between 0.05 and %.1f seconds" % MAX_CW_SECONDS)

    original = None
    started = None
    final_readback = None
    try:
        original, enabled_readback = apply_vendor_cfg(tx, entries, enable_cw=True)
        started = time.time()
        print("TX7316 stock CW ON: 3.125 MHz for %.3f seconds" % duration)
        time.sleep(duration)
    finally:
        if original is not None:
            final_readback = restore_original(tx, original)
        else:
            final_readback = force_cw_off(tx)
    elapsed = time.time() - started if started is not None else 0.0
    write_result(args.output, {
        "status": "complete", "cw_enabled": False, "tx_bf_mode_enabled": False,
        "stock_bf_clock_hz": 200000000, "stock_cw_frequency_hz": 3125000,
        "requested_seconds": duration, "elapsed_seconds": elapsed,
        "vendor_cfg_sha256": cfg_hash, "final_register24": "0x%08X" % final_readback,
    })
    print("TX7316 CW test complete; CW OFF readback verified")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("ERROR:", repr(exc))
        sys.exit(1)
