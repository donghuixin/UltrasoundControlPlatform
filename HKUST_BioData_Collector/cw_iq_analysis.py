"""Inspect one HSDC AFE58JD48 demod capture and create an operator preview."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal


WORDS_PER_IQ_FRAME = 16  # I1,Q1,...,I8,Q8


def load_iq(path: Path) -> np.memmap:
    words = path.stat().st_size // 2
    if words == 0 or words % WORDS_PER_IQ_FRAME:
        raise ValueError(f"{path.name} is not a complete 16-word I/Q capture")
    raw = np.memmap(path, dtype="<u2", mode="r")
    # HSDC profile Data Postprocessing=1:32768 converts offset binary.
    signed = np.bitwise_xor(raw, np.uint16(0x8000)).view("<i2")
    return signed.reshape((-1, WORDS_PER_IQ_FRAME))


def analyze_iq_capture(
    bin_path: Path,
    output_rate_hz: float,
    output_dir: Path,
    rx_channels: tuple[int, ...] = (1, 2, 3),
) -> dict:
    if output_rate_hz <= 0:
        raise ValueError("output_rate_hz must be positive")
    matrix = load_iq(bin_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = tuple(channel for channel in rx_channels if 1 <= channel <= 8)
    if not selected:
        raise ValueError("at least one RX channel in 1..8 is required")

    max_preview = min(matrix.shape[0], 1_000_000)
    start = max(0, (matrix.shape[0] - max_preview) // 2)
    stop = start + max_preview
    preview = np.asarray(matrix[start:stop], dtype=np.float32)
    time_stride = max(1, preview.shape[0] // 6000)

    fig, axes = plt.subplots(2, 1, figsize=(11.2, 6.4), constrained_layout=True)
    summaries = []
    colors = ("#1E5EFF", "#00A7C8", "#D97706", "#7C3AED")
    for index, channel in enumerate(selected):
        i_data = preview[:, 2 * (channel - 1)]
        q_data = preview[:, 2 * (channel - 1) + 1]
        complex_data = i_data + 1j * q_data
        centered = complex_data - np.mean(complex_data)
        t_ms = np.arange(0, preview.shape[0], time_stride) / output_rate_hz * 1e3
        axes[0].plot(
            t_ms,
            np.abs(complex_data[::time_stride]),
            lw=0.8,
            color=colors[index % len(colors)],
            label=f"CH{channel}",
        )
        spectrum_samples = centered[: min(centered.size, 262_144)]
        window = signal.windows.hann(spectrum_samples.size, sym=False)
        spectrum = np.fft.fftshift(np.fft.fft(spectrum_samples * window))
        frequencies = np.fft.fftshift(np.fft.fftfreq(spectrum_samples.size, 1.0 / output_rate_hz))
        magnitude = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1.0))
        magnitude -= np.max(magnitude)
        band = np.abs(frequencies) <= min(100_000.0, output_rate_hz / 2.0)
        axes[1].plot(
            frequencies[band] / 1e3,
            magnitude[band],
            lw=0.9,
            color=colors[index % len(colors)],
            label=f"CH{channel}",
        )
        peak_index = int(np.argmax(np.abs(spectrum)))
        summaries.append(
            {
                "channel": channel,
                "i_rms_codes": float(np.sqrt(np.mean(i_data * i_data))),
                "q_rms_codes": float(np.sqrt(np.mean(q_data * q_data))),
                "mean_magnitude_codes": float(np.mean(np.abs(complex_data))),
                "peak_baseband_hz": float(frequencies[peak_index]),
            }
        )

    axes[0].set_title("Captured complex I/Q magnitude")
    axes[0].set_xlabel("Preview time (ms)")
    axes[0].set_ylabel("Magnitude (ADC codes)")
    axes[0].grid(alpha=0.2)
    axes[0].legend(ncol=len(selected))
    axes[1].set_title("Baseband spectrum (DC removed)")
    axes[1].set_xlabel("Frequency (kHz)")
    axes[1].set_ylabel("Relative level (dB)")
    axes[1].set_ylim(-90, 3)
    axes[1].grid(alpha=0.2)
    axes[1].legend(ncol=len(selected))
    fig.suptitle(f"{bin_path.name} · {output_rate_hz / 1e6:g} MSPS · I/Q pair mapping")

    image_path = output_dir / "cw_iq_preview.png"
    fig.savefig(image_path, dpi=150)
    plt.close(fig)
    result = {
        "schema": "hkust-cw-iq-analysis/v1",
        "input": str(bin_path.resolve()),
        "frames": int(matrix.shape[0]),
        "duration_s": float(matrix.shape[0] / output_rate_hz),
        "output_rate_hz": float(output_rate_hz),
        "mapping": "I1,Q1,I2,Q2,...,I8,Q8",
        "channels": summaries,
        "preview": str(image_path.resolve()),
    }
    (output_dir / "cw_iq_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bin", type=Path)
    parser.add_argument("--output-rate-hz", type=float, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--rx-channels", default="1,2,3")
    args = parser.parse_args()
    channels = tuple(int(value) for value in args.rx_channels.split(",") if value.strip())
    output_dir = args.output_dir or args.bin.parent / "analysis" / "cw_iq"
    result = analyze_iq_capture(args.bin, args.output_rate_hz, output_dir, channels)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
