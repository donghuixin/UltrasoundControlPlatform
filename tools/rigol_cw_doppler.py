#!/usr/bin/env python3
"""Rigol RG01 oscilloscope CW Doppler analyzer.

The intended acquisition is:
  CH1..CH3: independent receive elements
  CH4:      an isolated/attenuated copy of the actual TX waveform

The input BIN is opened read-only.  Every run creates a new timestamped output
directory; existing files are never overwritten.

This program reports Doppler frequency by default.  Velocity is emitted only
when an explicit calibration slope or complete bistatic geometry is supplied.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import struct
import sys
from pathlib import Path

import numpy as np

try:
    from scipy import signal
except ImportError as exc:  # pragma: no cover - environment diagnostic
    raise SystemExit("scipy is required: pip install scipy") from exc

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - environment diagnostic
    raise SystemExit("matplotlib is required: pip install matplotlib") from exc


RIGOL_MAGIC = b"RG01"
CHANNEL_DATA0 = 164
CHANNEL_TRAILER_BYTES = 152


def csv_ints(value: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated channel numbers") from exc
    if not values:
        raise argparse.ArgumentTypeError("at least one channel is required")
    return values


def csv_floats(value: str) -> list[float]:
    try:
        values = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated numbers") from exc
    if not values:
        raise argparse.ArgumentTypeError("at least one number is required")
    return values


def read_rigol_header(path: Path) -> dict:
    with path.open("rb") as handle:
        header = handle.read(CHANNEL_DATA0)
    if len(header) < CHANNEL_DATA0 or header[:4] != RIGOL_MAGIC:
        raise ValueError(f"{path} is not a supported Rigol RG01 BIN file")

    channels = struct.unpack_from("<I", header, 8)[0]
    header_size = struct.unpack_from("<I", header, 12)[0]
    points = struct.unpack_from("<Q", header, 24)[0]
    duration_s = float(struct.unpack_from("<f", header, 32)[0])
    dt_s = float(struct.unpack_from("<d", header, 44)[0])
    if channels < 1 or channels > 8 or points < 1 or dt_s <= 0:
        raise ValueError("invalid RG01 header values")

    # Rigol inserts the 152-byte channel metadata/separator between channel
    # sample arrays; there is no extra separator after the final channel.
    expected_minimum = (
        CHANNEL_DATA0
        + channels * points * 4
        + max(channels - 1, 0) * CHANNEL_TRAILER_BYTES
    )
    actual_bytes = path.stat().st_size
    if actual_bytes < expected_minimum:
        raise ValueError(
            f"truncated BIN: expected at least {expected_minimum} bytes, got {actual_bytes}"
        )
    return {
        "magic": header[:4].decode("ascii"),
        "channels": int(channels),
        "header_size_field": int(header_size),
        "points_per_channel": int(points),
        "duration_s_header": duration_s,
        "sample_interval_s": dt_s,
        "sample_rate_hz": 1.0 / dt_s,
        "file_bytes": int(actual_bytes),
    }


def channel_memmap(path: Path, header: dict, channel_1based: int) -> np.memmap:
    if channel_1based < 1 or channel_1based > header["channels"]:
        raise ValueError(
            f"channel {channel_1based} is outside recorded range 1..{header['channels']}"
        )
    points = header["points_per_channel"]
    offset = CHANNEL_DATA0 + (channel_1based - 1) * (points * 4 + CHANNEL_TRAILER_BYTES)
    return np.memmap(path, dtype="<f4", mode="r", offset=offset, shape=(points,))


def robust_rms(values: np.ndarray) -> float:
    values = np.asarray(values)
    if values.size == 0:
        return 0.0
    centered = values - np.median(values)
    return float(np.sqrt(np.mean(np.abs(centered) ** 2)))


def estimate_carrier(
    samples: np.ndarray,
    fs_hz: float,
    fmin_hz: float,
    fmax_hz: float,
) -> tuple[float, float]:
    count = min(samples.size, 2**20)
    x = np.asarray(samples[:count], dtype=np.float64)
    x -= np.mean(x)
    if not np.any(np.isfinite(x)) or np.std(x) == 0:
        raise ValueError("carrier-estimation channel is constant")
    window = signal.windows.hann(count, sym=False)
    spectrum = np.fft.rfft(x * window)
    freqs = np.fft.rfftfreq(count, 1.0 / fs_hz)
    mask = (freqs >= fmin_hz) & (freqs <= min(fmax_hz, 0.49 * fs_hz))
    if not np.any(mask):
        raise ValueError("carrier search band is outside the sampled bandwidth")
    indices = np.flatnonzero(mask)
    peak_index = int(indices[np.argmax(np.abs(spectrum[mask]))])

    # Three-bin parabolic interpolation for a less quantized carrier estimate.
    correction = 0.0
    if 0 < peak_index < spectrum.size - 1:
        y0, y1, y2 = np.log(np.maximum(np.abs(spectrum[peak_index - 1 : peak_index + 2]), 1e-30))
        denom = y0 - 2.0 * y1 + y2
        if abs(denom) > 1e-12:
            correction = float(0.5 * (y0 - y2) / denom)
    carrier = (peak_index + correction) * fs_hz / count

    inband_power = float(np.sum(np.abs(spectrum[mask]) ** 2))
    peak_power = float(np.abs(spectrum[peak_index]) ** 2)
    peak_fraction = peak_power / max(inband_power, 1e-30)
    return float(carrier), float(peak_fraction)


def stream_demodulate(
    raw: np.ndarray,
    fs_hz: float,
    carrier_hz: float,
    decimation: int,
    lowpass_hz: float,
    points_to_process: int,
    chunk_samples: int = 2**20,
) -> np.ndarray:
    if decimation < 1:
        raise ValueError("decimation must be at least 1")
    normalized = lowpass_hz / (0.5 * fs_hz)
    if not 0 < normalized < 1:
        raise ValueError("invalid I/Q low-pass cutoff")
    sos = signal.butter(6, normalized, btype="lowpass", output="sos")
    zi = np.zeros((sos.shape[0], 2), dtype=np.complex128)
    blocks: list[np.ndarray] = []

    absolute = 0
    while absolute < points_to_process:
        stop = min(points_to_process, absolute + chunk_samples)
        x = np.asarray(raw[absolute:stop], dtype=np.float64)
        x -= np.mean(x)
        n = np.arange(absolute, stop, dtype=np.float64)
        mixed = x * np.exp((-2j * np.pi * carrier_hz / fs_hz) * n)
        filtered, zi = signal.sosfilt(sos, mixed, zi=zi)
        first = (-absolute) % decimation
        blocks.append(np.asarray(filtered[first::decimation], dtype=np.complex64))
        absolute = stop
    return np.concatenate(blocks) if blocks else np.empty(0, dtype=np.complex64)


def highpass_complex(iq: np.ndarray, fs_hz: float, wall_hz: float) -> np.ndarray:
    centered = np.asarray(iq, dtype=np.complex128) - np.median(iq.real) - 1j * np.median(iq.imag)
    if wall_hz <= 0:
        return centered.astype(np.complex64)
    if wall_hz >= 0.45 * fs_hz:
        raise ValueError("wall filter must be below 45% of I/Q sample rate")
    sos = signal.butter(4, wall_hz / (0.5 * fs_hz), btype="highpass", output="sos")
    pad_needed = 3 * (2 * sos.shape[0] + 1)
    if centered.size <= pad_needed:
        return signal.sosfilt(sos, centered).astype(np.complex64)
    return signal.sosfiltfilt(sos, centered).astype(np.complex64)


def common_mode_metrics(iq_matrix: np.ndarray) -> dict:
    if iq_matrix.ndim != 2 or iq_matrix.shape[1] < 2:
        return {"rank1_variance_fraction": None, "median_pairwise_coherence": None}
    centered = iq_matrix - np.mean(iq_matrix, axis=0, keepdims=True)
    covariance = centered.conj().T @ centered
    eigenvalues = np.maximum(np.linalg.eigvalsh(covariance).real, 0.0)
    rank1 = float(eigenvalues[-1] / max(np.sum(eigenvalues), 1e-30))
    coherences = []
    for left in range(centered.shape[1]):
        for right in range(left + 1, centered.shape[1]):
            numerator = abs(np.vdot(centered[:, left], centered[:, right]))
            denominator = math.sqrt(
                float(np.vdot(centered[:, left], centered[:, left]).real)
                * float(np.vdot(centered[:, right], centered[:, right]).real)
            )
            coherences.append(float(numerator / max(denominator, 1e-30)))
    return {
        "rank1_variance_fraction": rank1,
        "median_pairwise_coherence": float(np.median(coherences)),
    }


def spectrogram(iq: np.ndarray, fs_hz: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nperseg = min(2048, max(256, 2 ** int(np.floor(np.log2(max(iq.size // 8, 256))))))
    noverlap = int(0.75 * nperseg)
    f_hz, t_s, z = signal.stft(
        iq,
        fs=fs_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        detrend=False,
        return_onesided=False,
        boundary=None,
        padded=False,
    )
    order = np.argsort(f_hz)
    return f_hz[order], t_s, np.abs(z[order, :]) ** 2


def candidate_heart_rate(power: np.ndarray, time_s: np.ndarray) -> tuple[float | None, float | None]:
    if power.size < 8 or time_s.size < 8 or time_s[-1] - time_s[0] < 2.0:
        return None, None
    envelope = np.sum(power, axis=0)
    envelope -= np.mean(envelope)
    fs_env = 1.0 / np.median(np.diff(time_s))
    f, p = signal.periodogram(envelope, fs=fs_env, window="hann")
    mask = (f >= 0.6) & (f <= 3.0)
    if not np.any(mask) or np.max(p[mask]) <= 0:
        return None, None
    peak_local = int(np.argmax(p[mask]))
    peak_index = int(np.flatnonzero(mask)[peak_local])
    confidence = float(p[peak_index] / max(np.sum(p[mask]), 1e-30))
    return float(60.0 * f[peak_index]), confidence


def signed_frequency_metrics(f_hz: np.ndarray, power: np.ndarray, wall_hz: float) -> dict:
    total_by_f = np.mean(power, axis=1)
    valid = np.abs(f_hz) >= max(wall_hz, 1.0)
    positive = valid & (f_hz > 0)
    negative = valid & (f_hz < 0)
    p_pos = float(np.sum(total_by_f[positive]))
    p_neg = float(np.sum(total_by_f[negative]))
    directionality = (p_pos - p_neg) / max(p_pos + p_neg, 1e-30)

    valid_freq = f_hz[valid]
    valid_power = total_by_f[valid]
    peak_hz = None
    centroid_hz = None
    if valid_freq.size and np.sum(valid_power) > 0:
        peak_hz = float(valid_freq[int(np.argmax(valid_power))])
        centroid_hz = float(np.sum(valid_freq * valid_power) / np.sum(valid_power))
    return {
        "positive_power": p_pos,
        "negative_power": p_neg,
        "directionality": float(directionality),
        "signed_peak_hz": peak_hz,
        "signed_centroid_hz": centroid_hz,
    }


def make_output_directory(root: Path, input_path: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = root / f"{stamp}_{input_path.stem}"
    candidate = base
    counter = 1
    while candidate.exists():
        candidate = root / f"{base.name}_{counter:02d}"
        counter += 1
    candidate.mkdir()
    return candidate


def velocity_scale_for_channel(args: argparse.Namespace, channel_index: int) -> tuple[float | None, str]:
    if args.calibration_hz_per_mps:
        values = args.calibration_hz_per_mps
        value = values[channel_index] if len(values) > 1 else values[0]
        if value == 0:
            raise ValueError("calibration slope cannot be zero")
        return 1.0 / value, "known-flow calibration"

    if args.tx_angle_deg is not None and args.rx_angles_deg is not None and args.flow_angle_deg is not None:
        if len(args.rx_angles_deg) != len(args.rx_channels):
            raise ValueError("--rx-angles-deg must have one angle per RX channel")
        tx = math.radians(args.tx_angle_deg - args.flow_angle_deg)
        rx = math.radians(args.rx_angles_deg[channel_index] - args.flow_angle_deg)
        hz_per_mps = args.carrier_for_velocity_hz / args.sound_speed_mps * (
            math.cos(tx) + math.cos(rx)
        )
        if abs(hz_per_mps) < 1e-12:
            raise ValueError("bistatic geometry is singular for the supplied angles")
        return 1.0 / hz_per_mps, "declared bistatic geometry"
    return None, "not calibrated"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Rigol RG01 CW Doppler analysis with optional TX phase reference"
    )
    parser.add_argument("--input", required=True, type=Path, help="Rigol RG01 BIN file")
    parser.add_argument("--out-root", required=True, type=Path, help="parent for new result directory")
    parser.add_argument("--rx-channels", type=csv_ints, default=[1, 2, 3])
    parser.add_argument("--tx-reference-channel", type=int, default=4)
    parser.add_argument("--no-tx-reference", action="store_true")
    parser.add_argument("--carrier-hz", type=float, help="fixed demodulation frequency")
    parser.add_argument("--carrier-search-min-hz", type=float, default=0.5e6)
    parser.add_argument("--carrier-search-max-hz", type=float, default=8.0e6)
    parser.add_argument("--target-iq-rate", type=float, default=25_000.0)
    parser.add_argument("--baseband-lowpass-hz", type=float, default=8_000.0)
    parser.add_argument("--wall-hz", type=float, default=100.0)
    parser.add_argument("--max-seconds", type=float, help="analyze only the first N seconds")
    parser.add_argument("--label", default="")
    parser.add_argument("--calibration-hz-per-mps", type=csv_floats)
    parser.add_argument("--tx-angle-deg", type=float)
    parser.add_argument("--rx-angles-deg", type=csv_floats)
    parser.add_argument("--flow-angle-deg", type=float)
    parser.add_argument(
        "--carrier-for-velocity-hz",
        type=float,
        help="carrier used by the velocity formula; defaults to the measured/demodulated carrier",
    )
    parser.add_argument("--sound-speed-mps", type=float, default=1540.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if args.target_iq_rate <= 0 or args.baseband_lowpass_hz <= 0:
        raise ValueError("I/Q rate and low-pass cutoff must be positive")

    header = read_rigol_header(input_path)
    for channel in args.rx_channels:
        if channel > header["channels"]:
            raise ValueError(f"RX channel {channel} was not recorded")
    tx_channel = None if args.no_tx_reference else args.tx_reference_channel
    if tx_channel is not None and tx_channel > header["channels"]:
        print(
            f"WARNING: requested TX reference CH{tx_channel}, but file has only "
            f"{header['channels']} channels; continuing without phase reference.",
            file=sys.stderr,
        )
        tx_channel = None
    if tx_channel in args.rx_channels:
        raise ValueError("TX reference channel cannot also be an RX channel")

    fs_hz = header["sample_rate_hz"]
    total_points = header["points_per_channel"]
    points_to_process = total_points
    if args.max_seconds is not None:
        if args.max_seconds <= 0:
            raise ValueError("--max-seconds must be positive")
        points_to_process = min(total_points, int(round(args.max_seconds * fs_hz)))

    source_channel = tx_channel if tx_channel is not None else args.rx_channels[0]
    source_raw = channel_memmap(input_path, header, source_channel)
    if args.carrier_hz is None:
        carrier_hz, carrier_peak_fraction = estimate_carrier(
            source_raw,
            fs_hz,
            args.carrier_search_min_hz,
            args.carrier_search_max_hz,
        )
    else:
        carrier_hz = float(args.carrier_hz)
        _, carrier_peak_fraction = estimate_carrier(
            source_raw,
            fs_hz,
            max(args.carrier_search_min_hz, carrier_hz * 0.8),
            min(args.carrier_search_max_hz, carrier_hz * 1.2),
        )
    if args.carrier_for_velocity_hz is None:
        args.carrier_for_velocity_hz = carrier_hz

    decimation = max(1, int(round(fs_hz / args.target_iq_rate)))
    iq_rate_hz = fs_hz / decimation
    lowpass_hz = min(args.baseband_lowpass_hz, 0.40 * iq_rate_hz)
    if lowpass_hz <= args.wall_hz:
        raise ValueError("baseband low-pass must be higher than wall-filter cutoff")

    tx_iq = None
    tx_reference_rms = None
    if tx_channel is not None:
        tx_reference_rms = robust_rms(np.asarray(source_raw[: min(points_to_process, 2**20)]))
        tx_iq = stream_demodulate(
            source_raw,
            fs_hz,
            carrier_hz,
            decimation,
            lowpass_hz,
            points_to_process,
        )

    rx_iq_unfiltered = []
    raw_rms = []
    for channel in args.rx_channels:
        raw = channel_memmap(input_path, header, channel)
        raw_rms.append(robust_rms(np.asarray(raw[: min(points_to_process, 2**20)])))
        iq = stream_demodulate(
            raw,
            fs_hz,
            carrier_hz,
            decimation,
            lowpass_hz,
            points_to_process,
        )
        if tx_iq is not None:
            count = min(iq.size, tx_iq.size)
            iq = iq[:count]
            ref = tx_iq[:count]
            floor = max(float(np.median(np.abs(ref))) * 1e-6, 1e-18)
            iq = iq * np.conj(ref / np.maximum(np.abs(ref), floor))
        rx_iq_unfiltered.append(np.asarray(iq, dtype=np.complex64))

    common_count = min(item.size for item in rx_iq_unfiltered)
    rx_iq_unfiltered = [item[:common_count] for item in rx_iq_unfiltered]
    # Discard the short IIR startup interval.  Keeping it would create a bright
    # false broadband stripe at t=0 in otherwise steady CW recordings.
    settling_count = min(int(round(0.020 * iq_rate_hz)), common_count // 10)
    if settling_count:
        rx_iq_unfiltered = [item[settling_count:] for item in rx_iq_unfiltered]
        if tx_iq is not None:
            tx_iq = tx_iq[settling_count : settling_count + rx_iq_unfiltered[0].size]
    rx_iq = [highpass_complex(item, iq_rate_hz, args.wall_hz) for item in rx_iq_unfiltered]
    matrix = np.column_stack(rx_iq)
    common = common_mode_metrics(matrix)

    spectra = [spectrogram(item, iq_rate_hz) for item in rx_iq]
    f_hz, t_s, _ = spectra[0]
    combined_power = np.mean(np.stack([entry[2] for entry in spectra], axis=0), axis=0)
    signed = signed_frequency_metrics(f_hz, combined_power, args.wall_hz)
    heart_bpm, heart_confidence = candidate_heart_rate(combined_power, t_s)

    per_channel = []
    for index, (channel, entry) in enumerate(zip(args.rx_channels, spectra)):
        metrics = signed_frequency_metrics(entry[0], entry[2], args.wall_hz)
        scale, method = velocity_scale_for_channel(args, index)
        if scale is not None:
            metrics["signed_peak_mps"] = metrics["signed_peak_hz"] * scale
            metrics["signed_centroid_mps"] = metrics["signed_centroid_hz"] * scale
        metrics.update(
            {
                "channel": channel,
                "raw_rms": raw_rms[index],
                "velocity_method": method,
                "velocity_validated": bool(args.calibration_hz_per_mps),
            }
        )
        per_channel.append(metrics)

    output = make_output_directory(args.out_root.expanduser().resolve(), input_path)
    np.savez_compressed(
        output / "iq_downsampled.npz",
        iq_raw=np.column_stack(rx_iq_unfiltered),
        iq_wall_filtered=matrix,
        sample_rate_hz=np.asarray(iq_rate_hz),
        rx_channels=np.asarray(args.rx_channels),
        tx_reference_iq=np.asarray(tx_iq if tx_iq is not None else [], dtype=np.complex64),
    )

    warnings = []
    if tx_channel is None:
        warnings.append(
            "No recorded TX reference: source phase drift and Doppler sign are not fully controlled."
        )
    if common["rank1_variance_fraction"] is not None and common["rank1_variance_fraction"] > 0.9:
        warnings.append(
            "More than 90% of multichannel variance is rank-1/common; electrical feedthrough, "
            "probe motion, or common acoustic clutter may dominate. No blind PCA subtraction was applied."
        )
    if args.calibration_hz_per_mps is None:
        warnings.append(
            "Velocity is unvalidated unless a known-flow calibration is supplied; Doppler Hz are primary."
        )

    qa = {
        "carrier_hz": carrier_hz,
        "carrier_peak_fraction_in_search_band": carrier_peak_fraction,
        "scope_sample_rate_hz": fs_hz,
        "iq_sample_rate_hz": iq_rate_hz,
        "decimation": decimation,
        "processed_seconds": matrix.shape[0] / iq_rate_hz,
        "settling_discard_seconds": settling_count / iq_rate_hz,
        "tx_reference_channel": tx_channel,
        "tx_reference_rms": tx_reference_rms,
        "common_mode": common,
        "combined_doppler": signed,
        "candidate_heart_rate_bpm": heart_bpm,
        "candidate_heart_rate_confidence": heart_confidence,
        "per_channel": per_channel,
        "warnings": warnings,
    }
    manifest = {
        "tool": "rigol_cw_doppler.py",
        "created_local": dt.datetime.now().astimezone().isoformat(),
        "input": str(input_path),
        "input_stat": {
            "bytes": input_path.stat().st_size,
            "mtime_ns": input_path.stat().st_mtime_ns,
        },
        "header": header,
        "parameters": {
            "label": args.label,
            "rx_channels": args.rx_channels,
            "tx_reference_channel": tx_channel,
            "carrier_hz_requested": args.carrier_hz,
            "carrier_hz_used": carrier_hz,
            "target_iq_rate_hz": args.target_iq_rate,
            "iq_rate_hz_actual": iq_rate_hz,
            "baseband_lowpass_hz": lowpass_hz,
            "wall_hz": args.wall_hz,
            "max_seconds": args.max_seconds,
            "settling_discard_seconds": settling_count / iq_rate_hz,
            "calibration_hz_per_mps": args.calibration_hz_per_mps,
            "tx_angle_deg": args.tx_angle_deg,
            "rx_angles_deg": args.rx_angles_deg,
            "flow_angle_deg": args.flow_angle_deg,
            "sound_speed_mps": args.sound_speed_mps,
        },
        "outputs": ["iq_downsampled.npz", "qa.json", "doppler_spectrogram.png"],
    }

    (output / "qa.json").write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    max_plot_hz = min(10_000.0, 0.49 * iq_rate_hz)
    display = (f_hz >= -max_plot_hz) & (f_hz <= max_plot_hz)
    power_db = 10.0 * np.log10(np.maximum(combined_power[display], 1e-30))
    power_db -= np.max(power_db)

    figure, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    time_iq = np.arange(matrix.shape[0]) / iq_rate_hz
    axes[0].plot(time_iq, np.abs(matrix), linewidth=0.6)
    axes[0].set_title("Wall-filtered coherent I/Q magnitude (no blind PCA subtraction)")
    axes[0].set_xlabel("Time (s)")
    axes[0].set_ylabel("Magnitude")
    axes[0].legend([f"RX CH{channel}" for channel in args.rx_channels], loc="upper right")

    mesh = axes[1].pcolormesh(t_s, f_hz[display], power_db, shading="auto", cmap="magma", vmin=-60, vmax=0)
    axes[1].axhline(0, color="white", linewidth=0.5, alpha=0.7)
    axes[1].set_title("Mean RX Doppler spectrogram (relative dB)")
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("Signed Doppler frequency (Hz)")
    figure.colorbar(mesh, ax=axes[1], label="dB relative to peak")
    figure.savefig(output / "doppler_spectrogram.png", dpi=160)
    plt.close(figure)

    print(f"Created new result directory: {output}")
    print(f"Carrier used: {carrier_hz:.3f} Hz")
    print(f"I/Q rate: {iq_rate_hz:.3f} S/s (decimation {decimation})")
    print(f"Processed after startup discard: {matrix.shape[0] / iq_rate_hz:.3f} s")
    if heart_bpm is not None:
        print(f"Candidate cardiac modulation: {heart_bpm:.1f} bpm (not diagnostic)")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
