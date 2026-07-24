#!/usr/bin/env python3
"""Validate the 16-channel JESD transport with unique AFE custom codes.

Load configs/afe58jd48/ADC_UNIQUE_CODES_16CH.cfg, capture a short raw BIN
with HSDC, then run:

    python automation/jesd_transport_qa.py path/to/jesd_unique_codes.bin

The test is deliberately independent of transducer acoustics, AFE gain, TX
timing and scene coherence. It verifies that every injected AFE code appears
exactly once in the 16 HSDC columns and that no output columns are bit-exact
duplicates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np


AFE_CODES = [
    0x1357, 0x2468, 0x369C, 0x47AD,
    0x58BE, 0x69CF, 0x7A01, 0x8B12,
    0x9C23, 0xAD34, 0xBE45, 0xCF56,
    0xD067, 0xE178, 0xF289, 0x0A9A,
]


def parse_int(text: str) -> int:
    return int(text, 0)


def column_digest(column: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(column).view(np.uint8)).hexdigest()


def choose_bin(path: Path) -> Path:
    if path.is_file():
        return path
    candidates = sorted(path.glob("*.bin"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"no .bin file found in {path}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="raw HSDC BIN or directory containing it")
    parser.add_argument("--channels", type=int, default=16)
    parser.add_argument("--xor", type=parse_int, default=0x8000,
                        help="HSDC Data Postprocessing XOR (default: 0x8000)")
    parser.add_argument("--min-modal-fraction", type=float, default=0.99)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    source = choose_bin(args.input.resolve())
    item_count = source.stat().st_size // np.dtype("<u2").itemsize
    if item_count == 0 or item_count % args.channels:
        raise ValueError(
            f"{source} contains {item_count} uint16 values; not divisible by {args.channels}"
        )
    data = np.memmap(source, dtype="<u2", mode="r").reshape(-1, args.channels)

    modes: list[int] = []
    modal_fractions: list[float] = []
    digests: list[str] = []
    for index in range(args.channels):
        values, counts = np.unique(data[:, index], return_counts=True)
        winner = int(np.argmax(counts))
        modes.append(int(values[winner]))
        modal_fractions.append(float(counts[winner]) / float(data.shape[0]))
        digests.append(column_digest(data[:, index]))

    digest_groups: dict[str, list[int]] = {}
    for slot, digest in enumerate(digests, start=1):
        digest_groups.setdefault(digest, []).append(slot)
    exact_groups = [members for members in digest_groups.values() if len(members) > 1]

    expected_hsdc = [code ^ args.xor for code in AFE_CODES]
    expected_counter = Counter(expected_hsdc)
    observed_counter = Counter(modes)
    code_to_afe = {code ^ args.xor: channel for channel, code in enumerate(AFE_CODES, start=1)}
    mapping = [
        {
            "hsdc_slot_1_based": slot,
            "observed_mode_hex": f"0x{mode:04X}",
            "afe_channel_1_based": code_to_afe.get(mode),
            "modal_fraction": modal_fractions[slot - 1],
        }
        for slot, mode in enumerate(modes, start=1)
    ]
    missing = sorted((expected_counter - observed_counter).elements())
    unexpected = sorted((observed_counter - expected_counter).elements())
    stable = all(value >= args.min_modal_fraction for value in modal_fractions)
    passed = not exact_groups and not missing and not unexpected and stable

    report = {
        "schema_version": 1,
        "source_bin": str(source),
        "sample_rows": int(data.shape[0]),
        "channels": args.channels,
        "postprocessing_xor_hex": f"0x{args.xor:04X}",
        "pass": passed,
        "acceptance": {
            "no_bit_exact_duplicate_columns": not exact_groups,
            "all_16_expected_codes_seen_once": not missing and not unexpected,
            "all_columns_stable": stable,
        },
        "bit_exact_duplicate_groups_1_based": exact_groups,
        "distinct_modal_code_count": len(set(modes)),
        "missing_expected_codes_hex": [f"0x{value:04X}" for value in missing],
        "unexpected_codes_hex": [f"0x{value:04X}" for value in unexpected],
        "mapping": mapping,
    }
    output = args.output or source.with_name(source.stem + "_jesd_transport_qa.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Source: {source}")
    print(f"Bit-exact duplicate groups: {exact_groups or 'none'}")
    print(f"Distinct modal codes: {len(set(modes))}/{args.channels}")
    print(f"Stable columns: {sum(v >= args.min_modal_fraction for v in modal_fractions)}/{args.channels}")
    print(f"AFE -> HSDC mapping recovered: {not missing and not unexpected}")
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    print(f"Report: {output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
