#!/usr/bin/env python3
"""Compare redacted jesd_transport_qa JSON reports and optional raw BIN hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def resolve_reports(items: Iterable[str]) -> List[Path]:
    reports: List[Path] = []
    for item in items:
        path = Path(item).expanduser()
        if path.is_dir():
            reports.extend(sorted(path.glob("jesd_transport_qa*.json")))
        elif path.is_file():
            reports.append(path)
        else:
            raise FileNotFoundError(item)
    if not reports:
        raise FileNotFoundError("No jesd_transport_qa JSON report found")
    return reports


def normalize_groups(groups: Any) -> List[List[int]]:
    return [sorted(int(value) for value in group) for group in (groups or [])]


def load_report(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    mapping = payload.get("mapping") or []
    slot_map = [entry.get("afe_channel_1_based") for entry in mapping]
    source_text = payload.get("source_bin")
    source = Path(source_text).expanduser() if source_text else None
    if source is not None and not source.is_absolute():
        source = path.parent / source
    source_hash = sha256(source) if source and source.is_file() else None
    return {
        "report": str(path.resolve()),
        "pass": bool(payload.get("pass")),
        "channels": payload.get("channels"),
        "sample_rows": payload.get("sample_rows"),
        "distinct_modal_code_count": payload.get("distinct_modal_code_count"),
        "duplicate_groups": normalize_groups(
            payload.get("bit_exact_duplicate_groups_1_based")
        ),
        "slot_to_afe_mapping": slot_map,
        "all_columns_stable": bool(
            (payload.get("acceptance") or {}).get("all_columns_stable")
        ),
        "source_bin": source_text,
        "source_sha256": source_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", help="QA JSON files or directories")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    results = [load_report(path) for path in resolve_reports(args.reports)]
    signatures = {
        json.dumps(
            {
                "duplicates": result["duplicate_groups"],
                "mapping": result["slot_to_afe_mapping"],
                "distinct": result["distinct_modal_code_count"],
            },
            sort_keys=True,
        )
        for result in results
    }
    available_hashes = [
        result["source_sha256"] for result in results if result["source_sha256"]
    ]
    unique_hashes = set(available_hashes)
    summary = {
        "report_count": len(results),
        "all_pass": all(result["pass"] for result in results),
        "same_failure_signature": len(signatures) == 1,
        "source_hash_report_count": len(available_hashes),
        "unique_source_hash_count": len(unique_hashes),
        "all_available_sources_byte_identical": (
            len(available_hashes) >= 2 and len(unique_hashes) == 1
        ),
        "results": results,
    }

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if summary["all_pass"] else 2

    for index, result in enumerate(results, start=1):
        print(f"[{index}] {result['report']}")
        print(
            "    PASS={pass_} stable={stable} distinct={distinct}/{channels} "
            "duplicates={duplicates}".format(
                pass_=result["pass"],
                stable=result["all_columns_stable"],
                distinct=result["distinct_modal_code_count"],
                channels=result["channels"],
                duplicates=result["duplicate_groups"],
            )
        )
        print(f"    mapping={result['slot_to_afe_mapping']}")
        print(f"    source_sha256={result['source_sha256'] or 'unavailable'}")
    print(f"Same failure signature: {summary['same_failure_signature']}")
    print(
        "All available raw sources byte-identical: "
        f"{summary['all_available_sources_byte_identical']}"
    )
    return 0 if summary["all_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
