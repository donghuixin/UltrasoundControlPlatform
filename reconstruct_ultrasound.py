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


def moving_average(values: np.ndarray, length: int) -> np.ndarray:
    length = max(1, int(length))
    return np.convolve(values, np.ones(length, dtype=np.float64) / length, mode="same")


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
    pairs: list[list[int]] = []
    probe = np.asarray(data[::257, :])
    for left in range(probe.shape[1]):
        for right in range(left + 1, probe.shape[1]):
            if np.array_equal(probe[:, left], probe[:, right]):
                pairs.append([left + 1, right + 1])
    return pairs


def detect_events(data: np.ndarray, channel_indices: list[int], baseline: np.ndarray) -> tuple[list[int], float]:
    signal = data[:, channel_indices].astype(np.float32) - baseline[channel_indices]
    score = np.max(np.abs(signal), axis=1)
    smoothed = moving_average(score, 32)
    threshold = max(1200.0, float(np.percentile(smoothed, 99.5)) * 0.55)
    candidates = np.where(
        (smoothed[1:-1] > smoothed[:-2])
        & (smoothed[1:-1] >= smoothed[2:])
        & (smoothed[1:-1] > threshold)
    )[0] + 1
    ordered = candidates[np.argsort(smoothed[candidates])[::-1]]
    centers: list[int] = []
    for candidate in ordered:
        position = int(candidate)
        if all(abs(position - existing) > 60_000 for existing in centers):
            centers.append(position)
        if len(centers) >= 12:
            break
    centers.sort()

    refined: list[int] = []
    for center in centers:
        if center < 1000 or center + WINDOW_SAMPLES + 500 >= data.shape[0]:
            continue
        lo = center - 180
        hi = center + 181
        marker = lo + int(np.argmax(score[lo:hi]))
        refined.append(marker)

    if len(refined) >= 2:
        period = float(np.median(np.diff(refined)))
        prf_hz = FS_HZ / period
    else:
        prf_hz = float("nan")
    return refined, prf_hz


def interp_complex(signal: np.ndarray, sample_positions: np.ndarray) -> np.ndarray:
    positions = np.arange(signal.shape[0], dtype=np.float64)
    real = np.interp(sample_positions, positions, signal.real, left=0.0, right=0.0)
    imag = np.interp(sample_positions, positions, signal.imag, left=0.0, right=0.0)
    return real + 1j * imag


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
) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 9.4), dpi=220, facecolor="black")
    ax.set_facecolor("black")
    ax.imshow(
        db_image,
        cmap="gray",
        vmin=-45.0,
        vmax=0.0,
        extent=[x_mm[0], x_mm[-1], z_mm[-1], z_mm[0]],
        aspect="auto",
        interpolation="bilinear",
    )
    ax.set_title(f"Soft-aligned plane-wave DAS · {rx_count} unique RX", color="white", fontsize=15, pad=28)
    ax.text(0.5, 1.014, source_label, transform=ax.transAxes, ha="center", va="bottom", color="#AFC4DC", fontsize=9)
    ax.set_xlabel("Lateral position (mm)", color="white", labelpad=9)
    ax.set_ylabel("Depth (mm)", color="white", labelpad=9)
    ax.tick_params(colors="#D6DEE8")
    for spine in ax.spines.values():
        spine.set_color("#8293A8")
    fig.tight_layout(pad=1.6)
    save_figure_pair(fig, path)


