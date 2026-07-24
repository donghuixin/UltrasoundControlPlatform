#!/usr/bin/env python3
"""Quantitative receive-channel QA and safe software masking.

This tool is deliberately read-only with respect to the hardware and raw BIN
files.  It answers three different questions that must not be conflated:

1. Are two HSDC output slots *bit-for-bit identical*?  If yes, the duplicate is
   deterministic and points to digital transport/unpacking/configuration, not
   ordinary analogue crosstalk.
2. Are channels merely highly correlated because a common transmit feedthrough
   or a planar reflector dominates?  Raw and common-mode-removed correlation
   matrices are both reported.
3. Which independent slots have useful echo SNR, low clipping and repeatable
   PRF events?  A conservative mask is generated without deleting raw data.

Typical use (from this repository root):

    python automation/channel_health_qa.py --capture-dir <capture_...>

Outputs are written below <capture_...>/analysis/channel_qa, including a compact
six-channel diagnostic package.  The package contains short event cut-outs and
metadata, not a second copy of the large raw BIN files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reconstruct_ultrasound import (  # noqa: E402
    FS_HZ,
    WINDOW_SAMPLES,
    detect_events_validated,
)


CHANNELS_IN_FILE = 16
DEFAULT_SOUND_SPEED_M_S = 1540.0
DEFAULT_TARGET_CHANNELS = 6
ANGLE_RE = re.compile(r"angle_([mp])(\d+)", re.IGNORECASE)


def parse_channels(text: str) -> list[int]:
    values = [int(part.strip()) for part in text.split(",") if part.strip()]
    if not values or len(values) != len(set(values)):
        raise argparse.ArgumentTypeError("channel list must be non-empty and unique")
    if any(value < 1 or value > CHANNELS_IN_FILE for value in values):
        raise argparse.ArgumentTypeError("HSDC slots must be in 1..16")
    return values


def finite_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if np.isfinite(number) else fallback


def load_manifest(capture_dir: Path) -> tuple[Path, dict[str, Any]]:
    candidates = [capture_dir / "capture_manifest.json", capture_dir / "manifest.json"]
    for path in candidates:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                return path, json.load(handle)
    return candidates[0], {}


def angle_from_name(path: Path) -> float | None:
    match = ANGLE_RE.search(path.stem)
    if not match:
        return None
    magnitude = float(match.group(2))
    return -magnitude if match.group(1).lower() == "m" else magnitude


def choose_analysis_file(files: list[Path], requested_angle: float) -> Path:
    matches = [path for path in files if angle_from_name(path) == requested_angle]
    if matches:
        return matches[0]
    if requested_angle == 0.0:
        textual = [path for path in files if "p00" in path.stem.lower()]
        if textual:
            return textual[0]
    return files[len(files) // 2]


def column_hashes(data: np.ndarray, chunk_rows: int = 131_072) -> list[str]:
    digests = [hashlib.sha256() for _ in range(data.shape[1])]
    for start in range(0, data.shape[0], chunk_rows):
        stop = min(data.shape[0], start + chunk_rows)
        block = np.asarray(data[start:stop, :])
        for channel, digest in enumerate(digests):
            contiguous = np.ascontiguousarray(block[:, channel])
            digest.update(contiguous.view(np.uint8))
    return [digest.hexdigest() for digest in digests]


def duplicate_groups_from_hashes(hashes: list[str]) -> list[list[int]]:
    groups: dict[str, list[int]] = {}
    for index, digest in enumerate(hashes, start=1):
        groups.setdefault(digest, []).append(index)
    return [members for members in groups.values() if len(members) > 1]


def duplicate_persistence(files: Iterable[Path], pairs: list[tuple[int, int]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for left, right in pairs:
        key = f"{left}={right}"
        matching: list[str] = []
        mismatching: list[str] = []
        for path in files:
            data = np.memmap(path, dtype="<u2", mode="r").reshape(-1, CHANNELS_IN_FILE)
            is_equal = True
            for start in range(0, data.shape[0], 131_072):
                stop = min(data.shape[0], start + 131_072)
                if not np.array_equal(data[start:stop, left - 1], data[start:stop, right - 1]):
                    is_equal = False
                    break
            (matching if is_equal else mismatching).append(path.name)
        result[key] = {
            "matching_file_count": len(matching),
            "total_file_count": len(matching) + len(mismatching),
            "persistent_in_all_files": not mismatching,
            "mismatching_files": mismatching,
        }
    return result


def fft_bandpass(signal: np.ndarray, low_hz: float, high_hz: float) -> np.ndarray:
    """Zero-phase FFT bandpass for QA metrics, with no hidden retuning."""
    spectrum = np.fft.rfft(signal, axis=0)
    frequency = np.fft.rfftfreq(signal.shape[0], d=1.0 / FS_HZ)
    spectrum[(frequency < low_hz) | (frequency > high_hz), :] = 0.0
    return np.fft.irfft(spectrum, n=signal.shape[0], axis=0).astype(np.float32)


def safe_corrcoef(samples_by_channel: np.ndarray) -> np.ndarray:
    if samples_by_channel.shape[0] < 2:
        return np.eye(samples_by_channel.shape[1], dtype=np.float64)
    centered = samples_by_channel - np.mean(samples_by_channel, axis=0, keepdims=True)
    scale = np.sqrt(np.sum(centered * centered, axis=0))
    normalized = centered / np.maximum(scale, 1e-12)
    result = normalized.T @ normalized
    return np.clip(result, -1.0, 1.0)


def noise_subtracted_snr_db(signal_power: float, noise_power: float) -> float:
    if noise_power <= 0.0:
        return float("nan")
    echo_power = max(signal_power - noise_power, noise_power * 1e-6)
    return float(10.0 * math.log10(echo_power / noise_power))


def depth_slice(z_min_mm: float, z_max_mm: float, sound_speed_m_s: float) -> slice:
    first = int(round(2.0 * z_min_mm * 1e-3 / sound_speed_m_s * FS_HZ))
    last = int(round(2.0 * z_max_mm * 1e-3 / sound_speed_m_s * FS_HZ))
    first = max(0, min(first, WINDOW_SAMPLES - 2))
    last = max(first + 1, min(last, WINDOW_SAMPLES))
    return slice(first, last)


def event_consistency(events: np.ndarray, window: slice) -> np.ndarray:
    """Median correlation of each channel's PRF echoes to its event template."""
    count, _, channels = events.shape
    consistency = np.full(channels, np.nan, dtype=np.float64)
    if count < 2:
        return consistency
    for channel in range(channels):
        traces = events[:, window, channel].astype(np.float64)
        traces -= np.mean(traces, axis=1, keepdims=True)
        norms = np.linalg.norm(traces, axis=1)
        valid = norms > 1e-12
        if np.count_nonzero(valid) < 2:
            continue
        normalized = traces[valid] / norms[valid, None]
        template = np.median(normalized, axis=0)
        template /= max(float(np.linalg.norm(template)), 1e-12)
        consistency[channel] = float(np.median(normalized @ template))
    return consistency


