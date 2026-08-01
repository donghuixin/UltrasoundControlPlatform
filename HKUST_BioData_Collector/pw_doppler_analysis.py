"""Offline PW Doppler analysis for one gap-free slow-time record.

The current hardware path supplies an interleaved 16-column HSDC raw-RF BIN.
Future FPGA/AFE backends may instead place ``pw_doppler_input_iq.npz`` in the
capture directory with a complex ``iq`` array shaped ``(pulses, channels)``.

This module never concatenates separate HSDC captures.  A heart-cycle result is
reported only when one source record is long enough and its velocity envelope
contains a repeatable periodic component.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import ndimage, signal


CHANNELS_IN_RAW_FILE = 16
UINT16_MIDCODE = 32768.0


@dataclass(frozen=True)
class AnalysisConfig:
    sample_rate_hz: float
    prf_hz: float
    center_frequency_hz: float
    flow_angle_deg: float
    steering_angle_deg: float
    target_depth_mm: float
    gate_length_mm: float
    wall_filter_hz: float
    ensemble_pulses: int
    expected_heart_rate_bpm: float
    sound_speed_m_s: float = 1540.0
    range_zero_offset_us: float = 0.0

    def validate(self) -> None:
        if self.sample_rate_hz <= 0 or self.prf_hz <= 0:
            raise ValueError("Sample rate and PRF must be positive.")
        if not 0 < self.center_frequency_hz < self.sample_rate_hz / 2.0:
            raise ValueError("Center frequency must lie below the ADC Nyquist frequency.")
        if not 0 <= self.flow_angle_deg < 89.0:
            raise ValueError("Flow angle must be in the range 0 to <89 degrees.")
        if self.target_depth_mm <= 0 or self.gate_length_mm <= 0:
            raise ValueError("Gate depth and length must be positive.")
        if not 0 <= self.wall_filter_hz < self.prf_hz / 2.0:
            raise ValueError("Wall-filter cutoff must lie between 0 and PRF/2.")
        if self.ensemble_pulses < 16:
            raise ValueError("Doppler ensemble must contain at least 16 pulses.")
        if not 20 <= self.expected_heart_rate_bpm <= 240:
            raise ValueError("Expected heart rate must be between 20 and 240 BPM.")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _value(mapping: dict[str, Any], name: str, fallback: Any) -> Any:
    value = mapping.get(name, fallback)
    return fallback if value is None else value


def config_from_capture(capture_dir: Path) -> tuple[AnalysisConfig, dict[str, Any], dict[str, Any]]:
    manifest = read_json(capture_dir / "capture_manifest.json")
    plan = read_json(capture_dir / "doppler_session_plan.json")
    plan_config = plan.get("configuration", {})
    hsdc = manifest.get("hsdc", {})
    arguments = manifest.get("arguments", {})

    sample_rate_hz = float(_value(hsdc, "sample_rate_hz", 120_000_000.0))
    center_frequency_mhz = float(
        _value(plan_config, "center_frequency_mhz", arguments.get("center_frequency_mhz", 1.5))
    )
    prf_hz = float(
        _value(plan_config, "prf_hz", manifest.get("expected_prf_hz", 0.0))
    )
    if prf_hz <= 0:
        raise ValueError(
            "No expected PRF is recorded. Re-run from the PW Doppler page or add a verified PRF to doppler_session_plan.json."
        )

    config = AnalysisConfig(
        sample_rate_hz=sample_rate_hz,
        prf_hz=prf_hz,
        center_frequency_hz=center_frequency_mhz * 1e6,
        flow_angle_deg=float(_value(plan_config, "flow_angle_deg", 60.0)),
        steering_angle_deg=float(_value(plan_config, "steering_angle_deg", 0.0)),
        target_depth_mm=float(_value(plan_config, "target_depth_mm", 25.0)),
        gate_length_mm=float(_value(plan_config, "gate_length_mm", 2.0)),
        wall_filter_hz=float(_value(plan_config, "wall_filter_hz", 50.0)),
        ensemble_pulses=int(_value(plan_config, "ensemble_pulses", 128)),
        expected_heart_rate_bpm=float(
            _value(plan_config, "expected_heart_rate_bpm", 75.0)
        ),
        sound_speed_m_s=float(
            _value(plan_config, "sound_speed_m_s", arguments.get("sound_speed_m_s", 1540.0))
        ),
        range_zero_offset_us=float(_value(plan_config, "range_zero_offset_us", 0.0)),
    )
    config.validate()
    return config, manifest, plan


def select_raw_capture(capture_dir: Path, manifest: dict[str, Any], steering_angle_deg: float) -> Path:
    captures = manifest.get("captures", [])
    candidates: list[tuple[float, int, Path]] = []
    for item in captures:
        path = capture_dir / str(item.get("filename", ""))
        if not path.is_file():
            continue
        angle_error = abs(float(item.get("requested_angle_deg", 0.0)) - steering_angle_deg)
        candidates.append((angle_error, -int(path.stat().st_size), path))
    if not candidates:
        candidates = [(0.0, -int(path.stat().st_size), path) for path in capture_dir.glob("*.bin")]
    if not candidates:
        raise FileNotFoundError(f"No HSDC BIN file found in {capture_dir}")
    candidates.sort(key=lambda item: (item[0], item[1], item[2].name))
    return candidates[0][2]


def raw_memmap(path: Path) -> np.memmap:
    words = path.stat().st_size // 2
    if words <= 0 or words % CHANNELS_IN_RAW_FILE:
        raise ValueError(
            f"{path.name} is not a complete {CHANNELS_IN_RAW_FILE}-column uint16 HSDC file."
        )
    return np.memmap(path, dtype="<u2", mode="r").reshape(-1, CHANNELS_IN_RAW_FILE)


def estimate_baseline(data: np.ndarray, channel_indices: list[int]) -> np.ndarray:
    stride = max(1, data.shape[0] // 50_000)
    sampled = np.asarray(data[::stride, channel_indices], dtype=np.float32)
    return np.median(sampled, axis=0).astype(np.float32)


def amplitude_score(
    data: np.ndarray,
    channel_indices: list[int],
    baseline: np.ndarray,
    chunk_samples: int = 1_048_576,
) -> np.ndarray:
    score = np.empty(data.shape[0], dtype=np.float32)
    for start in range(0, data.shape[0], chunk_samples):
        stop = min(data.shape[0], start + chunk_samples)
        block = np.asarray(data[start:stop, channel_indices], dtype=np.float32)
        block -= baseline[None, :]
        score[start:stop] = np.max(np.abs(block), axis=1)
    return score


def detect_prf_events(
    score: np.ndarray,
    sample_rate_hz: float,
    expected_prf_hz: float,
    final_offset_samples: int,
) -> tuple[np.ndarray, float, dict[str, Any]]:
    smoothed = ndimage.uniform_filter1d(score, size=32, mode="nearest")
    center = float(np.median(smoothed))
    mad = float(np.median(np.abs(smoothed - center)))
    sigma = max(1.0, 1.4826 * mad)
    threshold = max(20.0, center + 8.0 * sigma, float(np.percentile(smoothed, 99.5)) * 0.35)
    nominal_period = sample_rate_hz / expected_prf_hz
    peaks, properties = signal.find_peaks(
        smoothed,
        height=threshold,
        distance=max(1, int(round(0.45 * nominal_period))),
    )
    if peaks.size < 2:
        raise RuntimeError("Fewer than two periodic TX markers were found in the raw block.")

    ordered = peaks[np.argsort(properties["peak_heights"])[::-1]]
    search_radius = int(min(4096, max(256, round(nominal_period * 0.02))))
    complete_start = 512
    complete_stop = score.size - max(512, final_offset_samples)
    best_markers: list[int] = []
    best_key = (-1, -1.0)
    for seed_value in ordered[: min(64, ordered.size)]:
        seed = int(seed_value)
        first_step = int(math.ceil((complete_start - seed) / nominal_period))
        last_step = int(math.floor((complete_stop - seed) / nominal_period))
        markers: list[int] = []
        strength = 0.0
        for step in range(first_step, last_step + 1):
            predicted = int(round(seed + step * nominal_period))
            lo = max(complete_start, predicted - search_radius)
            hi = min(complete_stop + 1, predicted + search_radius + 1)
            if hi <= lo:
                continue
            marker = lo + int(np.argmax(smoothed[lo:hi]))
            if smoothed[marker] < threshold:
                continue
            if not markers or marker != markers[-1]:
                markers.append(marker)
                strength += float(smoothed[marker])
        key = (len(markers), strength)
        if key > best_key:
            best_key = key
            best_markers = markers

    if len(best_markers) < 2:
        raise RuntimeError("TX marker candidates did not form one PRF-periodic train.")
    ordinal = np.arange(len(best_markers), dtype=np.float64)
    slope, intercept = np.polyfit(ordinal, np.asarray(best_markers, dtype=np.float64), 1)
    measured_prf_hz = sample_rate_hz / float(slope)
    error_fraction = abs(measured_prf_hz - expected_prf_hz) / expected_prf_hz
    if error_fraction > 0.02:
        raise RuntimeError(
            f"Measured PRF {measured_prf_hz:.3f} Hz differs from expected {expected_prf_hz:.3f} Hz by more than 2%."
        )

    refined: list[int] = []
    residuals: list[float] = []
    for predicted in intercept + slope * ordinal:
        predicted_int = int(round(float(predicted)))
        lo = max(0, predicted_int - 256)
        hi = min(score.size, predicted_int + 257)
        marker = lo + int(np.argmax(score[lo:hi]))
        if marker + final_offset_samples < score.size:
            refined.append(marker)
            residuals.append(marker - float(predicted))
    diagnostics = {
        "candidate_count": int(peaks.size),
        "accepted_event_count": len(refined),
        "threshold_codes": threshold,
        "noise_center_codes": center,
        "noise_sigma_codes": sigma,
        "expected_prf_hz": expected_prf_hz,
        "measured_prf_hz": measured_prf_hz,
        "prf_error_percent": error_fraction * 100.0,
        "timing_residual_rms_samples": float(np.sqrt(np.mean(np.square(residuals)))),
        "timing_residual_max_samples": float(np.max(np.abs(residuals))),
    }
    return np.asarray(refined, dtype=np.int64), measured_prf_hz, diagnostics


def extract_range_gate_iq(
    data: np.ndarray,
    markers: np.ndarray,
    channel_indices: list[int],
    baseline: np.ndarray,
    config: AnalysisConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    propagation_s = 2.0 * (config.target_depth_mm * 1e-3) / config.sound_speed_m_s
    center_offset = int(
        round((propagation_s + config.range_zero_offset_us * 1e-6) * config.sample_rate_hz)
    )
    gate_samples = max(
        16,
        int(round(2.0 * config.gate_length_mm * 1e-3 / config.sound_speed_m_s * config.sample_rate_hz)),
    )
    half = gate_samples // 2
    taper = np.hanning(gate_samples).astype(np.float32)
    if not np.any(taper):
        taper[:] = 1.0
    taper /= float(np.sum(taper))
    relative_samples = np.arange(-half, gate_samples - half, dtype=np.float64) + center_offset
    mixer = np.exp(
        -2j * np.pi * config.center_frequency_hz * relative_samples / config.sample_rate_hz
    ).astype(np.complex64)
    kernel = taper.astype(np.complex64) * mixer

    iq_rows: list[np.ndarray] = []
    rail_codes = 0
    for marker in markers:
        start = int(marker) + center_offset - half
        stop = start + gate_samples
        if start < 0 or stop > data.shape[0]:
            continue
        segment_u16 = np.asarray(data[start:stop, channel_indices], dtype=np.uint16)
        rail_codes += int(np.count_nonzero((segment_u16 <= 16) | (segment_u16 >= 65519)))
        segment = segment_u16.astype(np.float32) - baseline[None, :]
        iq_rows.append(np.sum(segment * kernel[:, None], axis=0))
    if len(iq_rows) < 16:
        raise RuntimeError("Fewer than 16 complete range-gated pulses remain after extraction.")
    iq = np.asarray(iq_rows, dtype=np.complex64)
    diagnostics = {
        "range_gate_center_offset_samples": center_offset,
        "range_gate_center_offset_us": center_offset / config.sample_rate_hz * 1e6,
        "range_gate_samples": gate_samples,
        "range_gate_duration_us": gate_samples / config.sample_rate_hz * 1e6,
        "range_gate_rail_code_count": rail_codes,
        "range_gate_value_count": int(iq.shape[0] * gate_samples * iq.shape[1]),
    }
    return iq, diagnostics


def coherent_channel_combine(iq: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    if iq.ndim == 1:
        return iq.astype(np.complex64), {"channel_count": 1, "first_mode_energy_fraction": 1.0}
    if iq.ndim != 2 or iq.shape[1] < 1:
        raise ValueError("I/Q data must have shape (pulses, channels).")
    u, singular, _vh = np.linalg.svd(iq.astype(np.complex128), full_matrices=False)
    beam = u[:, 0] * singular[0]
    energy_fraction = float(singular[0] ** 2 / max(np.sum(singular**2), np.finfo(float).eps))
    return beam.astype(np.complex64), {
        "channel_count": int(iq.shape[1]),
        "first_mode_energy_fraction": energy_fraction,
        "combine_method": "first coherent SVD mode; direction sign remains calibration-dependent",
    }


def wall_filter(iq: np.ndarray, prf_hz: float, cutoff_hz: float) -> np.ndarray:
    if cutoff_hz <= 0:
        return iq - np.mean(iq)
    normalized = cutoff_hz / (prf_hz / 2.0)
    sos = signal.butter(3, normalized, btype="highpass", output="sos")
    min_length = 3 * (2 * sos.shape[0] + 1)
    if iq.size <= min_length:
        return iq - np.mean(iq)
    return signal.sosfiltfilt(sos, iq).astype(np.complex64)


def estimate_cardiac_period(
    time_s: np.ndarray,
    velocity_envelope_m_s: np.ndarray,
    expected_heart_rate_bpm: float,
) -> dict[str, Any]:
    if time_s.size < 8:
        return {"detected": False, "reason": "too few spectrogram time bins"}
    duration_s = float(time_s[-1] - time_s[0])
    if duration_s < 3.0:
        return {"detected": False, "reason": "continuous record is shorter than 3 seconds"}
    dt = float(np.median(np.diff(time_s)))
    series = np.asarray(velocity_envelope_m_s, dtype=np.float64)
    if series.size >= 7:
        window = min(series.size if series.size % 2 else series.size - 1, 11)
        if window >= 5:
            series = signal.savgol_filter(series, window, 2)
    series -= np.mean(series)
    scale = float(np.linalg.norm(series))
    if scale <= np.finfo(float).eps:
        return {"detected": False, "reason": "velocity envelope has no measurable modulation"}
    autocorrelation = signal.correlate(series, series, mode="full", method="fft")[series.size - 1 :]
    autocorrelation /= max(float(autocorrelation[0]), np.finfo(float).eps)
    expected_period_s = 60.0 / expected_heart_rate_bpm
    min_period_s = max(0.33, expected_period_s * 0.55)
    max_period_s = min(2.0, expected_period_s * 1.8)
    lo = max(1, int(math.ceil(min_period_s / dt)))
    hi = min(autocorrelation.size, int(math.floor(max_period_s / dt)) + 1)
    if hi <= lo:
        return {"detected": False, "reason": "record is too short for the expected heart-rate search range"}
    local = autocorrelation[lo:hi]
    lag = lo + int(np.argmax(local))
    peak = float(autocorrelation[lag])
    period_s = lag * dt
    cycles = duration_s / period_s
    detected = peak >= 0.20 and cycles >= 3.0
    return {
        "detected": detected,
        "period_s": period_s,
        "heart_rate_bpm": 60.0 / period_s,
        "autocorrelation_peak": peak,
        "cycles_in_spectrogram": cycles,
        "reason": "periodic velocity modulation accepted" if detected else "periodicity confidence or cycle count is insufficient",
    }


def analyze_slow_time_iq(
    iq: np.ndarray,
    prf_hz: float,
    center_frequency_hz: float,
    flow_angle_deg: float,
    wall_filter_hz: float,
    ensemble_pulses: int,
    expected_heart_rate_bpm: float,
    sound_speed_m_s: float = 1540.0,
) -> dict[str, Any]:
    if iq.ndim == 1:
        iq = iq[:, None]
    if iq.shape[0] < 16:
        raise ValueError("At least 16 slow-time I/Q samples are required.")
    coherent, combine_diagnostics = coherent_channel_combine(iq)
    filtered = wall_filter(coherent, prf_hz, wall_filter_hz)
    nperseg = min(int(ensemble_pulses), int(filtered.size))
    if nperseg < 16:
        raise ValueError("Not enough pulses for the selected Doppler ensemble.")
    noverlap = min(nperseg - 1, int(round(0.75 * nperseg)))
    frequency_hz, time_s, spectrum = signal.stft(
        filtered,
        fs=prf_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        nfft=max(256, 1 << int(math.ceil(math.log2(nperseg)))),
        detrend=False,
        return_onesided=False,
        boundary=None,
        padded=False,
    )
    frequency_hz = np.fft.fftshift(frequency_hz)
    spectrum = np.fft.fftshift(spectrum, axes=0)
    power = np.abs(spectrum) ** 2
    power_db = 10.0 * np.log10(power / max(float(np.max(power)), np.finfo(float).eps) + 1e-12)
    cosine = abs(math.cos(math.radians(flow_angle_deg)))
    velocity_axis = frequency_hz * sound_speed_m_s / (2.0 * center_frequency_hz * cosine)
    wall_velocity = wall_filter_hz * sound_speed_m_s / (2.0 * center_frequency_hz * cosine)
    positive = velocity_axis >= wall_velocity
    negative = velocity_axis <= -wall_velocity
    positive_energy = float(np.sum(power[positive, :])) if np.any(positive) else 0.0
    negative_energy = float(np.sum(power[negative, :])) if np.any(negative) else 0.0
    direction = 1 if positive_energy >= negative_energy else -1
    direction_mask = positive if direction > 0 else negative
    if not np.any(direction_mask):
        direction_mask = np.ones_like(velocity_axis, dtype=bool)
    directional_velocity = velocity_axis[direction_mask]
    directional_power = power[direction_mask, :]
    peak_indices = np.argmax(directional_power, axis=0)
    peak_velocity = directional_velocity[peak_indices]
    weighted_velocity = np.sum(directional_power * directional_velocity[:, None], axis=0) / np.maximum(
        np.sum(directional_power, axis=0), np.finfo(float).eps
    )
    velocity_envelope = np.abs(peak_velocity)
    cardiac = estimate_cardiac_period(time_s, velocity_envelope, expected_heart_rate_bpm)
    record_duration_s = (iq.shape[0] - 1) / prf_hz
    expected_cycles = record_duration_s * expected_heart_rate_bpm / 60.0
    cardiac_visible = bool(
        record_duration_s >= 3.0 and expected_cycles >= 3.0 and cardiac.get("detected", False)
    )
    return {
        "coherent_iq": coherent,
        "filtered_iq": filtered,
        "frequency_hz": frequency_hz,
        "time_s": time_s,
        "velocity_axis_m_s": velocity_axis,
        "power_db": power_db,
        "peak_velocity_m_s": peak_velocity,
        "weighted_velocity_m_s": weighted_velocity,
        "record_duration_s": record_duration_s,
        "expected_heart_cycles": expected_cycles,
        "cardiac_cycle_visible": cardiac_visible,
        "cardiac_periodicity": cardiac,
        "dominant_direction_sign_uncalibrated": direction,
        "direction_sign_calibrated": False,
        "combine_diagnostics": combine_diagnostics,
        "ensemble_pulses_used": nperseg,
        "wall_velocity_m_s": wall_velocity,
    }


def render_result(result: dict[str, Any], target: Path, title: str) -> None:
    time_s = np.asarray(result["time_s"])
    velocity = np.asarray(result["velocity_axis_m_s"])
    power_db = np.asarray(result["power_db"])
    peak = np.asarray(result["peak_velocity_m_s"])
    weighted = np.asarray(result["weighted_velocity_m_s"])
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(12, 7.2),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1.2]},
        constrained_layout=True,
    )
    image = axes[0].pcolormesh(time_s, velocity, power_db, shading="auto", cmap="magma", vmin=-45, vmax=0)
    axes[0].axhline(0.0, color="white", linewidth=0.8, alpha=0.75)
    axes[0].set_ylabel("Velocity (m/s)\nangle-corrected")
    axes[0].set_title(title)
    colorbar = figure.colorbar(image, ax=axes[0], pad=0.015)
    colorbar.set_label("Relative power (dB)")
    axes[1].plot(time_s, peak, color="#1E5EFF", linewidth=1.5, label="Peak velocity")
    axes[1].plot(time_s, weighted, color="#D97706", linewidth=1.1, linestyle="--", label="Power-weighted velocity")
    axes[1].axhline(0.0, color="#60738A", linewidth=0.8)
    axes[1].set_xlabel("Continuous slow time (s)")
    axes[1].set_ylabel("Velocity (m/s)")
    axes[1].grid(True, alpha=0.22)
    axes[1].legend(loc="upper right")
    cardiac = result["cardiac_periodicity"]
    if result["cardiac_cycle_visible"]:
        note = f"Cardiac modulation accepted: {cardiac['heart_rate_bpm']:.1f} BPM, {cardiac['cycles_in_spectrogram']:.1f} cycles"
    else:
        note = f"Cardiac modulation NOT accepted: {cardiac.get('reason', 'insufficient evidence')}"
    figure.text(0.012, 0.01, note + " · velocity direction sign requires a known-flow calibration", fontsize=9, color="#38516C")
    figure.savefig(target, dpi=160, facecolor="white")
    plt.close(figure)


def save_outputs(
    output_dir: Path,
    result: dict[str, Any],
    config: AnalysisConfig,
    source: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_dir / "pw_doppler_slow_time_iq.npz",
        coherent_iq=np.asarray(result["coherent_iq"], dtype=np.complex64),
        filtered_iq=np.asarray(result["filtered_iq"], dtype=np.complex64),
        prf_hz=np.asarray([config.prf_hz], dtype=np.float64),
    )
    with (output_dir / "pw_doppler_velocity.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["slow_time_s", "peak_velocity_m_s", "power_weighted_velocity_m_s"])
        for row in zip(result["time_s"], result["peak_velocity_m_s"], result["weighted_velocity_m_s"]):
            writer.writerow([f"{float(row[0]):.9g}", f"{float(row[1]):.9g}", f"{float(row[2]):.9g}"])

    render_result(
        result,
        output_dir / "pw_doppler_spectrogram.png",
        f"PW Doppler · {config.center_frequency_hz / 1e6:.3g} MHz · PRF {config.prf_hz:.3g} Hz · gate {config.target_depth_mm:.1f} mm",
    )
    summary = {
        "status": "complete",
        "source": source,
        "configuration": asdict(config),
        "event_diagnostics": diagnostics,
        "result": {
            "slow_time_sample_count": int(np.asarray(result["coherent_iq"]).size),
            "record_duration_s": float(result["record_duration_s"]),
            "expected_heart_cycles": float(result["expected_heart_cycles"]),
            "cardiac_cycle_visible": bool(result["cardiac_cycle_visible"]),
            "cardiac_periodicity": result["cardiac_periodicity"],
            "direction_sign_calibrated": bool(result["direction_sign_calibrated"]),
            "dominant_direction_sign_uncalibrated": int(result["dominant_direction_sign_uncalibrated"]),
            "ensemble_pulses_used": int(result["ensemble_pulses_used"]),
            "wall_velocity_m_s": float(result["wall_velocity_m_s"]),
            "peak_velocity_abs_max_m_s": float(np.max(np.abs(result["peak_velocity_m_s"]))),
            "weighted_velocity_abs_median_m_s": float(np.median(np.abs(result["weighted_velocity_m_s"]))),
            "combine_diagnostics": result["combine_diagnostics"],
        },
        "outputs": {
            "spectrogram_png": "pw_doppler_spectrogram.png",
            "velocity_csv": "pw_doppler_velocity.csv",
            "slow_time_iq_npz": "pw_doppler_slow_time_iq.npz",
        },
        "validity": {
            "separate_hsdc_files_concatenated": False,
            "range_zero_requires_scope_or_known_reflector_calibration": True,
            "velocity_magnitude_requires_known_speed_validation": True,
            "velocity_direction_requires_known_flow_calibration": True,
            "human_use_authorized": False,
        },
    }
    (output_dir / "pw_doppler_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def analyze_capture(capture_dir: Path, force: bool = False) -> dict[str, Any]:
    capture_dir = capture_dir.resolve()
    config, manifest, _plan = config_from_capture(capture_dir)
    output_dir = capture_dir / "analysis" / "pw_doppler"
    summary_path = output_dir / "pw_doppler_summary.json"
    if summary_path.exists() and not force:
        cached = read_json(summary_path)
        if cached.get("status") == "complete":
            return cached

    iq_input = capture_dir / "pw_doppler_input_iq.npz"
    if iq_input.is_file():
        loaded = np.load(iq_input, allow_pickle=False)
        iq = np.asarray(loaded["iq"], dtype=np.complex64)
        file_prf = float(np.asarray(loaded.get("prf_hz", [config.prf_hz])).ravel()[0])
        if abs(file_prf - config.prf_hz) / config.prf_hz > 0.001:
            raise ValueError("I/Q file PRF does not match the Doppler session plan.")
        diagnostics: dict[str, Any] = {"input": "pre-extracted continuous I/Q", "pulse_count": int(iq.shape[0])}
        source = {
            "type": "continuous_iq_npz",
            "filename": iq_input.name,
            "sha256": sha256_file(iq_input),
        }
    else:
        raw_path = select_raw_capture(capture_dir, manifest, config.steering_angle_deg)
        data = raw_memmap(raw_path)
        configured_slots = manifest.get("array", {}).get("rx_hsdc_slots_1_based", list(range(1, 9)))
        channel_indices = [int(slot) - 1 for slot in configured_slots]
        if not channel_indices or any(index < 0 or index >= CHANNELS_IN_RAW_FILE for index in channel_indices):
            raise ValueError("Manifest contains invalid HSDC receive slots.")
        baseline = estimate_baseline(data, channel_indices)
        score = amplitude_score(data, channel_indices, baseline)
        propagation_samples = int(
            round(
                (
                    2.0 * config.target_depth_mm * 1e-3 / config.sound_speed_m_s
                    + config.range_zero_offset_us * 1e-6
                )
                * config.sample_rate_hz
            )
        )
        gate_samples = int(
            round(2.0 * config.gate_length_mm * 1e-3 / config.sound_speed_m_s * config.sample_rate_hz)
        )
        markers, measured_prf, event_diagnostics = detect_prf_events(
            score,
            config.sample_rate_hz,
            config.prf_hz,
            propagation_samples + gate_samples + 512,
        )
        iq, gate_diagnostics = extract_range_gate_iq(
            data, markers, channel_indices, baseline, config
        )
        diagnostics = {
            **event_diagnostics,
            **gate_diagnostics,
            "measured_prf_hz": measured_prf,
            "rx_hsdc_slots_1_based": [index + 1 for index in channel_indices],
        }
        source = {
            "type": "hsdc_interleaved_raw_rf",
            "filename": raw_path.name,
            "file_bytes": raw_path.stat().st_size,
            "sha256": sha256_file(raw_path),
        }

    result = analyze_slow_time_iq(
        iq,
        prf_hz=config.prf_hz,
        center_frequency_hz=config.center_frequency_hz,
        flow_angle_deg=config.flow_angle_deg,
        wall_filter_hz=config.wall_filter_hz,
        ensemble_pulses=config.ensemble_pulses,
        expected_heart_rate_bpm=config.expected_heart_rate_bpm,
        sound_speed_m_s=config.sound_speed_m_s,
    )
    return save_outputs(output_dir, result, config, source, diagnostics)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze one continuous PW Doppler capture.")
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--force", action="store_true", help="replace cached PW Doppler analysis")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = analyze_capture(args.capture_dir, force=args.force)
    result = summary["result"]
    print(
        "PW Doppler analysis complete: duration={:.3f}s, expected cycles={:.2f}, cardiac_visible={}".format(
            result["record_duration_s"],
            result["expected_heart_cycles"],
            result["cardiac_cycle_visible"],
        )
    )
    print(args.capture_dir / "analysis" / "pw_doppler" / "pw_doppler_spectrogram.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
