"""Conservative blood-flow localisation for continuous PW-Doppler I/Q.

The module keeps three questions separate:

1. is the RF coherently demodulated into one complex sample per pulse/depth;
2. is the Doppler energy localised to a plausible range gate rather than
   shared by the complete fast-time record;
3. does the selected gate pass spectral, directionality, comb and reference
   checks before a velocity is promoted from a numerical candidate.

The routines are hardware-independent NumPy/SciPy references.  They are also
the executable specification for a future FPGA range-gate implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import numpy as np
from scipy import signal


@dataclass(frozen=True)
class FlowDetectionConfig:
    wall_filter_hz: float = 80.0
    flow_max_hz: float = 3500.0
    sample_volume_mm: float = 2.0
    welch_pulses: int = 2048
    comb_base_hz: float | None = None
    comb_half_width_hz: float = 25.0
    minimum_snr_db: float = 3.0
    minimum_directionality: float = 0.15
    minimum_reference_excess_db: float = 3.0
    minimum_localisation_db: float = 1.5
    minimum_adjacent_support: float = 0.35
    minimum_kasai_coherence: float = 0.08
    maximum_comb_fraction: float = 0.50
    maximum_common_mode_correlation: float = 0.80

    def validate(self, prf_hz: float) -> None:
        nyquist_hz = prf_hz / 2.0
        if not 0.0 <= self.wall_filter_hz < nyquist_hz:
            raise ValueError("Wall-filter cutoff must be below PRF/2.")
        if not self.wall_filter_hz < self.flow_max_hz < nyquist_hz:
            raise ValueError("Flow band must lie between the wall filter and PRF/2.")
        if self.sample_volume_mm <= 0.0:
            raise ValueError("Sample-volume length must be positive.")
        if self.welch_pulses < 16:
            raise ValueError("Welch ensemble must contain at least 16 pulses.")


def select_longest_contiguous_run(
    iq: np.ndarray,
    prf_hz: float,
    pulse_index: np.ndarray | None = None,
    timestamp_s: np.ndarray | None = None,
    tolerance_fraction: float = 0.05,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return one gap-free slow-time run; never concatenate across a gap."""

    values = np.asarray(iq)
    if values.ndim < 1 or values.shape[0] < 1:
        raise ValueError("I/Q input must contain at least one pulse.")
    count = values.shape[0]
    boundaries = np.zeros(max(0, count - 1), dtype=bool)
    checks: list[str] = []

    if pulse_index is not None:
        indices = np.asarray(pulse_index).reshape(-1)
        if indices.size != count:
            raise ValueError("pulse_index length does not match I/Q pulse count.")
        boundaries |= np.diff(indices.astype(np.int64)) != 1
        checks.append("pulse_index")

    if timestamp_s is not None:
        timestamps = np.asarray(timestamp_s, dtype=float).reshape(-1)
        if timestamps.size != count:
            raise ValueError("timestamp_s length does not match I/Q pulse count.")
        expected_s = 1.0 / prf_hz
        delta = np.diff(timestamps)
        boundaries |= (~np.isfinite(delta)) | (delta <= 0.0) | (
            np.abs(delta - expected_s) > tolerance_fraction * expected_s
        )
        checks.append("timestamp_s")

    cuts = np.flatnonzero(boundaries) + 1
    starts = np.r_[0, cuts]
    stops = np.r_[cuts, count]
    lengths = stops - starts
    best = int(np.argmax(lengths))
    start = int(starts[best])
    stop = int(stops[best])
    diagnostics = {
        "continuity_checks": checks or ["assumed_from_file_order"],
        "input_pulse_count": int(count),
        "gap_count": int(cuts.size),
        "selected_start_index": start,
        "selected_stop_index_exclusive": stop,
        "selected_pulse_count": int(stop - start),
        "discarded_pulse_count": int(count - (stop - start)),
        "continuous": bool(cuts.size == 0),
    }
    return values[start:stop], diagnostics


