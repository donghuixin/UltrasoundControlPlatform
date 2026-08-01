"""Read-only audit for repository capture and PW Doppler configuration files."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any

from doppler_model import DopplerConfig, TSW14J50_TOTAL_16BIT_SAMPLES, calculate_doppler
from doppler_presets import CAROTID_PHANTOM_PRESETS, CAROTID_PHANTOM_PRESETS_BY_KEY


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
EXPECTED_RX_SLOTS = "5,6,7,8,9,10,11,12"
REGISTER_LINE = re.compile(r"^[A-Za-z0-9_-]+(?:\|0x[0-9A-Fa-f]+)?\s+0x[0-9A-Fa-f]+$")


@dataclass(frozen=True)
class AuditFinding:
    severity: str
    target: str
    message: str


def _loose_ini_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("\\") or line.startswith("[") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def audit_hsdc_profiles() -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    expected_pattern = ",".join(str(index) for index in range(1, 17))
    for path in sorted((REPO_ROOT / "configs" / "hsdc").glob("*.ini")):
        target = str(path.relative_to(REPO_ROOT))
        try:
            values = _loose_ini_values(path)
        except OSError as exc:
            findings.append(AuditFinding("error", target, f"cannot read profile: {exc}"))
            continue
        required = {
            "Interface name": "TSW14J50RX_FIRMWARE",
            "Number of channels": "16",
            "Channel Pattern": expected_pattern,
            "Number of Bits": "16",
            "JESD IP Core_L": "8",
            "JESD IP Core_F": "4",
            "JESD IP Core_K": "8",
            "JESD IP Core_N": "16",
            "JESD IP Core_NTotal": "16",
            "Menu Enable": "Trigger Option",
        }
        for key, expected in required.items():
            actual = values.get(key)
            if actual != expected:
                findings.append(
                    AuditFinding("error", target, f"{key}={actual!r}; expected {expected!r}")
                )
        try:
            if int(values.get("Max sample Rate", "0")) < 120_000_000:
                findings.append(AuditFinding("error", target, "Max sample Rate is below 120 MSPS"))
        except ValueError:
            findings.append(AuditFinding("error", target, "Max sample Rate is not an integer"))
        lane_mapping = values.get("Lane Mapping", "")
        for lane in range(8):
            if f"lane{lane}:" not in lane_mapping:
                findings.append(AuditFinding("error", target, f"lane{lane} missing from Lane Mapping"))
        subclass = values.get("JESD IP Core_Subclass")
        expected_subclass = "2" if "S2" in path.name else "1"
        if subclass != expected_subclass:
            findings.append(
                AuditFinding(
                    "error", target,
                    f"Subclass={subclass!r} does not match filename expectation {expected_subclass}",
                )
            )
        findings.append(
            AuditFinding(
                "warning",
                target,
                "syntax is internally consistent, but this profile has not passed the 16/16 unique-code transport gate",
            )
        )
    return findings


def _register_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    ]


def audit_register_snapshots() -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    afe_dir = REPO_ROOT / "configs" / "afe58jd48"
    for path in sorted(afe_dir.glob("*.cfg")):
        target = str(path.relative_to(REPO_ROOT))
        try:
            lines = _register_lines(path)
        except OSError as exc:
            findings.append(AuditFinding("error", target, f"cannot read snapshot: {exc}"))
            continue
        invalid = [line for line in lines if not REGISTER_LINE.fullmatch(line)]
        if invalid:
            findings.append(AuditFinding("error", target, f"{len(invalid)} malformed register command(s)"))
            continue
        if not lines or not lines[-1].endswith("0x0000"):
            findings.append(AuditFinding("error", target, "snapshot does not restore the page selector to zero"))
            continue
        if path.name.startswith("AFE58JD48_120M_8L"):
            findings.append(
                AuditFinding(
                    "warning",
                    target,
                    "overlay syntax is valid; use only with its named Subclass/K experiment and verify both-die readback",
                )
            )
        elif path.name == "ADC_UNIQUE_CODES_16CH.cfg":
            if len(lines) != 49:
                findings.append(AuditFinding("error", target, "unique-code snapshot does not contain 16 channel triplets plus restore"))
            else:
                findings.append(AuditFinding("pass", target, "16-channel transport-test snapshot is structurally complete"))
        elif path.name == "ADC_ANALOG_RESTORE.cfg":
            findings.append(AuditFinding("pass", target, "analog restore snapshot is structurally complete"))

    tx_path = REPO_ROOT / "configs" / "tx7316" / "1MHz_5pulses.cfg"
    target = str(tx_path.relative_to(REPO_ROOT))
    try:
        tx_lines = _register_lines(tx_path)
    except OSError as exc:
        findings.append(AuditFinding("error", target, f"cannot read snapshot: {exc}"))
    else:
        invalid = [line for line in tx_lines if not REGISTER_LINE.fullmatch(line)]
        if invalid:
            findings.append(AuditFinding("error", target, f"{len(invalid)} malformed register command(s)"))
        else:
            findings.append(
                AuditFinding(
                    "warning",
                    target,
                    "syntax is valid, but the TI filename is misleading: this is a four-cycle, nonzero-delay quick-start snapshot, not the one-click PW preset",
                )
            )
    return findings


def audit_collector_config(path: Path) -> list[AuditFinding]:
    target = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [AuditFinding("error", target, f"invalid JSON: {exc}")]

    findings: list[AuditFinding] = []
    if str(payload.get("rx_hsdc_slots")) != EXPECTED_RX_SLOTS:
        findings.append(
            AuditFinding("error", target, f"rx_hsdc_slots must be {EXPECTED_RX_SLOTS}")
        )
    if int(payload.get("elements", 0)) != 8:
        findings.append(AuditFinding("error", target, "elements must be 8 for the current A1-A8 aperture"))
    if float(payload.get("center_frequency_mhz", 0.0)) != 1.5:
        findings.append(AuditFinding("warning", target, "current qualified collector baseline is 1.5 MHz"))
    if str(payload.get("waveform_mode", "")) != "tapered-5level":
        findings.append(AuditFinding("error", target, "waveform_mode must be tapered-5level for the one-click PW baseline"))
    preset_key = str(payload.get("doppler_preset_key", ""))
    if preset_key not in CAROTID_PHANTOM_PRESETS_BY_KEY:
        findings.append(AuditFinding("error", target, f"unknown doppler_preset_key: {preset_key!r}"))
    samples = int(payload.get("doppler_block_samples", 0))
    theoretical_limit = TSW14J50_TOTAL_16BIT_SAMPLES // 16
    if samples <= 0 or samples % 4096:
        findings.append(AuditFinding("error", target, "doppler_block_samples must be a positive multiple of 4096"))
    if samples > theoretical_limit:
        findings.append(AuditFinding("error", target, "doppler_block_samples exceeds the M=16 DDR share"))
    source = str(payload.get("doppler_prf_source", ""))
    prf_hz = float(payload.get("doppler_prf_hz", 0.0))
    trigger = str(payload.get("doppler_trigger", ""))
    if source.startswith("Onboard CPLD") and (prf_hz != 1000.0 or trigger != "normal"):
        findings.append(
            AuditFinding("error", target, "onboard CPLD preset must use PRF=1000 and trigger=normal")
        )
    if not findings:
        findings.append(AuditFinding("pass", target, "collector configuration is internally consistent"))
    return findings


def audit_presets() -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    labels: set[str] = set()
    keys: set[str] = set()
    for preset in CAROTID_PHANTOM_PRESETS:
        target = f"preset:{preset.key}"
        if preset.key in keys or preset.label in labels:
            findings.append(AuditFinding("error", target, "duplicate preset key or label"))
            continue
        keys.add(preset.key)
        labels.add(preset.label)
        try:
            result = calculate_doppler(
                DopplerConfig(
                    center_frequency_mhz=preset.center_frequency_mhz,
                    prf_hz=preset.prf_hz,
                    steering_angle_deg=preset.steering_angle_deg,
                    flow_angle_deg=preset.flow_angle_deg,
                    target_depth_mm=preset.target_depth_mm,
                    expected_velocity_m_s=preset.expected_velocity_m_s,
                    desired_duration_s=preset.desired_duration_s,
                    ensemble_pulses=preset.ensemble_pulses,
                    gate_length_mm=preset.gate_length_mm,
                    wall_filter_hz=preset.wall_filter_hz,
                    expected_heart_rate_bpm=preset.expected_heart_rate_bpm,
                    block_samples_per_channel=preset.block_samples_per_channel,
                    rx_channels=16,
                    iq_channels=8,
                    capture_mode=preset.capture_mode,
                )
            )
        except ValueError as exc:
            findings.append(AuditFinding("error", target, str(exc)))
            continue
        if preset.flow_angle_deg > 60.0:
            findings.append(AuditFinding("error", target, "flow angle exceeds the 60-degree phantom limit"))
        if preset.expected_velocity_m_s >= 0.8 * result.nyquist_velocity_m_s:
            findings.append(AuditFinding("warning", target, "expected speed has less than 20% Nyquist margin"))
        if preset.current_backend_executable and result.pulses_per_raw_block < preset.ensemble_pulses:
            findings.append(AuditFinding("error", target, "raw block is shorter than one STFT ensemble"))
        if not preset.current_backend_executable and not result.cardiac_duration_requirement_met:
            findings.append(AuditFinding("error", target, "multi-cycle preset does not cover three expected cycles"))
        if not any(item.target == target and item.severity == "error" for item in findings):
            findings.append(
                AuditFinding(
                    "pass",
                    target,
                    "mathematical checks pass; hardware readiness remains governed by the selected backend gate",
                )
            )
    return findings


def run_audit(config_path: Path | None = None) -> dict[str, Any]:
    config_path = config_path or APP_DIR / "collector_config.example.json"
    findings = [
        *audit_hsdc_profiles(),
        *audit_register_snapshots(),
        *audit_collector_config(config_path),
        *audit_presets(),
    ]
    counts = {
        severity: sum(item.severity == severity for item in findings)
        for severity in ("pass", "warning", "error")
    }
    return {
        "status": "pass" if counts["error"] == 0 else "fail",
        "scope": "repository snapshots only; live GUI/register readback is not audited",
        "counts": counts,
        "findings": [asdict(item) for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit repository ultrasound configuration snapshots.")
    parser.add_argument("--collector-config", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_audit(args.collector_config)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        counts = report["counts"]
        print(
            f"CONFIG AUDIT {report['status'].upper()} | "
            f"pass={counts['pass']} warning={counts['warning']} error={counts['error']}"
        )
        for finding in report["findings"]:
            print(f"[{finding['severity'].upper()}] {finding['target']}: {finding['message']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
