from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import base64
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
matplotlib.rcParams["svg.fonttype"] = "none"
import matplotlib.pyplot as plt
from scipy.interpolate import RegularGridInterpolator


ROOT = Path(__file__).resolve().parent

FS_HZ = 120_000_000.0
C_M_S = 1540.0
PITCH_M = 1.59e-3
CENTER_FREQUENCY_HZ = 1.0e6
LOW_HZ = 0.6e6
HIGH_HZ = 1.4e6
WINDOW_SAMPLES = 7500


def angle_from_name(path: Path) -> int:
    match = re.search(r"angle_([mp])(\d+)", path.name)
    if not match:
        raise ValueError(f"Cannot parse angle from {path.name}")
    value = int(match.group(2))
    return -value if match.group(1) == "m" else value


def parse_rx_channels(text: str) -> list[int]:
    values = [int(item.strip()) for item in text.split(",") if item.strip()]
    if not values or len(set(values)) != len(values) or any(value < 1 or value > 16 for value in values):
        raise argparse.ArgumentTypeError("RX channels must be unique 1-based HSDC slots in 1..16")
    return values


def moving_average(values: np.ndarray, length: int) -> np.ndarray:
    length = max(1, int(length))
    return np.convolve(values, np.ones(length, dtype=np.float64) / length, mode="same")


def tukey_window(length: int, alpha: float = 0.5) -> np.ndarray:
    """Return a symmetric Tukey window without requiring scipy.signal."""
    length = int(length)
    alpha = float(alpha)
    if length < 1:
        raise ValueError("Window length must be positive")
    if length == 1 or alpha <= 0.0:
        return np.ones(length, dtype=np.float64)
    if alpha >= 1.0:
        return np.hanning(length).astype(np.float64)
    x = np.linspace(0.0, 1.0, length)
    window = np.ones(length, dtype=np.float64)
    leading = x < alpha / 2.0
    trailing = x > 1.0 - alpha / 2.0
    window[leading] = 0.5 * (
        1.0 + np.cos(np.pi * (2.0 * x[leading] / alpha - 1.0))
    )
    window[trailing] = 0.5 * (
        1.0 + np.cos(np.pi * (2.0 * x[trailing] / alpha - 2.0 / alpha + 1.0))
    )
    return window


def receive_apodization_weights(
    mode: str,
    physical_element_numbers: np.ndarray,
    active_element_count: int,
    tukey_alpha: float = 0.5,
) -> np.ndarray:
    """Build receive weights in physical A1..AN order, then select active slots."""
    mode = str(mode).strip().lower()
    active_element_count = int(active_element_count)
    if mode == "uniform":
        full_window = np.ones(active_element_count, dtype=np.float64)
    elif mode == "hann":
        full_window = (
            np.hanning(active_element_count).astype(np.float64)
            if active_element_count >= 3
            else np.ones(active_element_count, dtype=np.float64)
        )
    elif mode == "tukey":
        full_window = tukey_window(active_element_count, tukey_alpha)
    else:
        raise ValueError(f"Unsupported receive apodization: {mode}")

    indices = np.asarray(physical_element_numbers, dtype=np.int64) - 1
    if np.any(indices < 0) or np.any(indices >= active_element_count):
        raise ValueError("Physical element numbers fall outside A1..AN")
    selected = full_window[indices]
    if float(np.sum(selected)) <= np.finfo(np.float64).eps:
        raise ValueError(
            "Selected receive elements have zero total apodization weight; "
            "use Tukey/uniform or include interior elements"
        )
    return selected


def coherence_factor_from_accumulators(
    coherent_sum: np.ndarray,
    weighted_incoherent_power: np.ndarray,
    weight_sum: float,
) -> np.ndarray:
    """Generalized coherence factor in [0, 1] for non-negative RX weights."""
    denominator = float(weight_sum) * np.asarray(weighted_incoherent_power, dtype=np.float64)
    numerator = np.abs(coherent_sum) ** 2
    factor = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator, dtype=np.float64),
        where=denominator > np.finfo(np.float64).eps,
    )
    return np.clip(factor, 0.0, 1.0)


def suppress_gated_common_mode(
    segment: np.ndarray,
    tx_reference_sample: float,
    max_depth_mm: float = 12.0,
    strength: float = 0.75,
) -> tuple[np.ndarray, float]:
    """Suppress rank-one/common RX ringing only in a shallow post-TX gate.

    A full-record common-mode subtraction would also remove a real broadside
    planar reflector.  The cosine-tapered gate deliberately limits this
    diagnostic option to the direct-coupling/ring-down region.
    """
    source = np.asarray(segment, dtype=np.float64)
    if source.ndim != 2 or source.shape[1] < 2:
        raise ValueError("Common-mode suppression requires a samples x channels matrix")
    strength = float(strength)
    max_depth_mm = float(max_depth_mm)
    if not (0.0 <= strength <= 1.0):
        raise ValueError("Common-mode strength must be in 0..1")
    if max_depth_mm <= 0.0 or strength == 0.0:
        return source.astype(segment.dtype, copy=True), 0.0

    start = max(0, min(source.shape[0], int(round(float(tx_reference_sample)))))
    stop = max(
        start,
        min(
            source.shape[0],
            int(
                round(
                    float(tx_reference_sample)
                    + 2.0 * max_depth_mm * 1e-3 * FS_HZ / C_M_S
                )
            ),
        ),
    )
    if stop <= start:
        return source.astype(segment.dtype, copy=True), 0.0

    common = np.median(source, axis=1)
    gate = np.zeros(source.shape[0], dtype=np.float64)
    gate[start:stop] = 1.0
    fade_length = min(stop - start, max(16, int(round(2.0 * 1e-3 * FS_HZ / C_M_S))))
    if fade_length > 1:
        gate[stop - fade_length : stop] = 0.5 * (
            1.0 + np.cos(np.linspace(0.0, np.pi, fade_length))
        )

    common_gate = common[start:stop]
    denominator = float(np.dot(common_gate, common_gate))
    if denominator <= np.finfo(np.float64).eps:
        return source.astype(segment.dtype, copy=True), 0.0
    coefficients = np.asarray(
        [
            np.clip(
                float(np.dot(source[start:stop, channel], common_gate)) / denominator,
                0.0,
                2.0,
            )
            for channel in range(source.shape[1])
        ],
        dtype=np.float64,
    )
    removed = strength * gate[:, None] * common[:, None] * coefficients[None, :]
    output = source - removed
    input_rms = float(np.sqrt(np.mean(source[start:stop, :] ** 2)))
    removed_rms = float(np.sqrt(np.mean(removed[start:stop, :] ** 2)))
    removed_fraction = removed_rms / input_rms if input_rms > 0.0 else 0.0
    return output.astype(segment.dtype, copy=False), removed_fraction


