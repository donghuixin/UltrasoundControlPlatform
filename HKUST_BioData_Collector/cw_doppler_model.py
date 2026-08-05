"""Geometry and feasibility model for the Science Advances CW Doppler page.

The 2021 DBUD paper uses three physically tilted rows.  This implementation
adapts that geometry to eight active hardware channels.  It deliberately keeps
physical ADC rate, decimated I/Q rate and HSDC transport slots separate and
contains no private hardware register values.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable, Sequence


PAPER_DOI = "10.1126/sciadv.abi9283"
TSW14J50_DDR_BYTES = 512 * 1024 * 1024
AFE_ADC_RATE_HZ = 120_000_000.0
# The AFE GUI's MANUAL_DECIMATION_FACTOR is the low-pass decimator D.  In
# down-conversion mode the complex I/Q output rate is fADC/(2*D); the extra
# factor of two must not be presented to the operator as the register value.
DEFAULT_DECIMATION = 4
ACTIVE_RX_CHANNELS = 8
STOCK_TX_CW_FREQUENCY_HZ = 3_125_000.0
SUPPORTED_TX_FREQUENCIES_HZ = (1_000_000.0, 2_000_000.0, STOCK_TX_CW_FREQUENCY_HZ, 4_000_000.0)
IQ_RATE_DECIMATION = {
    15_000_000.0: 4,
    10_000_000.0: 6,
    7_500_000.0: 8,
    6_000_000.0: 10,
    5_000_000.0: 12,
}
PRESET_FIR_MAX_DECIMATION = 20


@dataclass(frozen=True)
class CwRowConfig:
    row_number: int
    physical_angle_deg: float
    tx_patch_ids: tuple[int, ...]
    rx_patch_id: int
    afe_rx_slot: int

    def validate(self) -> None:
        if self.row_number < 1:
            raise ValueError("Row number must be positive.")
        if not 0.0 < self.physical_angle_deg < 70.0:
            raise ValueError("Each physical row angle must be between 0 and 70 degrees.")
        if not self.tx_patch_ids:
            raise ValueError("Each row needs at least one transmit patch.")
        patch_ids = self.tx_patch_ids + (self.rx_patch_id,)
        if any(value < 1 or value > ACTIVE_RX_CHANNELS for value in patch_ids):
            raise ValueError("Logical patch IDs must be in the range 1..8.")
        if len(set(patch_ids)) != len(patch_ids):
            raise ValueError("A row cannot use the same logical patch for TX and RX.")
        if not 1 <= self.afe_rx_slot <= 16:
            raise ValueError("AFE receive slots must be in the range 1..16.")


DEFAULT_ROWS = (
    CwRowConfig(1, 17.0, (1, 3), 2, 1),
    CwRowConfig(2, 20.0, (4, 6), 5, 2),
    CwRowConfig(3, 23.0, (7,), 8, 3),
)


@dataclass(frozen=True)
class CwDopplerConfig:
    center_frequency_hz: float = 4_000_000.0
    adc_rate_hz: float = AFE_ADC_RATE_HZ
    decimation: int = DEFAULT_DECIMATION
    logical_patch_count: int = ACTIVE_RX_CHANNELS
    tissue_sound_speed_m_s: float = 1540.0
    substrate_sound_speed_m_s: float = 1000.0
    analysis_rate_hz: float = 50_000.0
    lowpass_hz: float = 20_000.0
    wall_filter_hz: float = 150.0
    stft_samples: int = 1024
    stft_overlap: int = 900
    desired_duration_s: float = 10.0
    rows: tuple[CwRowConfig, ...] = DEFAULT_ROWS

    @property
    def iq_output_rate_hz(self) -> float:
        return self.adc_rate_hz / (2.0 * float(self.decimation))

    def validate(self) -> None:
        if not any(abs(self.center_frequency_hz - value) <= 1.0 for value in SUPPORTED_TX_FREQUENCIES_HZ):
            raise ValueError("The selectable center frequencies are 1, 2, 3.125 or 4 MHz.")
        if self.adc_rate_hz <= 0.0 or self.decimation < 1:
            raise ValueError("ADC rate and decimation must be positive.")
        if abs(self.adc_rate_hz - AFE_ADC_RATE_HZ) > 1.0:
            raise ValueError("The qualified JESD baseline keeps the physical ADC at 120 MSPS.")
        if self.decimation not in IQ_RATE_DECIMATION.values():
            raise ValueError("Select an I/Q output rate of 15, 10, 7.5, 6 or 5 MSPS.")
        if self.logical_patch_count != ACTIVE_RX_CHANNELS:
            raise ValueError("This hardware adaptation uses exactly eight active channels.")
        if len(self.rows) != 3:
            raise ValueError("DBUD requires three physically different row angles.")
        for row in self.rows:
            row.validate()
        if len({row.physical_angle_deg for row in self.rows}) != 3:
            raise ValueError("The three DBUD row angles must be different.")
        all_patch_ids = [
            patch_id
            for row in self.rows
            for patch_id in row.tx_patch_ids + (row.rx_patch_id,)
        ]
        if set(all_patch_ids) != set(range(1, ACTIVE_RX_CHANNELS + 1)):
            raise ValueError("The adapted topology must cover logical patches 1..8 exactly once.")
        if not 0.0 < self.substrate_sound_speed_m_s < self.tissue_sound_speed_m_s:
            raise ValueError("Substrate speed must be positive and below tissue sound speed.")
        if self.analysis_rate_hz <= 0.0:
            raise ValueError("Analysis sample rate must be positive.")
        if not self.wall_filter_hz < self.lowpass_hz < self.analysis_rate_hz / 2.0:
            raise ValueError("Require wall filter < low-pass cutoff < analysis Nyquist.")
        if self.stft_samples < 16 or not 0 <= self.stft_overlap < self.stft_samples:
            raise ValueError("STFT overlap must be from 0 to window_length-1.")
        if self.desired_duration_s <= 0.0:
            raise ValueError("Desired duration must be positive.")
        for row in self.rows:
            refracted_angle_deg(
                row.physical_angle_deg,
                self.substrate_sound_speed_m_s,
                self.tissue_sound_speed_m_s,
            )


@dataclass(frozen=True)
class CwDopplerResult:
    refracted_angles_deg: tuple[float, ...]
    nco_word: int
    nco_actual_hz: float
    iq_output_rate_hz: float
    hsdc_16slot_bytes_per_s: float
    hsdc_8slot_bytes_per_s: float
    hsdc_16slot_duration_s: float
    hsdc_8slot_duration_s: float
    raw_rf_16slot_bytes_per_s: float
    raw_rf_16slot_duration_s: float
    preset_fir_supported: bool
    full_chain_write_ready: bool
    external_iq_bytes: int
    stft_bin_hz: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class DbudVelocityEstimate:
    signed_speed_m_s: float
    speed_magnitude_m_s: float
    flow_angle_deg: float
    predicted_doppler_hz: tuple[float, ...]
    residual_rms_hz: float


def nco_frequency_word(frequency_hz: float, sample_rate_hz: float) -> int:
    if sample_rate_hz <= 0.0:
        raise ValueError("Sample rate must be positive.")
    if not 0.0 <= frequency_hz < sample_rate_hz:
        raise ValueError("NCO frequency must be inside [0, sample_rate).")
    return int(round(float(frequency_hz) * 65536.0 / float(sample_rate_hz))) & 0xFFFF


def nco_actual_frequency_hz(word: int, sample_rate_hz: float) -> float:
    return (int(word) & 0xFFFF) * float(sample_rate_hz) / 65536.0


def refracted_angle_deg(
    physical_angle_deg: float,
    substrate_sound_speed_m_s: float = 1000.0,
    tissue_sound_speed_m_s: float = 1540.0,
) -> float:
    """Return the beam angle in tissue using Snell's law.

    The paper writes ``sin(theta) / sin(beta) = c_substrate / c_tissue``.
    Therefore ``sin(beta) = sin(theta) * c_tissue / c_substrate``.
    """
    argument = (
        math.sin(math.radians(float(physical_angle_deg)))
        * float(tissue_sound_speed_m_s)
        / float(substrate_sound_speed_m_s)
    )
    if abs(argument) > 1.0:
        raise ValueError(
            "Row angle is above the refraction limit for the selected sound speeds."
        )
    return math.degrees(math.asin(argument))


def calculate_cw_doppler(config: CwDopplerConfig) -> CwDopplerResult:
    config.validate()
    refracted = tuple(
        refracted_angle_deg(
            row.physical_angle_deg,
            config.substrate_sound_speed_m_s,
            config.tissue_sound_speed_m_s,
        )
        for row in config.rows
    )
    word = nco_frequency_word(config.center_frequency_hz, config.adc_rate_hz)
    # HSDC still allocates complete converter slots.  Eight active analog
    # channels reduce DDR use only after a matching demod/compression transport
    # profile is verified in the AFE and TSW14J50 together.
    # One complex I/Q sample contains int16 I + int16 Q = four bytes.
    # The demod HSDC profile exposes eight logical channels, each consisting
    # of one int16 I word and one int16 Q word.  Its Channel Pattern therefore
    # contains 16 converter words: 1,1,2,2,...,8,8.  Do not multiply those 16
    # words by another complex factor; doing so incorrectly doubles bandwidth.
    hsdc_16slot_bps = config.iq_output_rate_hz * 16.0 * 2.0
    # Retained for backwards-compatible plan files: an ideal four-complex-
    # channel transport would contain eight int16 words per sample instant.
    hsdc_8slot_bps = config.iq_output_rate_hz * 8.0 * 2.0
    raw_rf_16slot_bps = config.adc_rate_hz * 16.0 * 2.0
    external_iq_bytes = int(round(config.analysis_rate_hz * config.desired_duration_s * 2 * 2))
    preset_fir_supported = config.decimation <= PRESET_FIR_MAX_DECIMATION
    warnings = [
        "Eight active channels do not reduce DDR use while the repaired raw-RF HSDC profile still carries 16 converter slots.",
        "Digital I/Q needs one matched AFE demod/decimation CFG and one matching TSW14J50 demod unpack profile.",
        "AFE analog CW_OUT is not carried over JESD; it needs an external simultaneous I/Q ADC.",
        "CW has no range gate, so echoes from the full TX/RX overlap volume contribute.",
        "Continuous high-voltage transmit requires phantom-only validation, current limiting, and thermal monitoring.",
    ]
    if config.center_frequency_hz != STOCK_TX_CW_FREQUENCY_HZ:
        warnings.append("The stock 200-MHz TX7316EVM BF_CLK cannot generate this exact CW frequency; 1/2/4 MHz requires a verified 128-MHz BF_CLK hardware path.")
    if not preset_fir_supported:
        warnings.append("The selected hardware decimator is outside the documented preset-coefficient range.")
    if TSW14J50_DDR_BYTES / hsdc_16slot_bps < config.desired_duration_s:
        warnings.append("The 8-complex-channel I/Q block does not fit the requested duration in 512 MiB DDR; capture will be clipped to the hardware maximum.")
    return CwDopplerResult(
        refracted_angles_deg=refracted,
        nco_word=word,
        nco_actual_hz=nco_actual_frequency_hz(word, config.adc_rate_hz),
        iq_output_rate_hz=config.iq_output_rate_hz,
        hsdc_16slot_bytes_per_s=hsdc_16slot_bps,
        hsdc_8slot_bytes_per_s=hsdc_8slot_bps,
        hsdc_16slot_duration_s=TSW14J50_DDR_BYTES / hsdc_16slot_bps,
        hsdc_8slot_duration_s=TSW14J50_DDR_BYTES / hsdc_8slot_bps,
        raw_rf_16slot_bytes_per_s=raw_rf_16slot_bps,
        raw_rf_16slot_duration_s=TSW14J50_DDR_BYTES / raw_rf_16slot_bps,
        preset_fir_supported=preset_fir_supported,
        full_chain_write_ready=False,
        external_iq_bytes=external_iq_bytes,
        stft_bin_hz=config.analysis_rate_hz / float(config.stft_samples),
        warnings=tuple(warnings),
    )


def estimate_dbud_velocity(
    doppler_hz: Sequence[float],
    refracted_angles_deg: Sequence[float],
    center_frequency_hz: float,
    sound_speed_m_s: float = 1540.0,
) -> DbudVelocityEstimate:
    """Least-squares DBUD solution using two or more tilted rows.

    For row i, ``fD_i = (2 f0 / c) v sin(beta_i - alpha)``.  Expanding the
    sine makes this linear in ``A=v*cos(alpha)`` and ``B=-v*sin(alpha)``.
    """
    if len(doppler_hz) != len(refracted_angles_deg) or len(doppler_hz) < 2:
        raise ValueError("DBUD needs equal-length Doppler/angle arrays with at least two rows.")
    if center_frequency_hz <= 0.0 or sound_speed_m_s <= 0.0:
        raise ValueError("Frequency and sound speed must be positive.")
    scale = 2.0 * float(center_frequency_hz) / float(sound_speed_m_s)
    sines = [math.sin(math.radians(float(angle))) for angle in refracted_angles_deg]
    cosines = [math.cos(math.radians(float(angle))) for angle in refracted_angles_deg]
    values = [float(value) / scale for value in doppler_hz]
    ss = sum(value * value for value in sines)
    cc = sum(value * value for value in cosines)
    sc = sum(a * b for a, b in zip(sines, cosines))
    sy = sum(a * y for a, y in zip(sines, values))
    cy = sum(a * y for a, y in zip(cosines, values))
    determinant = ss * cc - sc * sc
    if abs(determinant) < 1e-10:
        raise ValueError("Row angles are too similar for a stable DBUD solution.")
    a_value = (sy * cc - cy * sc) / determinant
    b_value = (cy * ss - sy * sc) / determinant
    magnitude = math.hypot(a_value, b_value)
    angle = math.degrees(math.atan2(-b_value, a_value))
    signed_speed = magnitude
    while angle > 90.0:
        angle -= 180.0
        signed_speed = -signed_speed
    while angle < -90.0:
        angle += 180.0
        signed_speed = -signed_speed
    predicted = tuple(
        scale * signed_speed * math.sin(math.radians(beta - angle))
        for beta in refracted_angles_deg
    )
    rms = math.sqrt(
        sum((measured - fitted) ** 2 for measured, fitted in zip(doppler_hz, predicted))
        / float(len(doppler_hz))
    )
    return DbudVelocityEstimate(
        signed_speed_m_s=signed_speed,
        speed_magnitude_m_s=magnitude,
        flow_angle_deg=angle,
        predicted_doppler_hz=predicted,
        residual_rms_hz=rms,
    )


def cw_plan_as_dict(config: CwDopplerConfig, result: CwDopplerResult) -> dict:
    return {
        "schema": "hkust-cw-doppler-plan/v2",
        "paper": {
            "doi": PAPER_DOI,
            "adaptation": "3 tilted rows adapted to 8 active hardware channels; stock CW is 3.125 MHz",
        },
        "configuration": {
            **asdict(config),
            "rows": [asdict(row) for row in config.rows],
        },
        "derived": asdict(result),
        "hardware_gates": {
            "ti_repaired_raw_rf_profile_must_be_preserved": True,
            "raw_rf_hsdc_device": "AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1",
            "requested_digital_iq": "experimental_until_matching_AFE_CFG_and_TSW14J50_unpack_pass_the_channel_gate",
            "logical_8_channels_reduce_ddr_only_with_matching_transport": True,
            "five_msps_uses_hardware_decimation_d12": config.decimation == 12,
            "recommended_long_recording": "AFE analog CW_OUT I/Q -> external simultaneous ADC -> 50 kSPS host stream",
            "tx_cw_auto_start": False,
        },
    }
