"""PW Doppler feasibility calculations for the collector UI.

The fast-time ADC sample rate, pulse-repetition frequency (PRF), and Doppler
slow-time sample rate are intentionally represented as separate quantities.
The current HSDC workflow records contiguous *raw RF blocks* into TSW DDR; it
does not perform a range gate or provide gap-free multi-second streaming.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


HSDC_SAMPLE_GRANULARITY = 4096
# TSW14J50 has 4-Gbit DDR3 and is specified for 256M 16-bit samples total.
# The total is shared by every converter stream in the selected JESD mode.
TSW14J50_TOTAL_16BIT_SAMPLES = 256 * 1024 * 1024
RAW_RF_DDR_MODE = "raw_rf_ddr"
FPGA_RANGE_GATE_IQ_MODE = "fpga_range_gate_iq"
AFE_DEMOD_IQ_MODE = "afe_demod_iq"
CAPTURE_MODES = {
    RAW_RF_DDR_MODE,
    FPGA_RANGE_GATE_IQ_MODE,
    AFE_DEMOD_IQ_MODE,
}


@dataclass(frozen=True)
class DopplerConfig:
    center_frequency_mhz: float = 1.0
    prf_hz: float = 5000.0
    steering_angle_deg: float = 0.0
    flow_angle_deg: float = 60.0
    target_depth_mm: float = 25.0
    expected_velocity_m_s: float = 1.0
    desired_duration_s: float = 6.0
    ensemble_pulses: int = 256
    gate_length_mm: float = 2.0
    wall_filter_hz: float = 50.0
    expected_heart_rate_bpm: float = 75.0
    adc_rate_msps: float = 120.0
    block_samples_per_channel: int = 4_194_304
    # ``rx_channels`` is the number of columns still transported into the raw
    # HSDC file.  ``iq_channels`` is the active aperture retained after range
    # gating.  They are deliberately separate: selecting eight physical RX
    # elements does not turn the current M=16 JESD/HSDC profile into M=8.
    rx_channels: int = 16
    iq_channels: int = 8
    bytes_per_adc_sample: int = 2
    sound_speed_m_s: float = 1540.0
    capture_mode: str = RAW_RF_DDR_MODE

    def validate(self) -> None:
        if self.center_frequency_mhz <= 0:
            raise ValueError("Center frequency must be positive.")
        if self.prf_hz <= 0:
            raise ValueError("PRF must be positive.")
        if abs(self.steering_angle_deg) > 30:
            raise ValueError("Steering angle must stay within +/-30 degrees.")
        if not 0 <= self.flow_angle_deg < 89.0:
            raise ValueError("Flow angle must be in the range 0 to <89 degrees.")
        if self.target_depth_mm <= 0:
            raise ValueError("Target depth must be positive.")
        if self.expected_velocity_m_s <= 0:
            raise ValueError("Expected velocity must be positive.")
        if self.desired_duration_s <= 0:
            raise ValueError("Desired duration must be positive.")
        if self.ensemble_pulses < 16:
            raise ValueError("Ensemble length must be at least 16 pulses.")
        if self.gate_length_mm <= 0:
            raise ValueError("Range-gate length must be positive.")
        if not 0 <= self.wall_filter_hz < self.prf_hz / 2.0:
            raise ValueError("Wall-filter cutoff must be between 0 and PRF/2.")
        if not 20 <= self.expected_heart_rate_bpm <= 240:
            raise ValueError("Expected heart rate must be between 20 and 240 BPM.")
        if self.adc_rate_msps <= 0:
            raise ValueError("ADC rate must be positive.")
        if self.block_samples_per_channel <= 0:
            raise ValueError("Block samples must be positive.")
        if self.block_samples_per_channel % HSDC_SAMPLE_GRANULARITY:
            raise ValueError("Block samples must be a multiple of 4096.")
        if self.rx_channels <= 0 or self.iq_channels <= 0 or self.bytes_per_adc_sample <= 0:
            raise ValueError("Channel count and bytes/sample must be positive.")
        if self.iq_channels > self.rx_channels:
            raise ValueError("Active I/Q channel count cannot exceed raw transport columns.")
        if self.sound_speed_m_s <= 0:
            raise ValueError("Sound speed must be positive.")
        if self.capture_mode not in CAPTURE_MODES:
            raise ValueError(f"Unsupported Doppler capture mode: {self.capture_mode}")


@dataclass(frozen=True)
class DopplerResult:
    prf_period_us: float
    max_unambiguous_depth_mm: float
    nyquist_velocity_m_s: float
    expected_doppler_shift_hz: float
    minimum_prf_for_expected_velocity_hz: float
    block_duration_ms: float
    pulses_per_raw_block: float
    raw_block_gib: float
    full_duration_raw_samples_per_channel: int
    full_duration_raw_gib: float
    range_gated_iq_mib: float
    ensemble_duration_ms: float
    velocity_bin_m_s: float
    requested_heart_cycles: float
    board_max_samples_per_channel: int
    board_max_raw_duration_s: float
    board_max_raw_pulses: float
    board_max_raw_heart_cycles: float
    current_mode_hardware_ready: bool
    cardiac_duration_requirement_met: bool
    warnings: tuple[str, ...]


def round_up_samples(samples: float, quantum: int = HSDC_SAMPLE_GRANULARITY) -> int:
    if samples <= 0:
        raise ValueError("samples must be positive")
    return int(math.ceil(samples / quantum) * quantum)


def calculate_doppler(config: DopplerConfig) -> DopplerResult:
    config.validate()
    f0_hz = config.center_frequency_mhz * 1e6
    adc_rate_hz = config.adc_rate_msps * 1e6
    cosine = abs(math.cos(math.radians(config.flow_angle_deg)))
    if cosine < 1e-4:
        raise ValueError("Flow angle is too close to 90 degrees for reliable velocity conversion.")

    prf_period_us = 1e6 / config.prf_hz
    max_depth_mm = config.sound_speed_m_s / (2.0 * config.prf_hz) * 1e3
    nyquist_velocity = (
        config.sound_speed_m_s * config.prf_hz / (4.0 * f0_hz * cosine)
    )
    expected_shift = (
        2.0 * f0_hz * config.expected_velocity_m_s * cosine
        / config.sound_speed_m_s
    )
    minimum_prf = 2.0 * expected_shift

    block_duration_s = config.block_samples_per_channel / adc_rate_hz
    pulses_per_block = block_duration_s * config.prf_hz
    raw_block_bytes = (
        config.block_samples_per_channel
        * config.rx_channels
        * config.bytes_per_adc_sample
    )
    full_samples = round_up_samples(config.desired_duration_s * adc_rate_hz)
    full_raw_bytes = full_samples * config.rx_channels * config.bytes_per_adc_sample

    # One complex int16 I/Q sample per channel and transmit pulse after range gating.
    range_gated_bytes = (
        config.desired_duration_s * config.prf_hz
        * config.iq_channels * 2 * config.bytes_per_adc_sample
    )
    ensemble_duration_s = config.ensemble_pulses / config.prf_hz
    doppler_bin_hz = config.prf_hz / config.ensemble_pulses
    velocity_bin = config.sound_speed_m_s * doppler_bin_hz / (2.0 * f0_hz * cosine)
    heart_period_s = 60.0 / config.expected_heart_rate_bpm
    requested_heart_cycles = config.desired_duration_s / heart_period_s
    board_max_samples_per_channel = TSW14J50_TOTAL_16BIT_SAMPLES // config.rx_channels
    board_max_raw_duration_s = board_max_samples_per_channel / adc_rate_hz
    board_max_raw_pulses = board_max_raw_duration_s * config.prf_hz
    board_max_raw_heart_cycles = board_max_raw_duration_s / heart_period_s
    current_mode_hardware_ready = config.capture_mode == RAW_RF_DDR_MODE
    cardiac_duration_requirement_met = (
        config.desired_duration_s >= max(3.0, 3.0 * heart_period_s)
        and requested_heart_cycles >= 3.0
    )

    warnings: list[str] = []
    if config.target_depth_mm > 0.8 * max_depth_mm:
        warnings.append(
            "Target depth uses more than 80% of the unambiguous range; lower PRF or add margin."
        )
    if config.expected_velocity_m_s > 0.8 * nyquist_velocity:
        warnings.append(
            "Expected velocity is close to the Nyquist limit; raise PRF or lower transmit frequency."
        )
    if pulses_per_block < config.ensemble_pulses:
        warnings.append(
            "One raw HSDC block contains fewer pulses than the selected Doppler ensemble."
        )
    if config.desired_duration_s > block_duration_s:
        warnings.append(
            "The desired cardiac duration exceeds one raw HSDC block; repeated Capture files are not gap-free."
        )
    if full_raw_bytes > 1024**3:
        warnings.append(
            "Gap-free full-duration raw RF exceeds 1 GiB; use AFE I/Q decimation or FPGA range gating."
        )
    if config.block_samples_per_channel > board_max_samples_per_channel:
        warnings.append(
            "Requested raw block exceeds the TSW14J50 theoretical per-channel DDR share."
        )
    if board_max_raw_heart_cycles < 1.0:
        warnings.append(
            "Even the theoretical maximum raw-RF DDR block is shorter than one expected heart cycle."
        )
    if not cardiac_duration_requirement_met:
        warnings.append(
            "Requested duration covers fewer than three expected heart cycles; cardiac periodicity is not defensible."
        )
    if config.capture_mode == FPGA_RANGE_GATE_IQ_MODE:
        warnings.append(
            "FPGA range-gated I/Q is the recommended cardiac path but requires a validated custom TSW firmware/backend."
        )
    elif config.capture_mode == AFE_DEMOD_IQ_MODE:
        warnings.append(
            "AFE demodulated I/Q requires a matched, validated JESD decompressor/profile before acquisition."
        )

    return DopplerResult(
        prf_period_us=prf_period_us,
        max_unambiguous_depth_mm=max_depth_mm,
        nyquist_velocity_m_s=nyquist_velocity,
        expected_doppler_shift_hz=expected_shift,
        minimum_prf_for_expected_velocity_hz=minimum_prf,
        block_duration_ms=block_duration_s * 1e3,
        pulses_per_raw_block=pulses_per_block,
        raw_block_gib=raw_block_bytes / float(1024**3),
        full_duration_raw_samples_per_channel=full_samples,
        full_duration_raw_gib=full_raw_bytes / float(1024**3),
        range_gated_iq_mib=range_gated_bytes / float(1024**2),
        ensemble_duration_ms=ensemble_duration_s * 1e3,
        velocity_bin_m_s=velocity_bin,
        requested_heart_cycles=requested_heart_cycles,
        board_max_samples_per_channel=board_max_samples_per_channel,
        board_max_raw_duration_s=board_max_raw_duration_s,
        board_max_raw_pulses=board_max_raw_pulses,
        board_max_raw_heart_cycles=board_max_raw_heart_cycles,
        current_mode_hardware_ready=current_mode_hardware_ready,
        cardiac_duration_requirement_met=cardiac_duration_requirement_met,
        warnings=tuple(warnings),
    )


def result_as_dict(config: DopplerConfig, result: DopplerResult) -> dict:
    return {
        "mode": config.capture_mode,
        "continuity": (
            "raw blocks are contiguous internally but gaps exist between HSDC captures"
            if config.capture_mode == RAW_RF_DDR_MODE
            else "requires one gap-free hardware-timestamped slow-time I/Q record"
        ),
        "configuration": {
            "center_frequency_mhz": config.center_frequency_mhz,
            "prf_hz": config.prf_hz,
            "steering_angle_deg": config.steering_angle_deg,
            "flow_angle_deg": config.flow_angle_deg,
            "target_depth_mm": config.target_depth_mm,
            "expected_velocity_m_s": config.expected_velocity_m_s,
            "desired_duration_s": config.desired_duration_s,
            "ensemble_pulses": config.ensemble_pulses,
            "gate_length_mm": config.gate_length_mm,
            "wall_filter_hz": config.wall_filter_hz,
            "expected_heart_rate_bpm": config.expected_heart_rate_bpm,
            "adc_rate_msps": config.adc_rate_msps,
            "block_samples_per_channel": config.block_samples_per_channel,
            "raw_transport_columns": config.rx_channels,
            "active_iq_channels": config.iq_channels,
            "sound_speed_m_s": config.sound_speed_m_s,
        },
        "calculated": {
            "prf_period_us": result.prf_period_us,
            "max_unambiguous_depth_mm": result.max_unambiguous_depth_mm,
            "nyquist_velocity_m_s": result.nyquist_velocity_m_s,
            "expected_doppler_shift_hz": result.expected_doppler_shift_hz,
            "minimum_prf_for_expected_velocity_hz": result.minimum_prf_for_expected_velocity_hz,
            "block_duration_ms": result.block_duration_ms,
            "pulses_per_raw_block": result.pulses_per_raw_block,
            "raw_block_gib": result.raw_block_gib,
            "full_duration_raw_samples_per_channel": result.full_duration_raw_samples_per_channel,
            "full_duration_raw_gib": result.full_duration_raw_gib,
            "range_gated_iq_mib": result.range_gated_iq_mib,
            "ensemble_duration_ms": result.ensemble_duration_ms,
            "velocity_bin_m_s": result.velocity_bin_m_s,
            "requested_heart_cycles": result.requested_heart_cycles,
            "board_max_samples_per_channel": result.board_max_samples_per_channel,
            "board_max_raw_duration_s": result.board_max_raw_duration_s,
            "board_max_raw_pulses": result.board_max_raw_pulses,
            "board_max_raw_heart_cycles": result.board_max_raw_heart_cycles,
            "current_mode_hardware_ready": result.current_mode_hardware_ready,
            "cardiac_duration_requirement_met": result.cardiac_duration_requirement_met,
        },
        "warnings": list(result.warnings),
    }