def build_mask(
    configured_slots: list[int],
    duplicate_groups: list[list[int]],
    metrics: dict[int, dict[str, Any]],
    target_count: int,
) -> tuple[list[int], list[int], dict[int, list[str]]]:
    parent = {slot: slot for slot in configured_slots}

    def find(slot: int) -> int:
        while parent[slot] != slot:
            parent[slot] = parent[parent[slot]]
            slot = parent[slot]
        return slot

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    configured_set = set(configured_slots)
    for group in duplicate_groups:
        members = [slot for slot in group if slot in configured_set]
        for member in members[1:]:
            union(members[0], member)

    equivalence: dict[int, list[int]] = {}
    for slot in configured_slots:
        equivalence.setdefault(find(slot), []).append(slot)

    reasons: dict[int, list[str]] = {slot: [] for slot in configured_slots}
    representatives: list[int] = []
    for members in equivalence.values():
        ranked = sorted(
            members,
            key=lambda slot: (
                finite_float(metrics[slot].get("quality_score"), -1e9),
                -configured_slots.index(slot),
            ),
            reverse=True,
        )
        representatives.append(ranked[0])
        for alias in ranked[1:]:
            reasons[alias].append(f"bit-exact digital alias of slot {ranked[0]}")

    representatives.sort(
        key=lambda slot: finite_float(metrics[slot].get("quality_score"), -1e9), reverse=True
    )
    selected = representatives[: max(1, min(target_count, len(representatives)))]
    for slot in representatives[len(selected) :]:
        reasons[slot].append(f"not selected: target independent-channel count is {target_count}")
    for slot in selected:
        if finite_float(metrics[slot].get("snr_internal_14_22mm_db"), -100.0) < 3.0:
            reasons[slot].append("warning only: internal 14-22 mm SNR is below 3 dB")
        if finite_float(metrics[slot].get("rail_fraction"), 0.0) > 1e-5:
            reasons[slot].append("warning only: ADC rail samples detected")
    excluded = [slot for slot in configured_slots if slot not in selected]
    return sorted(selected, key=configured_slots.index), excluded, reasons


