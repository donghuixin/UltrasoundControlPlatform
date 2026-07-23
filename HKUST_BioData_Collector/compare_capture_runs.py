"""Compare two completed HKUST capture runs without rerunning beamforming.

The script reads each run's analysis/visual_data.json, reconstructs the compact
B-mode matrix, calculates normalized-image similarity, samples matching BIN
files for raw ADC correlation, and writes an auditable PNG/SVG/JSON report.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
matplotlib.rcParams["svg.fonttype"] = "none"
import matplotlib.pyplot as plt
import numpy as np


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_visual(run: Path) -> tuple[np.ndarray, dict, dict]:
    visual = read_json(run / "analysis" / "visual_data.json")
    summary = read_json(run / "analysis" / "analysis_summary.json")
    raw = base64.b64decode(visual["bmode_u8_base64"])
    image = np.frombuffer(raw, dtype=np.uint8).reshape(
        int(visual["bmode_nz"]), int(visual["bmode_nx"])
    )
    return image.astype(np.float64), visual, summary


def sampled_raw_metrics(old_run: Path, new_run: Path) -> list[dict]:
    rows: list[dict] = []
    for old_file in sorted(old_run.glob("*.bin")):
        new_file = new_run / old_file.name
        if not new_file.exists():
            continue
        old = np.memmap(old_file, dtype="<u2", mode="r")[::4096].astype(np.float64)
        new = np.memmap(new_file, dtype="<u2", mode="r")[::4096].astype(np.float64)
        length = min(old.size, new.size)
        old = old[:length]
        new = new[:length]
        rows.append(
            {
                "file": old_file.name,
                "sampled_values": int(length),
                "correlation": round(float(np.corrcoef(old, new)[0, 1]), 6),
                "rms_difference_codes": round(float(np.sqrt(np.mean((old - new) ** 2))), 3),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two reconstructed capture runs")
    parser.add_argument("old_run", type=Path)
    parser.add_argument("new_run", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    old_run = args.old_run.resolve()
    new_run = args.new_run.resolve()
    output_dir = (args.output_dir or (new_run.parent / f"comparison_{old_run.name}_vs_{new_run.name}")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    old_image, old_visual, old_summary = load_visual(old_run)
    new_image, new_visual, new_summary = load_visual(new_run)
    if old_image.shape != new_image.shape:
        raise RuntimeError(f"B-mode shapes differ: {old_image.shape} vs {new_image.shape}")

    signed_difference = new_image - old_image
    absolute_difference = np.abs(signed_difference)
    image_correlation = float(np.corrcoef(old_image.ravel(), new_image.ravel())[0, 1])
    mean_absolute_difference = float(np.mean(absolute_difference))
    rms_difference = float(np.sqrt(np.mean(signed_difference**2)))
    raw_metrics = sampled_raw_metrics(old_run, new_run)

    extent = [
        float(old_visual["x_min_mm"]),
        float(old_visual["x_max_mm"]),
        float(old_visual["z_max_mm"]),
        float(old_visual["z_min_mm"]),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15.8, 7.2), dpi=220, facecolor="#F8FAFC")
    panels = [
        (old_image, f"OLD · {old_run.name}\n{old_summary.get('capture_fingerprint_sha256', '')[:12]}…", "gray", 0, 255),
        (new_image, f"NEW · {new_run.name}\n{new_summary.get('capture_fingerprint_sha256', '')[:12]}…", "gray", 0, 255),
        (absolute_difference, "ABSOLUTE DIFFERENCE\n(normalized display codes)", "magma", 0, max(32.0, float(np.percentile(absolute_difference, 99)))),
    ]
    for ax, (image, title, cmap, vmin, vmax) in zip(axes, panels):
        ax.imshow(image, cmap=cmap, vmin=vmin, vmax=vmax, extent=extent, aspect="auto", interpolation="bilinear")
        ax.set_title(title, fontsize=11, pad=10)
        ax.set_xlabel("Lateral position (mm)")
        ax.set_ylabel("Depth (mm)")
    fig.suptitle(
        f"Two different captures · normalized B-mode correlation {image_correlation:.4f} · mean |Δ| {mean_absolute_difference:.2f}/255",
        fontsize=15,
        y=0.985,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95), pad=1.4)
    report_png = output_dir / "capture_run_comparison.png"
    fig.savefig(report_png, dpi=220, facecolor=fig.get_facecolor())
    fig.savefig(report_png.with_suffix(".svg"), facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "old_run": str(old_run),
        "new_run": str(new_run),
        "old_capture_fingerprint_sha256": old_summary.get("capture_fingerprint_sha256"),
        "new_capture_fingerprint_sha256": new_summary.get("capture_fingerprint_sha256"),
        "normalized_bmode_correlation": round(image_correlation, 6),
        "normalized_bmode_mean_absolute_difference_codes": round(mean_absolute_difference, 4),
        "normalized_bmode_rms_difference_codes": round(rms_difference, 4),
        "matching_raw_bin_metrics": raw_metrics,
        "conclusion": "different" if any(abs(row["correlation"]) < 0.999 for row in raw_metrics) else "possibly identical",
    }
    (output_dir / "capture_run_comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
