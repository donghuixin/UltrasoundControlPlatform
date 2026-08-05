"""Named PW Doppler presets for carotid-like *flow phantom* validation.

These presets are engineering test points, not human scanning protocols or
stenosis classifiers.  Only the finite HSDC raw-RF preset is executable with
the current backend.  Multi-cycle presets intentionally target the gated
continuous-I/Q contract and remain protected by the application's hardware
gate until that backend is validated.
"""

from __future__ import annotations

from dataclasses import dataclass

from doppler_model import FPGA_RANGE_GATE_IQ_MODE, RAW_RF_DDR_MODE


ONBOARD_PRF_SOURCE = "Onboard CPLD - fixed 1 kHz"
EXTERNAL_PRF_SOURCE = "External synchronized source - manual wiring"


@dataclass(frozen=True)
class DopplerPreset:
    key: str
    label: str
    purpose: str
    capture_mode: str
    prf_source: str
    center_frequency_mhz: float
    prf_hz: float
    steering_angle_deg: float
    flow_angle_deg: float
    target_depth_mm: float
    gate_length_mm: float
    expected_velocity_m_s: float
    desired_duration_s: float
    ensemble_pulses: int
    wall_filter_hz: float
    expected_heart_rate_bpm: float
    block_samples_per_channel: int = 8_388_608
    repeats: int = 1
    trigger: str = "hardware"

    @property
    def current_backend_executable(self) -> bool:
        return self.capture_mode == RAW_RF_DDR_MODE


CAROTID_PHANTOM_PRESETS = (
    DopplerPreset(
        key="carotid_phantom_raw_low_flow",
        label="可執行｜頸動脈仿體低速短塊 · 1 kHz / 70 ms",
        purpose="現有HSDC鏈路的頻移、距離門與方向短時驗證；不能判定心動周期。",
        capture_mode=RAW_RF_DDR_MODE,
        prf_source=ONBOARD_PRF_SOURCE,
        center_frequency_mhz=1.0,
        prf_hz=1_000.0,
        steering_angle_deg=0.0,
        flow_angle_deg=60.0,
        target_depth_mm=25.0,
        gate_length_mm=2.0,
        expected_velocity_m_s=0.25,
        desired_duration_s=0.07,
        ensemble_pulses=64,
        wall_filter_hz=30.0,
        expected_heart_rate_bpm=75.0,
        trigger="normal",
    ),
    DopplerPreset(
        key="carotid_phantom_routine_10s",
        label="需I/Q固件｜頸動脈仿體常規波形 · 5 kHz / 10 s",
        purpose="首次多心動周期驗收；75 BPM約12.5周期，量程覆蓋約1.5 m/s峰值。",
        capture_mode=FPGA_RANGE_GATE_IQ_MODE,
        prf_source=EXTERNAL_PRF_SOURCE,
        center_frequency_mhz=1.0,
        prf_hz=5_000.0,
        steering_angle_deg=0.0,
        flow_angle_deg=60.0,
        target_depth_mm=25.0,
        gate_length_mm=2.0,
        expected_velocity_m_s=1.5,
        desired_duration_s=10.0,
        ensemble_pulses=128,
        wall_filter_hz=50.0,
        expected_heart_rate_bpm=75.0,
    ),
    DopplerPreset(
        key="carotid_phantom_low_flow_15s",
        label="需I/Q固件｜頸動脈仿體低速/舒張流 · 2.5 kHz / 15 s",
        purpose="低速泵與舒張期速度調制；降低wall filter以避免抹除慢流。",
        capture_mode=FPGA_RANGE_GATE_IQ_MODE,
        prf_source=EXTERNAL_PRF_SOURCE,
        center_frequency_mhz=1.0,
        prf_hz=2_500.0,
        steering_angle_deg=0.0,
        flow_angle_deg=60.0,
        target_depth_mm=25.0,
        gate_length_mm=2.0,
        expected_velocity_m_s=0.6,
        desired_duration_s=15.0,
        ensemble_pulses=128,
        wall_filter_hz=20.0,
        expected_heart_rate_bpm=75.0,
    ),
    DopplerPreset(
        key="carotid_phantom_high_velocity_10s",
        label="需I/Q固件｜頸動脈仿體高速射流 · 7.5 kHz / 10 s",
        purpose="已知狹窄管模擬的高速射流；量程優先，必須檢查混疊與後狹窄湍流。",
        capture_mode=FPGA_RANGE_GATE_IQ_MODE,
        prf_source=EXTERNAL_PRF_SOURCE,
        center_frequency_mhz=1.0,
        prf_hz=7_500.0,
        steering_angle_deg=0.0,
        flow_angle_deg=60.0,
        target_depth_mm=25.0,
        gate_length_mm=1.5,
        expected_velocity_m_s=3.0,
        desired_duration_s=10.0,
        ensemble_pulses=256,
        wall_filter_hz=75.0,
        expected_heart_rate_bpm=75.0,
    ),
    DopplerPreset(
        key="carotid_phantom_extended_30s",
        label="需I/Q固件｜頸動脈仿體長記錄 · 5 kHz / 30 s",
        purpose="10秒連續性Gate通過後使用；75 BPM約37.5周期，適合周期穩定性分析。",
        capture_mode=FPGA_RANGE_GATE_IQ_MODE,
        prf_source=EXTERNAL_PRF_SOURCE,
        center_frequency_mhz=1.0,
        prf_hz=5_000.0,
        steering_angle_deg=0.0,
        flow_angle_deg=60.0,
        target_depth_mm=25.0,
        gate_length_mm=2.0,
        expected_velocity_m_s=1.5,
        desired_duration_s=30.0,
        ensemble_pulses=128,
        wall_filter_hz=50.0,
        expected_heart_rate_bpm=75.0,
    ),
)

CAROTID_PHANTOM_PRESETS_BY_KEY = {
    preset.key: preset for preset in CAROTID_PHANTOM_PRESETS
}
CAROTID_PHANTOM_PRESETS_BY_LABEL = {
    preset.label: preset for preset in CAROTID_PHANTOM_PRESETS
}


def get_preset(key: str) -> DopplerPreset:
    try:
        return CAROTID_PHANTOM_PRESETS_BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"Unknown PW Doppler preset: {key}") from exc