def analytic_bandpass(values: np.ndarray) -> np.ndarray:
    """FFT bandpass followed by an analytic-signal transform."""
    n = values.shape[0]
    spectrum = np.fft.fft(values, axis=0)
    freq = np.fft.fftfreq(n, d=1.0 / FS_HZ)
    spectrum[(np.abs(freq) < LOW_HZ) | (np.abs(freq) > HIGH_HZ), :] = 0
    real_bandpassed = np.fft.ifft(spectrum, axis=0).real
    spectrum = np.fft.fft(real_bandpassed, axis=0)
    hilbert = np.zeros(n, dtype=np.float64)
    hilbert[0] = 1.0
    hilbert[1 : n // 2] = 2.0
    if n % 2 == 0:
        hilbert[n // 2] = 1.0
    return np.fft.ifft(spectrum * hilbert[:, None], axis=0).astype(np.complex64)


def find_duplicate_pairs(data: np.ndarray) -> list[list[int]]:
    """Return bit-for-bit duplicate HSDC output slots.

    The sparse probe is only a fast candidate filter.  A pair is reported only
    after every sample in the capture is compared, so analog similarity cannot
    be mistaken for a duplicated digital channel.
    """
    pairs: list[list[int]] = []
    probe = np.asarray(data[::257, :])
    for left in range(probe.shape[1]):
        for right in range(left + 1, probe.shape[1]):
            if np.array_equal(probe[:, left], probe[:, right]) and np.array_equal(
                data[:, left], data[:, right]
            ):
                pairs.append([left + 1, right + 1])
    return pairs


def duplicate_pair_persistence(files: list[Path], pairs: list[list[int]]) -> list[dict[str, object]]:
    """Verify whether each exact pair persists in every angle capture."""
    results: list[dict[str, object]] = []
    for left, right in pairs:
        matching_files: list[str] = []
        for path in files:
            data = np.memmap(path, dtype="<u2", mode="r").reshape(-1, 16)
            if np.array_equal(data[:, left - 1], data[:, right - 1]):
                matching_files.append(path.name)
        results.append(
            {
                "channels_1_based": [left, right],
                "matching_file_count": len(matching_files),
                "total_file_count": len(files),
                "persists_in_every_file": len(matching_files) == len(files),
            }
        )
    return results


def estimate_received_pulse_spectrum(
    path: Path,
    channel_indices: list[int],
) -> tuple[np.ndarray, np.ndarray, float, int, float]:
    """Measure the early received burst/ring-down spectrum from one capture.

    This is deliberately named *received* spectrum.  It is not proof of the
    electrical TX7316 output frequency because the transducer, matching network,
    T/R path and AFE all shape the waveform.
    """
    data = np.memmap(path, dtype="<u2", mode="r").reshape(-1, 16)
    baseline = np.median(data[::256, :], axis=0).astype(np.float32)
    markers, prf_hz = detect_events(data, channel_indices, baseline)
    powers: list[np.ndarray] = []
    nfft = 8192
    for marker in markers:
        start = marker + 250
        stop = min(marker + 1200, data.shape[0])
        if stop - start < 512:
            continue
        segment = data[start:stop, channel_indices].astype(np.float32)
        segment -= baseline[channel_indices]
        segment -= np.mean(segment, axis=0, keepdims=True)
        taper = np.hanning(segment.shape[0])[:, None]
        powers.append(np.mean(np.abs(np.fft.rfft(segment * taper, n=nfft, axis=0)) ** 2, axis=1))
    if not powers:
        raise RuntimeError(f"Could not estimate received pulse spectrum from {path.name}")
    power = np.median(np.stack(powers, axis=0), axis=0)
    freq_hz = np.fft.rfftfreq(nfft, d=1.0 / FS_HZ)
    mask = (freq_hz >= 0.5e6) & (freq_hz <= 8.0e6)
    peak_hz = float(freq_hz[mask][int(np.argmax(power[mask]))])
    return freq_hz, power, peak_hz, len(powers), prf_hz


def detect_events_validated(
    data: np.ndarray,
    channel_indices: list[int],
    baseline: np.ndarray,
    expected_prf_hz: float = 1000.0,
) -> tuple[list[int], float, dict[str, object]]:
    """Detect a periodic train and preserve every complete PRF-grid event.

    A high sample alone is never accepted as a transmit event. Candidates must
    establish one fitted PRF grid. Waveform correlation is retained as a signal
    quality diagnostic, but it is not allowed to silently delete real emissions:
    late echoes/ringing may legitimately decorrelate even when the synchronous
    direct-coupling marker is present. Per-event fast-time alignment is performed
    later from that direct-coupling marker.
    """
    signal = data[:, channel_indices].astype(np.float32) - baseline[channel_indices]
    score = np.max(np.abs(signal), axis=1)
    smoothed = moving_average(score, 32)
    # The direct-coupling marker amplitude depends strongly on the programmed
    # TX waveform.  The older tapered five-level pattern produced >1200-code
    # markers, while the simple PHV_A/MHV_A bipolar pattern can be perfectly
    # periodic with peaks below 600 codes.  A fixed 1200-code floor therefore
    # rejected every real emission in otherwise valid captures.
    noise_center = float(np.median(smoothed))
    noise_mad = float(np.median(np.abs(smoothed - noise_center)))
    noise_sigma = max(1.0, 1.4826 * noise_mad)
    threshold = max(
        20.0,
        noise_center + 8.0 * noise_sigma,
        float(np.percentile(smoothed, 99.5)) * 0.35,
    )
    candidates = np.where(
        (smoothed[1:-1] > smoothed[:-2])
        & (smoothed[1:-1] >= smoothed[2:])
        & (smoothed[1:-1] > threshold)
    )[0] + 1
    ordered = candidates[np.argsort(smoothed[candidates])[::-1]]

    # Select candidates as one PRF-periodic train instead of taking the twelve
    # strongest isolated peaks.  Low-amplitude captures contain occasional
    # noise peaks between emissions; including those in a straight-line fit can
    # make a valid 1 kHz train look aperiodic.  Each strong candidate is tried as
    # the phase seed of the expected PRF grid, and the grid with the greatest
    # accumulated marker strength is retained.
    nominal_period = FS_HZ / float(expected_prf_hz)
    search_radius = int(min(4096, max(512, round(nominal_period * 0.025))))
    complete_start = 1000
    complete_stop = data.shape[0] - WINDOW_SAMPLES - 500
    best_centers: list[int] = []
    best_grid_score = -1.0
    for candidate in ordered[: min(64, len(ordered))]:
        seed = int(candidate)
        first_step = int(math.ceil((complete_start - seed) / nominal_period))
        last_step = int(math.floor((complete_stop - seed) / nominal_period))
        grid_centers: list[int] = []
        grid_score = 0.0
        for step in range(first_step, last_step + 1):
            predicted = int(round(seed + step * nominal_period))
            lo = max(complete_start, predicted - search_radius)
            hi = min(complete_stop + 1, predicted + search_radius + 1)
            if hi <= lo:
                continue
            refined = lo + int(np.argmax(smoothed[lo:hi]))
            strength = float(smoothed[refined])
            if strength < threshold:
                continue
            if not grid_centers or refined != grid_centers[-1]:
                grid_centers.append(refined)
                grid_score += strength
        if len(grid_centers) >= 2 and (
            grid_score, len(grid_centers)
        ) > (
            best_grid_score, len(best_centers)
        ):
            best_centers = grid_centers
            best_grid_score = grid_score
    centers = best_centers

    coarse: list[int] = []
    for center in centers:
        if center < 1000 or center + WINDOW_SAMPLES + 500 >= data.shape[0]:
            continue
        lo = center - 180
        hi = center + 181
        marker = lo + int(np.argmax(score[lo:hi]))
        coarse.append(marker)

    diagnostics: dict[str, object] = {
        "amplitude_candidate_count": int(len(candidates)),
        "coarse_event_count": len(coarse),
        "amplitude_threshold_codes": round(float(threshold), 3),
        "noise_center_codes": round(noise_center, 3),
        "noise_sigma_codes": round(noise_sigma, 3),
        "prf_grid_search_radius_samples": search_radius,
        "prf_grid_score": round(float(best_grid_score), 3),
        "expected_prf_hz": float(expected_prf_hz),
        "validation": "amplitude candidates establish a fitted PRF grid; waveform-template correlation is diagnostic",
    }
    if len(coarse) < 2:
        diagnostics.update({"accepted_event_count": 0, "failure": "fewer than two periodic candidates"})
        return [], float("nan"), diagnostics

    coarse_array = np.asarray(coarse, dtype=np.float64)
    ordinal = np.arange(len(coarse_array), dtype=np.float64)
    slope, intercept = np.polyfit(ordinal, coarse_array, 1)
    measured_prf_hz = FS_HZ / float(slope)
    prf_error_fraction = abs(measured_prf_hz - expected_prf_hz) / expected_prf_hz
    if prf_error_fraction > 0.02:
        diagnostics.update(
            {
                "accepted_event_count": 0,
                "measured_prf_hz": round(float(measured_prf_hz), 6),
                "prf_error_percent": round(float(prf_error_fraction * 100.0), 4),
                "failure": "detected train differs from expected PRF by more than 2%",
            }
        )
        return [], measured_prf_hz, diagnostics

    grid_refined: list[int] = []
    for predicted in intercept + slope * ordinal:
        center = int(round(float(predicted)))
        lo = max(0, center - 256)
        hi = min(score.size, center + 257)
        grid_refined.append(lo + int(np.argmax(score[lo:hi])))

    validation_samples = 1800
    waveforms: list[np.ndarray] = []
    valid_markers: list[int] = []
    for marker in grid_refined:
        if marker < 1000 or marker + max(WINDOW_SAMPLES + 500, validation_samples) >= data.shape[0]:
            continue
        waveform = signal[marker : marker + validation_samples, :].astype(np.float64).ravel()
        waveform -= np.mean(waveform)
        scale = float(np.linalg.norm(waveform))
        if scale > 0:
            waveforms.append(waveform / scale)
            valid_markers.append(marker)
    if len(waveforms) < 2:
        diagnostics.update({"accepted_event_count": 0, "failure": "not enough complete waveform windows"})
        return [], measured_prf_hz, diagnostics

    template = np.median(np.stack(waveforms, axis=0), axis=0)
    template_norm = float(np.linalg.norm(template))
    correlations = [float(np.dot(waveform, template) / template_norm) for waveform in waveforms]
    fitted = np.polyval(np.polyfit(np.arange(len(valid_markers)), valid_markers, 1), np.arange(len(valid_markers)))
    residuals = np.asarray(valid_markers, dtype=np.float64) - fitted
    # The synchronous amplitude pulse exists at every fitted grid point. Do not
    # collapse a 9-pulse record to 5 pulses merely because the later acoustic
    # field is unstable. Such instability is exactly what the QA output must
    # expose. Timing outliers remain visible in diagnostics.
    accepted = list(valid_markers)
    correlation_outliers = [
        int(marker)
        for marker, correlation in zip(valid_markers, correlations)
        if correlation < 0.80
    ]
    diagnostics.update(
        {
            "accepted_event_count": len(accepted),
            "rejected_event_count": 0,
            "measured_prf_hz": round(float(measured_prf_hz), 6),
            "prf_error_percent": round(float(abs(measured_prf_hz - expected_prf_hz) / expected_prf_hz * 100.0), 4),
            "timing_residual_max_samples": round(float(np.max(np.abs(residuals))), 4),
            "template_correlation_min": round(float(min(correlations)), 6),
            "template_correlation_median": round(float(np.median(correlations)), 6),
            "template_correlation_outlier_markers": correlation_outliers,
            "accepted_markers": accepted,
        }
    )
    return accepted, measured_prf_hz, diagnostics


def detect_events(data: np.ndarray, channel_indices: list[int], baseline: np.ndarray) -> tuple[list[int], float]:
    markers, prf_hz, _ = detect_events_validated(data, channel_indices, baseline)
    return markers, prf_hz


def interp_complex(signal: np.ndarray, sample_positions: np.ndarray) -> np.ndarray:
    positions = np.arange(signal.shape[0], dtype=np.float64)
    real = np.interp(sample_positions, positions, signal.real, left=0.0, right=0.0)
    imag = np.interp(sample_positions, positions, signal.imag, left=0.0, right=0.0)
    return real + 1j * imag


def event_direct_reference_samples(
    segment: np.ndarray,
    search_start: int = 300,
    search_stop: int = 950,
) -> int:
    """Locate the direct-coupling pulse center inside one extracted PRF event."""
    analytic = analytic_bandpass(segment)
    energy = np.percentile(np.abs(analytic), 90.0, axis=1)
    stop = min(int(search_stop), int(energy.size))
    start = min(max(0, int(search_start)), max(0, stop - 1))
    return start + int(np.argmax(energy[start:stop]))


def normalized_best_lag(
    reference: np.ndarray,
    candidate: np.ndarray,
    max_lag: int,
) -> tuple[int, float]:
    """Return candidate lag and normalized correlation over a bounded search."""
    reference = np.asarray(reference, dtype=np.float64)
    candidate = np.asarray(candidate, dtype=np.float64)
    reference -= np.mean(reference)
    candidate -= np.mean(candidate)
    best_lag = 0
    best_correlation = -1.0
    for lag in range(-int(max_lag), int(max_lag) + 1):
        if lag < 0:
            left, right = reference[-lag:], candidate[:lag]
        elif lag > 0:
            left, right = reference[:-lag], candidate[lag:]
        else:
            left, right = reference, candidate
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        correlation = float(np.dot(left, right) / denominator) if denominator else -1.0
        if correlation > best_correlation:
            best_lag = lag
            best_correlation = correlation
    return best_lag, best_correlation


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    """Hash one capture without loading the multi-megabyte BIN into RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_figure_pair(fig: plt.Figure, path: Path, dpi: int = 220) -> None:
    """Write a crisp PNG preview and an SVG with vector axes and text."""
    fig.savefig(path, dpi=dpi, facecolor=fig.get_facecolor())
    fig.savefig(path.with_suffix(".svg"), facecolor=fig.get_facecolor())
    plt.close(fig)


def save_ultrasound_image(
    db_image: np.ndarray,
    x_mm: np.ndarray,
    z_mm: np.ndarray,
    path: Path,
    rx_count: int,
    source_label: str,
    title: str | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 9.4), dpi=220, facecolor="black")
    ax.set_facecolor("black")
    image = ax.imshow(
        db_image,
        cmap="gray",
        vmin=-45.0,
        vmax=0.0,
        extent=[x_mm[0], x_mm[-1], z_mm[-1], z_mm[0]],
        aspect="auto",
        interpolation="bilinear",
    )
    ax.set_title(
        title or f"Soft-aligned plane-wave DAS · {rx_count} unique RX",
        color="white",
        fontsize=15,
        pad=28,
    )
    ax.text(0.5, 1.014, source_label, transform=ax.transAxes, ha="center", va="bottom", color="#AFC4DC", fontsize=9)
    ax.set_xlabel("Lateral position (mm)", color="white", labelpad=9)
    ax.set_ylabel("Depth (mm)", color="white", labelpad=9)
    ax.tick_params(colors="#D6DEE8")
    for spine in ax.spines.values():
        spine.set_color("#8293A8")
    colorbar = fig.colorbar(image, ax=ax, pad=0.025, shrink=0.82)
    colorbar.set_label("Envelope (dB; strong echo → white)", color="white")
    colorbar.ax.tick_params(colors="#D6DEE8")
    fig.tight_layout(pad=1.6)
    save_figure_pair(fig, path)


def save_cycle_montage(
    db_images: list[np.ndarray],
    x_mm: np.ndarray,
    z_mm: np.ndarray,
    path: Path,
    source_label: str,
    title: str,
) -> None:
    """Save all detected PRF-repeat images with one shared dB scale."""
    count = len(db_images)
    columns = min(3, max(1, count))
    rows = int(math.ceil(count / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(4.2 * columns, 4.8 * rows), dpi=200, facecolor="white")
    axes_array = np.atleast_1d(axes).ravel()
    for index, ax in enumerate(axes_array):
        if index >= count:
            ax.axis("off")
            continue
        ax.imshow(
            db_images[index],
            cmap="gray",
            vmin=-45.0,
            vmax=0.0,
            extent=[x_mm[0], x_mm[-1], z_mm[-1], z_mm[0]],
            aspect="auto",
            interpolation="bilinear",
        )
        ax.set_title(f"PRF pulse {index + 1}", fontsize=11)
        ax.set_xlabel("Lateral (mm)")
        ax.set_ylabel("Depth (mm)")
        ax.tick_params(labelsize=8)
    fig.suptitle(title, fontsize=15, y=0.995)
    fig.text(0.5, 0.004, source_label, ha="center", va="bottom", color="#60738A", fontsize=8)
    fig.tight_layout(rect=(0.0, 0.018, 1.0, 0.975), pad=1.2)
    save_figure_pair(fig, path, dpi=200)


def save_channel_diagnostics(
    data: np.ndarray,
    duplicate_pairs: list[list[int]],
    path: Path,
    source_label: str,
) -> None:
    """Visualize HSDC slot correlation without implying an analog wiring map."""
    probe = data[::257, :].astype(np.float64)
    probe -= np.mean(probe, axis=0, keepdims=True)
    correlation = np.corrcoef(probe, rowvar=False)
    correlation = np.nan_to_num(correlation, nan=0.0)
    fig, ax = plt.subplots(figsize=(8.6, 7.6), dpi=210, facecolor="white")
    image = ax.imshow(correlation, cmap="coolwarm", vmin=-1.0, vmax=1.0, interpolation="nearest")
    ax.set_xticks(np.arange(16), labels=np.arange(1, 17))
    ax.set_yticks(np.arange(16), labels=np.arange(1, 17))
    ax.set_xlabel("HSDC output slot")
    ax.set_ylabel("HSDC output slot")
    ax.set_title("Digital output-slot correlation (exact pairs outlined)", pad=22)
    for left, right in duplicate_pairs:
        for row, column in ((left - 1, right - 1), (right - 1, left - 1)):
            ax.add_patch(plt.Rectangle((column - 0.5, row - 0.5), 1, 1, fill=False, edgecolor="#111827", linewidth=2.0))
    fig.colorbar(image, ax=ax, shrink=0.82, label="Pearson correlation")
    ax.text(0.5, 1.01, source_label, transform=ax.transAxes, ha="center", va="bottom", color="#60738A", fontsize=8)
    fig.tight_layout(pad=1.4)
    save_figure_pair(fig, path, dpi=210)


def save_event_time_domain_plot(
    data: np.ndarray,
    channel_indices: list[int],
    baseline: np.ndarray,
    markers: list[int],
    path: Path,
    source_label: str,
    validation: dict[str, object],
) -> None:
    """Expose the actual accepted RF records used by reconstruction."""
    if not markers:
        return
    segments = np.stack(
        [
            data[marker : marker + WINDOW_SAMPLES, channel_indices].astype(np.float32)
            - baseline[channel_indices]
            for marker in markers
        ],
        axis=0,
    )
    time_us = np.arange(WINDOW_SAMPLES, dtype=np.float64) / FS_HZ * 1e6
    rf_median = np.median(segments[:, :, 0], axis=0)
    rf_low = np.percentile(segments[:, :, 0], 10.0, axis=0)
    rf_high = np.percentile(segments[:, :, 0], 90.0, axis=0)
    envelope = np.sqrt(np.mean(segments.astype(np.float64) ** 2, axis=(0, 2)))
    envelope_db = 20.0 * np.log10(np.maximum(envelope / np.max(envelope), 1e-8))

    score = np.max(np.abs(data[:, channel_indices].astype(np.float32) - baseline[channel_indices]), axis=1)
    overview_step = max(1, data.shape[0] // 12000)
    overview_time_ms = np.arange(0, data.shape[0], overview_step) / FS_HZ * 1e3

    fig, axes = plt.subplots(3, 1, figsize=(12.0, 9.0), dpi=210, facecolor="white")
    axes[0].plot(overview_time_ms, score[::overview_step], color="#355C7D", linewidth=0.8)
    for index, marker in enumerate(markers, start=1):
        axes[0].axvline(marker / FS_HZ * 1e3, color="#C23A42", alpha=0.65, linewidth=0.9)
        axes[0].text(marker / FS_HZ * 1e3, axes[0].get_ylim()[1] * 0.88, str(index), ha="center", va="top", fontsize=8, color="#8C2730")
    axes[0].set_title(
        "Accepted transmit-event train: periodic grid and waveform-template validated",
        fontsize=13,
    )
    axes[0].set_xlabel("Capture time (ms)")
    axes[0].set_ylabel("Max |ADC-baseline| (codes)")
    axes[0].grid(True, color="#E3EBF4", linewidth=0.7)

    axes[1].fill_between(time_us, rf_low, rf_high, color="#9FC3FF", alpha=0.38, label="10–90% across accepted pulses")
    axes[1].plot(time_us, rf_median, color="#1E5EFF", linewidth=0.9, label=f"Median RF, HSDC slot {channel_indices[0] + 1}")
    axes[1].axvspan(2.0 * 8.0e-3 / C_M_S * 1e6, 2.0 * 42.0e-3 / C_M_S * 1e6, color="#E7F6F0", alpha=0.5, label="Displayed 8–42 mm range")
    axes[1].set_xlim(0.0, WINDOW_SAMPLES / FS_HZ * 1e6)
    axes[1].set_xlabel("Time after accepted marker (µs)")
    axes[1].set_ylabel("ADC-baseline (codes)")
    axes[1].legend(loc="upper right", frameon=False, fontsize=9)
    axes[1].grid(True, color="#E3EBF4", linewidth=0.7)

    axes[2].plot(time_us, envelope_db, color="#0E8F6A", linewidth=1.2)
    axes[2].axvspan(2.0 * 8.0e-3 / C_M_S * 1e6, 2.0 * 42.0e-3 / C_M_S * 1e6, color="#E7F6F0", alpha=0.5)
    axes[2].set_xlim(0.0, WINDOW_SAMPLES / FS_HZ * 1e6)
    axes[2].set_ylim(-60.0, 1.0)
    axes[2].set_xlabel("Time after accepted marker (µs)")
    axes[2].set_ylabel("Multichannel RMS (dB)")
    axes[2].grid(True, color="#E3EBF4", linewidth=0.7)
    axes[2].text(
        0.99,
        0.93,
        f"accepted={len(markers)}  PRF={validation.get('measured_prf_hz', '—')} Hz\n"
        f"template corr min={validation.get('template_correlation_min', '—')}  "
        f"timing residual max={validation.get('timing_residual_max_samples', '—')} samples",
        transform=axes[2].transAxes,
        ha="right",
        va="top",
        fontsize=9,
        color="#38516C",
    )
    fig.text(0.5, 0.006, source_label, ha="center", va="bottom", color="#60738A", fontsize=8)
    fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0), pad=1.4)
    save_figure_pair(fig, path, dpi=210)


def save_angle_depth_image(
    db_image: np.ndarray,
    angles: np.ndarray,
    depth_mm: np.ndarray,
    path: Path,
    source_label: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 7.2), dpi=220, facecolor="black")
    ax.set_facecolor("black")
    image = ax.imshow(
        db_image,
        cmap="gray",
        vmin=-45.0,
        vmax=0.0,
        extent=[angles[0], angles[-1], depth_mm[-1], depth_mm[0]],
        aspect="auto",
        interpolation="bilinear",
    )
    ax.set_title("Steered-angle envelope scan (not receive-DAS)", color="white", fontsize=14, pad=26)
    ax.text(0.5, 1.012, source_label, transform=ax.transAxes, ha="center", va="bottom", color="#AFC4DC", fontsize=9)
    ax.set_xlabel("Transmit angle (deg)", color="white")
    ax.set_ylabel("Depth (mm)", color="white")
    ax.tick_params(colors="#D6DEE8")
    for spine in ax.spines.values():
        spine.set_color("#8293A8")
    colorbar = fig.colorbar(image, ax=ax, pad=0.025, shrink=0.82)
    colorbar.set_label("Envelope (dB; strong echo → white)", color="white")
    colorbar.ax.tick_params(colors="#D6DEE8")
    fig.tight_layout(pad=1.5)
    save_figure_pair(fig, path)


def save_profile_plot(
    depth_mm: np.ndarray,
    profile_db: np.ndarray,
    reflectors: list[dict[str, float]],
    path: Path,
    source_label: str,
) -> None:
    fig, ax = plt.subplots(figsize=(10.0, 5.6), dpi=220, facecolor="white")
    ax.plot(depth_mm, profile_db, color="#1E5EFF", linewidth=1.8)
    for index, reflector in enumerate(reflectors, start=1):
        depth = reflector["depth_mm"]
        value = reflector["level_db"]
        ax.scatter([depth], [value], s=34, color="#C23A42", zorder=3)
        ax.annotate(f"R{index}  {depth:.1f} mm", (depth, value), xytext=(6, 8), textcoords="offset points", color="#9B2730", fontsize=9)
    ax.set_title("Lateral 90th-percentile envelope and detected axial peaks", fontsize=14, pad=24)
    ax.text(0.5, 1.012, source_label, transform=ax.transAxes, ha="center", va="bottom", color="#60738A", fontsize=9)
    ax.set_xlabel("Depth (mm)")
    ax.set_ylabel("Envelope (dB)")
    ax.set_xlim(float(depth_mm[0]), float(depth_mm[-1]))
    ax.set_ylim(-45.0, 1.0)
    ax.grid(True, color="#DDE7F2", linewidth=0.8)
    fig.tight_layout(pad=1.5)
    save_figure_pair(fig, path)


def save_sector_image(
    db_by_angle_depth: np.ndarray,
    angles: np.ndarray,
    depth_mm: np.ndarray,
    path: Path,
    source_label: str,
) -> None:
    """Map the eleven steered A-lines to a narrow fan display."""
    plot_w, plot_h = 600, 650
    x_axis = np.linspace(-10.0, 10.0, plot_w)
    z_axis = np.linspace(0.0, float(depth_mm[-1]), plot_h)
    xx, zz = np.meshgrid(x_axis, z_axis)
    radius = np.sqrt(xx**2 + zz**2)
    theta = np.degrees(np.arctan2(xx, np.maximum(zz, 1e-9)))
    interpolator = RegularGridInterpolator(
        (depth_mm, angles),
        db_by_angle_depth.T,
        bounds_error=False,
        fill_value=-45.0,
    )
    fan_db = interpolator(np.column_stack([radius.ravel(), theta.ravel()])).reshape(plot_h, plot_w)
    inside = (
        (radius >= depth_mm[0])
        & (radius <= depth_mm[-1])
        & (theta >= angles[0])
        & (theta <= angles[-1])
    )
    display_db = np.full_like(fan_db, -45.0)
    display_db[inside] = fan_db[inside]
    fig, ax = plt.subplots(figsize=(7.8, 8.5), dpi=220, facecolor="black")
    ax.set_facecolor("black")
    image = ax.imshow(
        display_db,
        cmap="gray",
        vmin=-45.0,
        vmax=0.0,
        extent=[x_axis[0], x_axis[-1], z_axis[-1], z_axis[0]],
        aspect="auto",
        interpolation="bilinear",
    )
    ax.set_title(
        f"Steered A-line sector view ({len(angles)} angles; not receive-DAS)",
        color="white",
        fontsize=14,
        pad=26,
    )
    ax.text(0.5, 1.012, source_label, transform=ax.transAxes, ha="center", va="bottom", color="#AFC4DC", fontsize=9)
    ax.set_xlabel("Lateral position (mm)", color="white")
    ax.set_ylabel("Depth (mm)", color="white")
    ax.tick_params(colors="#D6DEE8")
    for spine in ax.spines.values():
        spine.set_color("#8293A8")
    colorbar = fig.colorbar(image, ax=ax, pad=0.025, shrink=0.82)
    colorbar.set_label("Envelope (dB; strong echo → white)", color="white")
    colorbar.ax.tick_params(colors="#D6DEE8")
    fig.tight_layout(pad=1.5)
    save_figure_pair(fig, path)


def save_spectrum_plot(
    freq_mhz: np.ndarray,
    received_pulse_db: np.ndarray,
    received_peak_mhz: float,
    delayed_echo_db: np.ndarray,
    delayed_echo_peak_mhz: float,
    requested_mhz: float,
    path: Path,
    source_label: str,
) -> None:
    fig, ax = plt.subplots(figsize=(10.0, 5.4), dpi=220, facecolor="white")
    ax.plot(
        freq_mhz,
        received_pulse_db,
        color="#1E5EFF",
        linewidth=1.7,
        label=f"Early received burst/ring-down: {received_peak_mhz:.3f} MHz",
    )
    ax.plot(
        freq_mhz,
        delayed_echo_db,
        color="#0E8F6A",
        linewidth=1.3,
        alpha=0.88,
        label=f"Delayed echo window: {delayed_echo_peak_mhz:.3f} MHz",
    )
    ax.axvline(requested_mhz, color="#C23A42", linewidth=1.5, linestyle="--", label=f"Requested TX setting: {requested_mhz:.3f} MHz")
    ax.set_title("Received spectra; not a direct measurement of TX7316 voltage waveform", fontsize=14, pad=24)
    ax.text(0.5, 1.012, source_label, transform=ax.transAxes, ha="center", va="bottom", color="#60738A", fontsize=9)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Relative power (dB)")
    ax.set_xlim(0.5, 8.0)
    ax.set_ylim(-45.0, 1.0)
    ax.grid(True, color="#DDE7F2", linewidth=0.8)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    fig.tight_layout(pad=1.5)
    save_figure_pair(fig, path)


def save_3d_surface(
    db_image: np.ndarray,
    x_mm: np.ndarray,
    z_mm: np.ndarray,
    path: Path,
    source_label: str,
) -> None:
    """Save a presentation-oriented 3D amplitude surface with a 2D fallback."""
    xx, zz = np.meshgrid(x_mm, z_mm)
    fig = plt.figure(figsize=(11.5, 7.2), dpi=200, facecolor="#F8FAFC")
    ax = fig.add_subplot(111, projection="3d", facecolor="#F8FAFC")
    surface = ax.plot_surface(
        xx[::2, ::2],
        zz[::2, ::2],
        db_image[::2, ::2],
        cmap="turbo",
        vmin=-45.0,
        vmax=0.0,
        linewidth=0,
        antialiased=True,
        rstride=1,
        cstride=1,
    )
    ax.set_xlabel("Lateral position (mm)", labelpad=10)
    ax.set_ylabel("Depth (mm)", labelpad=10)
    ax.set_zlabel("Envelope (dB)", labelpad=8)
    ax.set_title(f"Plane-wave compound amplitude surface\n{source_label}", pad=18, fontsize=14)
    ax.set_zlim(-45.0, 0.0)
    ax.invert_yaxis()
    ax.view_init(elev=34, azim=-58)
    ax.grid(True, alpha=0.22)
    colorbar = fig.colorbar(surface, ax=ax, shrink=0.68, pad=0.08)
    colorbar.set_label("Envelope (dB)")
    fig.tight_layout()
    save_figure_pair(fig, path, dpi=200)


def detect_reflectors(depth_mm: np.ndarray, profile_db: np.ndarray) -> list[dict[str, float]]:
    # Use a local prominence measure so the long T/R-switch recovery tail is not
    # mistaken for a single broad reflector.
    fine = moving_average(profile_db, 5)
    broad = moving_average(profile_db, 31)
    prominence = fine - broad
    candidates = np.where((fine[1:-1] > fine[:-2]) & (fine[1:-1] >= fine[2:]))[0] + 1
    candidates = candidates[(depth_mm[candidates] >= 10.0) & (depth_mm[candidates] <= 41.0)]

    # Treat the deep high-amplitude band separately: in the current gel scan it
    # is much more likely to be the phantom/base boundary than a small inclusion.
    interior = candidates[depth_mm[candidates] < 34.0]
    boundary = candidates[depth_mm[candidates] >= 34.0]
    ordered = list(interior[np.argsort(prominence[interior])[::-1]])
    if len(boundary):
        ordered.append(int(boundary[np.argmax(prominence[boundary])]))
    selected: list[int] = []
    for candidate in ordered:
        if prominence[candidate] < 0.8:
            continue
        if all(abs(depth_mm[candidate] - depth_mm[existing]) >= 1.7 for existing in selected):
            selected.append(int(candidate))
        if len(selected) >= 5:
            break
    selected.sort(key=lambda index: depth_mm[index])
    return [
        {
            "depth_mm": round(float(depth_mm[index]), 2),
            "level_db": round(float(profile_db[index]), 2),
            "local_prominence_db": round(float(prominence[index]), 2),
            "classification": "deep boundary candidate" if depth_mm[index] >= 34.0 else "internal reflector candidate",
        }
        for index in selected
    ]


def estimate_tx_reference_samples(path: Path, rx_indices: list[int]) -> float:
    """Estimate the pulse-center timing from the repeatable direct-coupling burst.

    HSDC and TX7316 do not share a hardware acquisition trigger in this setup.
    The large synchronous artifact is therefore used as a per-record PRF marker,
    and the zero-degree acquisition supplies the fixed marker-to-pulse offset.
    This is adequate for a static phantom, but it is not a substitute for a
    cabled trigger when phase-coherent compounding is required.
    """
    data = np.memmap(path, dtype="<u2", mode="r").reshape(-1, 16)
    baseline = np.median(data[::256, :], axis=0).astype(np.float32)
    markers, _ = detect_events(data, rx_indices, baseline)
    centers: list[int] = []
    for marker in markers:
        segment = data[marker : marker + 1800, rx_indices].astype(np.float32)
        segment -= baseline[rx_indices]
        centers.append(event_direct_reference_samples(segment, 300, 950))
    if not centers:
        raise RuntimeError("Could not estimate TX timing reference from the zero-degree capture")
    return float(np.median(centers))


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline analysis of one TX7316/HSDC angle sweep")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Capture directory. Default: newest complete auto_runs/capture_* directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Default: <input-dir>/analysis.",
    )
    parser.add_argument(
        "--tx-reference-samples",
        type=float,
        default=None,
        help="Override marker-to-pulse timing in ADC samples; otherwise estimated from 0-degree data.",
    )
    parser.add_argument("--pitch-mm", type=float, default=None, help="override array pitch from manifest")
    parser.add_argument(
        "--center-frequency-mhz",
        type=float,
        default=None,
        help="override centre frequency from manifest",
    )
    parser.add_argument(
        "--tx-elements",
        type=int,
        default=None,
        help="override active A1..AN element count from manifest (2..8)",
    )
    parser.add_argument(
        "--rx-channels",
        type=parse_rx_channels,
        default=None,
        help="comma-separated 1-based HSDC slots wired to physical A1..AN; default from manifest or 9..16",
    )
    parser.add_argument(
        "--duplicate-policy",
        choices=["drop-later", "keep-all", "manual"],
        default="drop-later",
        help="how receive-DAS handles exact digital duplicate pairs",
    )
    parser.add_argument(
        "--das-rx-channels",
        type=parse_rx_channels,
        default=None,
        help="manual 1-based DAS slots; required only with --duplicate-policy manual",
    )
    parser.add_argument(
        "--reconstruction-angle-step-deg",
        type=float,
        default=None,
        help="offline angle subset spacing, for example 2 uses -10,-8,...,+10 from a 1-degree capture",
    )
    parser.add_argument(
        "--receive-apodization",
        choices=["uniform", "hann", "tukey"],
        default="uniform",
        help="receive aperture weighting used by DAS (default: uniform)",
    )
    parser.add_argument(
        "--tukey-alpha",
        type=float,
        default=0.5,
        help="Tukey receive-window alpha in 0..1 (default: 0.5)",
    )
    parser.add_argument(
        "--coherence-factor",
        action="store_true",
        help="multiply DAS amplitude by a conservative power of the generalized receive coherence factor",
    )
    parser.add_argument(
        "--coherence-factor-exponent",
        type=float,
        default=0.5,
        help="coherence-factor exponent in (0, 1], default 0.5 (square-root CF)",
    )
    parser.add_argument(
        "--common-mode-ringdown-suppression",
        action="store_true",
        help="subtract a fitted channel-common waveform in a shallow post-TX gate",
    )
    parser.add_argument(
        "--common-mode-max-depth-mm",
        type=float,
        default=12.0,
        help="maximum depth affected by common-mode suppression (default: 12 mm)",
    )
    parser.add_argument(
        "--common-mode-strength",
        type=float,
        default=0.5,
        help="common-mode subtraction strength in 0..1 (default: 0.5)",
    )
    parser.add_argument(
        "--z-min-mm",
        type=float,
        default=4.0,
        help="minimum displayed/reconstructed depth in mm (default 4, so a 5 mm interface is not cropped)",
    )
    parser.add_argument(
        "--z-max-mm",
        type=float,
        default=42.0,
        help="maximum displayed/reconstructed depth in mm (default 42)",
    )
    return parser.parse_args()


def newest_complete_capture() -> Path:
    candidates = sorted((ROOT / "auto_runs").glob("capture_*"), reverse=True)
    for candidate in candidates:
        manifest_path = candidate / "capture_manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("status") == "complete":
                return candidate
    raise RuntimeError("No complete auto_runs/capture_* directory was found")


def main() -> None:
    global PITCH_M
    global CENTER_FREQUENCY_HZ
    global LOW_HZ
    global HIGH_HZ

    args = parse_arguments()
    input_dir = (args.input_dir or newest_complete_capture()).resolve()
    output_dir = (args.output_dir or (input_dir / "analysis")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = input_dir / "capture_manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    array_config = manifest.get("array", {}) if isinstance(manifest, dict) else {}
    PITCH_M = float(
        args.pitch_mm if args.pitch_mm is not None else array_config.get("pitch_mm", 1.59)
    ) * 1e-3
    CENTER_FREQUENCY_HZ = float(
        args.center_frequency_mhz
        if args.center_frequency_mhz is not None
        else array_config.get("center_frequency_hz", 1.0e6) / 1e6
    ) * 1e6
    active_tx_elements = int(
        args.tx_elements
        if args.tx_elements is not None
        else array_config.get("active_tx_elements", 8)
    )
    if not (2 <= active_tx_elements <= 8):
        raise RuntimeError("Active TX element count must be 2..8")
    if not (0.0 <= float(args.tukey_alpha) <= 1.0):
        raise RuntimeError("Tukey alpha must be in 0..1")
    if not (0.0 < float(args.coherence_factor_exponent) <= 1.0):
        raise RuntimeError("Coherence-factor exponent must be in (0, 1]")
    if not (0.0 <= float(args.common_mode_strength) <= 1.0):
        raise RuntimeError("Common-mode strength must be in 0..1")
    if float(args.common_mode_max_depth_mm) <= 0.0:
        raise RuntimeError("Common-mode maximum depth must be positive")
    manifest_files = [
        input_dir / entry.get("filename", "")
        for entry in manifest.get("captures", [])
        if isinstance(entry, dict) and entry.get("filename")
    ]
    files = [path for path in manifest_files if path.exists()]
    if not files:
        files = sorted(input_dir.glob("gel_*MHz_angle_*.bin"), key=angle_from_name)
    else:
        files = sorted(files, key=angle_from_name)
    if not files:
        raise SystemExit("No gel_*MHz_angle_*.bin files found")
    capture_metadata_by_name = {
        entry.get("filename"): entry
        for entry in manifest.get("captures", [])
        if isinstance(entry, dict) and entry.get("filename")
    }
    source_files = list(files)
    source_angles = np.asarray([angle_from_name(path) for path in source_files], dtype=np.float64)
    if args.reconstruction_angle_step_deg is not None:
        requested_step = float(args.reconstruction_angle_step_deg)
        if requested_step <= 0:
            raise RuntimeError("Reconstruction angle step must be positive")
        anchor = float(source_angles[0])
        keep_mask = np.isclose(
            (source_angles - anchor) / requested_step,
            np.round((source_angles - anchor) / requested_step),
            atol=1e-6,
        )
        files = [path for path, keep in zip(source_files, keep_mask) if bool(keep)]
        if len(files) < 3:
            raise RuntimeError(
                f"Angle subset {requested_step:g} deg retained fewer than three files"
            )
    angles = np.asarray([angle_from_name(path) for path in files], dtype=np.float64)

    input_file_sha256: dict[str, str] = {}
    capture_digest = hashlib.sha256()
    for path in files:
        file_digest = sha256_file(path)
        input_file_sha256[path.name] = file_digest
        capture_digest.update(path.name.encode("utf-8"))
        capture_digest.update(bytes.fromhex(file_digest))
    capture_fingerprint = capture_digest.hexdigest()
    source_label = f"Run {input_dir.name} · data SHA-256 {capture_fingerprint[:12]}…"

    first = np.memmap(files[0], dtype="<u2", mode="r").reshape(-1, 16)
    duplicate_pairs = find_duplicate_pairs(first)
    duplicate_persistence = duplicate_pair_persistence(files, duplicate_pairs)

    configured_rx_slots = list(
        args.rx_channels
        if args.rx_channels is not None
        else array_config.get(
            "rx_hsdc_slots_1_based",
            list(range(9, 9 + active_tx_elements)),
        )
    )
    configured_rx_slots = [int(value) for value in configured_rx_slots]
    if len(configured_rx_slots) != active_tx_elements:
        raise RuntimeError(
            "Configured RX slot count must equal active physical T/R element count "
            f"({active_tx_elements}); got {configured_rx_slots}"
        )
    if len(set(configured_rx_slots)) != len(configured_rx_slots) or any(
        value < 1 or value > 16 for value in configured_rx_slots
    ):
        raise RuntimeError("Configured RX slots must be unique 1-based HSDC slots in 1..16")
    configured_rx_slot_set = set(configured_rx_slots)

    configured_duplicate_pairs = [
        (left, right)
        for left, right in duplicate_pairs
        if left in configured_rx_slot_set and right in configured_rx_slot_set
    ]
    auto_excluded_slots: set[int] = set()
    if args.duplicate_policy == "drop-later":
        configured_position = {
            slot: position for position, slot in enumerate(configured_rx_slots)
        }
        for left, right in configured_duplicate_pairs:
            later_slot = (
                left
                if configured_position[left] > configured_position[right]
                else right
            )
            auto_excluded_slots.add(later_slot)
        selected_rx_slots = [
            slot for slot in configured_rx_slots if slot not in auto_excluded_slots
        ]
    elif args.duplicate_policy == "keep-all":
        selected_rx_slots = list(configured_rx_slots)
    else:
        if args.das_rx_channels is None:
            raise RuntimeError(
                "--das-rx-channels is required when --duplicate-policy manual"
            )
        selected_rx_slots = [int(slot) for slot in args.das_rx_channels]
        if len(set(selected_rx_slots)) != len(selected_rx_slots):
            raise RuntimeError("Manual DAS RX slots must be unique")
        if not selected_rx_slots or any(
            slot not in configured_rx_slot_set for slot in selected_rx_slots
        ):
            raise RuntimeError(
                "Manual DAS RX slots must be a non-empty subset of configured RX slots"
            )
    rx_indices = [slot - 1 for slot in selected_rx_slots]
    if len(rx_indices) < 2:
        raise RuntimeError("Fewer than two independent receive channels remain after duplicate removal")
    distinct_parent = {slot: slot for slot in selected_rx_slots}

    def distinct_find(slot: int) -> int:
        while distinct_parent[slot] != slot:
            distinct_parent[slot] = distinct_parent[distinct_parent[slot]]
            slot = distinct_parent[slot]
        return slot

    retained_duplicate_pairs: list[list[int]] = []
    for left, right in duplicate_pairs:
        if left in distinct_parent and right in distinct_parent:
            retained_duplicate_pairs.append([left, right])
            left_root = distinct_find(left)
            right_root = distinct_find(right)
            if left_root != right_root:
                distinct_parent[right_root] = left_root
    distinct_waveform_count = len({distinct_find(slot) for slot in selected_rx_slots})
    physical_element_numbers = np.asarray(
        [
            physical_index + 1
            for physical_index, slot in enumerate(configured_rx_slots)
            if slot in selected_rx_slots
        ],
        dtype=np.float64,
    )
    element_x_m = (
        physical_element_numbers - (active_tx_elements + 1.0) / 2.0
    ) * PITCH_M
    receive_weights = receive_apodization_weights(
        args.receive_apodization,
        physical_element_numbers,
        active_tx_elements,
        args.tukey_alpha,
    )
    receive_weight_sum = float(np.sum(receive_weights))

    zero_degree_files = [path for path in files if angle_from_name(path) == 0]
    if not zero_degree_files:
        raise RuntimeError("A zero-degree capture is required to estimate the timing reference")

    received_freq_hz, received_pulse_power, received_peak_hz, received_event_count, received_prf_hz = (
        estimate_received_pulse_spectrum(zero_degree_files[0], rx_indices)
    )
    frequency_mismatch_fraction = abs(received_peak_hz - CENTER_FREQUENCY_HZ) / CENTER_FREQUENCY_HZ
    # Reconstruction follows the requested/known TX pattern.  A mismatching
    # received ring-down peak is diagnostic evidence, never a hidden command to
    # retune the image filter.
    processing_center_hz = CENTER_FREQUENCY_HZ
    processing_center_source = "requested/known TX pattern; received peak is diagnostic only"
    LOW_HZ = max(0.25e6, processing_center_hz * 0.60)
    HIGH_HZ = min(FS_HZ * 0.45, processing_center_hz * 1.40)

    marker_to_tx_samples = (
        float(args.tx_reference_samples)
        if args.tx_reference_samples is not None
        else estimate_tx_reference_samples(zero_degree_files[0], rx_indices)
    )

    if not (0.5 <= float(args.z_min_mm) < float(args.z_max_mm) <= 80.0):
        raise RuntimeError("Require 0.5 <= z-min-mm < z-max-mm <= 80")
    x_mm = np.linspace(-10.0, 10.0, 161)
    axial_step_target_mm = 0.125
    z_count = int(round((float(args.z_max_mm) - float(args.z_min_mm)) / axial_step_target_mm)) + 1
    z_mm = np.linspace(float(args.z_min_mm), float(args.z_max_mm), z_count)
    xx_m, zz_m = np.meshgrid(x_mm * 1e-3, z_mm * 1e-3)
    accumulated_power = np.zeros_like(xx_m, dtype=np.float64)
    angle_profiles: list[np.ndarray] = []
    event_spectra: list[np.ndarray] = []
    file_results: list[dict[str, object]] = []
    event_images_by_angle: list[list[np.ndarray]] = []
    event_markers_by_angle: list[list[int]] = []
    event_references_by_angle: list[list[int]] = []
    common_mode_removed_rms_fractions: list[float] = []
    reference_search_boundary_hits = 0
    reference_search_total = 0
    # Normal-trigger captures do not have a user-declared PRF contract.  The
    # acquisition manifest therefore stores JSON null at the top level (and
    # 0.0 in older/newer argument blocks).  dict.get(..., 1000.0) does not use
    # its default when the key exists with a null value, so never pass the raw
    # manifest value directly to float().  Prefer any finite positive value;
    # otherwise use the TX7316EVM CPLD's nominal 1 kHz PRF as the event-search
    # prior.  The measured PRF is still calculated from the accepted markers.
    expected_prf_hz = 1000.0
    manifest_arguments = manifest.get("arguments") or {}
    for candidate in (
        manifest.get("expected_prf_hz"),
        manifest_arguments.get("expected_prf_hz"),
    ):
        try:
            candidate_hz = float(candidate)
        except (TypeError, ValueError):
            continue
        if np.isfinite(candidate_hz) and candidate_hz > 0.0:
            expected_prf_hz = candidate_hz
            break

    for angle, path in zip(angles, files):
        data = np.memmap(path, dtype="<u2", mode="r").reshape(-1, 16)
        baseline = np.median(data[::256, :], axis=0).astype(np.float32)
        markers, prf_hz, event_validation = detect_events_validated(
            data,
            rx_indices,
            baseline,
            expected_prf_hz=expected_prf_hz,
        )
        event_analytic: list[np.ndarray] = []
        event_profiles: list[np.ndarray] = []
        event_reference_samples: list[int] = []

        for marker in markers:
            segment = data[marker : marker + WINDOW_SAMPLES, rx_indices].astype(np.float32)
            segment -= baseline[rx_indices]
            segment -= np.mean(segment[:64, :], axis=0, keepdims=True)
            detected_reference = event_direct_reference_samples(segment, 300, 950)
            event_reference_samples.append(detected_reference)
            reference_search_total += 1
            if detected_reference <= 302 or detected_reference >= 947:
                reference_search_boundary_hits += 1
            spectrum_window = segment[1200:6500, :]
            taper = np.hanning(spectrum_window.shape[0])[:, None]
            event_spectra.append(
                np.mean(np.abs(np.fft.rfft(spectrum_window * taper, n=8192, axis=0)) ** 2, axis=1)
            )
            processing_segment = segment
            if args.common_mode_ringdown_suppression:
                processing_segment, removed_fraction = suppress_gated_common_mode(
                    segment,
                    marker_to_tx_samples,
                    max_depth_mm=args.common_mode_max_depth_mm,
                    strength=args.common_mode_strength,
                )
                common_mode_removed_rms_fractions.append(float(removed_fraction))
            analytic = analytic_bandpass(processing_segment)
            event_analytic.append(analytic)
            channel_scale = np.percentile(np.abs(analytic[250:6500, :]), 99.5, axis=0)
            channel_scale = np.maximum(channel_scale, 1.0)
            event_profiles.append(np.median(np.abs(analytic) / channel_scale[None, :], axis=1))

        if not event_analytic:
            raise RuntimeError(f"No complete PRF events detected in {path.name}")

        angle_profile = np.median(np.stack(event_profiles, axis=0), axis=0)
        angle_profiles.append(angle_profile)

        theta = math.radians(float(angle))
        tx_time = (xx_m * math.sin(theta) + zz_m * math.cos(theta)) / C_M_S
        event_images: list[np.ndarray] = []
        # Use one record-wide marker-to-TX offset for reconstruction.  Per-event
        # searches are retained as QA only: when a decaying ring-down makes the
        # argmax land on the search boundary, treating that boundary as a newly
        # measured t0 shifts separate angles by an arbitrary amount and blurs the
        # compound image.  The amplitude marker grid itself is phase-stable to
        # sub-sample precision in validated captures.
        reconstruction_reference = float(marker_to_tx_samples)
        for analytic, event_reference in zip(event_analytic, event_reference_samples):
            coherent_sum = np.zeros_like(xx_m, dtype=np.complex128)
            weighted_incoherent_power = np.zeros_like(xx_m, dtype=np.float64)
            for channel, (element_x, channel_weight) in enumerate(
                zip(element_x_m, receive_weights)
            ):
                rx_time = np.sqrt((xx_m - element_x) ** 2 + zz_m**2) / C_M_S
                # Each PRF emission gets its own direct-coupling timing reference.
                # A single global offset can move a complete B-mode frame when
                # the largest raw sample changes from one edge/ring-down peak to
                # another.
                sample = (tx_time + rx_time) * FS_HZ + reconstruction_reference
                delayed = interp_complex(
                    analytic[:, channel], sample.ravel()
                ).reshape(sample.shape)
                coherent_sum += float(channel_weight) * delayed
                weighted_incoherent_power += float(channel_weight) * np.abs(delayed) ** 2
            event_image = np.abs(coherent_sum) / receive_weight_sum
            if args.coherence_factor:
                event_image *= coherence_factor_from_accumulators(
                    coherent_sum,
                    weighted_incoherent_power,
                    receive_weight_sum,
                ) ** float(args.coherence_factor_exponent)
            event_images.append(event_image)
        angle_image = np.median(np.stack(event_images, axis=0), axis=0)
        accumulated_power += angle_image**2
        event_images_by_angle.append(event_images)
        event_markers_by_angle.append(markers)
        event_references_by_angle.append(event_reference_samples)

        file_results.append(
            {
                "file": path.name,
                "angle_deg": int(angle),
                "profile_number": capture_metadata_by_name.get(path.name, {}).get("profile_number"),
                "profile_batch_number": capture_metadata_by_name.get(path.name, {}).get("profile_batch_number"),
                "hardware_profile_number": capture_metadata_by_name.get(path.name, {}).get("hardware_profile_number"),
                "events_used": len(event_analytic),
                "event_direct_reference_samples": event_reference_samples,
                "prf_hz": round(float(prf_hz), 3),
                "minimum_code": int(data.min()),
                "maximum_code": int(data.max()),
                "rail_sample_count": int(np.count_nonzero((data == 0) | (data == 65535))),
                "event_validation": event_validation,
            }
        )

    compound = np.sqrt(accumulated_power / len(files))
    # Mild display-only TGC. A stronger curve makes the electronic/noise floor
    # at 35-42 mm dominate this particular capture, so it is deliberately capped.
    tgc = np.clip((zz_m / 0.010) ** 0.35, 1.0, 2.2)
    compound_display = compound * tgc
    reference = float(np.percentile(compound_display, 99.8))
    bmode_db = 20.0 * np.log10(np.maximum(compound_display / reference, 1e-8))
    bmode_db = np.clip(bmode_db, -45.0, 0.0)

    # Preserve the PRF repeats instead of discarding them after the median.  The
    # 0-degree frames are true consecutive emissions inside one 8.74 ms HSDC
    # record.  Cross-angle frames below are only static-phantom QA because every
    # angle was saved in a separate acquisition tens of seconds apart.
    zero_angle_index = int(np.where(angles == 0)[0][0])
    zero_event_images = event_images_by_angle[zero_angle_index]
    zero_event_markers = event_markers_by_angle[zero_angle_index]
    zero_event_references = event_references_by_angle[zero_angle_index]
    nominal_prf_period_samples = FS_HZ / expected_prf_hz
    zero_event_ordinals = [
        int(round((marker - zero_event_markers[0]) / nominal_prf_period_samples)) + 1
        for marker in zero_event_markers
    ]
    zero_display_stack = np.stack([image * tgc for image in zero_event_images], axis=0)
    zero_reference = float(np.percentile(zero_display_stack, 99.8))
    zero_cycle_db = [
        np.clip(20.0 * np.log10(np.maximum(image / zero_reference, 1e-8)), -45.0, 0.0)
        for image in zero_display_stack
    ]
    zero_cycle_dir = output_dir / "prf_cycles" / "zero_degree"
    zero_cycle_dir.mkdir(parents=True, exist_ok=True)
    zero_cycle_metrics: list[dict[str, float | int | str]] = []
    zero_median = np.median(zero_display_stack, axis=0)
    median_flat = zero_median.ravel()
    median_norm = float(np.linalg.norm(median_flat))
    zero_energies = [float(np.mean(image**2)) for image in zero_display_stack]
    max_zero_energy = max(zero_energies) if zero_energies else 1.0
    zero_axial_profiles = [np.median(image, axis=1) for image in zero_display_stack]
    axial_reference_profile = zero_axial_profiles[0]
    axial_step_mm = float(z_mm[1] - z_mm[0])
    zero_axial_lags = [
        normalized_best_lag(axial_reference_profile, profile, max_lag=48)
        for profile in zero_axial_profiles
    ]
    for index, (db_image, linear_image, marker, event_reference, emission_ordinal, axial_lag) in enumerate(
        zip(
            zero_cycle_db,
            zero_display_stack,
            zero_event_markers,
            zero_event_references,
            zero_event_ordinals,
            zero_axial_lags,
        ),
        start=1,
    ):
        filename = f"zero_degree_prf_pulse_{index:02d}.png"
        time_ms = (marker - zero_event_markers[0]) / FS_HZ * 1e3
        vector = linear_image.ravel()
        denominator = float(np.linalg.norm(vector)) * median_norm
        correlation = float(np.dot(vector, median_flat) / denominator) if denominator else 0.0
        save_ultrasound_image(
            db_image,
            x_mm,
            z_mm,
            zero_cycle_dir / filename,
            len(rx_indices),
            source_label,
            title=(
                f"0° single-emission RX-DAS · emission {emission_ordinal} "
                f"({index}/{len(zero_cycle_db)} retained) · t={time_ms:.3f} ms"
            ),
        )
        zero_cycle_metrics.append(
            {
                "pulse_index": index,
                "emission_ordinal": emission_ordinal,
                "marker_sample": int(marker),
                "direct_reference_sample": int(event_reference),
                "relative_time_ms": round(float(time_ms), 6),
                "normalized_energy": round(zero_energies[index - 1] / max_zero_energy, 6),
                "cosine_similarity_to_cycle_median": round(correlation, 6),
                "axial_lag_to_first_mm": round(float(axial_lag[0] * axial_step_mm), 4),
                "axial_profile_correlation_to_first": round(float(axial_lag[1]), 6),
                "file": str(Path("prf_cycles") / "zero_degree" / filename),
            }
        )
    maximum_axial_drift_mm = max(
        (abs(float(item[0] * axial_step_mm)) for item in zero_axial_lags),
        default=0.0,
    )
    zero_validation_for_stability = file_results[zero_angle_index].get("event_validation", {})
    timing_residual_samples = float(
        zero_validation_for_stability.get("timing_residual_max_samples", float("inf"))
        if isinstance(zero_validation_for_stability, dict)
        else float("inf")
    )
    timing_grid_jitter_depth_mm = timing_residual_samples * C_M_S / (2.0 * FS_HZ) * 1e3
    minimum_cycle_similarity = min(
        (float(item["cosine_similarity_to_cycle_median"]) for item in zero_cycle_metrics),
        default=0.0,
    )
    # A full-profile RF correlation is highly ambiguous for a narrowband image:
    # it can jump to a neighbouring fringe and report several millimetres of
    # fictitious motion.  Use the measured event-grid jitter plus whole-image
    # repeatability as the primary stability verdict and retain the legacy lag as
    # an explicitly phase-ambiguous diagnostic only.
    fast_time_stable = timing_grid_jitter_depth_mm <= 0.05 and minimum_cycle_similarity >= 0.90
    save_cycle_montage(
        zero_cycle_db,
        x_mm,
        z_mm,
        output_dir / "zero_degree_prf_cycle_montage.png",
        source_label,
        "Consecutive 0° PRF emissions from one HSDC record",
    )

    common_event_count = min(len(images) for images in event_images_by_angle)
    indexed_compounds: list[np.ndarray] = []
    for event_index in range(common_event_count):
        event_power = np.zeros_like(xx_m, dtype=np.float64)
        for angle_images in event_images_by_angle:
            event_power += angle_images[event_index] ** 2
        indexed_compounds.append(np.sqrt(event_power / len(event_images_by_angle)) * tgc)
    indexed_stack = np.stack(indexed_compounds, axis=0)
    indexed_reference = float(np.percentile(indexed_stack, 99.8))
    indexed_cycle_db = [
        np.clip(20.0 * np.log10(np.maximum(image / indexed_reference, 1e-8)), -45.0, 0.0)
        for image in indexed_stack
    ]
    indexed_cycle_dir = output_dir / "prf_cycles" / "angle_compound_static_qa"
    indexed_cycle_dir.mkdir(parents=True, exist_ok=True)
    indexed_cycle_files: list[str] = []
    for index, db_image in enumerate(indexed_cycle_db, start=1):
        filename = f"angle_compound_prf_index_{index:02d}.png"
        save_ultrasound_image(
            db_image,
            x_mm,
            z_mm,
            indexed_cycle_dir / filename,
            len(rx_indices),
            source_label,
            title=f"Static-QA angle compound · PRF ordinal {index}/{common_event_count} · not time-synchronous",
        )
        indexed_cycle_files.append(str(Path("prf_cycles") / "angle_compound_static_qa" / filename))
    save_cycle_montage(
        indexed_cycle_db,
        x_mm,
        z_mm,
        output_dir / "angle_compound_prf_index_montage.png",
        source_label,
        "PRF-index angle compounds (angles acquired sequentially; static QA only)",
    )

    profiles = np.stack(angle_profiles, axis=0)
    q_for_depth = (2.0 * z_mm * 1e-3 / C_M_S) * FS_HZ + marker_to_tx_samples
    sampled_profiles = np.stack(
        [np.interp(q_for_depth, np.arange(WINDOW_SAMPLES), profile, left=0.0, right=0.0) for profile in profiles],
        axis=0,
    )
    sampled_profiles *= np.clip((z_mm[None, :] / 10.0) ** 0.35, 1.0, 2.2)
    scan_reference = float(np.percentile(sampled_profiles, 99.8))
    angle_depth_db = 20.0 * np.log10(np.maximum(sampled_profiles / scan_reference, 1e-8))
    angle_depth_db = np.clip(angle_depth_db, -45.0, 0.0)

    # Reflector ranges are estimated from the angle/RX envelope profile. It is
    # more robust than the lateral percentile of the sparse-aperture DAS image,
    # whose grating lobes otherwise bias the axial trace.
    axial_profile = np.percentile(sampled_profiles, 90, axis=0)
    axial_reference = float(np.max(axial_profile))
    axial_db = 20.0 * np.log10(np.maximum(axial_profile / axial_reference, 1e-8))
    axial_db = np.clip(axial_db, -45.0, 0.0)
    reflectors = detect_reflectors(z_mm, axial_db)

    save_ultrasound_image(
        bmode_db,
        x_mm,
        z_mm,
        output_dir / "plane_wave_das_bmode.png",
        len(rx_indices),
        source_label,
        title=(
            f"Plane-wave DAS · {active_tx_elements} physical T/R · "
            f"{len(rx_indices)} selected HSDC slots / {distinct_waveform_count} distinct · "
            f"RX {args.receive_apodization} · "
            f"CF {'on' if args.coherence_factor else 'off'} · "
            f"CM {'on' if args.common_mode_ringdown_suppression else 'off'}"
        ),
    )
    save_angle_depth_image(angle_depth_db.T, angles, z_mm, output_dir / "angle_depth_envelope.png", source_label)
    save_sector_image(angle_depth_db, angles, z_mm, output_dir / "sector_scan.png", source_label)
    save_profile_plot(z_mm, axial_db, reflectors, output_dir / "reflector_depth_profile.png", source_label)
    save_channel_diagnostics(first, duplicate_pairs, output_dir / "channel_diagnostics.png", source_label)
    zero_data = np.memmap(zero_degree_files[0], dtype="<u2", mode="r").reshape(-1, 16)
    zero_baseline = np.median(zero_data[::256, :], axis=0).astype(np.float32)
    zero_validation = file_results[zero_angle_index].get("event_validation", {})
    save_event_time_domain_plot(
        zero_data,
        rx_indices,
        zero_baseline,
        zero_event_markers,
        output_dir / "echo_time_domain_validation.png",
        source_label,
        zero_validation if isinstance(zero_validation, dict) else {},
    )

    # Compare the nominal 5--42 mm echo interval against an equal-length quiet
    # window approximately 500 us after TX.  Any ordinary phantom echo from the
    # displayed depth has ended long before the quiet window.  This prevents a
    # narrow-band electronics/noise floor from being mistaken for useful echo
    # simply because it lies inside the requested processing band.
    echo_start_offset = int(round(marker_to_tx_samples + 2.0 * 0.005 * FS_HZ / C_M_S))
    echo_stop_offset = int(round(marker_to_tx_samples + 2.0 * 0.042 * FS_HZ / C_M_S))
    echo_window_length = max(1, echo_stop_offset - echo_start_offset)
    quiet_start_offset = 60_000
    echo_powers: list[float] = []
    quiet_powers: list[float] = []
    for marker in zero_event_markers:
        if marker + quiet_start_offset + echo_window_length >= zero_data.shape[0]:
            continue
        echo_values = zero_data[
            marker + echo_start_offset : marker + echo_stop_offset,
            rx_indices,
        ].astype(np.float64)
        quiet_values = zero_data[
            marker + quiet_start_offset : marker + quiet_start_offset + echo_window_length,
            rx_indices,
        ].astype(np.float64)
        echo_values -= np.mean(echo_values, axis=0, keepdims=True)
        quiet_values -= np.mean(quiet_values, axis=0, keepdims=True)
        echo_powers.append(float(np.mean(echo_values**2)))
        quiet_powers.append(float(np.mean(quiet_values**2)))
    median_echo_power = float(np.median(echo_powers)) if echo_powers else float("nan")
    median_quiet_power = float(np.median(quiet_powers)) if quiet_powers else float("nan")
    echo_to_quiet_power_db = (
        10.0 * math.log10(median_echo_power / median_quiet_power)
        if median_echo_power > 0.0 and median_quiet_power > 0.0
        else float("nan")
    )
    excess_echo_snr_db = (
        10.0 * math.log10((median_echo_power - median_quiet_power) / median_quiet_power)
        if median_echo_power > median_quiet_power > 0.0
        else None
    )
    depth_window_power_qa: dict[str, dict[str, float | None]] = {}
    for window_name, depth_start_mm, depth_stop_mm in (
        ("shallow_4_to_8mm", 4.0, 8.0),
        ("internal_14_to_22mm", 14.0, 22.0),
        ("deep_34_to_42mm", 34.0, 42.0),
    ):
        start_offset = int(
            round(marker_to_tx_samples + 2.0 * depth_start_mm * 1e-3 * FS_HZ / C_M_S)
        )
        stop_offset = int(
            round(marker_to_tx_samples + 2.0 * depth_stop_mm * 1e-3 * FS_HZ / C_M_S)
        )
        window_length = max(1, stop_offset - start_offset)
        signal_powers: list[float] = []
        noise_powers: list[float] = []
        for marker in zero_event_markers:
            if marker + quiet_start_offset + window_length >= zero_data.shape[0]:
                continue
            signal_values = zero_data[
                marker + start_offset : marker + stop_offset,
                rx_indices,
            ].astype(np.float64)
            noise_values = zero_data[
                marker + quiet_start_offset : marker + quiet_start_offset + window_length,
                rx_indices,
            ].astype(np.float64)
            signal_values -= np.mean(signal_values, axis=0, keepdims=True)
            noise_values -= np.mean(noise_values, axis=0, keepdims=True)
            signal_powers.append(float(np.mean(signal_values**2)))
            noise_powers.append(float(np.mean(noise_values**2)))
        signal_power = float(np.median(signal_powers)) if signal_powers else float("nan")
        noise_power = float(np.median(noise_powers)) if noise_powers else float("nan")
        ratio_db = (
            10.0 * math.log10(signal_power / noise_power)
            if signal_power > 0.0 and noise_power > 0.0
            else float("nan")
        )
        excess_db = (
            10.0 * math.log10((signal_power - noise_power) / noise_power)
            if signal_power > noise_power > 0.0
            else None
        )
        depth_window_power_qa[window_name] = {
            "depth_start_mm": depth_start_mm,
            "depth_stop_mm": depth_stop_mm,
            "signal_to_late_quiet_power_db": round(ratio_db, 4),
            "noise_subtracted_snr_db": round(excess_db, 4) if excess_db is not None else None,
        }

    delayed_echo_power = np.median(np.stack(event_spectra, axis=0), axis=0)
    spectrum_freq_hz = np.fft.rfftfreq(8192, d=1.0 / FS_HZ)
    spectrum_mask = (spectrum_freq_hz >= 0.5e6) & (spectrum_freq_hz <= 8.0e6)
    spectrum_freq_mhz = spectrum_freq_hz[spectrum_mask] / 1e6
    delayed_echo_db = 10.0 * np.log10(
        np.maximum(
            delayed_echo_power[spectrum_mask] / np.max(delayed_echo_power[spectrum_mask]),
            1e-12,
        )
    )
    delayed_echo_peak_mhz = float(spectrum_freq_mhz[int(np.argmax(delayed_echo_db))])
    received_pulse_db = 10.0 * np.log10(
        np.maximum(
            received_pulse_power[spectrum_mask] / np.max(received_pulse_power[spectrum_mask]),
            1e-12,
        )
    )
    received_peak_mhz = received_peak_hz / 1e6
    echo_band_fraction = float(
        np.sum(delayed_echo_power[(spectrum_freq_hz >= LOW_HZ) & (spectrum_freq_hz <= HIGH_HZ)])
        / np.sum(delayed_echo_power[spectrum_mask])
    )
    save_spectrum_plot(
        spectrum_freq_mhz,
        received_pulse_db,
        received_peak_mhz,
        delayed_echo_db,
        delayed_echo_peak_mhz,
        CENTER_FREQUENCY_HZ / 1e6,
        output_dir / "echo_spectrum.png",
        source_label,
    )

    tx_original = manifest.get("tx_original", {}) if isinstance(manifest, dict) else {}
    waveform_readback = manifest.get("tx_waveform_readback", {}) if isinstance(manifest, dict) else {}
    captured_reg25_text = str(
        waveform_readback.get("register25", tx_original.get("register25", "unknown"))
        if isinstance(waveform_readback, dict)
        else tx_original.get("register25", "unknown")
    )
    try:
        captured_reg25 = int(captured_reg25_text, 0)
    except (TypeError, ValueError):
        captured_reg25 = None
    known_pattern_reference: dict[str, object] = {
        "requested_name": (
            waveform_readback.get("reference_name", "no bundled reference")
            if isinstance(waveform_readback, dict)
            else "no bundled reference"
        ),
        "capture_manifest_register25": captured_reg25_text,
        "pattern_profile_registers_recorded_during_capture": bool(waveform_readback),
    }
    if isinstance(waveform_readback, dict) and waveform_readback:
        known_pattern_reference["captured_readback"] = waveform_readback
        reference_matches = waveform_readback.get("reference_matches") is True
        known_pattern_reference.update(
            {
                "reference_register25": waveform_readback.get("reference_register25", "unknown"),
                "reference_pattern_clock_hz": waveform_readback.get("pattern_clock_hz"),
                "reference_base_pattern_clock_cycles": waveform_readback.get("base_pattern_clocks"),
                "reference_base_pattern_repetition_mhz": round(
                    float(waveform_readback.get("nominal_base_pattern_hz", 0.0)) / 1e6,
                    6,
                ),
                "register25_matches_reference": (
                    captured_reg25_text.casefold()
                    == str(waveform_readback.get("reference_register25", "")).casefold()
                ),
                "status": (
                    "verified against captured TX pattern readback"
                    if reference_matches
                    else "captured TX pattern/readback mismatch"
                ),
                "warning": "The received ring-down peak cannot verify the electrical TX frequency. Register readback verifies programmed timing only; an oscilloscope or hydrophone remains the definitive electrical/acoustic check.",
            }
        )
    else:
        known_pattern_reference.update(
            {
                "status": "no matching bundled TX reference decoded",
                "warning": "Received spectral peaks do not directly verify the TX7316 electrical waveform.",
            }
        )

    summary = {
        "method": "%d physical T/R elements; %d selected HSDC slots representing %d distinguishable waveforms; RX %s apodization; coherence factor %s; shallow common-mode suppression %s; median summary plus per-PRF frames; incoherent power compounding over %d transmit angles"
        % (
            active_tx_elements,
            len(rx_indices),
            distinct_waveform_count,
            args.receive_apodization,
            "enabled" if args.coherence_factor else "disabled",
            "enabled" if args.common_mode_ringdown_suppression else "disabled",
            len(files),
        ),
        "sampling_rate_hz": FS_HZ,
        "sound_speed_m_s": C_M_S,
        "input_directory": str(input_dir),
        "output_directory": str(output_dir),
        "capture_fingerprint_sha256": capture_fingerprint,
        "input_file_sha256": input_file_sha256,
        "array_pitch_mm": PITCH_M * 1e3,
        "active_tx_elements": active_tx_elements,
        "physical_tr_elements": active_tx_elements,
        "hsdc_output_slots": 16,
        "configured_rx_hsdc_slots_1_based": configured_rx_slots,
        "duplicate_handling_policy": args.duplicate_policy,
        "manual_das_rx_slots_requested_1_based": (
            list(args.das_rx_channels) if args.das_rx_channels is not None else None
        ),
        "excluded_rx_slots_1_based": [
            slot for slot in configured_rx_slots if slot not in selected_rx_slots
        ],
        "selected_das_rx_slots_1_based": selected_rx_slots,
        "selected_rx_slot_count": len(rx_indices),
        "unique_rx_waveforms_used": distinct_waveform_count,
        "receive_apodization": {
            "mode": args.receive_apodization,
            "tukey_alpha": float(args.tukey_alpha),
            "physical_element_numbers": physical_element_numbers.astype(int).tolist(),
            "selected_weights": np.round(receive_weights, 8).tolist(),
            "weight_sum": round(receive_weight_sum, 8),
        },
        "coherence_factor": {
            "enabled": bool(args.coherence_factor),
            "definition": "abs(sum(w*x))^2 / (sum(w) * sum(w*abs(x)^2))",
            "exponent": float(args.coherence_factor_exponent),
            "application": "CF^exponent multiplies each single-emission DAS amplitude before temporal/angle compounding",
        },
        "common_mode_ringdown_suppression": {
            "enabled": bool(args.common_mode_ringdown_suppression),
            "maximum_depth_mm": float(args.common_mode_max_depth_mm),
            "strength": float(args.common_mode_strength),
            "mean_removed_rms_fraction_in_gate": round(
                float(np.mean(common_mode_removed_rms_fractions)), 6
            )
            if common_mode_removed_rms_fractions
            else 0.0,
            "safety_scope": "cosine-tapered shallow post-TX gate only; full-depth median subtraction is intentionally not used",
        },
        "retained_exact_duplicate_pairs": retained_duplicate_pairs,
        "dropped_duplicate_slots_1_based": sorted(auto_excluded_slots),
        "tx_profile_batch_count": array_config.get("profile_batch_count", 1),
        "angle_profile_programming_batch_count": array_config.get("profile_batch_count", 1),
        "tx_profile_batches": manifest.get("tx_profile_batches", []),
        "requested_tx_center_frequency_mhz": CENTER_FREQUENCY_HZ / 1e6,
        "center_frequency_mhz": CENTER_FREQUENCY_HZ / 1e6,
        "received_pulse_ringdown_peak_mhz": round(received_peak_mhz, 4),
        "delayed_echo_window_peak_mhz": round(delayed_echo_peak_mhz, 4),
        "received_to_requested_frequency_ratio": round(received_peak_hz / CENTER_FREQUENCY_HZ, 5),
        "processing_band_center_source": processing_center_source,
        "tx_waveform_reference_check": known_pattern_reference,
        "bandpass_hz": [LOW_HZ, HIGH_HZ],
        "marker_to_tx_samples": marker_to_tx_samples,
        "marker_to_tx_us": round(marker_to_tx_samples / FS_HZ * 1e6, 4),
        "timing_reference_method": "median direct-coupling pulse center in the zero-degree capture",
        "reconstruction_timing_reference_method": "one fixed zero-degree marker-to-TX offset for every event and angle",
        "timing_reference_search_boundary_hits": reference_search_boundary_hits,
        "timing_reference_search_total": reference_search_total,
        "timing_reference_search_valid": reference_search_total > 0 and reference_search_boundary_hits == 0,
        "calibration_status": "soft PRF-marker alignment only; no per-channel cable/phase/gain, sound-speed, element-position, or known-phantom-depth calibration has been applied",
        "measured_echo_spectral_peak_mhz": round(received_peak_mhz, 4),
        "delayed_echo_power_fraction_in_processing_band": round(echo_band_fraction, 4),
        "echo_5_to_42mm_vs_late_quiet_power_db": round(echo_to_quiet_power_db, 4),
        "noise_subtracted_echo_snr_db": (
            round(excess_echo_snr_db, 4) if excess_echo_snr_db is not None else None
        ),
        "late_quiet_window_start_us": round(quiet_start_offset / FS_HZ * 1e6, 3),
        "depth_window_power_qa": depth_window_power_qa,
        "received_spectrum_event_count": received_event_count,
        "zero_degree_record_prf_hz": round(float(received_prf_hz), 3),
        "angles_deg": angles.astype(int).tolist(),
        "source_angles_deg": source_angles.astype(int).tolist(),
        "source_angle_count": len(source_files),
        "reconstruction_angle_step_deg": args.reconstruction_angle_step_deg,
        "reconstruction_angle_subset_count": len(files),
        "receiver_channels_used_1_based": [index + 1 for index in rx_indices],
        "assumed_physical_elements": physical_element_numbers.astype(int).tolist(),
        "rx_mapping_warning": (
            "The physical A1..A%d receive elements are configured in order on HSDC slots %s. "
            "Duplicate handling is user-selectable and this run used policy '%s', producing "
            "DAS slots %s. Exact digital duplicates cannot be interpreted as two independent "
            "physical measurements until the SMA-to-HSDC map is verified. The %d-waveform DAS "
            "is diagnostic, not a validated %d-RX image."
            % (
                active_tx_elements,
                configured_rx_slots,
                args.duplicate_policy,
                selected_rx_slots,
                distinct_waveform_count,
                active_tx_elements,
            )
        ),
        "exact_duplicate_channel_pairs": duplicate_pairs,
        "duplicate_pair_persistence": duplicate_persistence,
        "duplicate_channel_interpretation": "bit-for-bit digital HSDC output-slot duplication; not plausible analog crosstalk and not a reconstruction threshold artifact",
        "event_detection_policy": "all complete events on the fitted PRF grid are retained; RF-template correlation is reported as QA and never silently deletes an emission",
        "echo_time_domain_validation": "echo_time_domain_validation.png",
        "zero_degree_prf_cycles": zero_cycle_metrics,
        "zero_degree_prf_cycle_count": len(zero_cycle_metrics),
        "zero_degree_fast_time_stability": {
            "stable": fast_time_stable,
            # Compatibility key consumed by the current desktop UI.  It now
            # reports marker-grid jitter rather than a fringe-ambiguous RF lag.
            "maximum_axial_drift_mm": round(timing_grid_jitter_depth_mm, 6),
            "event_grid_jitter_depth_mm": round(timing_grid_jitter_depth_mm, 6),
            "event_grid_jitter_threshold_mm": 0.05,
            "minimum_cycle_image_similarity": round(minimum_cycle_similarity, 6),
            "minimum_cycle_image_similarity_threshold": 0.90,
            "legacy_phase_ambiguous_profile_lag_mm": round(maximum_axial_drift_mm, 4),
            "interpretation": (
                "event grid and reconstructed image repeatability pass the diagnostic thresholds"
                if fast_time_stable
                else "event timing or image repeatability failed; moving horizontal bands are not credible static-phantom motion and should be treated as interference/ringing/reconstruction artifacts"
            ),
        },
        "zero_degree_prf_cycle_montage": "zero_degree_prf_cycle_montage.png",
        "angle_compound_prf_index_count": common_event_count,
        "angle_compound_prf_index_files": indexed_cycle_files,
        "angle_compound_prf_index_montage": "angle_compound_prf_index_montage.png",
        "angle_compound_prf_index_warning": "Each steering angle was captured in a separate HSDC acquisition; equal PRF ordinals across angles are not the same physical time and are valid only for static-phantom QA, not cardiac-cycle imaging.",
        "reflector_candidates": reflectors,
        "distance_systematic_uncertainty_mm": 1.0,
        "display_reference_linear": reference,
        "file_results": file_results,
    }
    (output_dir / "analysis_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    compact_db = bmode_db[::2, ::2]
    compact_u8 = np.uint8(np.round(np.clip((compact_db + 45.0) / 45.0, 0.0, 1.0) * 255.0))
    visual = {
        "x_min_mm": float(x_mm[0]),
        "x_max_mm": float(x_mm[-1]),
        "z_min_mm": float(z_mm[0]),
        "z_max_mm": float(z_mm[-1]),
        "bmode_nx": int(compact_u8.shape[1]),
        "bmode_nz": int(compact_u8.shape[0]),
        "bmode_u8_base64": base64.b64encode(compact_u8.tobytes()).decode("ascii"),
        "profile_depth_mm": np.round(z_mm[::2], 3).tolist(),
        "profile_db": np.round(axial_db[::2], 2).tolist(),
        "reflectors": reflectors,
        "prf_hz": round(float(np.median([result["prf_hz"] for result in file_results])), 3),
        "events_total": int(sum(result["events_used"] for result in file_results)),
        "spectrum_frequency_mhz": np.round(spectrum_freq_mhz[::4], 4).tolist(),
        "spectrum_db": np.round(received_pulse_db[::4], 2).tolist(),
        "delayed_echo_spectrum_db": np.round(delayed_echo_db[::4], 2).tolist(),
        "spectral_peak_mhz": round(received_peak_mhz, 4),
        "delayed_echo_spectral_peak_mhz": round(delayed_echo_peak_mhz, 4),
        "zero_degree_prf_cycle_count": len(zero_cycle_metrics),
        "angle_compound_prf_index_count": common_event_count,
        "receive_apodization_mode": args.receive_apodization,
        "coherence_factor_enabled": bool(args.coherence_factor),
        "common_mode_ringdown_suppression_enabled": bool(
            args.common_mode_ringdown_suppression
        ),
        "capture_fingerprint_sha256": capture_fingerprint,
        "input_directory": str(input_dir),
    }
    (output_dir / "visual_data.json").write_text(json.dumps(visual, separators=(",", ":")), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