def write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)


def json_number(value: float) -> float | None:
    return round(float(value), 6) if np.isfinite(value) else None


def plot_report(
    output_path: Path,
    slots: list[int],
    metrics: dict[int, dict[str, Any]],
    raw_corr: np.ndarray,
    residual_corr: np.ndarray,
    singular_energy: np.ndarray,
    selected: list[int],
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.0), constrained_layout=True)
    positions = np.arange(len(slots))
    colors = ["#1f77b4" if slot in selected else "#d95f5f" for slot in slots]
    internal_snr = [finite_float(metrics[slot].get("snr_internal_14_22mm_db"), -60.0) for slot in slots]
    full_snr = [finite_float(metrics[slot].get("snr_4_42mm_db"), -60.0) for slot in slots]
    width = 0.38
    axes[0, 0].bar(positions - width / 2, full_snr, width, label="4-42 mm", color=colors, alpha=0.55)
    axes[0, 0].bar(positions + width / 2, internal_snr, width, label="14-22 mm", color=colors)
    axes[0, 0].axhline(3.0, color="#333333", linestyle="--", linewidth=1.0, label="3 dB")
    axes[0, 0].set_xticks(positions, [str(slot) for slot in slots])
    axes[0, 0].set_xlabel("HSDC slot (1-based)")
    axes[0, 0].set_ylabel("Noise-subtracted SNR (dB)")
    axes[0, 0].set_title("Echo-window SNR; blue=selected, red=masked")
    axes[0, 0].legend(fontsize=8)

    for axis, matrix, title in (
        (axes[0, 1], raw_corr, "Raw echo correlation"),
        (axes[1, 0], residual_corr, "Correlation after removing per-sample common mode"),
    ):
        image = axis.imshow(matrix, vmin=-1.0, vmax=1.0, cmap="coolwarm")
        axis.set_xticks(positions, [str(slot) for slot in slots])
        axis.set_yticks(positions, [str(slot) for slot in slots])
        axis.set_xlabel("HSDC slot")
        axis.set_ylabel("HSDC slot")
        axis.set_title(title)
        fig.colorbar(image, ax=axis, shrink=0.82)

    axes[1, 1].bar(np.arange(1, len(singular_energy) + 1), singular_energy * 100.0, color="#4c78a8")
    axes[1, 1].set_xlabel("Singular component")
    axes[1, 1].set_ylabel("Energy (%)")
    axes[1, 1].set_title("Aperture data singular-value energy")
    axes[1, 1].set_ylim(0.0, 100.0)
    fig.suptitle("AFE58JD48 / TSW14J50 channel health QA", fontsize=15)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--rx-channels", type=parse_channels)
    parser.add_argument("--analysis-angle", type=float, default=0.0)
    parser.add_argument("--target-channels", type=int, default=DEFAULT_TARGET_CHANNELS)
    parser.add_argument("--center-frequency-mhz", type=float)
    parser.add_argument("--expected-prf-hz", type=float)
    parser.add_argument("--sound-speed-m-s", type=float)
    parser.add_argument("--skip-all-angle-duplicate-check", action="store_true")
    args = parser.parse_args()

    capture_dir = args.capture_dir.resolve()
    if not capture_dir.is_dir():
        raise RuntimeError(f"capture directory does not exist: {capture_dir}")
    files = sorted(capture_dir.glob("*.bin"), key=lambda path: (angle_from_name(path) or 0.0, path.name))
    if not files:
        raise RuntimeError(f"no raw BIN files found in {capture_dir}")

    manifest_path, manifest = load_manifest(capture_dir)
    manifest_args = manifest.get("arguments") or {}
    array = manifest.get("array") or {}
    configured_slots = args.rx_channels or manifest_args.get("rx_channels") or array.get("rx_hsdc_slots_1_based")
    if configured_slots is None:
        configured_slots = list(range(9, 17))
    configured_slots = [int(value) for value in configured_slots]
    if len(configured_slots) != len(set(configured_slots)) or any(
        value < 1 or value > CHANNELS_IN_FILE for value in configured_slots
    ):
        raise RuntimeError(f"invalid configured HSDC slots: {configured_slots}")

    center_mhz = args.center_frequency_mhz
    if center_mhz is None:
        center_mhz = finite_float(manifest_args.get("center_frequency_mhz"), 1.5)
    center_hz = center_mhz * 1e6
    low_hz, high_hz = max(0.25e6, center_hz * 0.60), min(FS_HZ * 0.45, center_hz * 1.40)
    sound_speed = args.sound_speed_m_s or finite_float(manifest_args.get("sound_speed_m_s"), DEFAULT_SOUND_SPEED_M_S)
    expected_prf = args.expected_prf_hz or finite_float(manifest_args.get("expected_prf_hz"), 1000.0)
    if expected_prf <= 0.0:
        expected_prf = 1000.0

    analysis_file = choose_analysis_file(files, args.analysis_angle)
    data = np.memmap(analysis_file, dtype="<u2", mode="r").reshape(-1, CHANNELS_IN_FILE)
    baseline = np.median(data[::256, :], axis=0).astype(np.float32)
    rx_indices = [slot - 1 for slot in configured_slots]
    markers, measured_prf, event_diagnostics = detect_events_validated(
        data, rx_indices, baseline, expected_prf_hz=expected_prf
    )
    if not markers:
        raise RuntimeError(
            "no validated PRF events found; inspect trigger/PRF and use a capture containing repeated emissions"
        )

    raw_events: list[np.ndarray] = []
    rail_events: list[np.ndarray] = []
    filtered_events: list[np.ndarray] = []
    quiet_events: list[np.ndarray] = []
    valid_markers: list[int] = []
    for marker in markers:
        if marker + WINDOW_SAMPLES > data.shape[0]:
            continue
        raw_codes = np.asarray(data[marker : marker + WINDOW_SAMPLES, rx_indices])
        rail_events.append((raw_codes == 0) | (raw_codes == 65535))
        raw = raw_codes.astype(np.float32)
        raw -= baseline[rx_indices]
        raw -= np.mean(raw[:64, :], axis=0, keepdims=True)
        raw_events.append(raw)
        filtered_events.append(fft_bandpass(raw, low_hz, high_hz))
        quiet_start = marker + 50_000
        quiet_stop = quiet_start + WINDOW_SAMPLES
        if quiet_stop <= data.shape[0]:
            quiet = data[quiet_start:quiet_stop, rx_indices].astype(np.float32)
            quiet -= baseline[rx_indices]
            quiet -= np.mean(quiet, axis=0, keepdims=True)
            quiet_events.append(fft_bandpass(quiet, low_hz, high_hz))
        valid_markers.append(marker)
    if not filtered_events or not quiet_events:
        raise RuntimeError("capture does not contain complete echo and quiet-noise windows")

    raw_stack = np.stack(raw_events, axis=0)
    rail_stack = np.stack(rail_events, axis=0)
    filtered_stack = np.stack(filtered_events, axis=0)
    quiet_stack = np.stack(quiet_events, axis=0)
    filtered_residual_stack = filtered_stack - np.median(filtered_stack, axis=2, keepdims=True)
    quiet_residual_stack = quiet_stack - np.median(quiet_stack, axis=2, keepdims=True)
    windows = {
        "4_42mm": depth_slice(4.0, 42.0, sound_speed),
        "shallow_4_8mm": depth_slice(4.0, 8.0, sound_speed),
        "internal_14_22mm": depth_slice(14.0, 22.0, sound_speed),
        "deep_34_42mm": depth_slice(34.0, 42.0, sound_speed),
    }
    consistency = event_consistency(filtered_stack, windows["4_42mm"])
    noise_power = np.mean(quiet_stack.astype(np.float64) ** 2, axis=(0, 1))
    residual_noise_power = np.mean(
        quiet_residual_stack.astype(np.float64) ** 2, axis=(0, 1)
    )
    metrics: dict[int, dict[str, Any]] = {}
    for position, slot in enumerate(configured_slots):
        record: dict[str, Any] = {
            "slot": slot,
            "baseline_code": json_number(baseline[slot - 1]),
            "noise_rms_codes": json_number(math.sqrt(float(noise_power[position]))),
            "event_consistency_median_corr": json_number(consistency[position]),
            "rail_fraction": json_number(float(np.mean(rail_stack[:, :, position]))),
        }
        for name, window in windows.items():
            power = float(np.mean(filtered_stack[:, window, position].astype(np.float64) ** 2))
            record[f"snr_{name}_db"] = json_number(noise_subtracted_snr_db(power, float(noise_power[position])))
            record[f"rms_{name}_codes"] = json_number(math.sqrt(power))
            residual_power = float(
                np.mean(filtered_residual_stack[:, window, position].astype(np.float64) ** 2)
            )
            record[f"common_mode_removed_snr_{name}_db"] = json_number(
                noise_subtracted_snr_db(residual_power, float(residual_noise_power[position]))
            )
        snr_score = finite_float(record.get("snr_4_42mm_db"), -60.0)
        consistency_score = finite_float(record.get("event_consistency_median_corr"), 0.0)
        rail_penalty = min(30.0, finite_float(record.get("rail_fraction"), 0.0) * 100_000.0)
        record["quality_score"] = json_number(snr_score + 8.0 * consistency_score - rail_penalty)
        metrics[slot] = record

    hashes = column_hashes(data)
    duplicate_groups = duplicate_groups_from_hashes(hashes)
    duplicate_pairs = [
        (group[0], member) for group in duplicate_groups for member in group[1:]
    ]
    persistence = (
        {}
        if args.skip_all_angle_duplicate_check
        else duplicate_persistence(files, duplicate_pairs)
    )

    echo_window = windows["4_42mm"]
    concatenated = np.concatenate(
        [event[echo_window, :] for event in filtered_events], axis=0
    )[::4, :].astype(np.float64)
    raw_corr = safe_corrcoef(concatenated)
    common_removed = concatenated - np.median(concatenated, axis=1, keepdims=True)
    residual_corr = safe_corrcoef(common_removed)
    centered = concatenated - np.mean(concatenated, axis=0, keepdims=True)
    singular = np.linalg.svd(centered, compute_uv=False)
    singular_energy = singular**2 / max(float(np.sum(singular**2)), 1e-12)
    cumulative = np.cumsum(singular_energy)
    effective_rank_95 = int(np.searchsorted(cumulative, 0.95) + 1)
    effective_rank_99 = int(np.searchsorted(cumulative, 0.99) + 1)

    selected, excluded, reasons = build_mask(
        configured_slots, duplicate_groups, metrics, max(1, args.target_channels)
    )
    output_dir = capture_dir / "analysis" / "channel_qa"
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "schema_version": 1,
        "capture_directory": str(capture_dir),
        "analysis_file": analysis_file.name,
        "manifest_file": manifest_path.name if manifest_path.exists() else None,
        "configured_hsdc_slots_1_based": configured_slots,
        "selected_independent_slots_1_based": selected,
        "masked_slots_1_based": excluded,
        "frequency_mhz": center_mhz,
        "qa_band_mhz": [low_hz / 1e6, high_hz / 1e6],
        "expected_prf_hz": expected_prf,
        "measured_prf_hz": json_number(measured_prf),
        "validated_event_count": len(valid_markers),
        "event_diagnostics": event_diagnostics,
        "bit_exact_duplicate_groups_all_16_slots": duplicate_groups,
        "duplicate_persistence_across_bin_files": persistence,
        "raw_echo_correlation_abs_ge_0p95_pairs": [
            [configured_slots[left], configured_slots[right], round(float(raw_corr[left, right]), 6)]
            for left in range(len(configured_slots))
            for right in range(left + 1, len(configured_slots))
            if abs(raw_corr[left, right]) >= 0.95
        ],
        "common_mode_removed_correlation_abs_ge_0p95_pairs": [
            [configured_slots[left], configured_slots[right], round(float(residual_corr[left, right]), 6)]
            for left in range(len(configured_slots))
            for right in range(left + 1, len(configured_slots))
            if abs(residual_corr[left, right]) >= 0.95
        ],
        "singular_value_energy_fraction": [round(float(value), 8) for value in singular_energy],
        "first_singular_value_energy_fraction": round(float(singular_energy[0]), 8),
        "effective_rank_95_percent": effective_rank_95,
        "effective_rank_99_percent": effective_rank_99,
        "important_interpretation": [
            "Bit-exact duplicates are deterministic digital aliases; masking removes duplicate columns but does not repair the JESD/INI mapping.",
            "High raw correlation alone is not proof of a digital duplicate; transmit feedthrough and planar reflectors create a strong common mode.",
            "The compact six-channel package is diagnostic only. It cannot restore lateral information missing at acquisition.",
            "Echo-window SNR measures band energy above late electronic noise and can include reverberation; it is not target-specific image SNR.",
            "Common-mode removal is a diagnostic for shared energy, not a calibrated target-SNR estimator; interpret its SNR values only with the correlation and rank results.",
        ],
        "channels": [metrics[slot] | {"selection_notes": reasons[slot]} for slot in configured_slots],
    }
    mask = {
        "configured_hsdc_slots_1_based": configured_slots,
        "selected_hsdc_slots_1_based": selected,
        "excluded_hsdc_slots_1_based": excluded,
        "duplicate_policy": "retain one representative from each bit-exact group; rank only remaining independent groups",
        "selection_reasons": {str(slot): reasons[slot] for slot in configured_slots},
        "reconstruction_arguments": [
            "--duplicate-policy",
            "manual",
            "--das-rx-channels",
            ",".join(str(slot) for slot in selected),
        ],
    }
    write_json(output_dir / "channel_health.json", report)
    write_json(output_dir / "channel_mask.json", mask)

    csv_fields = [
        "slot", "baseline_code", "noise_rms_codes", "snr_4_42mm_db",
        "snr_shallow_4_8mm_db", "snr_internal_14_22mm_db", "snr_deep_34_42mm_db",
        "common_mode_removed_snr_4_42mm_db",
        "common_mode_removed_snr_internal_14_22mm_db",
        "common_mode_removed_snr_deep_34_42mm_db",
        "event_consistency_median_corr", "rail_fraction", "quality_score", "selected", "notes",
    ]
    with (output_dir / "channel_health.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for slot in configured_slots:
            row = {field: metrics[slot].get(field) for field in csv_fields}
            row["selected"] = slot in selected
            row["notes"] = "; ".join(reasons[slot])
            writer.writerow(row)

    plot_report(
        output_dir / "channel_health.png",
        configured_slots,
        metrics,
        raw_corr,
        residual_corr,
        singular_energy,
        selected,
    )

    selected_positions = [configured_slots.index(slot) for slot in selected]
    compact_events = raw_stack[:, :, selected_positions].astype(np.float32)
    np.savez_compressed(
        output_dir / "six_channel_event_cutouts.npz",
        event_waveforms_codes=compact_events,
        selected_hsdc_slots_1_based=np.asarray(selected, dtype=np.int16),
        event_markers=np.asarray(valid_markers, dtype=np.int64),
        sample_rate_hz=np.asarray([FS_HZ], dtype=np.float64),
        center_frequency_hz=np.asarray([center_hz], dtype=np.float64),
        baseline_codes=np.asarray([baseline[slot - 1] for slot in selected], dtype=np.float32),
    )

    reconstruction_command = (
        f'python reconstruct_ultrasound.py --capture-dir "{capture_dir}" '
        f'--duplicate-policy manual --das-rx-channels {",".join(str(slot) for slot in selected)}\n'
    )
    (output_dir / "reconstruct_selected_channels.txt").write_text(
        reconstruction_command, encoding="utf-8"
    )
    source_files = [
        output_dir / "channel_health.json",
        output_dir / "channel_mask.json",
        output_dir / "channel_health.csv",
        output_dir / "channel_health.png",
        output_dir / "six_channel_event_cutouts.npz",
        output_dir / "reconstruct_selected_channels.txt",
    ]
    for optional in (
        manifest_path,
        capture_dir / "run.log",
        capture_dir / "TX7316_verified_cfg_index.json",
    ):
        if optional.exists():
            source_files.append(optional)
    source_files.extend(sorted(capture_dir.glob("TX7316_*verified.cfg")))
    package_path = output_dir / "channel_baseline_6ch.zip"
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in source_files:
            archive.write(source, arcname=source.name)

    print(f"Analysis file: {analysis_file.name}")
    print(f"Validated PRF events: {len(valid_markers)}; measured PRF={measured_prf:.6f} Hz")
    print(f"Bit-exact duplicate groups: {duplicate_groups or 'none'}")
    print(f"First singular component energy: {singular_energy[0] * 100.0:.3f}%")
    print(f"Effective rank: {effective_rank_95} at 95%, {effective_rank_99} at 99%")
    print(f"Selected HSDC slots: {selected}; masked: {excluded}")
    print(f"Report: {output_dir / 'channel_health.json'}")
    print(f"Compact package: {package_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
