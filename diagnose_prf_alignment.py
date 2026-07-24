"""Read-only diagnostic for per-PRF fast-time alignment in one HSDC BIN."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import numpy as np


def load_reconstruction_module(script: Path):
    spec = importlib.util.spec_from_file_location("reconstruct_ultrasound", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def best_lag(reference: np.ndarray, candidate: np.ndarray, max_lag: int) -> tuple[int, float]:
    reference = reference.astype(np.float64) - float(np.mean(reference))
    candidate = candidate.astype(np.float64) - float(np.mean(candidate))
    best = (0, -1.0)
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            left, right = reference[-lag:], candidate[:lag]
        elif lag > 0:
            left, right = reference[:-lag], candidate[lag:]
        else:
            left, right = reference, candidate
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        correlation = float(np.dot(left, right) / denominator) if denominator else -1.0
        if correlation > best[1]:
            best = (lag, correlation)
    return best


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bin_file", type=Path)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--rx", default="9,10,11,12,13,14")
    parser.add_argument("--prf", type=float, default=1000.0)
    args = parser.parse_args()

    reconstruction = load_reconstruction_module(args.script)
    rx = [int(value) - 1 for value in args.rx.split(",")]
    data = np.memmap(args.bin_file, dtype="<u2", mode="r").reshape(-1, 16)
    baseline = np.median(data[::256, :], axis=0).astype(np.float32)
    markers, measured_prf, diagnostics = reconstruction.detect_events_validated(
        data, rx, baseline, expected_prf_hz=args.prf
    )
    signal = data[:, rx].astype(np.float32) - baseline[rx]
    score = np.max(np.abs(signal), axis=1)
    if len(markers) >= 2:
        # Infer skipped ordinals against the nominal period, then fit one line
        # through the accepted markers.  This avoids treating a five-period
        # rejection gap as a single PRF interval.
        nominal_period = reconstruction.FS_HZ / args.prf
        accepted_ordinals = np.rint((np.asarray(markers) - markers[0]) / nominal_period)
        period, first_grid = np.polyfit(accepted_ordinals, np.asarray(markers), 1)
    else:
        period, first_grid = reconstruction.FS_HZ / args.prf, float(markers[0])

    # Complete the PRF grid between the first and last accepted marker. This is
    # diagnostic only: it shows whether rejected emissions still contain RF.
    first = float(first_grid)
    grid = []
    ordinal = 0
    while first + ordinal * period + reconstruction.WINDOW_SAMPLES < data.shape[0]:
        predicted = int(round(first + ordinal * period))
        lo, hi = max(0, predicted - 512), min(score.size, predicted + 513)
        marker = lo + int(np.argmax(score[lo:hi]))
        grid.append(marker)
        ordinal += 1

    profiles = []
    early_profiles = []
    direct_centers = []
    for marker in grid:
        segment = data[marker : marker + reconstruction.WINDOW_SAMPLES, rx].astype(np.float32)
        segment -= baseline[rx]
        segment -= np.mean(segment[:64, :], axis=0, keepdims=True)
        analytic = reconstruction.analytic_bandpass(segment)
        early_profile = np.percentile(np.abs(analytic), 90.0, axis=1)
        direct_centers.append(400 + int(np.argmax(early_profile[400:900])))
        early_profiles.append(early_profile)
        scale = np.maximum(np.percentile(np.abs(analytic[250:6500, :]), 99.5, axis=0), 1.0)
        profiles.append(np.median(np.abs(analytic) / scale[None, :], axis=1))

    print(f"samples={data.shape[0]} measured_prf_hz={measured_prf:.6f} fitted_period={period:.6f}")
    print(f"accepted={markers}")
    print(f"validation={diagnostics}")
    print("grid event marker residual peak_score direct_center early_lag profile_lag_samples profile_lag_mm correlation broad_peak_depths_mm")
    reference = profiles[0][800:7000]
    early_reference = early_profiles[0][:1800]
    for index, (marker, profile, early_profile, direct_center) in enumerate(
        zip(grid, profiles, early_profiles, direct_centers)
    ):
        predicted = int(round(first + index * period))
        lag, correlation = best_lag(reference, profile[800:7000], 900)
        early_lag, early_correlation = best_lag(early_reference, early_profile[:1800], 900)
        depth_shift_mm = lag / reconstruction.FS_HZ * reconstruction.C_M_S * 0.5 * 1e3
        smooth_profile = reconstruction.moving_average(profile, 241)
        candidates = np.argsort(smooth_profile[1500:7000])[::-1] + 1500
        broad_peaks = []
        for candidate in candidates:
            if all(abs(int(candidate) - existing) > 900 for existing in broad_peaks):
                broad_peaks.append(int(candidate))
            if len(broad_peaks) == 3:
                break
        broad_peaks.sort()
        broad_depths = [
            (position - 572.0) / reconstruction.FS_HZ * reconstruction.C_M_S * 0.5 * 1e3
            for position in broad_peaks
        ]
        accepted = "yes" if any(abs(marker - value) <= 8 for value in markers) else "no"
        print(
            f"{index:02d} {accepted:>3} {marker:8d} {marker-predicted:+5d} "
            f"{score[marker]:9.1f} {direct_center:5d} {early_lag:+5d}/{early_correlation:.3f} "
            f"{lag:+6d} {depth_shift_mm:+8.3f} {correlation:.5f} "
            f"{','.join('%.2f' % depth for depth in broad_depths)}"
        )


if __name__ == "__main__":
    main()
