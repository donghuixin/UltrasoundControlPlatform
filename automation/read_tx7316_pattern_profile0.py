# -*- coding: utf-8 -*-
from __future__ import print_function

"""Fast, read-only TX7316 Profile 0 register diagnostic.

This script intentionally has no write_register call.  It uses the locally
verified ActiveX endpoint (application ``TX7316 EVM``, port NaN), reads the
global control words and Pattern Profile 0, decodes the transition count, and
writes one JSON evidence file next to the script.
"""

import ctypes
import imp
import json
import os
import struct
import sys
import time


MODULE = r"E:\Program Files (x86)\Texas Instruments\TX7316 EVM\Scripts\TX7316 EVM.py"
OUTPUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tx_pattern_profile0_readback.json"
)


def reg_name(address):
    return "Register %d" % int(address)


def read(gui, block, address):
    return int(gui.read_register(block, reg_name(address))) & 0xffffffff


def decode_pattern(registers):
    transitions = []
    terminated = False
    for value in registers:
        for byte_index in range(4):
            encoded = (value >> (8 * byte_index)) & 0xff
            level = encoded & 0x7
            period = (encoded >> 3) & 0x1f
            if level == 7:
                terminated = True
                break
            transitions.append({
                "index": len(transitions) + 1,
                "level_code": level,
                "period_field": period,
                "duration_pattern_clocks": period + 2,
            })
        if terminated:
            break
    return transitions, terminated


def main():
    if struct.calcsize("P") * 8 != 32:
        print("ERROR: use C:\\Python27\\python.exe (32-bit).")
        return 2
    if not bool(ctypes.windll.shell32.IsUserAnAdmin()):
        print("ERROR: run this read-only diagnostic as Administrator.")
        return 2
    if not os.path.isfile(MODULE):
        print("ERROR: TX7316 Python module not found: " + MODULE)
        return 2

    module = imp.load_source("ti_tx7316_pattern_readonly", MODULE)
    gui = module.Device_GUI("TX7316 EVM", float("nan"))
    globals_read = dict(
        ("register_%d" % address, "0x%08X" % read(gui, "GLOBAL", address))
        for address in (0, 22, 24, 25)
    )
    registers = [read(gui, "PATTERN-PROFILE", 0x60 + offset) for offset in range(8)]
    transitions, terminated = decode_pattern(registers)
    reg24 = int(globals_read["register_24"], 16)
    reg25 = int(globals_read["register_25"], 16)
    clk_div = (reg24 >> 3) & 0x7
    pattern_clock_hz = 200000000.0 / float(2 ** clk_div)
    base_clocks = sum(item["duration_pattern_clocks"] for item in transitions)
    pattern_valid = bool(terminated and transitions and any(registers))
    result = {
        "status": "pass" if pattern_valid else "invalid_pattern",
        "read_only": True,
        "timestamp_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "application": "TX7316 EVM",
        "port": "NaN (local ActiveX)",
        "global_registers": globals_read,
        "tx_bf_mode": bool(reg24 & 0x1),
        "cw_en_1": bool(reg24 & (1 << 14)),
        "cw_en_2": bool(reg24 & (1 << 13)),
        "profile0_registers_0x60_to_0x67": ["0x%08X" % value for value in registers],
        "terminated_by_level7": bool(terminated),
        "pattern_valid": pattern_valid,
        "total_transitions": len(transitions),
        "transitions": transitions,
        "repeat_count_field": (reg25 >> 1) & 0x1f,
        "acoustic_cycles_from_repeat": ((reg25 >> 1) & 0x1f) + 1,
        "tail_count_field": (reg25 >> 6) & 0x1f,
        "clk_div": clk_div,
        "pattern_clock_hz": pattern_clock_hz,
        "base_pattern_clocks": base_clocks,
        "nominal_base_pattern_hz": (
            pattern_clock_hz / float(base_clocks)
            if pattern_valid and base_clocks else None
        ),
    }
    with open(OUTPUT, "wb") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True).encode("ascii"))
        handle.write(b"\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print("READ-ONLY: no TX register was written.")
    print("Saved: " + OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