def save_angle_depth_image(
    db_image: np.ndarray,
    angles: np.ndarray,
    depth_mm: np.ndarray,
    path: Path,
    source_label: str,
) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 7.2), dpi=220, facecolor="black")
    ax.set_facecolor("black")
    ax.imshow(
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
    ax.imshow(
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
    fig.tight_layout(pad=1.5)
    save_figure_pair(fig, path)


def save_spectrum_plot(
    freq_mhz: np.ndarray,
    spectrum_db: np.ndarray,
    peak_mhz: float,
    path: Path,
    source_label: str,
) -> None:
    fig, ax = plt.subplots(figsize=(10.0, 5.4), dpi=220, facecolor="white")
    ax.plot(freq_mhz, spectrum_db, color="#1E5EFF", linewidth=1.6)
    ax.axvline(peak_mhz, color="#C23A42", linewidth=1.5, label=f"Peak {peak_mhz:.3f} MHz")
    ax.set_title("Median echo spectrum across detected transmit events", fontsize=14, pad=24)
    ax.text(0.5, 1.012, source_label, transform=ax.transAxes, ha="center", va="bottom", color="#60738A", fontsize=9)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Relative power (dB)")
    ax.set_xlim(0.5, 8.0)
    ax.set_ylim(-45.0, 1.0)
    ax.grid(True, color="#DDE7F2", linewidth=0.8)
    ax.legend(loc="upper right", frameon=False)
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
        analytic = analytic_bandpass(segment)
        energy = np.percentile(np.abs(analytic), 90.0, axis=1)
        centers.append(400 + int(np.argmax(energy[400:900])))
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
    LOW_HZ = max(0.25e6, CENTER_FREQUENCY_HZ * 0.60)
    HIGH_HZ = min(FS_HZ * 0.45, CENTER_FREQUENCY_HZ * 1.40)

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

    duplicate_right_channels = {
        right - 1
        for left, right in duplicate_pairs
        if left <= active_tx_elements and right <= active_tx_elements
    }
    rx_indices = [
        index for index in range(active_tx_elements) if index not in duplicate_right_channels
    ]
    if len(rx_indices) < 2:
        raise RuntimeError("Fewer than two independent receive channels remain after duplicate removal")
    physical_element_numbers = np.asarray([index + 1 for index in rx_indices], dtype=np.float64)
    element_x_m = (
        physical_element_numbers - (active_tx_elements + 1.0) / 2.0
    ) * PITCH_M

    zero_degree_files = [path for path in files if angle_from_name(path) == 0]
    if not zero_degree_files:
        raise RuntimeError("A zero-degree capture is required to estimate the timing reference")
    marker_to_tx_samples = (
        float(args.tx_reference_samples)
        if args.tx_reference_samples is not None
        else estimate_tx_reference_samples(zero_degree_files[0], rx_indices)
    )

    x_mm = np.linspace(-10.0, 10.0, 161)
    z_mm = np.linspace(8.0, 42.0, 273)
    xx_m, zz_m = np.meshgrid(x_mm * 1e-3, z_mm * 1e-3)
    accumulated_power = np.zeros_like(xx_m, dtype=np.float64)
    angle_profiles: list[np.ndarray] = []
    event_spectra: list[np.ndarray] = []
    file_results: list[dict[str, float | int | str]] = []

    for angle, path in zip(angles, files):
        data = np.memmap(path, dtype="<u2", mode="r").reshape(-1, 16)
        baseline = np.median(data[::256, :], axis=0).astype(np.float32)
        markers, prf_hz = detect_events(data, rx_indices, baseline)
        event_analytic: list[np.ndarray] = []
        event_profiles: list[np.ndarray] = []

        for marker in markers:
            segment = data[marker : marker + WINDOW_SAMPLES, rx_indices].astype(np.float32)
            segment -= baseline[rx_indices]
            segment -= np.mean(segment[:64, :], axis=0, keepdims=True)
            spectrum_window = segment[1200:6500, :]
            taper = np.hanning(spectrum_window.shape[0])[:, None]
            event_spectra.append(
                np.mean(np.abs(np.fft.rfft(spectrum_window * taper, n=8192, axis=0)) ** 2, axis=1)
            )
            analytic = analytic_bandpass(segment)
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
        for analytic in event_analytic:
            coherent_sum = np.zeros_like(xx_m, dtype=np.complex128)
            for channel, element_x in enumerate(element_x_m):
                rx_time = np.sqrt((xx_m - element_x) ** 2 + zz_m**2) / C_M_S
                sample = (tx_time + rx_time) * FS_HZ + marker_to_tx_samples
                coherent_sum += interp_complex(analytic[:, channel], sample.ravel()).reshape(sample.shape)
            event_images.append(np.abs(coherent_sum) / len(rx_indices))
        angle_image = np.median(np.stack(event_images, axis=0), axis=0)
        accumulated_power += angle_image**2

        file_results.append(
            {
                "file": path.name,
                "angle_deg": int(angle),
                "profile_number": capture_metadata_by_name.get(path.name, {}).get("profile_number"),
                "profile_batch_number": capture_metadata_by_name.get(path.name, {}).get("profile_batch_number"),
                "hardware_profile_number": capture_metadata_by_name.get(path.name, {}).get("hardware_profile_number"),
                "events_used": len(event_analytic),
                "prf_hz": round(float(prf_hz), 3),
                "minimum_code": int(data.min()),
                "maximum_code": int(data.max()),
                "rail_sample_count": int(np.count_nonzero((data == 0) | (data == 65535))),
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
    )
    save_angle_depth_image(angle_depth_db.T, angles, z_mm, output_dir / "angle_depth_envelope.png", source_label)
    save_sector_image(angle_depth_db, angles, z_mm, output_dir / "sector_scan.png", source_label)
    save_profile_plot(z_mm, axial_db, reflectors, output_dir / "reflector_depth_profile.png", source_label)
    save_3d_surface(bmode_db, x_mm, z_mm, output_dir / "bmode_3d_surface.png", source_label)

    spectrum_power = np.median(np.stack(event_spectra, axis=0), axis=0)
    spectrum_freq_hz = np.fft.rfftfreq(8192, d=1.0 / FS_HZ)
    spectrum_mask = (spectrum_freq_hz >= 0.5e6) & (spectrum_freq_hz <= 8.0e6)
    spectrum_freq_mhz = spectrum_freq_hz[spectrum_mask] / 1e6
    spectrum_db = 10.0 * np.log10(
        np.maximum(spectrum_power[spectrum_mask] / np.max(spectrum_power[spectrum_mask]), 1e-12)
    )
    spectral_peak_mhz = float(spectrum_freq_mhz[int(np.argmax(spectrum_db))])
    echo_band_fraction = float(
        np.sum(spectrum_power[(spectrum_freq_hz >= LOW_HZ) & (spectrum_freq_hz <= HIGH_HZ)])
        / np.sum(spectrum_power[spectrum_mask])
    )
    save_spectrum_plot(spectrum_freq_mhz, spectrum_db, spectral_peak_mhz, output_dir / "echo_spectrum.png", source_label)

    summary = {
        "method": "%d-unique-channel receive DAS, envelope median over PRF events, incoherent power compounding over %d transmit angles"
        % (len(rx_indices), len(files)),
        "sampling_rate_hz": FS_HZ,
        "sound_speed_m_s": C_M_S,
        "input_directory": str(input_dir),
        "output_directory": str(output_dir),
        "capture_fingerprint_sha256": capture_fingerprint,
        "input_file_sha256": input_file_sha256,
        "array_pitch_mm": PITCH_M * 1e3,
        "active_tx_elements": active_tx_elements,
        "tx_profile_batch_count": array_config.get("profile_batch_count", 1),
        "tx_profile_batches": manifest.get("tx_profile_batches", []),
        "center_frequency_mhz": CENTER_FREQUENCY_HZ / 1e6,
        "bandpass_hz": [LOW_HZ, HIGH_HZ],
        "marker_to_tx_samples": marker_to_tx_samples,
        "marker_to_tx_us": round(marker_to_tx_samples / FS_HZ * 1e6, 4),
        "timing_reference_method": "median direct-coupling pulse center in the zero-degree capture",
        "measured_echo_spectral_peak_mhz": round(spectral_peak_mhz, 4),
        "echo_power_fraction_in_configured_band": round(echo_band_fraction, 4),
        "angles_deg": angles.astype(int).tolist(),
        "receiver_channels_used_1_based": [index + 1 for index in rx_indices],
        "assumed_physical_elements": physical_element_numbers.astype(int).tolist(),
        "exact_duplicate_channel_pairs": duplicate_pairs,
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
        "spectrum_db": np.round(spectrum_db[::4], 2).tolist(),
        "spectral_peak_mhz": round(spectral_peak_mhz, 4),
        "capture_fingerprint_sha256": capture_fingerprint,
        "input_directory": str(input_dir),
    }
    (output_dir / "visual_data.json").write_text(json.dumps(visual, separators=(",", ":")), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