def demodulate_range_grid(
    data: np.ndarray,
    markers: np.ndarray,
    channel_indices: list[int],
    baseline: np.ndarray,
    sample_rate_hz: float,
    center_frequency_hz: float,
    depths_mm: np.ndarray,
    gate_length_mm: float,
    sound_speed_m_s: float = 1540.0,
    range_zero_offset_us: float = 0.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Matched complex demodulation over a monostatic depth grid.

    Output shape is ``(pulses, depths, channels)``.  Fast-time integration is
    performed before the slow-time sequence is analysed or decimated.
    """

    depth = np.asarray(depths_mm, dtype=float).reshape(-1)
    if depth.size < 1 or np.any(~np.isfinite(depth)) or np.any(depth <= 0.0):
        raise ValueError("depths_mm must contain positive finite depths.")
    marker = np.asarray(markers, dtype=np.int64).reshape(-1)
    if marker.size < 1:
        raise ValueError("At least one PRF marker is required.")
    channels = np.asarray(channel_indices, dtype=np.int64)
    offsets = np.rint(
        (
            2.0 * depth * 1e-3 / sound_speed_m_s
            + range_zero_offset_us * 1e-6
        )
        * sample_rate_hz
    ).astype(np.int64)
    gate_samples = max(
        16,
        int(round(2.0 * gate_length_mm * 1e-3 / sound_speed_m_s * sample_rate_hz)),
    )
    half = gate_samples // 2
    local = np.arange(-half, gate_samples - half, dtype=np.int64)
    taper = np.hanning(gate_samples).astype(np.float64)
    if not np.any(taper):
        taper[:] = 1.0
    taper /= np.sum(taper)
    phase_samples = offsets[:, None] + local[None, :]
    kernel = taper[None, :] * np.exp(
        -2j * np.pi * center_frequency_hz * phase_samples / sample_rate_hz
    )

    valid = (marker + offsets.min() + local.min() >= 0) & (
        marker + offsets.max() + local.max() < data.shape[0]
    )
    marker = marker[valid]
    if marker.size < 16:
        raise RuntimeError("Fewer than 16 complete pulses remain for range-grid demodulation.")

    output = np.empty((marker.size, depth.size, channels.size), dtype=np.complex64)
    rail_codes = 0
    values_per_pulse = max(1, depth.size * gate_samples * channels.size)
    block_pulses = max(8, min(512, int(24_000_000 / values_per_pulse)))
    for start in range(0, marker.size, block_pulses):
        stop = min(marker.size, start + block_pulses)
        current = marker[start:stop]
        indices = current[:, None, None] + offsets[None, :, None] + local[None, None, :]
        rows_u16 = np.asarray(data[indices[..., None], channels], dtype=np.uint16)
        rail_codes += int(np.count_nonzero((rows_u16 <= 16) | (rows_u16 >= 65519)))
        rows = rows_u16.astype(np.float32) - np.asarray(baseline, dtype=np.float32)[None, None, None, :]
        output[start:stop] = np.sum(rows * kernel[None, :, :, None], axis=2)

    diagnostics = {
        "demodulation": "complex matched mixer followed by fast-time sample-volume integration",
        "pulse_count": int(marker.size),
        "depth_count": int(depth.size),
        "channel_count": int(channels.size),
        "depth_min_mm": float(depth.min()),
        "depth_max_mm": float(depth.max()),
        "gate_samples": int(gate_samples),
        "gate_duration_us": float(gate_samples / sample_rate_hz * 1e6),
        "rail_code_count": int(rail_codes),
        "value_count": int(marker.size * depth.size * gate_samples * channels.size),
    }
    return output, diagnostics


def _wall_filter(iq: np.ndarray, prf_hz: float, cutoff_hz: float) -> np.ndarray:
    values = np.asarray(iq, dtype=np.complex64)
    if cutoff_hz <= 0.0:
        return values - np.mean(values, axis=0, keepdims=True)
    sos = signal.butter(4, cutoff_hz, btype="highpass", fs=prf_hz, output="sos")
    minimum = 3 * (2 * sos.shape[0] + 1)
    if values.shape[0] <= minimum:
        return values - np.mean(values, axis=0, keepdims=True)
    return signal.sosfiltfilt(sos, values, axis=0).astype(np.complex64)


def _spectral_metrics(
    iq: np.ndarray,
    prf_hz: float,
    config: FlowDetectionConfig,
) -> dict[str, np.ndarray]:
    filtered = _wall_filter(iq, prf_hz, config.wall_filter_hz)
    nperseg = min(int(config.welch_pulses), int(filtered.shape[0]))
    noverlap = min(nperseg - 1, 3 * nperseg // 4)
    frequency, power = signal.welch(
        filtered,
        fs=prf_hz,
        window="hann",
        nperseg=nperseg,
        noverlap=noverlap,
        detrend=False,
        return_onesided=False,
        scaling="density",
        axis=0,
    )
    frequency = np.fft.fftshift(frequency)
    power = np.fft.fftshift(power, axes=0).astype(np.float64)
    flow = (np.abs(frequency) >= config.wall_filter_hz) & (
        np.abs(frequency) <= config.flow_max_hz
    )
    positive = flow & (frequency > 0.0)
    negative = flow & (frequency < 0.0)
    comb = np.zeros(frequency.size, dtype=bool)
    if config.comb_base_hz is not None and config.comb_base_hz > 0.0:
        harmonics = int(config.flow_max_hz // config.comb_base_hz)
        for harmonic in range(1, harmonics + 1):
            comb |= (
                np.abs(np.abs(frequency) - harmonic * config.comb_base_hz)
                <= config.comb_half_width_hz
            )
    clean = flow & ~comb
    nyquist_hz = prf_hz / 2.0
    noise = (np.abs(frequency) >= max(config.flow_max_hz * 1.35, 0.65 * nyquist_hz)) & (
        np.abs(frequency) <= 0.92 * nyquist_hz
    )
    if np.count_nonzero(noise) >= 8:
        floor = np.median(power[noise], axis=0)
    else:
        floor = np.percentile(power[clean], 35.0, axis=0)
    positive_power = np.sum(power[positive & ~comb], axis=0)
    negative_power = np.sum(power[negative & ~comb], axis=0)
    clean_power = positive_power + negative_power
    expected_noise = floor * max(1, np.count_nonzero(clean))
    snr_db = 10.0 * np.log10((clean_power + 1e-30) / (expected_noise + 1e-30))
    directionality = (positive_power - negative_power) / (clean_power + 1e-30)
    excess = np.maximum(power - floor[None, ...], 0.0)
    comb_fraction = np.sum(excess[flow & comb], axis=0) / (
        np.sum(excess[flow], axis=0) + 1e-30
    )
    return {
        "frequency_hz": frequency,
        "power": power,
        "filtered_iq": filtered,
        "positive_power": positive_power,
        "negative_power": negative_power,
        "clean_power": clean_power,
        "expected_noise": expected_noise,
        "snr_db": snr_db,
        "directionality": directionality,
        "comb_fraction": comb_fraction,
    }


def _common_mode_correlation(iq: np.ndarray, gate: np.ndarray, prf_hz: float) -> float | None:
    if iq.shape[1] < 4 or np.count_nonzero(~gate) < 2:
        return None
    block = max(1, int(round(prf_hz / 200.0)))
    blocks = iq.shape[0] // block
    if blocks < 12:
        return None
    magnitude = np.abs(iq[: blocks * block]).reshape(
        blocks, block, iq.shape[1], iq.shape[2]
    )
    slow = np.mean(magnitude, axis=1)
    slow_db = 20.0 * np.log10(np.maximum(slow, np.median(slow) * 1e-9 + 1e-30))
    gate_trace = np.median(slow_db[:, gate, :], axis=(1, 2))
    off_trace = np.median(slow_db[:, ~gate, :], axis=(1, 2))
    gate_trace = signal.detrend(gate_trace)
    off_trace = signal.detrend(off_trace)
    denominator = np.linalg.norm(gate_trace) * np.linalg.norm(off_trace)
    if denominator <= np.finfo(float).eps:
        return 0.0
    return float(np.dot(gate_trace, off_trace) / denominator)


def _kasai_gate(filtered: np.ndarray, gate: np.ndarray, prf_hz: float) -> dict[str, float]:
    values = filtered[:, gate, :].reshape(filtered.shape[0], -1).astype(np.complex128)
    r1 = np.sum(np.conj(values[:-1]) * values[1:])
    e0 = float(np.sum(np.abs(values[:-1]) ** 2))
    e1 = float(np.sum(np.abs(values[1:]) ** 2))
    coherence = float(abs(r1) / (math.sqrt(e0 * e1) + 1e-30))
    frequency_hz = float(np.angle(r1) * prf_hz / (2.0 * np.pi))
    return {"lag_one_coherence": coherence, "mean_frequency_hz": frequency_hz}


def locate_blood_flow_gate(
    iq: np.ndarray,
    depths_mm: np.ndarray,
    prf_hz: float,
    center_frequency_hz: float,
    config: FlowDetectionConfig | None = None,
    reference_iq: np.ndarray | None = None,
    sound_speed_m_s: float = 1540.0,
    flow_angle_deg: float = 0.0,
) -> dict[str, Any]:
    """Rank range gates and return conservative blood-flow evidence."""

    cfg = config or FlowDetectionConfig(flow_max_hz=min(3500.0, 0.45 * prf_hz))
    cfg.validate(prf_hz)
    values = np.asarray(iq)
    if values.ndim == 2:
        values = values[:, :, None]
    if values.ndim != 3:
        raise ValueError("I/Q grid must have shape (pulses, depths[, channels]).")
    depth = np.asarray(depths_mm, dtype=float).reshape(-1)
    if depth.size != values.shape[1]:
        raise ValueError("depths_mm length does not match I/Q depth dimension.")
    order = np.argsort(depth)
    depth = depth[order]
    values = values[:, order, :]
    if reference_iq is not None:
        reference = np.asarray(reference_iq)
        if reference.ndim == 2:
            reference = reference[:, :, None]
        if reference.shape[1:] != values.shape[1:]:
            raise ValueError("Reference I/Q depth/channel shape must match candidate I/Q.")
        reference = reference[:, order, :]
    else:
        reference = None

    metrics = _spectral_metrics(values, prf_hz, cfg)
    reference_metrics = None if reference is None else _spectral_metrics(reference, prf_hz, cfg)
    per_depth_power = np.sum(metrics["clean_power"], axis=1)
    per_depth_noise = np.sum(metrics["expected_noise"], axis=1)
    per_depth_positive = np.sum(metrics["positive_power"], axis=1)
    per_depth_negative = np.sum(metrics["negative_power"], axis=1)
    per_depth_comb_excess = np.sum(
        metrics["comb_fraction"] * np.maximum(metrics["clean_power"], 0.0), axis=1
    )
    per_depth_reference = (
        None
        if reference_metrics is None
        else np.sum(reference_metrics["clean_power"], axis=1)
    )

    candidates: list[dict[str, Any]] = []
    for center in depth:
        gate = np.abs(depth - center) <= cfg.sample_volume_mm / 2.0
        if not np.any(gate):
            continue
        flank = (np.abs(depth - center) >= cfg.sample_volume_mm) & (
            np.abs(depth - center) <= cfg.sample_volume_mm * 2.5
        )
        if not np.any(flank):
            flank = ~gate
        flow_power = float(np.sum(per_depth_power[gate]))
        expected_noise = float(np.sum(per_depth_noise[gate]))
        positive_power = float(np.sum(per_depth_positive[gate]))
        negative_power = float(np.sum(per_depth_negative[gate]))
        snr_db = 10.0 * math.log10((flow_power + 1e-30) / (expected_noise + 1e-30))
        directionality = (positive_power - negative_power) / (flow_power + 1e-30)
        if np.any(flank):
            gate_density = float(np.median(per_depth_power[gate]))
            flank_density = float(np.median(per_depth_power[flank]))
            localisation_db = 10.0 * math.log10((gate_density + 1e-30) / (flank_density + 1e-30))
            support_threshold = flank_density * (10.0 ** (cfg.minimum_localisation_db / 10.0))
            adjacent_support = float(np.mean(per_depth_power[gate] >= support_threshold))
        else:
            localisation_db = None
            adjacent_support = None
        comb_numerator = float(np.sum(per_depth_comb_excess[gate]))
        comb_fraction = comb_numerator / (flow_power + 1e-30)
        reference_excess_db = None
        if per_depth_reference is not None:
            reference_power = float(np.sum(per_depth_reference[gate]))
            reference_excess_db = 10.0 * math.log10(
                (flow_power + 1e-30) / (reference_power + 1e-30)
            )
        common_correlation = _common_mode_correlation(values, gate, prf_hz)
        kasai = _kasai_gate(metrics["filtered_iq"], gate, prf_hz)
        cosine = abs(math.cos(math.radians(flow_angle_deg)))
        velocity_factor = sound_speed_m_s / (
            2.0 * center_frequency_hz * max(cosine, 1e-6)
        )
        kasai_velocity = kasai["mean_frequency_hz"] * velocity_factor

        failures: list[str] = []
        if snr_db < cfg.minimum_snr_db:
            failures.append("snr_below_threshold")
        if abs(directionality) < cfg.minimum_directionality:
            failures.append("directionality_below_threshold")
        if comb_fraction > cfg.maximum_comb_fraction:
            failures.append("comb_energy_above_threshold")
        if kasai["lag_one_coherence"] < cfg.minimum_kasai_coherence:
            failures.append("kasai_coherence_below_threshold")
        if localisation_db is not None and localisation_db < cfg.minimum_localisation_db:
            failures.append("depth_localisation_below_threshold")
        if adjacent_support is not None and adjacent_support < cfg.minimum_adjacent_support:
            failures.append("adjacent_depth_support_below_threshold")
        if (
            common_correlation is not None
            and abs(common_correlation) > cfg.maximum_common_mode_correlation
        ):
            failures.append("common_mode_motion_above_threshold")
        if (
            reference_excess_db is not None
            and reference_excess_db < cfg.minimum_reference_excess_db
        ):
            failures.append("static_reference_excess_below_threshold")

        internal_failures = [
            item for item in failures if item != "static_reference_excess_below_threshold"
        ]
        blood_flow_candidate = not internal_failures
        accepted = blood_flow_candidate and reference_excess_db is not None and not failures
        score = (
            snr_db
            + 4.0 * abs(directionality)
            + (0.0 if localisation_db is None else 0.8 * localisation_db)
            + 2.0 * kasai["lag_one_coherence"]
            + (0.0 if reference_excess_db is None else reference_excess_db)
            - 5.0 * comb_fraction
            - (0.0 if common_correlation is None else 1.5 * abs(common_correlation))
        )
        candidates.append(
            {
                "center_mm": float(center),
                "depth_min_mm": float(depth[gate].min()),
                "depth_max_mm": float(depth[gate].max()),
                "depth_indices": np.flatnonzero(gate).astype(int).tolist(),
                "snr_db": float(snr_db),
                "directionality": float(directionality),
                "comb_energy_fraction": float(comb_fraction),
                "reference_excess_db": reference_excess_db,
                "localisation_db": localisation_db,
                "adjacent_depth_support": adjacent_support,
                "common_mode_correlation": common_correlation,
                "kasai_lag_one_coherence": kasai["lag_one_coherence"],
                "kasai_mean_frequency_hz": kasai["mean_frequency_hz"],
                "kasai_projected_velocity_m_s": float(kasai_velocity),
                "score": float(score),
                "blood_flow_candidate": bool(blood_flow_candidate),
                "accepted_blood_flow": bool(accepted),
                "failures": failures,
            }
        )

    if not candidates:
        raise RuntimeError("No complete range-gate candidate could be formed.")
    best = max(candidates, key=lambda item: item["score"])
    if best["accepted_blood_flow"]:
        classification = "accepted_against_static_reference"
    elif best["blood_flow_candidate"] and reference is None:
        classification = "signal_candidate_needs_static_reference"
    else:
        classification = "rejected"
    return {
        "method": "coherent I/Q -> wall filter -> clean Doppler spectrum + Kasai -> spatial/reference quality gates",
        "configuration": asdict(cfg),
        "reference_supplied": bool(reference is not None),
        "classification": classification,
        "blood_flow_candidate": bool(best["blood_flow_candidate"]),
        "accepted_blood_flow": bool(best["accepted_blood_flow"]),
        "selected_gate": best,
        "ranked_gates": sorted(candidates, key=lambda item: item["score"], reverse=True),
    }


def assess_fixed_gate(
    iq: np.ndarray,
    prf_hz: float,
    center_frequency_hz: float,
    config: FlowDetectionConfig | None = None,
    reference_iq: np.ndarray | None = None,
    target_depth_mm: float = 0.0,
    sound_speed_m_s: float = 1540.0,
    flow_angle_deg: float = 0.0,
) -> dict[str, Any]:
    """Apply the same evidence gates when only one sample volume is present."""

    values = np.asarray(iq)
    if values.ndim == 1:
        values = values[:, None]
    cube = values[:, None, :]
    reference_cube = None
    if reference_iq is not None:
        reference_values = np.asarray(reference_iq)
        if reference_values.ndim == 1:
            reference_values = reference_values[:, None]
        reference_cube = reference_values[:, None, :]
    result = locate_blood_flow_gate(
        cube,
        np.asarray([target_depth_mm], dtype=float),
        prf_hz,
        center_frequency_hz,
        config=config,
        reference_iq=reference_cube,
        sound_speed_m_s=sound_speed_m_s,
        flow_angle_deg=flow_angle_deg,
    )
    result["spatial_localisation_available"] = False
    return result
