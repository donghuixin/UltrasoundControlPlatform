"""Planning model for TI external-trigger deterministic replay captures.

This module deliberately calls the result a *virtual stitched span*.  HSDC Pro
still records one finite TSW14J50 DDR block at a time; the model never treats
successive host-side files as a gap-free live acquisition.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math


TI_VERIFIED_RAW_LANE_RATE_HZ = 60_000_000.0
TI_CANDIDATE_RAW_LANE_RATE_HZ = 20_000_000.0
TI_MAX_RAW_ROWS_PER_LANE = 33_554_432
TI_RAW_LANES = 8
TI_BYTES_PER_LANE_SAMPLE = 2
TI_RAW_ROWS_PER_SEPARATED_ROW = 64


@dataclass(frozen=True)
class TiReplayCaptureConfig:
    desired_span_s: float = 5.0
    overlap_s: float = 0.05
    raw_lane_rate_hz: float = TI_VERIFIED_RAW_LANE_RATE_HZ
    raw_rows_per_lane: int = TI_MAX_RAW_ROWS_PER_LANE
    raw_lanes: int = TI_RAW_LANES
    bytes_per_lane_sample: int = TI_BYTES_PER_LANE_SAMPLE
    raw_rows_per_separated_row: int = TI_RAW_ROWS_PER_SEPARATED_ROW
    prf_hz: float = 1_000.0


@dataclass(frozen=True)
class TiReplayCaptureResult:
    block_duration_s: float
    step_s: float
    block_count: int
    virtual_span_s: float
    trigger_offsets_s: tuple[float, ...]
    raw_file_bytes: int
    total_file_bytes: int
    separated_rows_per_block: int | None
    separated_row_rate_hz: float | None
    overlap_raw_rows: int
    overlap_separated_rows: int | None
    pulses_per_block: float
    capture_ready: bool
    mode_label: str
    warnings: tuple[str, ...]


def calculate_ti_replay_capture(config: TiReplayCaptureConfig) -> TiReplayCaptureResult:
    """Validate and calculate a deterministic replay/stitch capture plan."""

    if config.desired_span_s <= 0:
        raise ValueError("Desired virtual span must be positive.")
    if config.raw_lane_rate_hz <= 0:
        raise ValueError("Raw lane rate must be positive.")
    if config.raw_rows_per_lane <= 0:
        raise ValueError("Raw rows per lane must be positive.")
    if config.raw_rows_per_lane > TI_MAX_RAW_ROWS_PER_LANE:
        raise ValueError("Raw rows per lane exceed TI's stated maximum capture depth.")
    if config.raw_lanes <= 0 or config.bytes_per_lane_sample <= 0:
        raise ValueError("Raw lane count and bytes per sample must be positive.")
    if config.raw_rows_per_separated_row <= 0:
        raise ValueError("Raw rows per separated row must be positive.")
    if config.prf_hz <= 0:
        raise ValueError("PRF must be positive.")

    block_duration_s = config.raw_rows_per_lane / config.raw_lane_rate_hz
    if config.overlap_s < 0:
        raise ValueError("Overlap must not be negative.")
    if config.overlap_s >= block_duration_s:
        raise ValueError("Overlap must be shorter than one DDR block.")

    step_s = block_duration_s - config.overlap_s
    if config.desired_span_s <= block_duration_s:
        block_count = 1
    else:
        block_count = int(math.ceil((config.desired_span_s - block_duration_s) / step_s)) + 1
    trigger_offsets_s = tuple(index * step_s for index in range(block_count))
    virtual_span_s = block_duration_s + (block_count - 1) * step_s

    raw_file_bytes = (
        config.raw_rows_per_lane * config.raw_lanes * config.bytes_per_lane_sample
    )
    is_verified_rate = math.isclose(
        config.raw_lane_rate_hz, TI_VERIFIED_RAW_LANE_RATE_HZ, rel_tol=0.0, abs_tol=0.5
    )
    is_candidate_rate = math.isclose(
        config.raw_lane_rate_hz, TI_CANDIDATE_RAW_LANE_RATE_HZ, rel_tol=0.0, abs_tol=0.5
    )
    if is_verified_rate:
        mode_label = "TI supplied 60 MSPS / 40x / M=32 package"
    elif is_candidate_rate:
        mode_label = "TI suggested 20 MSPS / 160x candidate"
    else:
        mode_label = "unsupported custom raw lane rate"

    if is_verified_rate:
        separated_rows_per_block = config.raw_rows_per_lane // config.raw_rows_per_separated_row
        separated_row_rate_hz = config.raw_lane_rate_hz / config.raw_rows_per_separated_row
        overlap_separated_rows = int(round(config.overlap_s * separated_row_rate_hz))
    else:
        separated_rows_per_block = None
        separated_row_rate_hz = None
        overlap_separated_rows = None

    warnings = [
        "Blocks may be stitched only from a deterministic replay phase-locked to the ADC clock and EXT_TRIG.",
        "The resulting virtual timeline is not a gap-free recording of live flow and must not support cardiac PSV/EDV claims.",
        "Trigger delay is an external-generator setting; HSDC Pro does not create the requested offset.",
    ]
    capture_ready = is_verified_rate
    if is_candidate_rate:
        warnings.append(
            "20 MSPS / 160x reduces the block count, but the supplied archive contains no matching configuration or separator; planning only."
        )
    elif not is_verified_rate:
        warnings.append("This raw lane rate has no qualified AFE/HSDC configuration in the TI package.")

    return TiReplayCaptureResult(
        block_duration_s=block_duration_s,
        step_s=step_s,
        block_count=block_count,
        virtual_span_s=virtual_span_s,
        trigger_offsets_s=trigger_offsets_s,
        raw_file_bytes=raw_file_bytes,
        total_file_bytes=raw_file_bytes * block_count,
        separated_rows_per_block=separated_rows_per_block,
        separated_row_rate_hz=separated_row_rate_hz,
        overlap_raw_rows=int(round(config.overlap_s * config.raw_lane_rate_hz)),
        overlap_separated_rows=overlap_separated_rows,
        pulses_per_block=block_duration_s * config.prf_hz,
        capture_ready=capture_ready,
        mode_label=mode_label,
        warnings=tuple(warnings),
    )


def ti_replay_plan_as_dict(
    config: TiReplayCaptureConfig, result: TiReplayCaptureResult
) -> dict:
    """Return a JSON-safe plan with an explicit non-continuity contract."""

    return {
        "schema_version": 1,
        "method": "ti_external_trigger_deterministic_replay_stitch",
        "continuity_contract": {
            "gap_free_live_recording": False,
            "deterministic_replay_stitch_only": True,
            "cardiac_cycle_claim_allowed": False,
        },
        "config": asdict(config),
        "result": {
            **asdict(result),
            "trigger_offsets_s": list(result.trigger_offsets_s),
            "warnings": list(result.warnings),
        },
        "operator_requirements": [
            "Use a repeatable input sequence with a reproducible t=0.",
            "Phase-lock input generation, ADC sampling clock, and EXT_TRIG.",
            "Set and record the external trigger delay for every block.",
            "Verify overlap by waveform agreement before trimming and stitching.",
            "Preserve every raw BIN and the capture manifest.",
        ],
    }
