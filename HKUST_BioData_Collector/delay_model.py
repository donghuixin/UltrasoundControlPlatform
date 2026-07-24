"""Delay-law and spatial-aliasing calculations shared by the desktop UI.

The equations intentionally mirror automation/tx7316_hsdc_batch_capture.py.
The hardware capture script remains the authority that writes TX7316 registers;
this module provides fast validation and preview in the Python 3 UI.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


TX_DELAY_MAX_COUNT = 8191
MAX_G1_ELEMENTS = 8
HARDWARE_DELAY_PROFILES_PER_BATCH = 16
# More angles are acquired by rewriting the 16 hardware slots between batches.
# This software guard prevents an accidental sweep from creating huge datasets.
MAX_SWEEP_ANGLES = 64


@dataclass(frozen=True)
class ArrayConfig:
    elements: int = 8
    pitch_mm: float = 1.59
    element_width_mm: float = 1.0
    center_frequency_mhz: float = 2.5
    sound_speed_m_s: float = 1540.0
    delay_quantum_ns: float = 5.0
    reverse_angle_sign: bool = False

    def validate(self) -> None:
        if not 2 <= self.elements <= MAX_G1_ELEMENTS:
            raise ValueError("陣元數必須在 2–8；目前採集腳本控制 TX7316 G1/A1–A8。")
        if self.pitch_mm <= 0:
            raise ValueError("陣元中心間距必須大於 0 mm。")
        if self.element_width_mm <= 0 or self.element_width_mm > self.pitch_mm:
            raise ValueError("陣元寬度必須大於0，且不能大於中心間距。")
        if self.center_frequency_mhz <= 0:
            raise ValueError("中心頻率必須大於 0 MHz。")
        if not 1000.0 <= self.sound_speed_m_s <= 2000.0:
            raise ValueError("聲速必須在 1000–2000 m/s 範圍內。")
        if self.delay_quantum_ns <= 0:
            raise ValueError("延時量化步長必須大於 0 ns。")

    @property
    def pitch_m(self) -> float:
        return self.pitch_mm * 1e-3

    @property
    def wavelength_m(self) -> float:
        return self.sound_speed_m_s / (self.center_frequency_mhz * 1e6)

    @property
    def pitch_over_wavelength(self) -> float:
        return self.pitch_m / self.wavelength_m

    @property
    def half_wavelength_pitch_limit_mhz(self) -> float:
        return self.sound_speed_m_s / (2.0 * self.pitch_m) / 1e6


@dataclass(frozen=True)
class DelayProfile:
    angle_deg: float
    realized_angle_deg: float
    counts_a1_to_a8: tuple[int, ...]
    active_counts: tuple[int, ...]
    mean_phase_step_deg: float
    aperture_delay_cycles: float
    nearest_grating_lobe_deg: float | None


def _linear_slope(xs: list[float], ys: list[float]) -> float:
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator


def grating_lobes_deg(angle_deg: float, config: ArrayConfig) -> list[float]:
    sine_steer = math.sin(math.radians(angle_deg))
    lobes: list[float] = []
    for order in range(-8, 9):
        if order == 0:
            continue
        spatial_value = sine_steer + order * config.wavelength_m / config.pitch_m
        if -1.0 <= spatial_value <= 1.0:
            lobes.append(math.degrees(math.asin(spatial_value)))
    return sorted(lobes, key=lambda value: abs(value - angle_deg))


def calculate_delay_profile(angle_deg: float, config: ArrayConfig) -> DelayProfile:
    config.validate()
    sign = -1.0 if config.reverse_angle_sign else 1.0
    theta = math.radians(angle_deg)
    positions_m = [index * config.pitch_m for index in range(config.elements)]
    raw_delays = [
        sign * position * math.sin(theta) / config.sound_speed_m_s
        for position in positions_m
    ]
    minimum = min(raw_delays)
    shifted = [value - minimum for value in raw_delays]
    quantum_s = config.delay_quantum_ns * 1e-9
    active_counts = [int(math.floor(value / quantum_s + 0.5)) for value in shifted]
    if max(active_counts) > TX_DELAY_MAX_COUNT:
        raise ValueError("延時超出 TX7316 13-bit 計數範圍。")

    active_quantized = [count * quantum_s for count in active_counts]
    slope = _linear_slope(positions_m, active_quantized)
    realized_sine = max(-1.0, min(1.0, config.sound_speed_m_s * slope))
    realized_angle = math.degrees(math.asin(realized_sine))
    adjacent = [
        active_quantized[index + 1] - active_quantized[index]
        for index in range(config.elements - 1)
    ]
    mean_adjacent_s = sum(adjacent) / len(adjacent)
    mean_phase_step = 360.0 * config.center_frequency_mhz * 1e6 * mean_adjacent_s
    aperture_cycles = (
        max(active_quantized) - min(active_quantized)
    ) * config.center_frequency_mhz * 1e6
    lobes = grating_lobes_deg(angle_deg, config)
    padded = active_counts + [0] * (MAX_G1_ELEMENTS - config.elements)
    return DelayProfile(
        angle_deg=angle_deg,
        realized_angle_deg=realized_angle,
        counts_a1_to_a8=tuple(padded),
        active_counts=tuple(active_counts),
        mean_phase_step_deg=mean_phase_step,
        aperture_delay_cycles=aperture_cycles,
        nearest_grating_lobe_deg=lobes[0] if lobes else None,
    )


def build_angle_list(minimum_deg: float, maximum_deg: float, step_deg: float) -> list[float]:
    if step_deg <= 0:
        raise ValueError("角度步進必須大於0。")
    if minimum_deg > maximum_deg:
        raise ValueError("最小角度不能大於最大角度。")
    count = int(math.floor((maximum_deg - minimum_deg) / step_deg + 1e-9)) + 1
    angles = [minimum_deg + index * step_deg for index in range(count)]
    if angles and maximum_deg - angles[-1] > step_deg * 1e-6:
        angles.append(maximum_deg)
    angles = [round(value, 6) for value in angles]
    if len(angles) > MAX_SWEEP_ANGLES:
        raise ValueError(f"角度數超過{MAX_SWEEP_ANGLES}；請縮小範圍或增大步進。")
    return angles


def calculate_profiles(angles: Iterable[float], config: ArrayConfig) -> list[DelayProfile]:
    values = list(angles)
    if not values:
        raise ValueError("至少需要一個掃描角度。")
    if len(values) > MAX_SWEEP_ANGLES:
        raise ValueError(f"角度數超過{MAX_SWEEP_ANGLES}；請縮小範圍或增大步進。")
    return [calculate_delay_profile(angle, config) for angle in values]


def format_angles_cli(angles: Iterable[float]) -> str:
    formatted: list[str] = []
    for value in angles:
        if abs(value - round(value)) < 1e-9:
            formatted.append(str(int(round(value))))
        else:
            formatted.append(("%.4f" % value).rstrip("0").rstrip("."))
    return ",".join(formatted)
