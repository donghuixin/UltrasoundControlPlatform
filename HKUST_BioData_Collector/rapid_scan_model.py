"""Timing model for deterministic per-PRF TX7316 beam scanning.

This module only plans a rapid scan.  It does not claim that the stock
TX7316EVM CPLD can sequence profiles: a verified FPGA/CPLD sequencer must
preload the delay profiles, reset the profile counter at frame start, and
select the next profile before the next TR_BF_SYNC edge.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable


DEFAULT_ADC_RATE_HZ = 120_000_000.0
HSDC_CHANNELS = 16
BYTES_PER_SAMPLE = 2
SAMPLE_QUANTUM = 4096
TX7316_PROFILE_CAPACITY = 16


@dataclass(frozen=True)
class RapidScanConfig:
    angles_deg: tuple[float, ...]
    prf_hz: float = 1000.0
    frames: int = 1
    guard_prfs: int = 1
    sample_rate_hz: float = DEFAULT_ADC_RATE_HZ
    profile_capacity: int = TX7316_PROFILE_CAPACITY


@dataclass(frozen=True)
class RapidScanEvent:
    bank_index: int
    frame_index: int
    event_in_bank: int
    global_angle_index: int
    hardware_profile: int
    angle_deg: float
    time_ms: float
    sample_offset: int


@dataclass(frozen=True)
class RapidScanBank:
    bank_index: int
    angles_deg: tuple[float, ...]
    event_count: int
    samples_per_channel: int
    duration_ms: float
    expected_bytes: int
    events: tuple[RapidScanEvent, ...]


@dataclass(frozen=True)
class RapidScanPlan:
    config: RapidScanConfig
    banks: tuple[RapidScanBank, ...]
    angle_count: int
    bank_count: int
    file_count: int
    sweep_time_ms: float
    captured_time_ms: float
    expected_bytes: int
    effective_scan_rate_hz: float


def _round_up(value: float, quantum: int) -> int:
    return int(math.ceil(value / float(quantum))) * quantum


def _round_down(value: float, quantum: int) -> int:
    return int(math.floor(value / float(quantum))) * quantum


def contiguous_prf_block_samples(
    prf_hz: float,
    pulse_count: int,
    sample_rate_hz: float = DEFAULT_ADC_RATE_HZ,
    quantum: int = SAMPLE_QUANTUM,
) -> int:
    """Samples/channel for one trigger-started contiguous same-angle PRF block.

    Emissions occur at t=0 through t=(pulse_count-1)/prf_hz.  The capture must
    stop before t=pulse_count/prf_hz, otherwise the next free-running SYNCP
    edge can add an unintended emission.  HSDC requires a multiple of 4096
    samples, so this exact-event-count mode rounds *down* from that boundary.
    """

    if not math.isfinite(prf_hz) or prf_hz <= 0:
        raise ValueError("PRF must be positive")
    if pulse_count <= 0:
        raise ValueError("pulse_count must be positive")
    if not math.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if quantum <= 0:
        raise ValueError("quantum must be positive")
    samples = _round_down(pulse_count / prf_hz * sample_rate_hz, quantum)
    last_emission_sample = (pulse_count - 1) / prf_hz * sample_rate_hz
    if samples <= last_emission_sample:
        raise ValueError("sample quantum leaves no receive window after the final emission")
    return samples


def _validate(config: RapidScanConfig) -> None:
    if not config.angles_deg:
        raise ValueError("至少需要一個掃描角度。")
    if not math.isfinite(config.prf_hz) or config.prf_hz <= 0:
        raise ValueError("PRF必須為正數。")
    if config.prf_hz > 10_000:
        raise ValueError("本規劃器把10 kHz設為原廠預設功率模式上限；更高PRF需另行驗證Dynamic Power Mode。")
    if config.frames <= 0:
        raise ValueError("掃描幀數必須大於0。")
    if config.guard_prfs < 1:
        raise ValueError("每個文件至少保留1個guard PRF，避免最後一次回波被截斷。")
    if config.sample_rate_hz <= 0:
        raise ValueError("ADC sample rate必須為正數。")
    if config.profile_capacity <= 0 or config.profile_capacity > TX7316_PROFILE_CAPACITY:
        raise ValueError("TX7316每個profile bank容量必須在1到16之間。")
    if any(not math.isfinite(angle) for angle in config.angles_deg):
        raise ValueError("角度列表包含非有限數值。")


def build_rapid_scan_plan(config: RapidScanConfig) -> RapidScanPlan:
    """Build the file/bank/event schedule for a synchronized rapid scan."""

    _validate(config)
    period_s = 1.0 / config.prf_hz
    banks: list[RapidScanBank] = []
    angles = config.angles_deg
    for bank_index, start in enumerate(range(0, len(angles), config.profile_capacity)):
        bank_angles = angles[start : start + config.profile_capacity]
        events: list[RapidScanEvent] = []
        event_in_bank = 0
        for frame_index in range(config.frames):
            for local_index, angle in enumerate(bank_angles):
                event_time_s = event_in_bank * period_s
                events.append(
                    RapidScanEvent(
                        bank_index=bank_index,
                        frame_index=frame_index,
                        event_in_bank=event_in_bank,
                        global_angle_index=start + local_index,
                        hardware_profile=local_index,
                        angle_deg=float(angle),
                        time_ms=event_time_s * 1000.0,
                        sample_offset=int(round(event_time_s * config.sample_rate_hz)),
                    )
                )
                event_in_bank += 1

        requested_samples = (event_in_bank + config.guard_prfs) * period_s * config.sample_rate_hz
        samples = _round_up(requested_samples, SAMPLE_QUANTUM)
        expected_bytes = samples * HSDC_CHANNELS * BYTES_PER_SAMPLE
        banks.append(
            RapidScanBank(
                bank_index=bank_index,
                angles_deg=tuple(bank_angles),
                event_count=event_in_bank,
                samples_per_channel=samples,
                duration_ms=samples / config.sample_rate_hz * 1000.0,
                expected_bytes=expected_bytes,
                events=tuple(events),
            )
        )

    captured_time_ms = sum(bank.duration_ms for bank in banks)
    total_bytes = sum(bank.expected_bytes for bank in banks)
    # This is the ideal coherent sweep interval inside a bank.  It excludes
    # HSDC file-save and profile-bank reprogramming gaps.
    sweep_time_ms = len(angles) / config.prf_hz * 1000.0
    effective_scan_rate_hz = (
        config.frames / (captured_time_ms / 1000.0) if captured_time_ms > 0 else 0.0
    )
    return RapidScanPlan(
        config=config,
        banks=tuple(banks),
        angle_count=len(angles),
        bank_count=len(banks),
        file_count=len(banks),
        sweep_time_ms=sweep_time_ms,
        captured_time_ms=captured_time_ms,
        expected_bytes=total_bytes,
        effective_scan_rate_hz=effective_scan_rate_hz,
    )


def plan_as_dict(plan: RapidScanPlan) -> dict:
    """Return a JSON-serializable plan with explicit hardware requirements."""

    data = asdict(plan)
    data["schema"] = "hkust.rapid-prf-scan-plan/v1"
    data["execution_state"] = "blocked_until_verified_sequencer"
    data["hardware_requirements"] = [
        "Preload at most 16 TX7316 delay profiles per bank.",
        "Reset profile index and arm HSDC before the frame-start trigger.",
        "Select the next profile between emissions; never rewrite delay RAM during HV output.",
        "Fan out one conditioned PRF source to TX timing and HSDC capture trigger with a shared ground.",
        "Record the frame-start/profile-index relation so offline angle mapping cannot rotate.",
    ]
    return data


def make_config(
    angles_deg: Iterable[float],
    prf_hz: float,
    frames: int,
    guard_prfs: int,
) -> RapidScanConfig:
    return RapidScanConfig(
        angles_deg=tuple(float(value) for value in angles_deg),
        prf_hz=float(prf_hz),
        frames=int(frames),
        guard_prfs=int(guard_prfs),
    )
