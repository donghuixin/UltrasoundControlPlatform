"""Validated TX7316 waveform plans used by the desktop collector.

The EVM pattern generator selects existing voltage rails; it does not program
the external high-voltage power supplies.  ``hv_a_v`` and ``hv_b_v`` are
therefore operator-entered, measured magnitudes that are recorded for safety
and reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass


TX_CYCLE_OPTIONS = (1, 2, 4, 6, 8, 10, 12)
TX_MIN_EXTERNAL_RAIL_V = 1.5
TX_MAX_EXTERNAL_RAIL_V = 100.0

TX_WAVEFORM_PRESETS = {
    "tapered-5level": {
        "label": "5-level tapered（P/M HV_A、P/M HV_B、AVSS）",
        "frequencies_mhz": (1.0, 1.5, 2.0, 2.5, 4.0),
        "levels": ("+B", "0", "+A", "0", "+B", "0", "-B", "0", "-A", "0", "-B", "0"),
        "purpose": "成像／PW Doppler burst",
    },
    "bipolar-a": {
        "label": "3-level bipolar A（P_HV_A、M_HV_A）",
        "frequencies_mhz": (1.5,),
        "levels": ("+A", "-A"),
        "purpose": "1.493 MHz 診斷方波",
    },
}


@dataclass(frozen=True)
class TxPlan:
    waveform_mode: str
    frequency_mhz: float
    cycles: int
    hv_a_v: float
    hv_b_v: float

    @property
    def preset(self) -> dict:
        return TX_WAVEFORM_PRESETS[self.waveform_mode]

    @property
    def level_sequence(self) -> tuple[str, ...]:
        return tuple(self.preset["levels"])

    @property
    def summary(self) -> str:
        return (
            f"{self.preset['label']} · {self.frequency_mhz:g} MHz · "
            f"{self.cycles} cycles · 外部實測 ±A={self.hv_a_v:g} V / ±B={self.hv_b_v:g} V"
        )


def _is_supported_frequency(value: float, choices: tuple[float, ...]) -> bool:
    return any(abs(value - candidate) < 1e-9 for candidate in choices)


def validate_tx_plan(
    waveform_mode: str,
    frequency_mhz: float,
    cycles: int,
    hv_a_v: float,
    hv_b_v: float,
) -> TxPlan:
    """Validate a conservative, GUI-programmable TX plan.

    The voltage values are magnitudes.  Both positive and negative supplies
    must be set symmetrically by the external bench supplies.
    """
    if waveform_mode not in TX_WAVEFORM_PRESETS:
        raise ValueError(f"不支援的 TX 波形：{waveform_mode}")
    preset = TX_WAVEFORM_PRESETS[waveform_mode]
    if not _is_supported_frequency(float(frequency_mhz), preset["frequencies_mhz"]):
        allowed = ", ".join(f"{value:g}" for value in preset["frequencies_mhz"])
        raise ValueError(
            f"{waveform_mode} 只允許 {allowed} MHz；目前是 {float(frequency_mhz):g} MHz。"
        )
    cycles = int(cycles)
    if cycles not in TX_CYCLE_OPTIONS:
        raise ValueError(
            "TX cycles 必須是 " + ", ".join(str(value) for value in TX_CYCLE_OPTIONS) + " 之一。"
        )
    hv_a_v = float(hv_a_v)
    hv_b_v = float(hv_b_v)
    if not (TX_MIN_EXTERNAL_RAIL_V <= hv_a_v <= TX_MAX_EXTERNAL_RAIL_V):
        raise ValueError("外部 ±HV_A 實測幅值必須在 1.5…100 V。")
    if not (TX_MIN_EXTERNAL_RAIL_V <= hv_b_v <= TX_MAX_EXTERNAL_RAIL_V):
        raise ValueError("外部 ±HV_B 實測幅值必須在 1.5…100 V。")
    # TX7316 5-level EVM nomenclature: HV_A is the outer (higher-
    # magnitude) rail and HV_B is the inner rail shown next to AVSS.
    if waveform_mode == "tapered-5level" and hv_a_v <= hv_b_v:
        raise ValueError("5-level EVM 要求外部 ±HV_A（外層）幅值高於 ±HV_B（內層）。")
    return TxPlan(waveform_mode, float(frequency_mhz), cycles, hv_a_v, hv_b_v)
