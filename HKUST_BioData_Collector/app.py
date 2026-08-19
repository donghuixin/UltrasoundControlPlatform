"""HKUST Ultrosound collector platform desktop UI.

This application provides a safe front end for the existing TX7316/HSDC Pro
automation and offline reconstruction scripts. It can program and verify a
small whitelist of TX pattern levels/timings and pulse counts, but it never
changes the external high-voltage supplies, PRF, or AFE gain.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageTk

from delay_model import (
    ArrayConfig,
    HARDWARE_DELAY_PROFILES_PER_BATCH,
    build_angle_list,
    calculate_profiles,
    format_angles_cli,
)
from cw_doppler_model import (
    CwDopplerConfig,
    CwDopplerResult,
    CwRowConfig,
    IQ_RATE_DECIMATION,
    calculate_cw_doppler,
    cw_plan_as_dict,
    estimate_dbud_velocity,
)
from cw_capture_ui import (
    build_cw_capture_panel,
    init_cw_capture_state,
    serialize_cw_capture_state,
)
from doppler_model import (
    AFE_DEMOD_IQ_MODE,
    FPGA_RANGE_GATE_IQ_MODE,
    RAW_RF_DDR_MODE,
    DopplerConfig,
    DopplerResult,
    calculate_doppler,
    result_as_dict,
)
from doppler_presets import (
    CAROTID_PHANTOM_PRESETS,
    CAROTID_PHANTOM_PRESETS_BY_KEY,
    CAROTID_PHANTOM_PRESETS_BY_LABEL,
    DopplerPreset,
)
from rapid_scan_model import (
    RapidScanConfig,
    build_rapid_scan_plan,
    contiguous_prf_block_samples,
    plan_as_dict,
)
from tx_plan import TX_CYCLE_OPTIONS, TX_WAVEFORM_PRESETS, TxPlan, validate_tx_plan


APP_DIR = Path(__file__).resolve().parent
CAPTURE_ROOT = APP_DIR.parent
AUTOMATION_SCRIPT = CAPTURE_ROOT / "automation" / "tx7316_hsdc_batch_capture.py"
RECONSTRUCTION_SCRIPT = CAPTURE_ROOT / "reconstruct_ultrasound.py"
DEFAULT_AUTO_RUNS = CAPTURE_ROOT / "auto_runs"
PYTHON27 = Path(r"C:\Python27\python.exe")
CONFIG_PATH = APP_DIR / "collector_config.json"
DOPPLER_GUIDE = APP_DIR / "PW_DOPPLER_OPERATION_GUIDE.md"
DOPPLER_ANALYSIS_SCRIPT = APP_DIR / "pw_doppler_analysis.py"
CW_DOPPLER_GUIDE = APP_DIR / "CW_DOPPLER_OPERATION_GUIDE.md"
CW_DOPPLER_STAGE_SCRIPT = CAPTURE_ROOT / "automation" / "stage_cw_doppler.py"
CW_TX_CONTROL_SCRIPT = CAPTURE_ROOT / "automation" / "tx7316_cw_control.py"
RX_CHANNELS_IN_CAPTURE_FILE = 16
BYTES_PER_ADC_SAMPLE = 2
ADC_SAMPLE_RATE_HZ = 120_000_000.0

AUTO_SCAN_CPLD_BLOCK_MODE = "板載CPLD：每角32個連續PRF（推薦）"

AUTO_SCAN_VERIFIED_MODE = "已驗證：每角度獨立BIN"
AUTO_SCAN_RAPID_MODE = "逐PRF：每SYNC換角度（需快速掃描固件）"

DUPLICATE_POLICY_OPTIONS = {
    "自動去重：保留映射中先出現者": "drop-later",
    "保留全部配置槽（僅作診斷）": "keep-all",
    "手動指定DAS接收槽": "manual",
}
ANGLE_SUBSET_OPTIONS = {
    "使用全部已採集角度": None,
    "按2°子集重建（1°資料隔一個取一個）": 2.0,
}
RECEIVE_APODIZATION_OPTIONS = {
    "均勻（原始）": "uniform",
    "Hann（較強旁瓣抑制）": "hann",
    "Tukey α=0.5（折衷）": "tukey",
}
DOPPLER_CAPTURE_MODE_OPTIONS = {
    "現有可執行：HSDC原始RF單塊": RAW_RF_DDR_MODE,
    "最佳心動周期：FPGA距離門I/Q（待驗證固件）": FPGA_RANGE_GATE_IQ_MODE,
    "研究路徑：AFE Demod I/Q（待JESD解包）": AFE_DEMOD_IQ_MODE,
}
CW_DOPPLER_BACKEND_OPTIONS = {
    "推薦長時：AFE類比CW I/Q + 外部同步ADC": "analog-cw-external-adc",
    "研究驗證：AFE數位DDC/8 + TSW14J50": "digital-iq-tsw14j50",
}


COLORS = {
    "background": "#F4F7FB",
    "surface": "#FFFFFF",
    "surface_soft": "#F8FAFD",
    "glass": "#F9FBFE",
    "border": "#DDE7F2",
    "border_strong": "#C9D8E8",
    "text": "#10233F",
    "muted": "#60738A",
    "primary": "#1E5EFF",
    "primary_hover": "#174BD0",
    "primary_soft": "#E9F0FF",
    "cyan": "#00A7C8",
    "success": "#12805C",
    "success_soft": "#E7F6F0",
    "warning": "#A76208",
    "warning_soft": "#FFF3DA",
    "danger": "#C23A42",
    "danger_soft": "#FDECEE",
}


def enable_high_dpi() -> None:
    """Prevent Windows from bitmap-scaling the whole Tk window.

    Tk uses TrueType/OpenType system fonts, but without process DPI awareness
    Windows may first draw the window at 96 DPI and then stretch that bitmap.
    Per-monitor-v2 awareness keeps text and controls vector-sharp at 125-250%.
    """
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def is_windows_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def complete_capture_runs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    runs: list[Path] = []
    for directory in root.glob("capture_*"):
        manifest = read_json(directory / "capture_manifest.json")
        if manifest.get("status") == "complete":
            runs.append(directory)
    return sorted(runs, key=lambda item: item.stat().st_mtime, reverse=True)


def visible_window_titles() -> list[str]:
    if os.name != "nt":
        return []
    titles: list[str] = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                titles.append(buffer.value)
        return True

    user32.EnumWindows(callback, 0)
    return titles


class CollectorApp(tk.Tk):
    def __init__(self, start_page: str = "array") -> None:
        super().__init__()
        # Match Tk's point-to-pixel conversion to the active monitor. The UI
        # fonts below are Windows TrueType fonts, never pre-rendered bitmaps.
        monitor_dpi = max(96.0, float(self.winfo_fpixels("1i")))
        self.tk.call("tk", "scaling", monitor_dpi / 72.0)
        self.title("HKUST Ultrosound collector platform")
        self.geometry("1440x900")
        self.minsize(1120, 720)
        self.configure(bg=COLORS["background"])
        self.option_add("*Font", ("Segoe UI", 10))
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        self.settings = read_json(CONFIG_PATH)
        self.background_photo: ImageTk.PhotoImage | None = None
        self.background_job: str | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.preview_path: Path | None = None
        self.preview_filename = "plane_wave_das_bmode.png"
        self.current_prf_cycle_index = -1
        self.processing_active = False
        self.tx_programming_active = False
        self.capture_watch: dict | None = None
        self.pages: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.active_page = ""

        self._configure_styles()
        self._create_variables()
        self._build_shell()
        self._build_array_page()
        self._build_capture_page()
        self._build_auto_scan_page()
        self._build_doppler_page()
        self._build_cw_doppler_page()
        self._build_processing_page()
        self.show_page(start_page if start_page in self.pages else "array")
        self.recalculate_delays(show_errors=False)
        self.recalculate_auto_scan(show_errors=False)
        self.recalculate_doppler(show_errors=False)
        self.recalculate_cw_doppler(show_errors=False)
        self.refresh_capture_runs()
        self._poll_external_state()

        self.bind("<Alt-Key-1>", lambda _event: self.show_page("array"))
        self.bind("<Alt-Key-2>", lambda _event: self.show_page("capture"))
        self.bind("<Alt-Key-3>", lambda _event: self.show_page("auto_scan"))
        self.bind("<Alt-Key-4>", lambda _event: self.show_page("doppler"))
        self.bind("<Alt-Key-5>", lambda _event: self.show_page("cw_doppler"))
        self.bind("<Alt-Key-6>", lambda _event: self.show_page("processing"))
        self.bind("<Configure>", self._schedule_background)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Glass.TFrame", background=COLORS["glass"])
        style.configure("TLabel", background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["surface"], foreground=COLORS["muted"])
        style.configure("Glass.TLabel", background=COLORS["glass"], foreground=COLORS["text"])
        style.configure("GlassMuted.TLabel", background=COLORS["glass"], foreground=COLORS["muted"])
        style.configure("PageTitle.TLabel", background=COLORS["background"], foreground=COLORS["text"], font=("Segoe UI Semibold", 22))
        style.configure("PageHint.TLabel", background=COLORS["background"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI Semibold", 12))
        style.configure("Metric.TLabel", background=COLORS["surface"], foreground=COLORS["primary"], font=("Cascadia Mono", 12, "bold"))

        style.configure(
            "Primary.TButton",
            background=COLORS["primary"],
            foreground="#FFFFFF",
            bordercolor=COLORS["primary"],
            focusthickness=2,
            focuscolor=COLORS["primary_hover"],
            padding=(18, 11),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Primary.TButton",
            background=[("pressed", COLORS["primary_hover"]), ("active", COLORS["primary_hover"]), ("disabled", "#A9BDE5")],
            foreground=[("disabled", "#F5F7FB")],
        )
        style.configure(
            "Secondary.TButton",
            background=COLORS["surface"],
            foreground=COLORS["primary"],
            bordercolor=COLORS["border_strong"],
            focusthickness=2,
            focuscolor=COLORS["primary"],
            padding=(16, 10),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Secondary.TButton", background=[("active", COLORS["primary_soft"]), ("pressed", "#DCE8FF")])
        style.configure(
            "Danger.TButton",
            background=COLORS["danger"],
            foreground="#FFFFFF",
            bordercolor=COLORS["danger"],
            focusthickness=2,
            focuscolor="#8F2229",
            padding=(18, 11),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Danger.TButton", background=[("active", "#A72D35"), ("pressed", "#8F2229"), ("disabled", "#D9A5A9")])
        style.configure(
            "Nav.TButton",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            borderwidth=0,
            anchor="w",
            padding=(16, 13),
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "NavSelected.TButton",
            background=COLORS["primary_soft"],
            foreground=COLORS["primary"],
            bordercolor=COLORS["primary_soft"],
            anchor="w",
            padding=(16, 13),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Nav.TButton", background=[("active", COLORS["surface_soft"])])

        style.configure("TEntry", fieldbackground="#FFFFFF", foreground=COLORS["text"], bordercolor=COLORS["border_strong"], lightcolor=COLORS["border_strong"], darkcolor=COLORS["border_strong"], padding=(10, 8))
        style.map("TEntry", bordercolor=[("focus", COLORS["primary"])], lightcolor=[("focus", COLORS["primary"])], darkcolor=[("focus", COLORS["primary"])])
        style.configure("TCombobox", fieldbackground="#FFFFFF", foreground=COLORS["text"], bordercolor=COLORS["border_strong"], padding=(9, 7))
        style.configure("TCheckbutton", background=COLORS["surface"], foreground=COLORS["text"], padding=(2, 4))
        style.map("TCheckbutton", background=[("active", COLORS["surface"])])
        style.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground=COLORS["text"], rowheight=30, bordercolor=COLORS["border"], font=("Cascadia Mono", 9))
        style.configure("Treeview.Heading", background=COLORS["surface_soft"], foreground=COLORS["text"], bordercolor=COLORS["border"], padding=(6, 8), font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", COLORS["primary_soft"])], foreground=[("selected", COLORS["primary_hover"])])
        style.configure("Horizontal.TProgressbar", background=COLORS["primary"], troughcolor=COLORS["primary_soft"], bordercolor=COLORS["primary_soft"], lightcolor=COLORS["primary"], darkcolor=COLORS["primary"])

    def _create_variables(self) -> None:
        get = self.settings.get
        self.elements_var = tk.IntVar(value=int(get("elements", 8)))
        self.pitch_var = tk.StringVar(value=str(get("pitch_mm", 1.59)))
        self.width_var = tk.StringVar(value=str(get("element_width_mm", 1.0)))
        self.rx_channels_var = tk.StringVar(
            value=str(get("rx_hsdc_slots", "1,2,3,4,5,6,7,8"))
        )
        saved_frequency = str(get("center_frequency_mhz", 1.0))
        saved_waveform = str(get("waveform_mode", "tapered-5level"))
        try:
            saved_frequency_value = float(saved_frequency)
        except ValueError:
            saved_frequency_value = 1.0
        # Migrate the older hidden default (bipolar-a + a newly edited 1 MHz
        # field) to a valid pair.  bipolar-a has only a qualified 1.5 MHz
        # profile; leaving that stale value would make the first TX write fail.
        if saved_waveform == "bipolar-a" and abs(saved_frequency_value - 1.5) > 1e-9:
            saved_waveform = "tapered-5level"
        self.frequency_var = tk.StringVar(value=saved_frequency)
        self.sound_speed_var = tk.StringVar(value=str(get("sound_speed_m_s", 1540.0)))
        self.quantum_var = tk.StringVar(value=str(get("delay_quantum_ns", 5.0)))
        self.min_angle_var = tk.StringVar(value=str(get("min_angle", -10.0)))
        self.max_angle_var = tk.StringVar(value=str(get("max_angle", 10.0)))
        self.angle_step_var = tk.StringVar(value=str(get("angle_step", 1.0)))
        self.reverse_var = tk.BooleanVar(value=bool(get("reverse_angle_sign", False)))

        self.samples_var = tk.StringVar(value=str(get("samples", 1048576)))
        self.repeats_var = tk.StringVar(value=str(get("repeats", 1)))
        self.settle_var = tk.StringVar(value=str(get("settle_seconds", 0.25)))
        self.trigger_var = tk.StringVar(value=str(get("trigger", "normal")))
        self.waveform_mode_var = tk.StringVar(
            value=saved_waveform
        )
        self.tx_cycles_var = tk.StringVar(value=str(get("tx_cycles", 4)))
        self.tx_hv_a_var = tk.StringVar(value=str(get("tx_hv_a_v", 100.0)))
        self.tx_hv_b_var = tk.StringVar(value=str(get("tx_hv_b_v", 50.0)))
        # A safety acknowledgement must never survive an application restart.
        self.tx_plan_confirmed_var = tk.BooleanVar(value=False)
        self.tx_plan_summary_var = tk.StringVar(value="TX 計畫尚未確認")
        self.tx_plan_detail_var = tk.StringVar(value="")
        for variable in (
            self.waveform_mode_var,
            self.frequency_var,
            self.tx_cycles_var,
            self.tx_hv_a_var,
            self.tx_hv_b_var,
        ):
            variable.trace_add("write", lambda *_args: self._tx_plan_changed())
        self.output_root_var = tk.StringVar(value=str(get("output_root", DEFAULT_AUTO_RUNS)))
        self.capture_folder_var = tk.StringVar(value="")
        self.capture_status_var = tk.StringVar(value="尚未啟動採集")
        self.command_preview_var = tk.StringVar(value="修改參數後，採集命令會顯示在這裡。")
        self.array_summary_var = tk.StringVar(value="等待計算")
        self.array_warning_var = tk.StringVar(value="")
        self.sweep_estimate_var = tk.StringVar(value="")
        self.processing_status_var = tk.StringVar(value="選擇一個完整的 capture_* 文件夾。")
        self.duplicate_policy_var = tk.StringVar(
            value=str(
                get(
                    "duplicate_policy_label",
                    "自動去重：保留映射中先出現者",
                )
            )
        )
        self.manual_das_rx_var = tk.StringVar(
            value=str(get("manual_das_rx_slots", "1,2,3,4,5,6,7,8"))
        )
        self.reconstruction_angle_subset_var = tk.StringVar(
            value=str(get("reconstruction_angle_subset_label", "使用全部已採集角度"))
        )
        saved_apodization = str(
            get("receive_apodization_label", "均勻（原始）")
        )
        if saved_apodization not in RECEIVE_APODIZATION_OPTIONS:
            saved_apodization = "均勻（原始）"
        self.receive_apodization_var = tk.StringVar(value=saved_apodization)
        self.coherence_factor_var = tk.BooleanVar(
            value=bool(get("coherence_factor_enabled", False))
        )
        self.common_mode_suppression_var = tk.BooleanVar(
            value=bool(get("common_mode_ringdown_suppression_enabled", False))
        )
        self.processing_option_help_var = tk.StringVar(value="")
        self.result_summary_var = tk.StringVar(value="尚未載入分析結果。")
        self.preview_source_var = tk.StringVar(value="尚未選擇結果來源")
        self.header_admin_var = tk.StringVar(value="Admin: checking")
        self.header_tx_var = tk.StringVar(value="TX GUI: checking")
        self.header_hsdc_var = tk.StringVar(value="HSDC: checking")
        self.prerequisite_vars = [tk.BooleanVar(value=False) for _ in range(5)]

        saved_auto_scan_mode = str(get("auto_scan_mode", AUTO_SCAN_CPLD_BLOCK_MODE))
        if saved_auto_scan_mode == AUTO_SCAN_RAPID_MODE:
            saved_auto_scan_mode = AUTO_SCAN_CPLD_BLOCK_MODE
        self.auto_scan_mode_var = tk.StringVar(value=saved_auto_scan_mode)
        self.auto_scan_prf_var = tk.StringVar(value=str(get("auto_scan_prf_hz", 1000.0)))
        self.auto_scan_frames_var = tk.StringVar(value=str(get("auto_scan_frames", 32)))
        self.auto_scan_guard_var = tk.StringVar(value=str(get("auto_scan_guard_prfs", 1)))
        self.auto_scan_summary_var = tk.StringVar(value="等待掃描時序計算")
        self.auto_scan_status_var = tk.StringVar(value="尚未生成逐PRF掃描方案")
        self.auto_scan_gate_var = tk.StringVar(value="FIRMWARE REQUIRED")
        self.auto_scan_confirm_vars = [tk.BooleanVar(value=False) for _ in range(3)]
        if self.auto_scan_mode_var.get() == AUTO_SCAN_CPLD_BLOCK_MODE:
            self.min_angle_var.set("-10")
            self.max_angle_var.set("10")
            self.angle_step_var.set("2")
            self.auto_scan_frames_var.set("32")

        self.doppler_prf_source_var = tk.StringVar(
            value=str(get("doppler_prf_source", "Onboard CPLD - fixed 1 kHz"))
        )
        saved_doppler_mode = str(
            get("doppler_capture_mode_label", "現有可執行：HSDC原始RF單塊")
        )
        if saved_doppler_mode not in DOPPLER_CAPTURE_MODE_OPTIONS:
            saved_doppler_mode = "現有可執行：HSDC原始RF單塊"
        self.doppler_capture_mode_var = tk.StringVar(value=saved_doppler_mode)
        saved_preset_key = str(get("doppler_preset_key", "carotid_phantom_raw_low_flow"))
        if saved_preset_key not in CAROTID_PHANTOM_PRESETS_BY_KEY:
            saved_preset_key = "carotid_phantom_raw_low_flow"
        self.doppler_preset_var = tk.StringVar(
            value=CAROTID_PHANTOM_PRESETS_BY_KEY[saved_preset_key].label
        )
        self.doppler_preset_note_var = tk.StringVar(value="")
        self.doppler_prf_var = tk.StringVar(value=str(get("doppler_prf_hz", 1000.0)))
        self.doppler_steering_var = tk.StringVar(value=str(get("doppler_steering_angle_deg", 0.0)))
        self.doppler_flow_angle_var = tk.StringVar(value=str(get("doppler_flow_angle_deg", 60.0)))
        self.doppler_depth_var = tk.StringVar(value=str(get("doppler_target_depth_mm", 25.0)))
        self.doppler_gate_length_var = tk.StringVar(value=str(get("doppler_gate_length_mm", 2.0)))
        self.doppler_velocity_var = tk.StringVar(value=str(get("doppler_expected_velocity_m_s", 1.0)))
        self.doppler_duration_var = tk.StringVar(value=str(get("doppler_duration_s", 6.0)))
        self.doppler_ensemble_var = tk.StringVar(value=str(get("doppler_ensemble_pulses", 256)))
        self.doppler_wall_filter_var = tk.StringVar(value=str(get("doppler_wall_filter_hz", 50.0)))
        self.doppler_heart_rate_var = tk.StringVar(value=str(get("doppler_expected_heart_rate_bpm", 75.0)))
        self.doppler_samples_var = tk.StringVar(value=str(get("doppler_block_samples", 4194304)))
        self.doppler_repeats_var = tk.StringVar(value=str(get("doppler_repeats", 1)))
        self.doppler_trigger_var = tk.StringVar(value=str(get("doppler_trigger", "normal")))
        self.doppler_sync_confirmed_var = tk.BooleanVar(value=False)
        self.doppler_phantom_confirmed_var = tk.BooleanVar(value=False)
        self.doppler_gap_ack_var = tk.BooleanVar(value=False)
        self.doppler_summary_var = tk.StringVar(value="等待PW Doppler計算")
        self.doppler_storage_var = tk.StringVar(value="")
        self.doppler_warning_var = tk.StringVar(value="")
        self.doppler_status_var = tk.StringVar(value="尚未啟動Doppler短塊採集")
        self.doppler_command_var = tk.StringVar(value="修改參數後，單角度命令會顯示在這裡。")
        self.doppler_analysis_status_var = tk.StringVar(value="尚未分析PW Doppler資料。")
        self.doppler_result_var = tk.StringVar(value="速度譜會保存到 capture/analysis/pw_doppler。")
        self.doppler_result_run: Path | None = None

        saved_cw_backend = str(
            get("cw_backend_label", "推薦長時：AFE類比CW I/Q + 外部同步ADC")
        )
        if saved_cw_backend not in CW_DOPPLER_BACKEND_OPTIONS:
            saved_cw_backend = "推薦長時：AFE類比CW I/Q + 外部同步ADC"
        self.cw_backend_var = tk.StringVar(value=saved_cw_backend)
        saved_cw_frequency = float(get("cw_center_frequency_mhz", 3.125))
        if saved_cw_frequency not in (1.0, 2.0, 3.125, 4.0):
            saved_cw_frequency = 3.125
        saved_cw_iq_rate = float(get("cw_iq_output_rate_msps", 15.0))
        if saved_cw_iq_rate not in (15.0, 10.0, 7.5, 6.0, 5.0):
            saved_cw_iq_rate = 15.0
        self.cw_frequency_var = tk.StringVar(value=f"{saved_cw_frequency:g}")
        self.cw_adc_rate_var = tk.StringVar(value="120")
        self.cw_iq_rate_var = tk.StringVar(value=f"{saved_cw_iq_rate:g}")
        self.cw_decimation_var = tk.StringVar(value=str(int(round(120.0 / (2.0 * saved_cw_iq_rate)))))
        self.cw_logical_channels_var = tk.StringVar(value="8")
        self.cw_duration_var = tk.StringVar(value=str(get("cw_duration_s", 10.0)))
        self.cw_analysis_rate_var = tk.StringVar(value=str(get("cw_analysis_rate_ksps", 50.0)))
        self.cw_lowpass_var = tk.StringVar(value=str(get("cw_lowpass_khz", 20.0)))
        self.cw_wall_filter_var = tk.StringVar(value=str(get("cw_wall_filter_hz", 150.0)))
        self.cw_stft_samples_var = tk.StringVar(value=str(get("cw_stft_samples", 1024)))
        self.cw_stft_overlap_var = tk.StringVar(value=str(get("cw_stft_overlap", 900)))
        saved_angles = get("cw_row_angles_deg", [17.0, 20.0, 23.0])
        saved_slots = get("cw_afe_rx_slots", [1, 2, 3])
        saved_doppler_hz = get("cw_row_doppler_hz", ["", "", ""])
        if not isinstance(saved_angles, list) or len(saved_angles) != 3:
            saved_angles = [17.0, 20.0, 23.0]
        if not isinstance(saved_slots, list) or len(saved_slots) != 3:
            saved_slots = [1, 2, 3]
        if not isinstance(saved_doppler_hz, list) or len(saved_doppler_hz) != 3:
            saved_doppler_hz = ["", "", ""]
        self.cw_row_angle_vars = [tk.StringVar(value=str(value)) for value in saved_angles]
        self.cw_row_rx_slot_vars = [tk.StringVar(value=str(value)) for value in saved_slots]
        self.cw_row_doppler_vars = [tk.StringVar(value=str(value)) for value in saved_doppler_hz]
        self.cw_summary_var = tk.StringVar(value="等待CW Doppler幾何計算")
        self.cw_storage_var = tk.StringVar(value="")
        self.cw_warning_var = tk.StringVar(value="")
        self.cw_velocity_result_var = tk.StringVar(value="輸入三行帶符號 fD（Hz）後計算 DBUD 流速與流向。")
        self.cw_status_var = tk.StringVar(value="尚未導出CW Doppler配置方案。")
        self.cw_phantom_confirmed_var = tk.BooleanVar(value=False)
        self.cw_thermal_confirmed_var = tk.BooleanVar(value=False)
        self.cw_path_confirmed_var = tk.BooleanVar(value=False)
        self.cw_tx_low_voltage_confirmed_var = tk.BooleanVar(value=False)
        self.cw_tx_supply_var = tk.StringVar(value=str(get("cw_tx_supply_v", 5.0)))
        self.cw_tx_test_seconds_var = tk.StringVar(value=str(get("cw_tx_test_seconds", 3.0)))
        self.cw_last_plan: Path | None = None
        init_cw_capture_state(self, get, APP_DIR, CAPTURE_ROOT, PYTHON27)

    def _build_shell(self) -> None:
        self.background_label = tk.Label(self, bg=COLORS["background"], borderwidth=0)
        self.background_label.place(x=0, y=0, relwidth=1, relheight=1)

        shell = tk.Frame(self, bg=COLORS["background"])
        shell.place(x=20, y=18, relwidth=1, relheight=1, width=-40, height=-36)
        shell.grid_rowconfigure(1, weight=1)
        shell.grid_columnconfigure(1, weight=1)

        header = tk.Frame(shell, bg=COLORS["surface"], highlightbackground=COLORS["border"], highlightthickness=1)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(1, weight=1)
        title_stack = tk.Frame(header, bg=COLORS["surface"])
        title_stack.grid(row=0, column=0, padx=24, pady=16, sticky="w")
        tk.Label(title_stack, text="HKUST Ultrosound collector platform", bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI Semibold", 19)).pack(anchor="w")
        tk.Label(title_stack, text="Ultrasound acquisition · delay control · offline reconstruction", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        status_row = tk.Frame(header, bg=COLORS["surface"])
        status_row.grid(row=0, column=2, padx=20, pady=16, sticky="e")
        self.admin_chip = self._status_chip(status_row, self.header_admin_var)
        self.tx_chip = self._status_chip(status_row, self.header_tx_var)
        self.hsdc_chip = self._status_chip(status_row, self.header_hsdc_var)

        sidebar = tk.Frame(shell, bg=COLORS["surface"], width=214, highlightbackground=COLORS["border"], highlightthickness=1)
        sidebar.grid(row=1, column=0, sticky="nsw", padx=(0, 14))
        sidebar.grid_propagate(False)
        tk.Label(sidebar, text="WORKSPACE", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=18, pady=(22, 8))
        nav_items = [
            ("array", "陣列與延時  Array"),
            ("capture", "自動採集  Capture"),
            ("auto_scan", "逐PRF掃描  Auto Scan"),
            ("doppler", "PW多普勒  Doppler"),
            ("cw_doppler", "CW多普勒  DBUD"),
            ("processing", "處理與成像  Process"),
        ]
        for key, label in nav_items:
            button = ttk.Button(sidebar, text=label, style="Nav.TButton", command=lambda name=key: self.show_page(name))
            button.pack(fill="x", padx=10, pady=3)
            self.nav_buttons[key] = button

        safety = tk.Frame(sidebar, bg=COLORS["warning_soft"], highlightbackground="#F0D49C", highlightthickness=1)
        safety.pack(side="bottom", fill="x", padx=12, pady=14)
        tk.Label(safety, text="凝膠／仿體限定", bg=COLORS["warning_soft"], fg=COLORS["warning"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=12, pady=(11, 3))
        tk.Label(safety, text="不自動修改高壓、PRF、脈衝數或AFE增益。", bg=COLORS["warning_soft"], fg=COLORS["warning"], justify="left", wraplength=170, font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(0, 11))

        self.page_host = tk.Frame(shell, bg=COLORS["background"])
        self.page_host.grid(row=1, column=1, sticky="nsew")
        self.page_host.grid_rowconfigure(0, weight=1)
        self.page_host.grid_columnconfigure(0, weight=1)

    def _status_chip(self, parent: tk.Widget, variable: tk.StringVar) -> tk.Label:
        label = tk.Label(parent, textvariable=variable, bg=COLORS["surface_soft"], fg=COLORS["muted"], padx=12, pady=7, font=("Segoe UI Semibold", 9), highlightbackground=COLORS["border"], highlightthickness=1)
        label.pack(side="left", padx=4)
        return label

    def _new_page(self, name: str) -> tk.Frame:
        frame = tk.Frame(self.page_host, bg=COLORS["background"])
        frame.grid(row=0, column=0, sticky="nsew")
        self.pages[name] = frame
        return frame

    def _page_heading(self, parent: tk.Widget, title: str, hint: str) -> None:
        top = tk.Frame(parent, bg=COLORS["background"])
        top.pack(fill="x", pady=(2, 14))
        ttk.Label(top, text=title, style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(top, text=hint, style="PageHint.TLabel").pack(anchor="w", pady=(3, 0))

    def _card(self, parent: tk.Widget) -> tk.Frame:
        shadow = tk.Frame(parent, bg="#DCE6F1")
        card = tk.Frame(shadow, bg=COLORS["surface"], highlightbackground=COLORS["border"], highlightthickness=1)
        card.pack(fill="both", expand=True, padx=(0, 2), pady=(0, 2))
        card._shadow_wrapper = shadow  # type: ignore[attr-defined]
        return card

    def _labeled_entry(self, parent: tk.Widget, label: str, variable: tk.Variable, width: int = 12) -> ttk.Entry:
        holder = tk.Frame(parent, bg=COLORS["surface"])
        tk.Label(holder, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        entry = ttk.Entry(holder, textvariable=variable, width=width)
        entry.pack(fill="x")
        holder.pack(side="left", fill="x", expand=True, padx=(0, 10))
        entry.bind("<FocusOut>", lambda _event: self.recalculate_delays(show_errors=False))
        return entry

    def _cw_labeled_entry(
        self,
        parent: tk.Widget,
        label: str,
        variable: tk.Variable,
        width: int = 12,
        readonly: bool = False,
    ) -> ttk.Entry:
        holder = tk.Frame(parent, bg=COLORS["surface"])
        tk.Label(holder, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        entry = ttk.Entry(holder, textvariable=variable, width=width, state="readonly" if readonly else "normal")
        entry.pack(fill="x")
        holder.pack(side="left", fill="x", expand=True, padx=(0, 10))
        if not readonly:
            entry.bind("<FocusOut>", lambda _event: self.recalculate_cw_doppler(show_errors=False))
        return entry

    def _cw_labeled_combo(
        self,
        parent: tk.Widget,
        label: str,
        variable: tk.Variable,
        values: tuple[str, ...],
        command,
    ) -> ttk.Combobox:
        holder = tk.Frame(parent, bg=COLORS["surface"])
        tk.Label(holder, text=label, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        combo = ttk.Combobox(holder, textvariable=variable, values=values, state="readonly")
        combo.pack(fill="x")
        holder.pack(side="left", fill="x", expand=True, padx=(0, 10))
        combo.bind("<<ComboboxSelected>>", lambda _event: command())
        return combo

    def _build_array_page(self) -> None:
        page = self._new_page("array")
        self._page_heading(page, "陣列幾何與角度延時", "輸入實際陣元參數；計算值會與正式 Python 2.7 採集腳本使用同一套公式。")

        scroll_host = tk.Frame(page, bg=COLORS["background"])
        scroll_host.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, bg=COLORS["background"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body = tk.Frame(canvas, bg=COLORS["background"])
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))

        top_row = tk.Frame(body, bg=COLORS["background"])
        top_row.pack(fill="x", pady=(0, 14))
        top_row.grid_columnconfigure(0, weight=3)
        top_row.grid_columnconfigure(1, weight=2)

        geometry = self._card(top_row)
        geometry._shadow_wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 10))  # type: ignore[attr-defined]
        ttk.Label(geometry, text="Array geometry", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(16, 12))
        row1 = tk.Frame(geometry, bg=COLORS["surface"])
        row1.pack(fill="x", padx=18)
        self._labeled_entry(row1, "陣元數 A1…AN", self.elements_var)
        self._labeled_entry(row1, "中心間距 (mm)", self.pitch_var)
        self._labeled_entry(row1, "陣元寬度 (mm)", self.width_var)
        row2 = tk.Frame(geometry, bg=COLORS["surface"])
        row2.pack(fill="x", padx=18, pady=(12, 16))
        self._labeled_entry(row2, "中心頻率 (MHz)", self.frequency_var)
        self._labeled_entry(row2, "聲速 (m/s)", self.sound_speed_var)
        self._labeled_entry(row2, "延時量化 (ns)", self.quantum_var)
        row3 = tk.Frame(geometry, bg=COLORS["surface"])
        row3.pack(fill="x", padx=18, pady=(0, 16))
        self._labeled_entry(
            row3,
            "A1…AN 對應的 HSDC 接收槽（依序；逗號分隔）",
            self.rx_channels_var,
            width=34,
        )

        sweep = self._card(top_row)
        sweep._shadow_wrapper.grid(row=0, column=1, sticky="nsew", padx=(10, 0))  # type: ignore[attr-defined]
        ttk.Label(sweep, text="Angle sweep", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(16, 12))
        sweep_fields = tk.Frame(sweep, bg=COLORS["surface"])
        sweep_fields.pack(fill="x", padx=18)
        self._labeled_entry(sweep_fields, "最小角度 (°)", self.min_angle_var)
        self._labeled_entry(sweep_fields, "最大角度 (°)", self.max_angle_var)
        step_holder = tk.Frame(sweep_fields, bg=COLORS["surface"])
        tk.Label(step_holder, text="角度步進 (°)", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        self.angle_step_combo = ttk.Combobox(
            step_holder,
            textvariable=self.angle_step_var,
            values=["1", "2"],
            state="readonly",
            width=12,
        )
        self.angle_step_combo.pack(fill="x")
        self.angle_step_combo.bind("<<ComboboxSelected>>", lambda _event: self.recalculate_delays(show_errors=False))
        step_holder.pack(side="left", fill="x", expand=True)
        reverse = ttk.Checkbutton(sweep, text="反轉陣列左右方向", variable=self.reverse_var, command=lambda: self.recalculate_delays(show_errors=False))
        reverse.pack(anchor="w", padx=18, pady=(12, 8))
        tk.Label(
            sweep,
            textvariable=self.sweep_estimate_var,
            bg=COLORS["primary_soft"],
            fg=COLORS["primary_hover"],
            anchor="w",
            justify="left",
            wraplength=430,
            padx=10,
            pady=7,
            font=("Cascadia Mono", 9),
        ).pack(fill="x", padx=18, pady=(0, 8))
        ttk.Button(sweep, text="重新計算延時", style="Primary.TButton", command=self.recalculate_delays).pack(anchor="e", padx=18, pady=(0, 16))

        tx_card = self._card(body)
        tx_card._shadow_wrapper.pack(fill="x", pady=(0, 12))  # type: ignore[attr-defined]
        tx_header = tk.Frame(tx_card, bg=COLORS["surface"])
        tx_header.pack(fill="x", padx=18, pady=(14, 8))
        ttk.Label(tx_header, text="TX7316 pattern plan", style="CardTitle.TLabel").pack(side="left")
        self.tx_plan_status_label = tk.Label(
            tx_header,
            textvariable=self.tx_plan_summary_var,
            bg=COLORS["warning_soft"],
            fg=COLORS["warning"],
            padx=10,
            pady=5,
            font=("Segoe UI Semibold", 9),
            highlightbackground="#F0D49C",
            highlightthickness=1,
        )
        self.tx_plan_status_label.pack(side="right")

        tx_body = tk.Frame(tx_card, bg=COLORS["surface"])
        tx_body.pack(fill="x", padx=18, pady=(0, 14))
        tx_controls = tk.Frame(tx_body, bg=COLORS["surface"])
        tx_controls.pack(side="left", fill="x", expand=True)

        tx_row = tk.Frame(tx_controls, bg=COLORS["surface"])
        tx_row.pack(fill="x")
        waveform_holder = tk.Frame(tx_row, bg=COLORS["surface"])
        waveform_holder.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(waveform_holder, text="波形／電平路徑", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        self.tx_waveform_combo = ttk.Combobox(
            waveform_holder,
            textvariable=self.waveform_mode_var,
            values=list(TX_WAVEFORM_PRESETS),
            state="readonly",
            width=22,
        )
        self.tx_waveform_combo.pack(fill="x")

        cycles_holder = tk.Frame(tx_row, bg=COLORS["surface"])
        cycles_holder.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(cycles_holder, text="Burst cycles", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        self.tx_cycles_combo = ttk.Combobox(
            cycles_holder,
            textvariable=self.tx_cycles_var,
            values=[str(value) for value in TX_CYCLE_OPTIONS],
            state="readonly",
            width=10,
        )
        self.tx_cycles_combo.pack(fill="x")
        self._labeled_entry(tx_row, "外部實測 ±HV_A（外層）(V)", self.tx_hv_a_var, width=12)
        self._labeled_entry(tx_row, "外部實測 ±HV_B（內層）(V)", self.tx_hv_b_var, width=12)

        tk.Label(
            tx_controls,
            textvariable=self.tx_plan_detail_var,
            bg=COLORS["warning_soft"],
            fg=COLORS["warning"],
            justify="left",
            anchor="w",
            padx=10,
            pady=6,
            font=("Segoe UI", 8),
        ).pack(fill="x", pady=(8, 0))

        preview_holder = tk.Frame(tx_body, bg=COLORS["surface"])
        preview_holder.pack(side="left", fill="x", padx=(16, 0))
        tk.Label(preview_holder, text="電平序列預覽（每個 base pattern）", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w")
        self.tx_waveform_canvas = tk.Canvas(
            preview_holder,
            width=440,
            height=96,
            bg="#F8FAFD",
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        self.tx_waveform_canvas.pack(pady=(5, 7))
        self.tx_confirm_button = ttk.Button(
            preview_holder,
            text="確認並寫入 TX（BF 保持 OFF）",
            style="Primary.TButton",
            command=self._confirm_tx_plan,
        )
        self.tx_confirm_button.pack(anchor="e")
        self.tx_waveform_combo.bind("<<ComboboxSelected>>", lambda _event: self._tx_plan_changed())
        self.tx_cycles_combo.bind("<<ComboboxSelected>>", lambda _event: self._tx_plan_changed())

        summary_card = self._card(body)
        summary_card._shadow_wrapper.pack(fill="x", pady=(0, 12))  # type: ignore[attr-defined]
        summary_line = tk.Frame(summary_card, bg=COLORS["surface"])
        summary_line.pack(fill="x", padx=18, pady=13)
        ttk.Label(summary_line, text="Array check", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(summary_line, textvariable=self.array_summary_var, style="Metric.TLabel").pack(side="left", padx=(18, 0))
        self.array_warning_label = tk.Label(summary_line, textvariable=self.array_warning_var, bg=COLORS["surface"], fg=COLORS["warning"], font=("Segoe UI Semibold", 9))
        self.array_warning_label.pack(side="right")

        table_card = self._card(body)
        table_card._shadow_wrapper.pack(fill="both", expand=True)  # type: ignore[attr-defined]
        table_header = tk.Frame(table_card, bg=COLORS["surface"])
        table_header.pack(fill="x", padx=18, pady=(14, 8))
        ttk.Label(table_header, text="Delay profiles", style="CardTitle.TLabel").pack(side="left")
        tk.Label(table_header, text="count = 5 ns（預設）", bg=COLORS["surface"], fg=COLORS["muted"], font=("Cascadia Mono", 9)).pack(side="right")

        columns = ["profile", "angle", "realized"] + [f"A{i}" for i in range(1, 9)] + ["phase", "grating"]
        self.delay_tree = ttk.Treeview(table_card, columns=columns, show="headings", height=10)
        headings = ["序號→HW", "設定角", "實現角"] + [f"A{i}" for i in range(1, 9)] + ["相鄰相位", "最近柵瓣"]
        widths = [68, 70, 72] + [48] * 8 + [90, 90]
        for column, heading, width in zip(columns, headings, widths):
            self.delay_tree.heading(column, text=heading)
            self.delay_tree.column(column, width=width, minwidth=40, anchor="center", stretch=column in {"phase", "grating"})
        scrollbar = ttk.Scrollbar(table_card, orient="vertical", command=self.delay_tree.yview)
        self.delay_tree.configure(yscrollcommand=scrollbar.set)
        self.delay_tree.pack(side="left", fill="both", expand=True, padx=(18, 0), pady=(0, 16))
        scrollbar.pack(side="right", fill="y", padx=(0, 18), pady=(0, 16))

    def _build_capture_page(self) -> None:
        page = self._new_page("capture")
        self._page_heading(page, "自動化採集", "點擊後會彈出獨立命令列窗口，逐角度控制 TX7316 並調用 HSDC Capture/Save。")

        scroll_host = tk.Frame(page, bg=COLORS["background"])
        scroll_host.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, bg=COLORS["background"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body = tk.Frame(canvas, bg=COLORS["background"])
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(1, weight=1)

        settings_card = self._card(body)
        settings_card._shadow_wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))  # type: ignore[attr-defined]
        ttk.Label(settings_card, text="Capture settings", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(16, 12))
        row1 = tk.Frame(settings_card, bg=COLORS["surface"])
        row1.pack(fill="x", padx=18)
        self._labeled_entry(row1, "Samples / channel", self.samples_var)
        self._labeled_entry(row1, "Repeats", self.repeats_var)
        self._labeled_entry(row1, "Settle (s)", self.settle_var)
        trigger_holder = tk.Frame(row1, bg=COLORS["surface"])
        trigger_holder.pack(side="left", fill="x", expand=True)
        tk.Label(trigger_holder, text="Trigger", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        ttk.Combobox(trigger_holder, textvariable=self.trigger_var, values=["normal", "software", "hardware"], state="readonly", width=12).pack(fill="x")

        output_row = tk.Frame(settings_card, bg=COLORS["surface"])
        output_row.pack(fill="x", padx=18, pady=(13, 16))
        tk.Label(output_row, text="輸出根目錄", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        path_line = tk.Frame(output_row, bg=COLORS["surface"])
        path_line.pack(fill="x")
        ttk.Entry(path_line, textvariable=self.output_root_var).pack(side="left", fill="x", expand=True)
        ttk.Button(path_line, text="選擇目錄", style="Secondary.TButton", command=self._browse_output_root).pack(side="left", padx=(8, 0))

        prereq_card = self._card(body)
        prereq_card._shadow_wrapper.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 12))  # type: ignore[attr-defined]
        ttk.Label(prereq_card, text="Pre-flight confirmation", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(16, 8))
        prereq_text = [
            "TX7316 GUI 已用管理員啟動並顯示 CONNECTED",
            "HSDC Pro 已用管理員啟動並顯示 CONNECTED",
            "AFE GUI 已完成 LMK 與 AFE 初始化",
            "探頭／凝膠／接線／電源已確認，CW 已關閉",
            "本次僅測凝膠或仿體，不接觸人體",
        ]
        for variable, text in zip(self.prerequisite_vars, prereq_text):
            ttk.Checkbutton(prereq_card, text=text, variable=variable).pack(anchor="w", padx=18, pady=2)
        tk.Label(prereq_card, text="UI 會寫入並回讀 TX 波形／cycles／延時；不會改變外部高壓電源或 AFE 增益。", bg=COLORS["warning_soft"], fg=COLORS["warning"], padx=10, pady=7, font=("Segoe UI Semibold", 9)).pack(fill="x", padx=18, pady=(8, 16))

        command_card = self._card(body)
        command_card._shadow_wrapper.grid(row=1, column=0, columnspan=2, sticky="nsew")  # type: ignore[attr-defined]
        command_card.grid_rowconfigure(2, weight=1)
        command_card.grid_columnconfigure(0, weight=1)
        command_top = tk.Frame(command_card, bg=COLORS["surface"])
        command_top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        ttk.Label(command_top, text="Launch & monitor", style="CardTitle.TLabel").pack(side="left")
        self.capture_progress = ttk.Progressbar(command_top, mode="indeterminate", length=180)
        self.capture_progress.pack(side="right")
        tk.Label(command_card, textvariable=self.capture_status_var, bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI Semibold", 10)).grid(row=1, column=0, sticky="ew", padx=18)
        command_box = tk.Label(command_card, textvariable=self.command_preview_var, bg="#F3F7FC", fg="#38516C", justify="left", anchor="nw", padx=14, pady=12, wraplength=980, font=("Cascadia Mono", 9), highlightbackground=COLORS["border"], highlightthickness=1)
        command_box.grid(row=2, column=0, sticky="nsew", padx=18, pady=10)
        button_row = tk.Frame(command_card, bg=COLORS["surface"])
        button_row.grid(row=3, column=0, sticky="e", padx=18, pady=(0, 16))
        ttk.Button(button_row, text="Dry run（不接觸硬件）", style="Secondary.TButton", command=lambda: self.launch_capture(True)).pack(side="left", padx=(0, 8))
        self.capture_button = ttk.Button(button_row, text="開始自動採集", style="Danger.TButton", command=lambda: self.launch_capture(False))
        self.capture_button.pack(side="left")

    def _build_auto_scan_page(self) -> None:
        page = self._new_page("auto_scan")
        self._page_heading(
            page,
            "逐PRF自動掃描",
            "每個PRF/SYNC週期切換一個beam；先生成可審核的角度—Profile—sample時序，再由已驗證的快速掃描固件執行。",
        )

        scroll_host = tk.Frame(page, bg=COLORS["background"])
        scroll_host.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, bg=COLORS["background"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body = tk.Frame(canvas, bg=COLORS["background"])
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)

        settings_card = self._card(body)
        settings_card._shadow_wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))  # type: ignore[attr-defined]
        ttk.Label(settings_card, text="Scan timing", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(16, 12))
        mode_holder = tk.Frame(settings_card, bg=COLORS["surface"])
        mode_holder.pack(fill="x", padx=18, pady=(0, 12))
        tk.Label(mode_holder, text="Execution mode", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        mode_combo = ttk.Combobox(
            mode_holder,
            textvariable=self.auto_scan_mode_var,
            values=[AUTO_SCAN_CPLD_BLOCK_MODE, AUTO_SCAN_VERIFIED_MODE, AUTO_SCAN_RAPID_MODE],
            state="readonly",
        )
        mode_combo.pack(fill="x")
        mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._auto_scan_mode_changed())

        timing_row = tk.Frame(settings_card, bg=COLORS["surface"])
        timing_row.pack(fill="x", padx=18, pady=(0, 12))
        prf_entry = self._labeled_entry(timing_row, "PRF / SYNC (Hz)", self.auto_scan_prf_var)
        frames_entry = self._labeled_entry(timing_row, "PRFs averaged / angle", self.auto_scan_frames_var)
        guard_entry = self._labeled_entry(timing_row, "Guard PRFs / BIN", self.auto_scan_guard_var)
        for entry in (prf_entry, frames_entry, guard_entry):
            entry.bind("<FocusOut>", lambda _event: self.recalculate_auto_scan(show_errors=False))
            entry.bind("<Return>", lambda _event: self.recalculate_auto_scan(show_errors=True))
        tk.Label(
            settings_card,
            textvariable=self.auto_scan_summary_var,
            bg=COLORS["primary_soft"],
            fg=COLORS["primary_hover"],
            justify="left",
            anchor="w",
            padx=12,
            pady=10,
            wraplength=780,
            font=("Cascadia Mono", 9),
        ).pack(fill="x", padx=18, pady=(0, 16))

        gate_card = self._card(body)
        gate_card._shadow_wrapper.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 12))  # type: ignore[attr-defined]
        gate_top = tk.Frame(gate_card, bg=COLORS["surface"])
        gate_top.pack(fill="x", padx=18, pady=(16, 8))
        ttk.Label(gate_top, text="Hardware gate", style="CardTitle.TLabel").pack(side="left")
        self.auto_scan_gate_label = tk.Label(
            gate_top,
            textvariable=self.auto_scan_gate_var,
            bg=COLORS["warning_soft"],
            fg=COLORS["warning"],
            padx=10,
            pady=5,
            font=("Segoe UI Semibold", 8),
        )
        self.auto_scan_gate_label.pack(side="right")
        requirements = [
            "SYNCP經有源緩衝後接TSW J13；AFE J25只作可選事件參考",
            "TSW使用外部上升沿；AFE固定增益；1 kHz不得接LMK時鐘輸入",
            "每角一個BIN；32個同角PRF完整保存後才由軟件換下一角",
        ]
        for variable, text in zip(self.auto_scan_confirm_vars, requirements):
            ttk.Checkbutton(
                gate_card,
                text=text,
                variable=variable,
                command=lambda: self.recalculate_auto_scan(show_errors=False),
            ).pack(anchor="w", padx=18, pady=2)
        tk.Label(
            gate_card,
            text="原廠TX7316EVM CPLD會持續輸出1 kHz SYNCP，但不會逐SYNC輪換Profile。推薦模式在BIN之間切角，BIN內保存32個同角PRF。",
            bg=COLORS["warning_soft"],
            fg=COLORS["warning"],
            justify="left",
            wraplength=430,
            padx=10,
            pady=8,
            font=("Segoe UI Semibold", 9),
        ).pack(fill="x", padx=18, pady=(10, 16))

        timeline_card = self._card(body)
        timeline_card._shadow_wrapper.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 12))  # type: ignore[attr-defined]
        timeline_top = tk.Frame(timeline_card, bg=COLORS["surface"])
        timeline_top.pack(fill="x", padx=18, pady=(15, 9))
        ttk.Label(timeline_top, text="Deterministic event map", style="CardTitle.TLabel").pack(side="left")
        tk.Label(
            timeline_top,
            text="SYNC n → bank / frame / TX profile / angle / HSDC sample",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Cascadia Mono", 9),
        ).pack(side="right")
        columns = ("bank", "frame", "event", "profile", "angle", "time", "sample")
        self.auto_scan_tree = ttk.Treeview(timeline_card, columns=columns, show="headings", height=9)
        headings = ("Bank", "Sweep", "SYNC event", "TX profile", "Beam angle", "Time", "Sample offset")
        widths = (65, 70, 90, 90, 95, 100, 130)
        for column, heading, width in zip(columns, headings, widths):
            self.auto_scan_tree.heading(column, text=heading)
            self.auto_scan_tree.column(column, width=width, minwidth=55, anchor="center", stretch=column == "sample")
        timeline_scroll = ttk.Scrollbar(timeline_card, orient="vertical", command=self.auto_scan_tree.yview)
        self.auto_scan_tree.configure(yscrollcommand=timeline_scroll.set)
        self.auto_scan_tree.pack(side="left", fill="both", expand=True, padx=(18, 0), pady=(0, 16))
        timeline_scroll.pack(side="right", fill="y", padx=(0, 18), pady=(0, 16))

        action_card = self._card(body)
        action_card._shadow_wrapper.grid(row=2, column=0, columnspan=2, sticky="ew")  # type: ignore[attr-defined]
        action_top = tk.Frame(action_card, bg=COLORS["surface"])
        action_top.pack(fill="x", padx=18, pady=(15, 8))
        ttk.Label(action_top, text="Plan & execute", style="CardTitle.TLabel").pack(side="left")
        self.auto_scan_progress = ttk.Progressbar(action_top, mode="indeterminate", length=180)
        self.auto_scan_progress.pack(side="right")
        tk.Label(
            action_card,
            textvariable=self.auto_scan_status_var,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            anchor="w",
            font=("Segoe UI Semibold", 10),
        ).pack(fill="x", padx=18, pady=(0, 10))
        buttons = tk.Frame(action_card, bg=COLORS["surface"])
        buttons.pack(fill="x", padx=18, pady=(0, 16))
        ttk.Button(
            buttons,
            text="保存逐PRF掃描方案 JSON",
            style="Secondary.TButton",
            command=self.export_auto_scan_plan,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Dry run / 時序檢查",
            style="Secondary.TButton",
            command=lambda: self.launch_auto_scan(True),
        ).pack(side="right", padx=(8, 0))
        self.auto_scan_start_button = ttk.Button(
            buttons,
            text="開始已驗證掃描",
            style="Danger.TButton",
            command=lambda: self.launch_auto_scan(False),
        )
        self.auto_scan_start_button.pack(side="right")

    def _build_doppler_page(self) -> None:
        page = self._new_page("doppler")
        self._page_heading(
            page,
            "PW Doppler長時量測",
            "固定波束角度後錄製一段連續慢時間資料；界面會區分可執行短塊與真正能辨識心動周期的I/Q路徑。",
        )

        scroll_host = tk.Frame(page, bg=COLORS["background"])
        scroll_host.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, bg=COLORS["background"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body = tk.Frame(canvas, bg=COLORS["background"])
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(2, weight=1)

        settings_card = self._card(body)
        settings_card._shadow_wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))  # type: ignore[attr-defined]
        header = tk.Frame(settings_card, bg=COLORS["surface"])
        header.pack(fill="x", padx=18, pady=(15, 10))
        ttk.Label(header, text="Acquisition & flow model", style="CardTitle.TLabel").pack(side="left")

        preset_row = tk.Frame(settings_card, bg=COLORS["surface"])
        preset_row.pack(fill="x", padx=18, pady=(0, 6))
        preset_text = tk.Frame(preset_row, bg=COLORS["surface"])
        preset_text.pack(side="left", fill="x", expand=True)
        tk.Label(
            preset_text,
            text="Carotid flow-phantom preset",
            bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(0, 5))
        preset_combo = ttk.Combobox(
            preset_text,
            textvariable=self.doppler_preset_var,
            values=[preset.label for preset in CAROTID_PHANTOM_PRESETS],
            state="readonly",
        )
        preset_combo.pack(fill="x")
        preset_combo.bind("<<ComboboxSelected>>", lambda _event: self._doppler_preset_changed())
        preset_actions = tk.Frame(preset_row, bg=COLORS["surface"])
        preset_actions.pack(side="right", padx=(12, 0), pady=(20, 0))
        ttk.Button(
            preset_actions,
            text="套用方案",
            style="Secondary.TButton",
            command=lambda: self._apply_selected_doppler_preset(False),
        ).pack(side="left", padx=(0, 8))
        self.doppler_preset_execute_button = ttk.Button(
            preset_actions,
            text="一鍵採集並分析",
            style="Primary.TButton",
            command=lambda: self._apply_selected_doppler_preset(True),
        )
        self.doppler_preset_execute_button.pack(side="left")
        tk.Label(
            settings_card,
            textvariable=self.doppler_preset_note_var,
            bg=COLORS["surface"], fg=COLORS["muted"], justify="left", anchor="w",
            wraplength=1050, font=("Segoe UI", 9),
        ).pack(fill="x", padx=18, pady=(0, 10))

        mode_row = tk.Frame(settings_card, bg=COLORS["surface"])
        mode_row.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(mode_row, text="Acquisition path", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.doppler_capture_mode_var,
            values=list(DOPPLER_CAPTURE_MODE_OPTIONS),
            state="readonly",
        )
        mode_combo.pack(fill="x")
        mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._doppler_mode_changed())

        source_row = tk.Frame(settings_card, bg=COLORS["surface"])
        source_row.pack(fill="x", padx=18, pady=(0, 10))
        source_holder = tk.Frame(source_row, bg=COLORS["surface"])
        source_holder.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(source_holder, text="PRF source", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        source_combo = ttk.Combobox(
            source_holder,
            textvariable=self.doppler_prf_source_var,
            values=["Onboard CPLD - fixed 1 kHz", "External synchronized source - manual wiring"],
            state="readonly",
        )
        source_combo.pack(fill="x")
        source_combo.bind("<<ComboboxSelected>>", lambda _event: self._doppler_source_changed())
        trigger_holder = tk.Frame(source_row, bg=COLORS["surface"])
        trigger_holder.pack(side="left", fill="x", expand=True)
        tk.Label(trigger_holder, text="HSDC trigger", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        trigger_combo = ttk.Combobox(
            trigger_holder,
            textvariable=self.doppler_trigger_var,
            values=["normal", "software", "hardware"],
            state="readonly",
        )
        trigger_combo.pack(fill="x")
        trigger_combo.bind("<<ComboboxSelected>>", lambda _event: self.recalculate_doppler(show_errors=False))

        doppler_entries: list[ttk.Entry] = []
        row1 = tk.Frame(settings_card, bg=COLORS["surface"])
        row1.pack(fill="x", padx=18, pady=(0, 9))
        doppler_entries.append(self._labeled_entry(row1, "PRF (Hz)", self.doppler_prf_var))
        doppler_entries.append(self._labeled_entry(row1, "TX steer (deg)", self.doppler_steering_var))
        doppler_entries.append(self._labeled_entry(row1, "Flow angle (deg)", self.doppler_flow_angle_var))
        doppler_entries.append(self._labeled_entry(row1, "Gate depth (mm)", self.doppler_depth_var))

        row2 = tk.Frame(settings_card, bg=COLORS["surface"])
        row2.pack(fill="x", padx=18, pady=(0, 9))
        doppler_entries.append(self._labeled_entry(row2, "Expected v (m/s)", self.doppler_velocity_var))
        doppler_entries.append(self._labeled_entry(row2, "Desired time (s)", self.doppler_duration_var))
        doppler_entries.append(self._labeled_entry(row2, "FFT ensemble", self.doppler_ensemble_var))
        doppler_entries.append(self._labeled_entry(row2, "Expected HR (BPM)", self.doppler_heart_rate_var))

        row3 = tk.Frame(settings_card, bg=COLORS["surface"])
        row3.pack(fill="x", padx=18, pady=(0, 9))
        doppler_entries.append(self._labeled_entry(row3, "Gate length (mm)", self.doppler_gate_length_var))
        doppler_entries.append(self._labeled_entry(row3, "Wall filter (Hz)", self.doppler_wall_filter_var))
        doppler_entries.append(self._labeled_entry(row3, "Block samples/ch", self.doppler_samples_var))
        doppler_entries.append(self._labeled_entry(row3, "Block repeats", self.doppler_repeats_var))

        row4 = tk.Frame(settings_card, bg=COLORS["surface"])
        row4.pack(fill="x", padx=18, pady=(0, 15))
        tk.Label(
            row4,
            text="原始RF模式保持120 MSPS；PRF是物理同步率。心動周期模式只會在經驗證的I/Q固件與解包後解鎖。",
            bg=COLORS["primary_soft"],
            fg=COLORS["primary_hover"],
            justify="left",
            anchor="w",
            wraplength=560,
            padx=12,
            pady=9,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left", fill="x", expand=True)
        for entry in doppler_entries:
            entry.bind("<FocusOut>", lambda _event: self.recalculate_doppler(show_errors=False), add="+")

        metrics_card = self._card(body)
        metrics_card._shadow_wrapper.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 12))  # type: ignore[attr-defined]
        ttk.Label(metrics_card, text="Feasibility", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(16, 10))
        tk.Label(
            metrics_card,
            textvariable=self.doppler_summary_var,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            justify="left",
            anchor="nw",
            wraplength=420,
            font=("Cascadia Mono", 10),
        ).pack(fill="x", padx=18)
        tk.Label(
            metrics_card,
            textvariable=self.doppler_storage_var,
            bg=COLORS["surface_soft"],
            fg="#38516C",
            justify="left",
            anchor="nw",
            wraplength=420,
            padx=12,
            pady=10,
            font=("Cascadia Mono", 9),
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        ).pack(fill="x", padx=18, pady=(10, 8))
        tk.Label(
            metrics_card,
            textvariable=self.doppler_warning_var,
            bg=COLORS["warning_soft"],
            fg=COLORS["warning"],
            justify="left",
            anchor="nw",
            wraplength=420,
            padx=12,
            pady=9,
            font=("Segoe UI Semibold", 9),
        ).pack(fill="both", expand=True, padx=18, pady=(0, 16))

        architecture_card = self._card(body)
        architecture_card._shadow_wrapper.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 12))  # type: ignore[attr-defined]
        architecture_card.grid_columnconfigure(0, weight=1)
        architecture_card.grid_columnconfigure(1, weight=1)
        current = tk.Frame(architecture_card, bg=COLORS["surface"])
        current.grid(row=0, column=0, sticky="nsew", padx=(18, 12), pady=14)
        future = tk.Frame(architecture_card, bg=COLORS["surface"])
        future.grid(row=0, column=1, sticky="nsew", padx=(12, 18), pady=14)
        ttk.Label(current, text="NOW · 可執行短塊", style="CardTitle.TLabel").pack(anchor="w")
        tk.Label(
            current,
            text="TX固定角度 → AFE 120 MSPS原始RF → TSW DDR → 單個BIN。每個BIN內連續；BIN之間因保存與重新Capture存在長缺口。",
            bg=COLORS["surface"], fg=COLORS["muted"], justify="left", anchor="w", wraplength=530, font=("Segoe UI", 9),
        ).pack(fill="x", pady=(5, 0))
        ttk.Label(future, text="BEST · 連續心動周期", style="CardTitle.TLabel").pack(anchor="w")
        tk.Label(
            future,
            text="5 kHz共同PRF → 固定角度 → FPGA在選定深度做距離門/IQ → 每個脈衝保留一個複數樣點 → 單次連續10秒。這是最多心動周期且資料量最小的推薦路徑。",
            bg=COLORS["surface"], fg=COLORS["muted"], justify="left", anchor="w", wraplength=530, font=("Segoe UI", 9),
        ).pack(fill="x", pady=(5, 0))

        launch_card = self._card(body)
        launch_card._shadow_wrapper.grid(row=2, column=0, columnspan=2, sticky="nsew")  # type: ignore[attr-defined]
        launch_card.grid_columnconfigure(0, weight=1)
        top = tk.Frame(launch_card, bg=COLORS["surface"])
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        ttk.Label(top, text="Plan, launch & monitor", style="CardTitle.TLabel").pack(side="left")
        self.doppler_progress = ttk.Progressbar(top, mode="indeterminate", length=180)
        self.doppler_progress.pack(side="right")
        checks = tk.Frame(launch_card, bg=COLORS["surface"])
        checks.grid(row=1, column=0, sticky="ew", padx=18)
        ttk.Checkbutton(checks, text="TX/AFE/HSDC已初始化，CW關閉，只測仿體", variable=self.doppler_phantom_confirmed_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="PRF同步路徑已實測，沒有把J7 pin 2當輸入", variable=self.doppler_sync_confirmed_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="理解多個BIN不構成連續心動資料，只有單一連續記錄可判定周期", variable=self.doppler_gap_ack_var).pack(anchor="w")
        tk.Label(launch_card, textvariable=self.doppler_status_var, bg=COLORS["surface"], fg=COLORS["text"], anchor="w", font=("Segoe UI Semibold", 10)).grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 0))
        tk.Label(
            launch_card,
            textvariable=self.doppler_command_var,
            bg="#F3F7FC", fg="#38516C", justify="left", anchor="nw", padx=12, pady=9,
            wraplength=1000, font=("Cascadia Mono", 9), highlightbackground=COLORS["border"], highlightthickness=1,
        ).grid(row=3, column=0, sticky="nsew", padx=18, pady=8)
        actions = tk.Frame(launch_card, bg=COLORS["surface"])
        actions.grid(row=4, column=0, sticky="e", padx=18, pady=(0, 8))
        ttk.Button(actions, text="打開完整操作文檔", style="Secondary.TButton", command=self._open_doppler_guide).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="導出Session Plan", style="Secondary.TButton", command=self.export_doppler_plan).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Doppler dry run", style="Secondary.TButton", command=lambda: self.launch_doppler_capture(True)).pack(side="left", padx=(0, 8))
        self.doppler_capture_button = ttk.Button(actions, text="開始固定角度採集並分析", style="Danger.TButton", command=lambda: self.launch_doppler_capture(False))
        self.doppler_capture_button.pack(side="left")

        analysis_row = tk.Frame(launch_card, bg=COLORS["surface_soft"], highlightbackground=COLORS["border"], highlightthickness=1)
        analysis_row.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 14))
        analysis_text = tk.Frame(analysis_row, bg=COLORS["surface_soft"])
        analysis_text.pack(side="left", fill="x", expand=True, padx=12, pady=9)
        tk.Label(analysis_text, textvariable=self.doppler_analysis_status_var, bg=COLORS["surface_soft"], fg=COLORS["text"], anchor="w", font=("Segoe UI Semibold", 9)).pack(fill="x")
        tk.Label(analysis_text, textvariable=self.doppler_result_var, bg=COLORS["surface_soft"], fg=COLORS["muted"], anchor="w", justify="left", wraplength=720, font=("Segoe UI", 9)).pack(fill="x", pady=(2, 0))
        ttk.Button(analysis_row, text="分析最新PW記錄", style="Secondary.TButton", command=self.launch_doppler_analysis).pack(side="left", padx=(8, 4), pady=9)
        ttk.Button(analysis_row, text="打開速度譜", style="Secondary.TButton", command=self._open_doppler_result).pack(side="left", padx=(4, 12), pady=9)
        self._doppler_preset_changed()

    def _cw_frequency_changed(self) -> None:
        self.recalculate_cw_doppler(show_errors=False)
        self._refresh_cw_tx_controls()

    def _refresh_cw_tx_controls(self) -> None:
        if not hasattr(self, "cw_tx_start_button"):
            return
        try:
            stock_clock_frequency = abs(float(self.cw_frequency_var.get()) - 3.125) < 1e-9
        except ValueError:
            stock_clock_frequency = False
        self.cw_tx_start_button.configure(state="normal" if stock_clock_frequency else "disabled")
        if not stock_clock_frequency:
            self.cw_status_var.set("精確1/2/4 MHz CW需要先把TX7316 BF_CLK硬件改為並驗證128 MHz；目前不會啟動CW。")

    def _cw_iq_rate_changed(self) -> None:
        try:
            requested_hz = float(self.cw_iq_rate_var.get()) * 1e6
            decimation = IQ_RATE_DECIMATION[requested_hz]
        except (KeyError, ValueError):
            return
        self.cw_decimation_var.set(str(decimation))
        self.recalculate_cw_doppler(show_errors=False)

    def _scroll_cw_page(self, event: tk.Event) -> str | None:
        if self.active_page != "cw_doppler" or not hasattr(self, "cw_scroll_canvas"):
            return None
        delta = int(getattr(event, "delta", 0))
        if delta:
            self.cw_scroll_canvas.yview_scroll(-1 if delta > 0 else 1, "units")
            return "break"
        return None

    def _build_cw_doppler_page(self) -> None:
        page = self._new_page("cw_doppler")
        self._page_heading(
            page,
            "CW Doppler · 三傾角DBUD",
            "依 Science Advances 2021 的三行傾角幾何估計流速與流向；本頁適配8個有效硬體通道。",
        )
        scroll_host = tk.Frame(page, bg=COLORS["background"])
        scroll_host.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, bg=COLORS["background"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body = tk.Frame(canvas, bg=COLORS["background"])
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
        self.cw_scroll_canvas = canvas
        self.bind("<MouseWheel>", self._scroll_cw_page, add="+")
        canvas.bind("<Enter>", lambda _event: canvas.focus_set())
        canvas.bind("<Prior>", lambda _event: canvas.yview_scroll(-1, "pages"))
        canvas.bind("<Next>", lambda _event: canvas.yview_scroll(1, "pages"))
        canvas.bind("<Home>", lambda _event: canvas.yview_moveto(0.0))
        canvas.bind("<End>", lambda _event: canvas.yview_moveto(1.0))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)

        settings_card = self._card(body)
        settings_card._shadow_wrapper.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 12))  # type: ignore[attr-defined]
        cw_settings_title = tk.Frame(settings_card, bg=COLORS["surface"])
        cw_settings_title.pack(fill="x", padx=18, pady=(15, 10))
        ttk.Label(cw_settings_title, text="Acquisition & processing", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(cw_settings_title, text="前往 DDR I/Q 採集", style="Primary.TButton", command=lambda: canvas.yview_moveto(0.28)).pack(side="right")
        backend_holder = tk.Frame(settings_card, bg=COLORS["surface"])
        backend_holder.pack(fill="x", padx=18, pady=(0, 10))
        tk.Label(backend_holder, text="資料路徑", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        backend = ttk.Combobox(backend_holder, textvariable=self.cw_backend_var, values=list(CW_DOPPLER_BACKEND_OPTIONS), state="readonly")
        backend.pack(fill="x")
        backend.bind("<<ComboboxSelected>>", lambda _event: self.recalculate_cw_doppler(show_errors=False))

        primary = tk.Frame(settings_card, bg=COLORS["surface"])
        primary.pack(fill="x", padx=18, pady=(0, 10))
        self._cw_labeled_combo(primary, "TX／NCO中心頻率 (MHz)", self.cw_frequency_var, ("3.125", "1", "2", "4"), self._cw_frequency_changed)
        self._cw_labeled_entry(primary, "AFE實體 ADC (MSPS)", self.cw_adc_rate_var, readonly=True)
        tx_safety = tk.Frame(settings_card, bg=COLORS["surface"])
        tx_safety.pack(fill="x", padx=18, pady=(0, 10))
        self._cw_labeled_entry(tx_safety, "J1 正／負高壓軌實測絕對值 (V)", self.cw_tx_supply_var)
        self._cw_labeled_entry(tx_safety, "限時 CW 測試 (s，最多 5)", self.cw_tx_test_seconds_var)
        transport = tk.Frame(settings_card, bg=COLORS["surface"])
        transport.pack(fill="x", padx=18, pady=(0, 10))
        self._cw_labeled_combo(transport, "目標數位 I/Q 輸出率 (MSPS)", self.cw_iq_rate_var, ("15", "10", "7.5", "6", "5"), self._cw_iq_rate_changed)
        self._cw_labeled_entry(transport, "AFE硬體抽取 D（I/Q率 = 120／2D）", self.cw_decimation_var, readonly=True)
        channel_row = tk.Frame(settings_card, bg=COLORS["surface"])
        channel_row.pack(fill="x", padx=18, pady=(0, 10))
        self._cw_labeled_entry(channel_row, "有效硬體通道", self.cw_logical_channels_var, readonly=True)
        timing = tk.Frame(settings_card, bg=COLORS["surface"])
        timing.pack(fill="x", padx=18, pady=(0, 10))
        self._cw_labeled_entry(timing, "目標時長 (s)", self.cw_duration_var)
        self._cw_labeled_entry(timing, "分析率 (kSPS)", self.cw_analysis_rate_var)
        filters = tk.Frame(settings_card, bg=COLORS["surface"])
        filters.pack(fill="x", padx=18, pady=(0, 10))
        self._cw_labeled_entry(filters, "低通 (kHz)", self.cw_lowpass_var)
        self._cw_labeled_entry(filters, "Wall filter (Hz)", self.cw_wall_filter_var)
        stft = tk.Frame(settings_card, bg=COLORS["surface"])
        stft.pack(fill="x", padx=18, pady=(0, 10))
        self._cw_labeled_entry(stft, "STFT window", self.cw_stft_samples_var)
        self._cw_labeled_entry(stft, "STFT overlap", self.cw_stft_overlap_var)
        tk.Label(
            settings_card,
            text="TX板載 BF_CLK=200 MHz；現有EVM可直接啟動的CW為3.125 MHz。精確1/2/4 MHz需要先把BF_CLK硬件改為並驗證128 MHz。實體ADC/JESD仍保持120 MSPS；I/Q抽取未完成匹配驗證前不寫AFE/HSDC。",
            bg=COLORS["primary_soft"], fg=COLORS["primary_hover"], justify="left", anchor="w",
            wraplength=430, padx=10, pady=8, font=("Segoe UI Semibold", 9),
        ).pack(fill="x", padx=18, pady=(0, 14))

        metrics_card = self._card(body)
        metrics_card._shadow_wrapper.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 12))  # type: ignore[attr-defined]
        ttk.Label(metrics_card, text="Feasibility", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(15, 10))
        tk.Label(metrics_card, textvariable=self.cw_summary_var, bg=COLORS["surface"], fg=COLORS["text"], justify="left", anchor="nw", wraplength=420, font=("Cascadia Mono", 10)).pack(fill="x", padx=18)
        tk.Label(metrics_card, textvariable=self.cw_storage_var, bg=COLORS["surface_soft"], fg="#38516C", justify="left", anchor="nw", wraplength=420, padx=12, pady=10, font=("Cascadia Mono", 9), highlightbackground=COLORS["border"], highlightthickness=1).pack(fill="x", padx=18, pady=(10, 8))
        tk.Label(metrics_card, textvariable=self.cw_warning_var, bg=COLORS["warning_soft"], fg=COLORS["warning"], justify="left", anchor="nw", wraplength=420, padx=12, pady=9, font=("Segoe UI Semibold", 9)).pack(fill="both", expand=True, padx=18, pady=(0, 16))

        geometry_card = self._card(body)
        geometry_card._shadow_wrapper.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 12))  # type: ignore[attr-defined]
        top = tk.Frame(geometry_card, bg=COLORS["surface"])
        top.pack(fill="x", padx=18, pady=(14, 8))
        ttk.Label(top, text="3-row / 8-channel tilted patch geometry", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(top, text="套用論文 17° / 20° / 23°", style="Secondary.TButton", command=self._reset_cw_paper_geometry).pack(side="right")
        ttk.Button(top, text="計算DBUD速度", style="Primary.TButton", command=lambda: self.recalculate_cw_doppler(show_errors=True)).pack(side="right", padx=(0, 8))
        headings = ("行", "實體貼片角 θ", "TX邏輯貼片", "RX邏輯貼片", "AFE RX slot", "實測 fD (Hz)", "組織內折射角 β")
        grid = tk.Frame(geometry_card, bg=COLORS["surface"])
        grid.pack(fill="x", padx=18, pady=(0, 14))
        for column, heading in enumerate(headings):
            tk.Label(grid, text=heading, bg=COLORS["surface_soft"], fg=COLORS["muted"], padx=8, pady=7, font=("Segoe UI Semibold", 9), highlightbackground=COLORS["border"], highlightthickness=1).grid(row=0, column=column, sticky="ew")
            grid.grid_columnconfigure(column, weight=1 if column else 0)
        tx_labels = ("1,3", "4,6", "7")
        rx_labels = ("2", "5", "8")
        self.cw_beta_labels = []
        for index in range(3):
            tk.Label(grid, text=f"Row {index + 1}", bg=COLORS["surface"], fg=COLORS["text"], padx=8, pady=8).grid(row=index + 1, column=0, sticky="ew")
            angle_entry = ttk.Entry(grid, textvariable=self.cw_row_angle_vars[index], width=12)
            angle_entry.grid(row=index + 1, column=1, sticky="ew", padx=6, pady=4)
            angle_entry.bind("<FocusOut>", lambda _event: self.recalculate_cw_doppler(show_errors=False))
            tk.Label(grid, text=tx_labels[index], bg=COLORS["surface"], fg=COLORS["text"], font=("Cascadia Mono", 9)).grid(row=index + 1, column=2, sticky="ew")
            tk.Label(grid, text=rx_labels[index], bg=COLORS["surface"], fg=COLORS["text"], font=("Cascadia Mono", 9)).grid(row=index + 1, column=3, sticky="ew")
            slot_entry = ttk.Entry(grid, textvariable=self.cw_row_rx_slot_vars[index], width=12)
            slot_entry.grid(row=index + 1, column=4, sticky="ew", padx=6, pady=4)
            slot_entry.bind("<FocusOut>", lambda _event: self.recalculate_cw_doppler(show_errors=False))
            doppler_entry = ttk.Entry(grid, textvariable=self.cw_row_doppler_vars[index], width=12)
            doppler_entry.grid(row=index + 1, column=5, sticky="ew", padx=6, pady=4)
            doppler_entry.bind("<FocusOut>", lambda _event: self.recalculate_cw_doppler(show_errors=False))
            beta = tk.Label(grid, text="—", bg=COLORS["surface"], fg=COLORS["primary"], font=("Cascadia Mono", 9, "bold"))
            beta.grid(row=index + 1, column=6, sticky="ew")
            self.cw_beta_labels.append(beta)
        tk.Label(
            geometry_card,
            textvariable=self.cw_velocity_result_var,
            bg=COLORS["primary_soft"],
            fg=COLORS["primary_hover"],
            anchor="w",
            justify="left",
            padx=12,
            pady=9,
            font=("Cascadia Mono", 9),
        ).pack(fill="x", padx=18, pady=(0, 14))

        workflow_card = self._card(body)
        workflow_card._shadow_wrapper.grid(row=4, column=0, columnspan=2, sticky="nsew")  # type: ignore[attr-defined]
        ttk.Label(workflow_card, text="Plan & hardware gates", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(14, 8))
        checks = tk.Frame(workflow_card, bg=COLORS["surface"])
        checks.pack(fill="x", padx=18)
        ttk.Checkbutton(checks, text="僅測凝膠／流體仿體，不接觸人體", variable=self.cw_phantom_confirmed_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="高壓電源限流、探頭溫升與占空風險已評估", variable=self.cw_thermal_confirmed_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="理解8個有效通道只有在匹配I/Q傳輸profile後才會減少DDR；類比CW_OUT需外部同步I/Q ADC", variable=self.cw_path_confirmed_var).pack(anchor="w")
        ttk.Checkbutton(checks, text="已用萬用表確認J1正／負高壓軌均為5 V，所有5 V電源限流依TI指南設為500 mA", variable=self.cw_tx_low_voltage_confirmed_var).pack(anchor="w")
        tk.Label(workflow_card, textvariable=self.cw_status_var, bg=COLORS["surface"], fg=COLORS["text"], anchor="w", font=("Segoe UI Semibold", 10)).pack(fill="x", padx=18, pady=(8, 8))
        actions = tk.Frame(workflow_card, bg=COLORS["surface"])
        actions.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Button(actions, text="查看論文", style="Secondary.TButton", command=lambda: webbrowser.open("https://www.science.org/doi/10.1126/sciadv.abi9283")).pack(side="left")
        ttk.Button(actions, text="打開操作文檔", style="Secondary.TButton", command=self._open_cw_doppler_guide).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="導出配置方案", style="Primary.TButton", command=self.export_cw_doppler_plan).pack(side="right")
        self.cw_stage_button = ttk.Button(actions, text="寫入寄存器／配置", style="Danger.TButton", command=self.stage_cw_doppler_tx)
        self.cw_stage_button.pack(side="right", padx=(0, 8))
        self.cw_tx_start_button = ttk.Button(actions, text="啟動限時3.125 MHz CW", style="Danger.TButton", command=self.start_tx7316_cw_test)
        self.cw_tx_start_button.pack(side="right", padx=(0, 8))
        self.cw_tx_stop_button = ttk.Button(actions, text="立即停止CW", style="Secondary.TButton", command=self.stop_tx7316_cw)
        self.cw_tx_stop_button.pack(side="right", padx=(0, 8))
        self._refresh_cw_tx_controls()
        build_cw_capture_panel(self, body, row=2)

    def _build_processing_page(self) -> None:
        page = self._new_page("processing")
        self._page_heading(page, "離線重建與事件驗證", "每次強制從所選 capture_* 原始BIN重建；同時輸出逐PRF影像、時域事件驗證與通道QA。")

        control_card = self._card(page)
        control_card._shadow_wrapper.pack(fill="x", pady=(0, 12))  # type: ignore[attr-defined]
        controls = tk.Frame(control_card, bg=COLORS["surface"])
        controls.pack(fill="x", padx=18, pady=16)
        left = tk.Frame(controls, bg=COLORS["surface"])
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="Capture directory", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
        self.capture_combo = ttk.Combobox(left, textvariable=self.capture_folder_var, state="normal")
        self.capture_combo.pack(fill="x")
        self.capture_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_existing_results())
        ttk.Button(controls, text="選擇文件夾", style="Secondary.TButton", command=self._browse_capture_folder).pack(side="left", padx=(10, 8), pady=(20, 0))
        ttk.Button(controls, text="刷新列表", style="Secondary.TButton", command=self.refresh_capture_runs).pack(side="left", padx=(0, 8), pady=(20, 0))
        ttk.Button(controls, text="清除分析緩存", style="Secondary.TButton", command=self._clear_analysis_cache).pack(side="left", padx=(0, 8), pady=(20, 0))
        self.process_button = ttk.Button(controls, text="套用選項並重新成像", style="Primary.TButton", command=self.start_processing)
        self.process_button.pack(side="left", pady=(20, 0))

        processing_options = tk.Frame(control_card, bg=COLORS["surface"])
        processing_options.pack(fill="x", padx=18, pady=(0, 10))

        duplicate_holder = tk.Frame(processing_options, bg=COLORS["surface"])
        duplicate_holder.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(
            duplicate_holder,
            text="重複數字槽處理",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(0, 5))
        self.duplicate_policy_combo = ttk.Combobox(
            duplicate_holder,
            textvariable=self.duplicate_policy_var,
            values=list(DUPLICATE_POLICY_OPTIONS),
            state="readonly",
            width=34,
        )
        self.duplicate_policy_combo.pack(fill="x")
        self.duplicate_policy_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._processing_options_changed()
        )

        manual_holder = tk.Frame(processing_options, bg=COLORS["surface"])
        manual_holder.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(
            manual_holder,
            text="手動DAS槽（逗號分隔）",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(0, 5))
        self.manual_das_rx_entry = ttk.Entry(
            manual_holder, textvariable=self.manual_das_rx_var, width=28
        )
        self.manual_das_rx_entry.pack(fill="x")

        angle_holder = tk.Frame(processing_options, bg=COLORS["surface"])
        angle_holder.pack(side="left", fill="x", expand=True)
        tk.Label(
            angle_holder,
            text="離線角度取樣",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(0, 5))
        self.reconstruction_angle_combo = ttk.Combobox(
            angle_holder,
            textvariable=self.reconstruction_angle_subset_var,
            values=list(ANGLE_SUBSET_OPTIONS),
            state="readonly",
            width=38,
        )
        self.reconstruction_angle_combo.pack(fill="x")
        self.reconstruction_angle_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._processing_options_changed()
        )

        artifact_options = tk.Frame(
            control_card,
            bg=COLORS["surface_soft"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        artifact_options.pack(fill="x", padx=18, pady=(2, 10))
        tk.Label(
            artifact_options,
            text="接收旁瓣／振鈴抑制（離線，可逆）",
            bg=COLORS["surface_soft"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 9),
        ).pack(side="left", padx=(10, 14), pady=9)

        apodization_combo = ttk.Combobox(
            artifact_options,
            textvariable=self.receive_apodization_var,
            values=list(RECEIVE_APODIZATION_OPTIONS),
            state="readonly",
            width=25,
        )
        apodization_combo.pack(side="left", padx=(0, 12), pady=7)
        apodization_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._processing_options_changed()
        )
        ttk.Checkbutton(
            artifact_options,
            text="Coherence factor（保守 √CF）",
            variable=self.coherence_factor_var,
            command=self._processing_options_changed,
        ).pack(side="left", padx=(0, 12), pady=5)
        ttk.Checkbutton(
            artifact_options,
            text="淺層共模振鈴抑制（0–12 mm）",
            variable=self.common_mode_suppression_var,
            command=self._processing_options_changed,
        ).pack(side="left", padx=(0, 12), pady=5)
        tk.Label(
            artifact_options,
            text="不修改原始 BIN",
            bg=COLORS["success_soft"],
            fg=COLORS["success"],
            padx=8,
            pady=4,
            font=("Segoe UI Semibold", 8),
        ).pack(side="right", padx=9, pady=6)

        tk.Label(
            control_card,
            textvariable=self.processing_option_help_var,
            bg=COLORS["surface_soft"],
            fg=COLORS["muted"],
            anchor="w",
            justify="left",
            padx=10,
            pady=7,
            font=("Segoe UI", 9),
        ).pack(fill="x", padx=18, pady=(0, 10))
        self._processing_options_changed()

        status_line = tk.Frame(control_card, bg=COLORS["surface"])
        status_line.pack(fill="x", padx=18, pady=(0, 14))
        tk.Label(status_line, textvariable=self.processing_status_var, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(side="left")
        self.processing_progress = ttk.Progressbar(status_line, mode="indeterminate", length=180)
        self.processing_progress.pack(side="right")

        result_body = tk.Frame(page, bg=COLORS["background"])
        result_body.pack(fill="both", expand=True)
        result_body.grid_columnconfigure(0, weight=4)
        result_body.grid_columnconfigure(1, weight=1)
        result_body.grid_rowconfigure(0, weight=1)

        preview_card = self._card(result_body)
        preview_card._shadow_wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 10))  # type: ignore[attr-defined]
        preview_top = tk.Frame(preview_card, bg=COLORS["surface"])
        preview_top.pack(fill="x", padx=18, pady=(14, 8))
        ttk.Label(preview_top, text="Result preview", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(
            preview_top,
            text="下一週期",
            style="Secondary.TButton",
            command=lambda: self._show_prf_cycle(1),
        ).pack(side="right", padx=(6, 0))
        ttk.Button(
            preview_top,
            text="上一週期",
            style="Secondary.TButton",
            command=lambda: self._show_prf_cycle(-1),
        ).pack(side="right", padx=(6, 0))
        for label, filename in [
            ("2D DAS", "plane_wave_das_bmode.png"),
            ("PRF週期", "zero_degree_prf_cycle_montage.png"),
            ("週期合成QA", "angle_compound_prf_index_montage.png"),
            ("通道QA", "channel_diagnostics.png"),
            ("回波時域", "echo_time_domain_validation.png"),
            ("Sector", "sector_scan.png"),
            ("Spectrum", "echo_spectrum.png"),
        ]:
            ttk.Button(preview_top, text=label, style="Secondary.TButton", command=lambda name=filename: self.show_result_image(name)).pack(side="right", padx=(6, 0))
        tk.Label(
            preview_card,
            textvariable=self.preview_source_var,
            bg=COLORS["primary_soft"],
            fg=COLORS["primary_hover"],
            anchor="w",
            padx=12,
            pady=7,
            font=("Cascadia Mono", 9),
        ).pack(fill="x", padx=18, pady=(0, 8))
        self.preview_frame = tk.Frame(preview_card, bg="#EEF3F8", highlightbackground=COLORS["border"], highlightthickness=1)
        self.preview_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.preview_label = tk.Label(self.preview_frame, text="完成處理後，結果圖會顯示在這裡。", bg="#EEF3F8", fg=COLORS["muted"], font=("Segoe UI", 11))
        self.preview_label.pack(fill="both", expand=True, padx=12, pady=12)
        self.preview_frame.bind("<Configure>", lambda _event: self._schedule_preview_resize())

        summary_card = self._card(result_body)
        summary_card._shadow_wrapper.grid(row=0, column=1, sticky="nsew", padx=(10, 0))  # type: ignore[attr-defined]
        ttk.Label(summary_card, text="Analysis summary", style="CardTitle.TLabel").pack(anchor="w", padx=18, pady=(16, 10))
        tk.Label(summary_card, textvariable=self.result_summary_var, bg=COLORS["surface"], fg=COLORS["text"], justify="left", anchor="nw", wraplength=260, font=("Segoe UI", 10)).pack(fill="both", expand=True, padx=18, pady=(0, 18))

    def show_page(self, name: str) -> None:
        self.pages[name].tkraise()
        self.active_page = name
        for key, button in self.nav_buttons.items():
            button.configure(style="NavSelected.TButton" if key == name else "Nav.TButton")

    def _current_array_config(self) -> ArrayConfig:
        return ArrayConfig(
            elements=int(self.elements_var.get()),
            pitch_mm=float(self.pitch_var.get()),
            element_width_mm=float(self.width_var.get()),
            center_frequency_mhz=float(self.frequency_var.get()),
            sound_speed_m_s=float(self.sound_speed_var.get()),
            delay_quantum_ns=float(self.quantum_var.get()),
            reverse_angle_sign=bool(self.reverse_var.get()),
        )

    def _current_tx_plan(self) -> TxPlan:
        try:
            return validate_tx_plan(
                self.waveform_mode_var.get(),
                float(self.frequency_var.get()),
                int(self.tx_cycles_var.get()),
                float(self.tx_hv_a_var.get()),
                float(self.tx_hv_b_var.get()),
            )
        except (ValueError, tk.TclError) as exc:
            raise ValueError(str(exc)) from exc

    def _tx_plan_changed(self) -> None:
        self.tx_plan_confirmed_var.set(False)
        self.tx_plan_summary_var.set("TX 計畫已修改，請重新確認")
        if hasattr(self, "tx_plan_status_label"):
            self.tx_plan_status_label.configure(
                bg=COLORS["warning_soft"],
                fg=COLORS["warning"],
                highlightbackground="#F0D49C",
            )
        if hasattr(self, "tx_waveform_canvas"):
            self._refresh_tx_waveform_preview()

    def _refresh_tx_waveform_preview(self) -> None:
        if not hasattr(self, "tx_waveform_canvas"):
            return
        canvas = self.tx_waveform_canvas
        canvas.delete("all")
        mode = self.waveform_mode_var.get()
        preset = TX_WAVEFORM_PRESETS.get(mode)
        if preset is None:
            self.tx_plan_detail_var.set("未知波形；不會寫入硬件。")
            return
        try:
            hv_a = abs(float(self.tx_hv_a_var.get()))
        except ValueError:
            hv_a = 100.0
        try:
            hv_b = abs(float(self.tx_hv_b_var.get()))
        except ValueError:
            hv_b = 50.0
        scale = max(hv_b, hv_a, 1.0)
        width = int(canvas.cget("width"))
        height = int(canvas.cget("height"))
        left, right, top, bottom = 34, width - 8, 8, height - 10
        center_y = (top + bottom) / 2.0
        canvas.create_line(left, center_y, right, center_y, fill="#9EB0C4", dash=(3, 3))
        for label, magnitude in (("+A", hv_a), ("+B", hv_b), ("0", 0.0), ("-B", -hv_b), ("-A", -hv_a)):
            y = center_y - (magnitude / scale) * (bottom - top) * 0.43
            canvas.create_text(4, y, text=label, anchor="w", fill=COLORS["muted"], font=("Cascadia Mono", 7))
        values = {"+A": hv_a, "-A": -hv_a, "+B": hv_b, "-B": -hv_b, "0": 0.0}
        sequence = tuple(preset["levels"])
        step_width = (right - left) / float(len(sequence))
        points: list[float] = []
        previous_y = center_y
        for index, level in enumerate(sequence):
            x0 = left + index * step_width
            x1 = left + (index + 1) * step_width
            y = center_y - (values[level] / scale) * (bottom - top) * 0.43
            points.extend((x0, previous_y, x0, y, x1, y))
            previous_y = y
        points.extend((right, previous_y, right, center_y))
        if len(points) >= 4:
            canvas.create_line(*points, fill=COLORS["primary"], width=2)
        try:
            cycles_text = str(int(self.tx_cycles_var.get()))
        except ValueError:
            cycles_text = "?"
        rail_note = (
            "HV_A 是外層、HV_B 是內層，必須 |HV_A| > |HV_B|；"
            if mode == "tapered-5level"
            else "bipolar-a 只選擇 ±HV_A，±HV_B 不參與此波形；"
        )
        self.tx_plan_detail_var.set(
            f"{preset['label']}；base level sequence：{' → '.join(sequence)}；重複為 {cycles_text} cycles。\n"
            f"{rail_note}兩者是外部電源實測記錄，不會被 SPI 改變。"
        )

    def _confirm_tx_plan(self) -> None:
        if self.tx_programming_active:
            messagebox.showinfo("TX 正在寫入", "請等待目前的 Pattern 寫入與讀回完成。", parent=self)
            return
        if self.capture_watch is not None:
            messagebox.showwarning("採集正在進行", "採集期間不能另外改寫 TX Pattern。", parent=self)
            return
        try:
            plan = self._current_tx_plan()
        except ValueError as exc:
            messagebox.showerror("TX 計畫無效", str(exc), parent=self)
            return
        proceed = messagebox.askyesno(
            "確認 TX7316 波形計畫",
            f"{plan.summary}\n\n"
            f"Level sequence：{' → '.join(plan.level_sequence)}\n\n"
            "確認後程式會立即強制 TX_BF_MODE=0，寫入 Pattern Profile 0 與 Repeat/Tail，"
            "並逐字讀回。這一步不連接HSDC、不採集，也不啟用發射；Delay Profile仍在採集時按角度寫入。\n\n"
            "注意：±HV_A／±HV_B 是你量測並輸入的外部電源值；程式不會調節高壓電源。是否確認？",
            parent=self,
            icon="warning",
        )
        if not proceed:
            return
        if not is_windows_admin():
            messagebox.showerror(
                "需要管理員權限",
                "請以管理員身份重新啟動 Collector；TX7316 GUI 與 Collector 必須使用相同權限。",
                parent=self,
            )
            return
        if not PYTHON27.is_file() or not AUTOMATION_SCRIPT.is_file():
            messagebox.showerror(
                "TX 寫入環境缺失",
                f"找不到：\n{PYTHON27}\n或\n{AUTOMATION_SCRIPT}",
                parent=self,
            )
            return
        self._program_tx_plan(plan)

    def _program_tx_plan(self, plan: TxPlan) -> None:
        """Write a whitelisted Pattern Profile while transmit remains disabled."""
        command = [
            str(PYTHON27),
            str(AUTOMATION_SCRIPT),
            "--program-tx-only",
            "--center-frequency-mhz",
            f"{plan.frequency_mhz:.9g}",
            "--waveform-mode",
            plan.waveform_mode,
            "--tx-cycles",
            str(plan.cycles),
            "--expected-hv-a-v",
            f"{plan.hv_a_v:.9g}",
            "--expected-hv-b-v",
            f"{plan.hv_b_v:.9g}",
        ]
        self.tx_programming_active = True
        self.tx_plan_confirmed_var.set(False)
        self.tx_plan_summary_var.set("正在寫入並讀回 TX Pattern…")
        self.tx_plan_status_label.configure(
            bg=COLORS["warning_soft"],
            fg=COLORS["warning"],
            highlightbackground="#F0D49C",
        )
        self.tx_confirm_button.state(["disabled"])

        def worker() -> None:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(APP_DIR),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                    check=False,
                )
                output = "\n".join(
                    part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
                )
                error = None if completed.returncode == 0 else (output or f"exit code {completed.returncode}")
            except (OSError, subprocess.SubprocessError) as exc:
                output = ""
                error = str(exc)
            self.after(0, lambda: self._finish_tx_programming(plan, output, error))

        threading.Thread(target=worker, name="tx-pattern-program", daemon=True).start()

    def _finish_tx_programming(
        self,
        programmed_plan: TxPlan,
        output: str,
        error: str | None,
    ) -> None:
        self.tx_programming_active = False
        self.tx_confirm_button.state(["!disabled"])
        if error is not None:
            self.tx_plan_confirmed_var.set(False)
            self.tx_plan_summary_var.set("TX Pattern 寫入失敗 · BF 已要求保持 OFF")
            self.tx_plan_status_label.configure(
                bg=COLORS["danger_soft"],
                fg=COLORS["danger"],
                highlightbackground="#E7BEC1",
            )
            messagebox.showerror("TX Pattern 寫入失敗", error[-1800:], parent=self)
            return
        try:
            current_plan = self._current_tx_plan()
        except ValueError:
            current_plan = None
        if current_plan != programmed_plan:
            self.tx_plan_confirmed_var.set(False)
            self.tx_plan_summary_var.set("TX 已寫入，但界面參數其後被修改")
            messagebox.showwarning(
                "TX 已寫入舊計畫",
                "寫入期間界面參數發生變化；請按目前參數重新確認並寫入。",
                parent=self,
            )
            return
        self.tx_plan_confirmed_var.set(True)
        self.tx_plan_summary_var.set("TX Pattern 已寫入／回讀 · TX_BF_MODE=OFF")
        self.tx_plan_status_label.configure(
            bg=COLORS["success_soft"],
            fg=COLORS["success"],
            highlightbackground="#CDE8DC",
        )
        self._update_command_preview(
            self._current_array_config(), self._current_angles(), dry_run=False
        )
        detail = output[-1400:] if output else "Pattern Profile 0 readback matched."
        messagebox.showinfo(
            "TX Pattern 寫入成功",
            f"{programmed_plan.summary}\n\n"
            "Pattern Profile 0 已逐字讀回一致，TX_BF_MODE 保持 OFF。\n"
            "若 TI GUI 畫面沒有立即刷新，切到其他頁籤再回到 Profile Configuration。\n\n"
            f"{detail}",
            parent=self,
        )

    def _current_rx_slots(self) -> list[int]:
        text = self.rx_channels_var.get().strip()
        try:
            slots = [int(token.strip()) for token in text.split(",") if token.strip()]
        except ValueError as exc:
            raise ValueError("HSDC接收槽必須是逗號分隔的整數，例如 1,2,3,4,5,6,7,8。") from exc
        expected = int(self.elements_var.get())
        if len(slots) != expected:
            raise ValueError(f"HSDC接收槽數必須等於物理T/R陣元數 {expected}；目前為 {slots}。")
        if len(set(slots)) != len(slots) or any(slot < 1 or slot > 16 for slot in slots):
            raise ValueError("HSDC接收槽必須互不重複，且全部位於1…16。")
        return slots

    def _current_manual_das_slots(self, configured_slots: list[int]) -> list[int]:
        text = self.manual_das_rx_var.get().strip()
        try:
            slots = [int(token.strip()) for token in text.split(",") if token.strip()]
        except ValueError as exc:
            raise ValueError("手動DAS槽必須是逗號分隔的整數。") from exc
        if len(slots) < 2:
            raise ValueError("手動DAS至少需要兩個接收槽。")
        if len(set(slots)) != len(slots):
            raise ValueError("手動DAS槽不能重複。")
        if any(slot not in configured_slots for slot in slots):
            raise ValueError(f"手動DAS槽必須是配置槽 {configured_slots} 的子集。")
        return slots

    def _processing_options_changed(self) -> None:
        if not hasattr(self, "manual_das_rx_entry"):
            return
        is_manual = DUPLICATE_POLICY_OPTIONS.get(self.duplicate_policy_var.get()) == "manual"
        self.manual_das_rx_entry.state(["!disabled"] if is_manual else ["disabled"])
        angle_text = (
            "2°模式只在離線重建時選取 -10,-8,…,+10；不重新採集，也不刪除原始1°文件。"
            if ANGLE_SUBSET_OPTIONS.get(self.reconstruction_angle_subset_var.get()) == 2.0
            else "全部模式使用capture中所有角度；可隨時切到2°子集重新運算。"
        )
        duplicate_text = (
            "手動模式按你輸入的槽做DAS，適合示波器/逐SMA排查後使用。"
            if is_manual
            else (
                "全部保留模式會把逐bit重複波形放在不同物理位置，只能作診斷比較。"
                if DUPLICATE_POLICY_OPTIONS.get(self.duplicate_policy_var.get()) == "keep-all"
                else "自動模式每個逐bit重複組只保留映射中先出現的槽；不會刪除原始BIN。"
            )
        )
        apodization_mode = RECEIVE_APODIZATION_OPTIONS.get(
            self.receive_apodization_var.get(), "uniform"
        )
        artifact_notes = [f"RX窗={apodization_mode}"]
        if self.coherence_factor_var.get():
            artifact_notes.append("√CF按通道相位一致性抑制旁瓣，可能降低弱散斑")
        if self.common_mode_suppression_var.get():
            artifact_notes.append("共模只作用於TX後0–12 mm，不做全深度中值相減")
        if len(artifact_notes) == 1 and apodization_mode == "uniform":
            artifact_notes.append("保持原始DAS")
        self.processing_option_help_var.set(
            f"{duplicate_text}  {angle_text}\n離線成像：{'；'.join(artifact_notes)}。"
        )

    def _current_angles(self) -> list[float]:
        return build_angle_list(float(self.min_angle_var.get()), float(self.max_angle_var.get()), float(self.angle_step_var.get()))

    def recalculate_delays(self, show_errors: bool = True) -> tuple[ArrayConfig, list[float]] | None:
        try:
            config = self._current_array_config()
            rx_slots = self._current_rx_slots()
            angles = self._current_angles()
            profiles = calculate_profiles(angles, config)
        except (ValueError, tk.TclError) as exc:
            self.array_summary_var.set("參數無效")
            self.array_warning_var.set(str(exc))
            if show_errors:
                messagebox.showerror("延時計算失敗", str(exc), parent=self)
            return None

        for item in self.delay_tree.get_children():
            self.delay_tree.delete(item)
        for profile_number, profile in enumerate(profiles):
            hardware_profile = profile_number % HARDWARE_DELAY_PROFILES_PER_BATCH
            grating = "—" if profile.nearest_grating_lobe_deg is None else f"{profile.nearest_grating_lobe_deg:+.2f}°"
            values = [
                f"{profile_number:02d}→P{hardware_profile:02d}",
                f"{profile.angle_deg:+.2f}°",
                f"{profile.realized_angle_deg:+.2f}°",
                *profile.counts_a1_to_a8,
                f"{profile.mean_phase_step_deg:+.1f}°",
                grating,
            ]
            self.delay_tree.insert("", "end", values=values)

        wavelength_mm = config.wavelength_m * 1e3
        batch_count = int(math.ceil(len(angles) / HARDWARE_DELAY_PROFILES_PER_BATCH))
        try:
            samples = int(self.samples_var.get())
            repeats = int(self.repeats_var.get())
            file_count = len(angles) * repeats
            gib = file_count * samples * RX_CHANNELS_IN_CAPTURE_FILE * BYTES_PER_ADC_SAMPLE / float(1024**3)
            save_minutes_low = file_count * 30.0 / 60.0
            save_minutes_high = file_count * 60.0 / 60.0
            self.sweep_estimate_var.set(
                f"{len(angles)} angles · {batch_count} TX batch{'es' if batch_count != 1 else ''} · "
                f"{file_count} BIN · ≈ {gib:.2f} GiB · save ≈ {save_minutes_low:.1f}–{save_minutes_high:.0f} min"
            )
        except (ValueError, tk.TclError):
            self.sweep_estimate_var.set(f"{len(angles)} angles · {batch_count} TX batches")
        self.array_summary_var.set(
            f"λ {wavelength_mm:.3f} mm   d/λ {config.pitch_over_wavelength:.2f}   "
            f"{len(angles)} angles / {batch_count} batch   RX slots {rx_slots}"
        )
        warning_parts: list[str] = []
        if config.pitch_over_wavelength > 0.5:
            warning_parts.append(f"存在柵瓣；λ/2上限 {config.half_wavelength_pitch_limit_mhz:.3f} MHz")
        else:
            warning_parts.append("間距 ≤ λ/2")
        if batch_count > 1:
            warning_parts.append(f"自動分{batch_count}批重寫16個硬件Profile")
        self.array_warning_var.set(" · ".join(warning_parts))
        self._refresh_tx_waveform_preview()
        self._update_command_preview(config, angles, dry_run=False)
        if hasattr(self, "auto_scan_tree"):
            self.recalculate_auto_scan(show_errors=False)
        return config, angles

    def _current_auto_scan_plan(self):
        # The stock-CPLD block mode does not change angle on each PRF. Use one
        # frame here only to render the angle/profile map; the per-angle PRF
        # block length is calculated separately below.
        frames = (
            1
            if self.auto_scan_mode_var.get() == AUTO_SCAN_CPLD_BLOCK_MODE
            else int(self.auto_scan_frames_var.get())
        )
        return build_rapid_scan_plan(
            RapidScanConfig(
                angles_deg=tuple(self._current_angles()),
                prf_hz=float(self.auto_scan_prf_var.get()),
                frames=frames,
                guard_prfs=int(self.auto_scan_guard_var.get()),
            )
        )

    def recalculate_auto_scan(self, show_errors: bool = True):
        if not hasattr(self, "auto_scan_tree"):
            return None
        try:
            plan = self._current_auto_scan_plan()
        except (ValueError, tk.TclError) as exc:
            self.auto_scan_summary_var.set(f"參數無效：{exc}")
            self.auto_scan_status_var.set("掃描方案無效")
            self.auto_scan_start_button.state(["disabled"])
            if show_errors:
                messagebox.showerror("逐PRF掃描參數錯誤", str(exc), parent=self)
            return None

        for item in self.auto_scan_tree.get_children():
            self.auto_scan_tree.delete(item)
        for bank in plan.banks:
            for event in bank.events:
                self.auto_scan_tree.insert(
                    "",
                    "end",
                    values=(
                        f"B{event.bank_index + 1:02d}",
                        f"{event.frame_index + 1}",
                        f"{event.event_in_bank:03d}",
                        f"P{event.hardware_profile:02d}",
                        f"{event.angle_deg:+.2f}°",
                        f"{event.time_ms:.3f} ms",
                        f"{event.sample_offset:,}",
                    ),
                )

        bank_sizes = ", ".join(
            f"B{bank.bank_index + 1}={bank.samples_per_channel:,} samples/{bank.expected_bytes / 1024**2:.1f} MiB"
            for bank in plan.banks
        )
        if self.auto_scan_mode_var.get() == AUTO_SCAN_CPLD_BLOCK_MODE:
            prf_hz = float(self.auto_scan_prf_var.get())
            pulse_count = int(self.auto_scan_frames_var.get())
            block_samples = contiguous_prf_block_samples(prf_hz, pulse_count)
            block_mib = (
                block_samples * RX_CHANNELS_IN_CAPTURE_FILE * BYTES_PER_ADC_SAMPLE
                / 1024**2
            )
            total_gib = block_mib * plan.angle_count / 1024.0
            block_ms = block_samples / ADC_SAMPLE_RATE_HZ * 1000.0
            self.auto_scan_summary_var.set(
                f"推薦板載CPLD方案：{plan.angle_count} angles / 單bank / "
                f"每角 {pulse_count} 個同角PRF。每BIN {block_samples:,} samples/ch，"
                f"{block_ms:.3f} ms，{block_mib:.2f} MiB；總計約 {total_gib:.3f} GiB。"
            )
            self.auto_scan_gate_var.set("STOCK CPLD / READY")
            self.auto_scan_gate_label.configure(bg=COLORS["success_soft"], fg=COLORS["success"])
            self.auto_scan_start_button.configure(text="開始11角 × 32 PRF同步採集")
            self.auto_scan_start_button.state(["!disabled"])
            self.auto_scan_status_var.set(
                "順序：選Profile → 開BF → 武裝TSW下一上升沿 → 連續錄32 PRF → 關BF → 保存。"
            )
        elif self.auto_scan_mode_var.get() == AUTO_SCAN_VERIFIED_MODE:
            try:
                repeats = int(self.repeats_var.get())
            except (ValueError, tk.TclError):
                repeats = 1
            files = plan.angle_count * max(1, repeats)
            self.auto_scan_summary_var.set(
                f"現有流程：{plan.angle_count} angles × {max(1, repeats)} repeat = {files} BIN。"
                "每個文件只對應一個角度，保存期間有長間隔；下表僅預覽升級後的逐PRF映射。"
            )
            self.auto_scan_gate_var.set("CURRENT WORKFLOW")
            self.auto_scan_gate_label.configure(bg=COLORS["success_soft"], fg=COLORS["success"])
            self.auto_scan_start_button.configure(text="開始已驗證逐角度掃描")
            self.auto_scan_start_button.state(["!disabled"])
            self.auto_scan_status_var.set("可直接調用現有Capture腳本；採集前仍須完成Capture頁五項Pre-flight。")
        else:
            self.auto_scan_summary_var.set(
                f"快速方案：{plan.angle_count} angles · {plan.bank_count} bank/{plan.file_count} BIN · "
                f"理想掃描 {plan.sweep_time_ms:.3f} ms · 實際記錄 {plan.captured_time_ms:.3f} ms · "
                f"總量 {plan.expected_bytes / 1024**2:.1f} MiB · {bank_sizes}"
            )
            self.auto_scan_gate_var.set("FIRMWARE REQUIRED")
            self.auto_scan_gate_label.configure(bg=COLORS["warning_soft"], fg=COLORS["warning"])
            self.auto_scan_start_button.configure(text="快速掃描尚未解鎖")
            self.auto_scan_start_button.state(["disabled"])
            confirmed = sum(1 for variable in self.auto_scan_confirm_vars if variable.get())
            self.auto_scan_status_var.set(
                f"硬件門檻 {confirmed}/3；即使全部勾選，仍須由軟件讀回快速掃描固件版本後才能解鎖。"
            )
        return plan

    def _auto_scan_mode_changed(self) -> None:
        if self.auto_scan_mode_var.get() == AUTO_SCAN_CPLD_BLOCK_MODE:
            self.min_angle_var.set("-10")
            self.max_angle_var.set("10")
            self.angle_step_var.set("2")
            self.auto_scan_prf_var.set("1000")
            self.auto_scan_frames_var.set("32")
            self.auto_scan_guard_var.set("1")
            self.recalculate_delays(show_errors=False)
        self.recalculate_auto_scan(show_errors=False)

    def export_auto_scan_plan(self) -> None:
        plan = self.recalculate_auto_scan(show_errors=True)
        if plan is None:
            return
        try:
            output_root = Path(self.output_root_var.get()).expanduser().resolve()
            output_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("無法建立輸出目錄", str(exc), parent=self)
            return
        default_name = time.strftime("rapid_scan_plan_%Y%m%d_%H%M%S.json")
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="保存逐PRF掃描方案",
            initialdir=str(output_root),
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON plan", "*.json")],
        )
        if not selected:
            return
        payload = plan_as_dict(plan)
        payload["array"] = {
            "elements": self.elements_var.get(),
            "pitch_mm": self.pitch_var.get(),
            "frequency_mhz": self.frequency_var.get(),
            "rx_hsdc_slots": self.rx_channels_var.get(),
        }
        payload["ui_mode"] = self.auto_scan_mode_var.get()
        if self.auto_scan_mode_var.get() == AUTO_SCAN_CPLD_BLOCK_MODE:
            prf_hz = float(self.auto_scan_prf_var.get())
            pulse_count = int(self.auto_scan_frames_var.get())
            payload["stock_cpld_same_angle_block"] = {
                "prf_hz": prf_hz,
                "prfs_per_bin": pulse_count,
                "samples_per_channel": contiguous_prf_block_samples(prf_hz, pulse_count),
                "trigger_edge": "rising",
                "required_capture_trigger_input": "TSW14J50 J13 TRIG_IN",
                "afe_j25_role": "optional receive-event reference; not HSDC capture trigger",
            }
        try:
            path = Path(selected)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存方案失敗", str(exc), parent=self)
            return
        self.auto_scan_status_var.set(f"方案已保存：{path}")

    def launch_auto_scan(self, dry_run: bool) -> None:
        plan = self.recalculate_auto_scan(show_errors=True)
        if plan is None:
            return
        if self.auto_scan_mode_var.get() == AUTO_SCAN_CPLD_BLOCK_MODE:
            prf_hz = float(self.auto_scan_prf_var.get())
            pulse_count = int(self.auto_scan_frames_var.get())
            block_samples = contiguous_prf_block_samples(prf_hz, pulse_count)
            self.launch_capture(
                dry_run=dry_run,
                status_var=self.auto_scan_status_var,
                progress=self.auto_scan_progress,
                button=self.auto_scan_start_button,
                title="HKUST Ultrosound collector platform - Stock CPLD synchronized block scan",
                samples=block_samples,
                repeats=1,
                trigger="hardware",
                expected_prf_hz=prf_hz,
                expected_prfs_per_bin=pulse_count,
            )
            return
        if self.auto_scan_mode_var.get() == AUTO_SCAN_VERIFIED_MODE:
            self.launch_capture(
                dry_run=dry_run,
                status_var=self.auto_scan_status_var,
                progress=self.auto_scan_progress,
                button=self.auto_scan_start_button,
                title="HKUST Ultrosound collector platform - Verified angle scan",
            )
            return
        if dry_run:
            requirements = "\n".join(
                f"B{bank.bank_index + 1}: {len(bank.angles_deg)} profiles, "
                f"{bank.event_count} emissions, {bank.samples_per_channel:,} samples/channel"
                for bank in plan.banks
            )
            messagebox.showinfo(
                "逐PRF時序檢查通過",
                f"方案在數學上有效：\n{requirements}\n\n"
                "這只是時序dry run；沒有連接GUI、沒有寫TX7316、沒有啟動HSDC。",
                parent=self,
            )
            self.auto_scan_status_var.set("Dry run通過；請保存JSON並交給CPLD/FPGA sequencer實現。")
            return
        messagebox.showwarning(
            "快速掃描硬件未解鎖",
            "原廠TX7316EVM CPLD不能自動逐SYNC切換Profile。\n\n"
            "必須先實現並驗證：profile counter、frame-start復位、SPI選擇時序、HSDC同時arm，以及固件版本讀回。"
            "在此之前只能使用『已驗證：每角度獨立BIN』模式。",
            parent=self,
        )

    def _doppler_source_changed(self) -> None:
        if self.doppler_prf_source_var.get().startswith("Onboard CPLD"):
            self.doppler_prf_var.set("1000")
            self.doppler_trigger_var.set("normal")
        else:
            self.doppler_trigger_var.set("hardware")
        self.recalculate_doppler(show_errors=False)

    def _doppler_mode_changed(self) -> None:
        mode = DOPPLER_CAPTURE_MODE_OPTIONS[self.doppler_capture_mode_var.get()]
        if mode == RAW_RF_DDR_MODE:
            self.doppler_status_var.set("原始RF單塊可執行；完成後會自動生成短時速度譜。")
        elif mode == FPGA_RANGE_GATE_IQ_MODE:
            self.doppler_status_var.set("推薦心動周期路徑；等待已驗證的TSW FPGA距離門/IQ後端。")
        else:
            self.doppler_status_var.set("AFE Demod研究路徑；等待匹配的JESD解包profile與通道Gate。")
        self.recalculate_doppler(show_errors=False)

    @staticmethod
    def _doppler_mode_label(capture_mode: str) -> str:
        for label, value in DOPPLER_CAPTURE_MODE_OPTIONS.items():
            if value == capture_mode:
                return label
        raise ValueError(f"找不到Doppler capture mode：{capture_mode}")

    def _selected_doppler_preset(self) -> DopplerPreset:
        try:
            return CAROTID_PHANTOM_PRESETS_BY_LABEL[self.doppler_preset_var.get()]
        except KeyError as exc:
            raise ValueError("請重新選擇一個有效的頸動脈流量仿體方案。") from exc

    def _doppler_preset_changed(self) -> None:
        try:
            preset = self._selected_doppler_preset()
        except ValueError:
            self.doppler_preset_note_var.set("預設無效，請重新選擇。")
            return
        backend = "現有後端可執行" if preset.current_backend_executable else "等待連續I/Q後端"
        self.doppler_preset_note_var.set(
            f"{backend} · {preset.purpose} 僅限已知流速仿體，不是人體或診斷配置。"
        )
        self.doppler_preset_execute_button.configure(
            text="一鍵採集並分析" if preset.current_backend_executable else "一鍵載入並檢查Gate"
        )

    def _apply_doppler_preset(self, preset: DopplerPreset, execute: bool = False) -> None:
        # Keep the physical aperture and current degraded RX mapping explicit.
        # Safety acknowledgements are never checked automatically.
        self.elements_var.set("8")
        self.pitch_var.set("1.59")
        self.width_var.set("1.0")
        self.rx_channels_var.set("1,2,3,4,5,6,7,8")
        self.sound_speed_var.set("1540.0")
        self.quantum_var.set("5.0")
        self.waveform_mode_var.set("tapered-5level")
        self.frequency_var.set(f"{preset.center_frequency_mhz:g}")
        self.doppler_capture_mode_var.set(self._doppler_mode_label(preset.capture_mode))
        self.doppler_prf_source_var.set(preset.prf_source)
        self.doppler_prf_var.set(f"{preset.prf_hz:g}")
        self.doppler_steering_var.set(f"{preset.steering_angle_deg:g}")
        self.doppler_flow_angle_var.set(f"{preset.flow_angle_deg:g}")
        self.doppler_depth_var.set(f"{preset.target_depth_mm:g}")
        self.doppler_gate_length_var.set(f"{preset.gate_length_mm:g}")
        self.doppler_velocity_var.set(f"{preset.expected_velocity_m_s:g}")
        self.doppler_duration_var.set(f"{preset.desired_duration_s:g}")
        self.doppler_ensemble_var.set(str(preset.ensemble_pulses))
        self.doppler_wall_filter_var.set(f"{preset.wall_filter_hz:g}")
        self.doppler_heart_rate_var.set(f"{preset.expected_heart_rate_bpm:g}")
        self.doppler_samples_var.set(str(preset.block_samples_per_channel))
        self.doppler_repeats_var.set(str(preset.repeats))
        self.doppler_trigger_var.set(preset.trigger)
        self.recalculate_delays(show_errors=False)
        calculated = self.recalculate_doppler(show_errors=True)
        if calculated is None:
            return
        self.doppler_status_var.set(f"已套用：{preset.label}")
        if execute:
            self.after_idle(lambda: self.launch_doppler_capture(False))

    def _apply_selected_doppler_preset(self, execute: bool = False) -> None:
        try:
            preset = self._selected_doppler_preset()
        except ValueError as exc:
            messagebox.showerror("PW Doppler預設錯誤", str(exc), parent=self)
            return
        self._apply_doppler_preset(preset, execute=execute)

    def _load_doppler_preset(self) -> None:
        preset = CAROTID_PHANTOM_PRESETS_BY_KEY["carotid_phantom_routine_10s"]
        self.doppler_preset_var.set(preset.label)
        self._doppler_preset_changed()
        self._apply_doppler_preset(preset)

    def _load_doppler_raw_preset(self) -> None:
        preset = CAROTID_PHANTOM_PRESETS_BY_KEY["carotid_phantom_raw_low_flow"]
        self.doppler_preset_var.set(preset.label)
        self._doppler_preset_changed()
        self._apply_doppler_preset(preset)

    def _current_doppler_config(self) -> DopplerConfig:
        return DopplerConfig(
            center_frequency_mhz=float(self.frequency_var.get()),
            prf_hz=float(self.doppler_prf_var.get()),
            steering_angle_deg=float(self.doppler_steering_var.get()),
            flow_angle_deg=float(self.doppler_flow_angle_var.get()),
            target_depth_mm=float(self.doppler_depth_var.get()),
            expected_velocity_m_s=float(self.doppler_velocity_var.get()),
            desired_duration_s=float(self.doppler_duration_var.get()),
            ensemble_pulses=int(self.doppler_ensemble_var.get()),
            gate_length_mm=float(self.doppler_gate_length_var.get()),
            wall_filter_hz=float(self.doppler_wall_filter_var.get()),
            expected_heart_rate_bpm=float(self.doppler_heart_rate_var.get()),
            adc_rate_msps=120.0,
            block_samples_per_channel=int(self.doppler_samples_var.get()),
            rx_channels=RX_CHANNELS_IN_CAPTURE_FILE,
            iq_channels=int(self.elements_var.get()),
            bytes_per_adc_sample=BYTES_PER_ADC_SAMPLE,
            sound_speed_m_s=float(self.sound_speed_var.get()),
            capture_mode=DOPPLER_CAPTURE_MODE_OPTIONS[self.doppler_capture_mode_var.get()],
        )

    @staticmethod
    def _localize_doppler_warning(warning: str) -> str:
        translations = {
            "Target depth uses more than 80%": "目標深度已使用超過80%的無模糊量程，請降低PRF或增加餘量。",
            "Expected velocity is close": "預期速度接近Nyquist上限，請提高PRF或降低發射頻率。",
            "One raw HSDC block": "單個HSDC原始塊的脈衝數少於所選FFT ensemble。",
            "The desired cardiac duration": "期望心動時長超過單個原始塊；多次Capture之間存在缺口。",
            "Gap-free full-duration raw RF": "全時長原始RF超過1 GiB；應改用AFE I/Q抽取或FPGA距離門。",
            "Requested raw block exceeds": "所填Samples/channel超過TSW14J50按16列分攤後的理論DDR上限。",
            "Even the theoretical maximum": "即使使用理論最大原始RF單塊，也短於一個預期心動周期。",
            "Requested duration covers fewer": "所填時長少於三個預期心動周期，不能可靠判定周期性。",
            "FPGA range-gated I/Q": "FPGA距離門I/Q是推薦心動路徑，但尚缺已驗證的TSW固件與採集後端。",
            "AFE demodulated I/Q": "AFE Demod I/Q尚缺匹配且通過通道Gate的JESD解包profile。",
        }
        for prefix, localized in translations.items():
            if warning.startswith(prefix):
                return localized
        return warning

    def recalculate_doppler(self, show_errors: bool = True) -> tuple[DopplerConfig, DopplerResult] | None:
        try:
            config = self._current_doppler_config()
            result = calculate_doppler(config)
            array_config = self._current_array_config()
            calculate_profiles([config.steering_angle_deg], array_config)
            repeats = int(self.doppler_repeats_var.get())
            if repeats <= 0:
                raise ValueError("Block repeats must be positive.")
        except (ValueError, tk.TclError) as exc:
            self.doppler_summary_var.set("參數無效")
            self.doppler_storage_var.set(str(exc))
            self.doppler_warning_var.set("修正紅旗參數後再進行dry run。")
            if show_errors:
                messagebox.showerror("PW Doppler參數錯誤", str(exc), parent=self)
            return None

        self.doppler_summary_var.set(
            f"PRF period       {result.prf_period_us:8.2f} us\n"
            f"Unambiguous z   {result.max_unambiguous_depth_mm:8.1f} mm\n"
            f"Velocity Nyq.   {result.nyquist_velocity_m_s:8.3f} m/s\n"
            f"Expected fD     {result.expected_doppler_shift_hz:8.1f} Hz\n"
            f"Minimum PRF     {result.minimum_prf_for_expected_velocity_hz:8.0f} Hz\n"
            f"Requested cycles{result.requested_heart_cycles:8.2f}"
        )
        self.doppler_storage_var.set(
            f"One raw block    {result.block_duration_ms:7.2f} ms / {result.pulses_per_raw_block:.1f} pulses\n"
            f"One BIN          {result.raw_block_gib:7.3f} GiB\n"
            f"{config.desired_duration_s:g}s raw RF      {result.full_duration_raw_gib:7.2f} GiB\n"
            f"Range-gated I/Q  {result.range_gated_iq_mib:7.2f} MiB\n"
            f"FFT window       {result.ensemble_duration_ms:7.2f} ms / {result.velocity_bin_m_s:.4f} m/s bin\n"
            f"TSW raw maximum  {result.board_max_raw_duration_s:7.3f} s / {result.board_max_raw_heart_cycles:.2f} cycles"
        )
        warnings = [self._localize_doppler_warning(item) for item in result.warnings]
        if self.doppler_prf_source_var.get().startswith("Onboard CPLD"):
            warnings.insert(0, "板載CPLD的PRF固定為1 kHz；GUI數值不能改變硬件PRF。")
        else:
            warnings.insert(0, "外部PRF需要隔離板載CPLD驅動並同步TX、AFE與TSW；J7 pin 2只是觀測輸出。")
        self.doppler_warning_var.set("\n".join(f"• {item}" for item in warnings))

        if config.capture_mode == RAW_RF_DDR_MODE:
            try:
                arguments = self._capture_arguments(
                    array_config,
                    [config.steering_angle_deg],
                    dry_run=False,
                    samples=config.block_samples_per_channel,
                    repeats=repeats,
                    settle=0.25,
                    trigger=self.doppler_trigger_var.get(),
                    expected_prf_hz=config.prf_hz,
                    expected_prfs_per_bin=max(1, int(math.floor(result.pulses_per_raw_block))),
                )
                self.doppler_command_var.set(
                    subprocess.list2cmdline([str(PYTHON27), str(AUTOMATION_SCRIPT), *arguments])
                )
            except ValueError:
                pass
        else:
            self.doppler_command_var.set(
                "HARDWARE GATE · 此模式不會調用現有raw-RF腳本；先導出Session Plan並完成固件、同步和已知流速驗收。"
            )
        return config, result

    def _doppler_plan(self) -> dict:
        calculated = self.recalculate_doppler(show_errors=True)
        if calculated is None:
            raise ValueError("PW Doppler parameters are invalid.")
        config, result = calculated
        plan = result_as_dict(config, result)
        plan["prf_source"] = self.doppler_prf_source_var.get()
        try:
            selected_preset = self._selected_doppler_preset()
            plan["selected_preset_key"] = selected_preset.key
            plan["selected_preset_label"] = selected_preset.label
            plan["preset_is_template_only"] = True
        except ValueError:
            plan["selected_preset_key"] = None
        plan["hsdc_trigger"] = self.doppler_trigger_var.get()
        plan["block_repeats"] = int(self.doppler_repeats_var.get())
        plan["prf_programmed_by_ui"] = False
        plan["tx_angle_programmed_by_ui"] = config.capture_mode == RAW_RF_DDR_MODE
        plan["capture_backend_ready"] = result.current_mode_hardware_ready
        plan["separate_capture_files_may_be_concatenated"] = False
        plan["cardiac_claim_requires_single_continuous_record"] = True
        plan["array"] = {
            "active_tx_elements": int(self.elements_var.get()),
            "active_rx_hsdc_slots_1_based": self._current_rx_slots(),
            "pitch_mm": float(self.pitch_var.get()),
            "element_width_mm": float(self.width_var.get()),
        }
        plan["calibration"] = {
            "range_zero_calibrated": False,
            "velocity_direction_calibrated": False,
            "flow_angle_source": "measure from B-mode or known phantom geometry; TX steering alone is insufficient",
        }
        if config.capture_mode != RAW_RF_DDR_MODE:
            plan["required_backend_contract"] = {
                "filename": "pw_doppler_input_iq.npz",
                "iq_shape": "(continuous_pulses, active_iq_channels)",
                "iq_dtype": "complex64 or complex int16 converted losslessly to complex64",
                "required_fields": ["iq", "prf_hz"],
                "continuity": "monotonic pulse_index/timestamp with no missing or repeated pulses",
            }
        plan["operation_guide"] = str(DOPPLER_GUIDE)
        return plan

    def export_doppler_plan(self) -> None:
        try:
            plan = self._doppler_plan()
            plan_dir = Path(self.output_root_var.get()).expanduser().resolve() / "doppler_plans"
            plan_dir.mkdir(parents=True, exist_ok=True)
            target = plan_dir / time.strftime("doppler_plan_%Y%m%d_%H%M%S.json")
            target.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError) as exc:
            messagebox.showerror("無法導出Session Plan", str(exc), parent=self)
            return
        self.doppler_status_var.set(f"Session Plan已保存：{target}")
        messagebox.showinfo("Session Plan已保存", str(target), parent=self)

    def _open_doppler_guide(self) -> None:
        if not DOPPLER_GUIDE.exists():
            messagebox.showerror("找不到操作文檔", str(DOPPLER_GUIDE), parent=self)
            return
        try:
            os.startfile(DOPPLER_GUIDE)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("無法打開操作文檔", str(exc), parent=self)

    def _current_cw_doppler_config(self) -> CwDopplerConfig:
        row_layout = (
            ((1, 3), 2),
            ((4, 6), 5),
            ((7,), 8),
        )
        rows = tuple(
            CwRowConfig(
                row_number=index + 1,
                physical_angle_deg=float(self.cw_row_angle_vars[index].get()),
                tx_patch_ids=layout[0],
                rx_patch_id=layout[1],
                afe_rx_slot=int(self.cw_row_rx_slot_vars[index].get()),
            )
            for index, layout in enumerate(row_layout)
        )
        return CwDopplerConfig(
            center_frequency_hz=float(self.cw_frequency_var.get()) * 1e6,
            adc_rate_hz=float(self.cw_adc_rate_var.get()) * 1e6,
            decimation=IQ_RATE_DECIMATION[float(self.cw_iq_rate_var.get()) * 1e6],
            logical_patch_count=int(self.cw_logical_channels_var.get()),
            analysis_rate_hz=float(self.cw_analysis_rate_var.get()) * 1e3,
            lowpass_hz=float(self.cw_lowpass_var.get()) * 1e3,
            wall_filter_hz=float(self.cw_wall_filter_var.get()),
            stft_samples=int(self.cw_stft_samples_var.get()),
            stft_overlap=int(self.cw_stft_overlap_var.get()),
            desired_duration_s=float(self.cw_duration_var.get()),
            rows=rows,
        )

    def recalculate_cw_doppler(
        self,
        show_errors: bool = True,
    ) -> tuple[CwDopplerConfig, CwDopplerResult] | None:
        try:
            config = self._current_cw_doppler_config()
            result = calculate_cw_doppler(config)
        except (ValueError, tk.TclError) as exc:
            self.cw_summary_var.set("參數無效")
            self.cw_storage_var.set(str(exc))
            self.cw_warning_var.set("修正參數後再導出或寫入待機配置。")
            if show_errors:
                messagebox.showerror("CW Doppler參數錯誤", str(exc), parent=self)
            return None
        if hasattr(self, "cw_beta_labels"):
            for label, beta in zip(self.cw_beta_labels, result.refracted_angles_deg):
                label.configure(text=f"{beta:.2f}°")
        doppler_text = [variable.get().strip() for variable in self.cw_row_doppler_vars]
        if not any(doppler_text):
            self.cw_velocity_result_var.set(
                "輸入三行帶符號 fD（Hz）後計算 DBUD 流速與流向。"
            )
        elif not all(doppler_text):
            self.cw_velocity_result_var.set("DBUD需要三行同時量得的帶符號 fD；目前輸入不完整。")
        else:
            try:
                estimate = estimate_dbud_velocity(
                    [float(value) for value in doppler_text],
                    result.refracted_angles_deg,
                    config.center_frequency_hz,
                    config.tissue_sound_speed_m_s,
                )
            except ValueError as exc:
                self.cw_velocity_result_var.set(f"DBUD計算失敗：{exc}")
            else:
                predicted = " / ".join(f"{value:+.1f}" for value in estimate.predicted_doppler_hz)
                self.cw_velocity_result_var.set(
                    f"DBUD signed v = {estimate.signed_speed_m_s:+.4f} m/s · "
                    f"|v| = {estimate.speed_magnitude_m_s:.4f} m/s · "
                    f"flow angle = {estimate.flow_angle_deg:+.2f}°\n"
                    f"fD fitted = {predicted} Hz · residual RMS = {estimate.residual_rms_hz:.2f} Hz"
                )
        self.cw_summary_var.set(
            f"f0 requested     {config.center_frequency_hz / 1e6:8.3f} MHz\n"
            f"Physical ADC/D   {config.adc_rate_hz / 1e6:5.0f} / {config.decimation:d}\n"
            f"Target I/Q       {result.iq_output_rate_hz / 1e6:8.3f} MSPS\n"
            f"NCO word         0x{result.nco_word:04X}\n"
            f"NCO actual       {result.nco_actual_hz / 1e6:8.6f} MHz\n"
            f"AFE FIR preset   {'YES' if result.preset_fir_supported else 'NO - custom FIR'}\n"
            f"beta rows        {' / '.join(f'{value:.2f}°' for value in result.refracted_angles_deg)}"
        )
        self.cw_storage_var.set(
            f"Raw RF 16-slot   {result.raw_rf_16slot_bytes_per_s / 1e6:7.1f} MB/s · {result.raw_rf_16slot_duration_s:.2f} s\n"
            f"IQ 8ch complex   {result.hsdc_16slot_bytes_per_s / 1e6:7.1f} MB/s · {result.hsdc_16slot_duration_s:.2f} s\n"
            f"External I/Q     {result.external_iq_bytes / 1048576.0:7.2f} MiB / {config.desired_duration_s:g} s\n"
            f"STFT bin         {result.stft_bin_hz:7.2f} Hz"
        )
        backend = CW_DOPPLER_BACKEND_OPTIONS[self.cw_backend_var.get()]
        warnings = list(result.warnings)
        if backend == "analog-cw-external-adc":
            warnings.insert(0, "推薦：CW_OUTP/M後接同時取樣I/Q ADC；頁面所選MSPS是AFE數位研究路徑，不是類比輸出的必要取樣率。")
        else:
            warnings.insert(0, "研究模式：目前缺少與所選M值匹配、且通過通道唯一性Gate的AFE CFG與HSDC demod解包；禁止直接採十秒。")
        self.cw_warning_var.set("\n".join(f"• {item}" for item in warnings))
        return config, result

    def _reset_cw_paper_geometry(self) -> None:
        for variable, value in zip(self.cw_row_angle_vars, (17.0, 20.0, 23.0)):
            variable.set(str(value))
        for variable, value in zip(self.cw_row_rx_slot_vars, (1, 2, 3)):
            variable.set(str(value))
        self.recalculate_cw_doppler(show_errors=True)

    def _cw_doppler_plan(self) -> dict:
        calculated = self.recalculate_cw_doppler(show_errors=True)
        if calculated is None:
            raise ValueError("CW Doppler parameters are invalid.")
        config, result = calculated
        plan = cw_plan_as_dict(config, result)
        doppler_text = [variable.get().strip() for variable in self.cw_row_doppler_vars]
        plan["dbud_analysis"] = {
            "measured_doppler_hz": [float(value) if value else None for value in doppler_text],
            "simultaneous_three_row_measurement_required": True,
            "result_text": self.cw_velocity_result_var.get(),
        }
        plan["selected_backend_label"] = self.cw_backend_var.get()
        plan["selected_backend"] = CW_DOPPLER_BACKEND_OPTIONS[self.cw_backend_var.get()]
        plan["gui_execution"] = {
            "tx_safe_standby": "supported_stock_3p125MHz_vendor_profile_or_1_2_4MHz_finite_pattern_CW_OFF",
            "tx_continuous_cw_start": (
                "supported_stock_3p125MHz_low_voltage_timed_test"
                if abs(config.center_frequency_hz - 3_125_000.0) < 1.0
                else "blocked_requires_verified_128MHz_BF_CLK"
            ),
            "afe_digital_iq": "blocked_until_matching_AFE_CFG_and_TSW14J50_unpack_pass_channel_gate",
            "requested_decimation": config.decimation,
            "requested_iq_output_rate_hz": result.iq_output_rate_hz,
            "preset_fir_supported": result.preset_fir_supported,
            "reason": "The TI repaired No-Demod profile is the raw-RF baseline and must not be overwritten.",
        }
        plan["operator_confirmations"] = {
            "phantom_only": bool(self.cw_phantom_confirmed_var.get()),
            "thermal_and_current_limit": bool(self.cw_thermal_confirmed_var.get()),
            "transport_path_understood": bool(self.cw_path_confirmed_var.get()),
            "j1_plus_minus_5v_measured": bool(self.cw_tx_low_voltage_confirmed_var.get()),
        }
        plan["operation_guide"] = str(CW_DOPPLER_GUIDE)
        return plan

    def _write_cw_doppler_plan(self) -> Path:
        plan = self._cw_doppler_plan()
        plan_dir = Path(self.output_root_var.get()).expanduser().resolve() / "cw_doppler_plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        target = plan_dir / time.strftime("cw_doppler_plan_%Y%m%d_%H%M%S.json")
        target.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        self.cw_last_plan = target
        return target

    def export_cw_doppler_plan(self) -> None:
        try:
            target = self._write_cw_doppler_plan()
        except (OSError, ValueError) as exc:
            messagebox.showerror("無法導出CW配置", str(exc), parent=self)
            return
        self.cw_status_var.set(f"CW配置方案已保存：{target}")
        messagebox.showinfo("CW配置方案已保存", str(target), parent=self)

    def _open_cw_doppler_guide(self) -> None:
        if not CW_DOPPLER_GUIDE.exists():
            messagebox.showerror("找不到操作文檔", str(CW_DOPPLER_GUIDE), parent=self)
            return
        try:
            os.startfile(CW_DOPPLER_GUIDE)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("無法打開操作文檔", str(exc), parent=self)

    def stage_cw_doppler_tx(self) -> None:
        if not all((self.cw_phantom_confirmed_var.get(), self.cw_thermal_confirmed_var.get(), self.cw_path_confirmed_var.get())):
            messagebox.showwarning("尚未完成CW安全確認", "請先勾選三項硬體與仿體確認。", parent=self)
            return
        try:
            config = self._current_cw_doppler_config()
            stock_cw = abs(config.center_frequency_hz - 3_125_000.0) < 1.0
            required_script = CW_TX_CONTROL_SCRIPT if stock_cw else CW_DOPPLER_STAGE_SCRIPT
            if not required_script.exists() or not PYTHON27.exists():
                raise ValueError("找不到Python 2.7或CW待機寫入腳本。")
            plan_path = self._write_cw_doppler_plan()
        except (OSError, ValueError) as exc:
            messagebox.showerror("無法建立CW待機配置", str(exc), parent=self)
            return
        tx_description = (
            "會載入TI隨TX7316 GUI安裝的3.125 MHz CW配置並讀回；完成後CW_EN與TX_BF_MODE保持OFF。\n\n"
            if stock_cw else
            f"會把{config.center_frequency_hz / 1e6:g} MHz有限Pattern寫入TX7316並讀回；CW_EN與TX_BF_MODE保持OFF。\n\n"
        )
        prompt = (
            tx_description
            + f"同時保存120 MSPS / M={config.decimation} / {config.iq_output_rate_hz / 1e6:g} MSPS I/Q配置方案。"
            + "AFE與HSDC尚無通過通道唯一性驗收的匹配profile，因此本次不會誤寫這兩部分。繼續嗎？"
        )
        if not messagebox.askyesno(
            "寫入可驗證寄存器／配置",
            prompt,
            parent=self,
        ):
            return
        self.cw_stage_button.configure(state="disabled")
        self.cw_status_var.set("正在寫入TX GUI寄存器並讀回，同時保存AFE/HSDC配置方案；CW保持OFF。")
        if stock_cw:
            command = [str(PYTHON27), str(CW_TX_CONTROL_SCRIPT), "--stage", "--output", str(plan_path.with_suffix(".tx_stage.json"))]
        else:
            command = [str(PYTHON27), str(CW_DOPPLER_STAGE_SCRIPT), "--plan", str(plan_path), "--apply"]

        def worker() -> None:
            completed = subprocess.run(command, capture_output=True, text=True, errors="replace")
            output = (completed.stdout + "\n" + completed.stderr).strip()
            self.after(0, lambda: finish(completed.returncode, output))

        def finish(returncode: int, output: str) -> None:
            self.cw_stage_button.configure(state="normal")
            tail = "\n".join(output.splitlines()[-8:])
            if returncode == 0:
                self.cw_status_var.set(f"TX {config.center_frequency_hz / 1e6:g} MHz已寫入並讀回；AFE/HSDC I/Q配置已保存但因未驗證而未寫板。")
                messagebox.showinfo("寄存器／配置處理完成", tail or "完成", parent=self)
            else:
                self.cw_status_var.set("TX安全待機寫入失敗；未解鎖連續CW。")
                messagebox.showerror("TX安全待機失敗", tail or "未知錯誤", parent=self)

        threading.Thread(target=worker, daemon=True).start()

    def start_tx7316_cw_test(self) -> None:
        confirmations = (
            self.cw_phantom_confirmed_var.get(),
            self.cw_thermal_confirmed_var.get(),
            self.cw_path_confirmed_var.get(),
            self.cw_tx_low_voltage_confirmed_var.get(),
        )
        if not all(confirmations):
            messagebox.showwarning("尚未完成CW安全確認", "請先完成四項安全確認，尤其是用萬用表確認J1正／負高壓軌均為5 V。", parent=self)
            return
        try:
            config = self._current_cw_doppler_config()
            if abs(config.center_frequency_hz - 3_125_000.0) >= 1.0:
                raise ValueError("現有200 MHz BF_CLK只允許啟動3.125 MHz CW；精確1/2/4 MHz需要已驗證的128 MHz BF_CLK硬件。")
            measured_supply = float(self.cw_tx_supply_var.get())
            duration = float(self.cw_tx_test_seconds_var.get())
            if abs(measured_supply - 5.0) > 0.1:
                raise ValueError("J1正／負高壓軌的實測絕對值必須在4.9至5.1 V。")
            if not 0.05 <= duration <= 5.0:
                raise ValueError("限時CW測試必須介於0.05至5.0秒。")
            if not CW_TX_CONTROL_SCRIPT.exists() or not PYTHON27.exists():
                raise ValueError("找不到Python 2.7或TX7316 CW控制腳本。")
            plan_path = self._write_cw_doppler_plan()
            result_path = plan_path.with_suffix(".tx_cw_run.json")
        except (OSError, ValueError) as exc:
            messagebox.showerror("不能啟動CW", str(exc), parent=self)
            return
        if not messagebox.askyesno(
            "最後確認：啟動限時CW",
            f"將在流體／凝膠仿體上啟動3.125 MHz CW {duration:g}秒，之後自動關閉。\n\n"
            "必須已用萬用表確認J1正、負高壓軌均為±5 V，所有5 V電源限流按TI指南設為500 mA。"
            "5-level EVM只使用B側CW通道。是否繼續？",
            parent=self,
        ):
            return
        self.cw_tx_start_button.configure(state="disabled")
        self.cw_stage_button.configure(state="disabled")
        self.cw_status_var.set(f"正在輸出3.125 MHz CW，最遲{duration:g}秒後由腳本自動關閉……")
        command = [
            str(PYTHON27), str(CW_TX_CONTROL_SCRIPT),
            "--run-seconds", f"{duration:g}",
            "--acknowledge-5v-supply",
            "--output", str(result_path),
        ]

        def worker() -> None:
            completed = subprocess.run(command, capture_output=True, text=True, errors="replace")
            output = (completed.stdout + "\n" + completed.stderr).strip()
            self.after(0, lambda: finish(completed.returncode, output))

        def finish(returncode: int, output: str) -> None:
            self.cw_stage_button.configure(state="normal")
            self._refresh_cw_tx_controls()
            tail = "\n".join(output.splitlines()[-10:])
            if returncode == 0:
                self.cw_status_var.set("限時3.125 MHz CW已完成；CW_EN與TX_BF_MODE已讀回為OFF。")
                messagebox.showinfo("CW測試完成並已關閉", tail or "完成", parent=self)
            else:
                self.cw_status_var.set("CW控制回報失敗；請按『立即停止CW』並切斷TX高壓供電確認。")
                messagebox.showerror("CW控制失敗", tail or "未知錯誤", parent=self)

        threading.Thread(target=worker, daemon=True).start()

    def stop_tx7316_cw(self) -> None:
        if not CW_TX_CONTROL_SCRIPT.exists() or not PYTHON27.exists():
            messagebox.showerror("不能停止CW", "找不到Python 2.7或TX7316 CW控制腳本；請立即切斷TX高壓供電。", parent=self)
            return
        stop_dir = Path(self.output_root_var.get()).expanduser().resolve() / "cw_doppler_plans"
        stop_dir.mkdir(parents=True, exist_ok=True)
        result_path = stop_dir / time.strftime("cw_emergency_stop_%Y%m%d_%H%M%S.json")
        self.cw_tx_start_button.configure(state="disabled")
        self.cw_status_var.set("正在清除CW_EN與TX_BF_MODE並讀回……")
        command = [str(PYTHON27), str(CW_TX_CONTROL_SCRIPT), "--stop", "--output", str(result_path)]

        def worker() -> None:
            completed = subprocess.run(command, capture_output=True, text=True, errors="replace")
            output = (completed.stdout + "\n" + completed.stderr).strip()
            self.after(0, lambda: finish(completed.returncode, output))

        def finish(returncode: int, output: str) -> None:
            self._refresh_cw_tx_controls()
            tail = "\n".join(output.splitlines()[-10:])
            if returncode == 0:
                self.cw_status_var.set("CW_EN與TX_BF_MODE已關閉並讀回。")
                messagebox.showinfo("CW已停止", tail or "完成", parent=self)
            else:
                self.cw_status_var.set("軟件停止失敗：請立即切斷TX高壓供電。")
                messagebox.showerror("停止CW失敗", (tail or "未知錯誤") + "\n\n請立即切斷TX高壓供電。", parent=self)

        threading.Thread(target=worker, daemon=True).start()

    def _latest_doppler_run(self) -> Path | None:
        if self.doppler_result_run is not None and self.doppler_result_run.is_dir():
            return self.doppler_result_run
        root = Path(self.output_root_var.get()).expanduser()
        if not root.exists():
            return None
        candidates: list[Path] = []
        for plan_path in root.rglob("doppler_session_plan.json"):
            path = plan_path.parent
            manifest = read_json(path / "capture_manifest.json")
            if manifest.get("status") == "complete":
                candidates.append(path)
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    def launch_doppler_analysis(
        self,
        run: Path | None = None,
        force: bool = True,
        automatic: bool = False,
    ) -> None:
        run = self._latest_doppler_run() if run is None else run.resolve()
        if run is None:
            if not automatic:
                messagebox.showinfo(
                    "沒有PW Doppler記錄",
                    "尚未找到帶doppler_session_plan.json的完整capture。",
                    parent=self,
                )
            return
        if not DOPPLER_ANALYSIS_SCRIPT.is_file():
            messagebox.showerror("缺少分析腳本", str(DOPPLER_ANALYSIS_SCRIPT), parent=self)
            return
        if self.processing_active:
            if not automatic:
                messagebox.showwarning("分析正在進行", "請等待目前的離線分析完成。", parent=self)
            return
        self.processing_active = True
        self.doppler_result_run = run
        self.doppler_analysis_status_var.set(f"正在分析 {run.name} 的單一連續記錄…")
        command = [sys.executable, str(DOPPLER_ANALYSIS_SCRIPT), str(run)]
        if force:
            command.append("--force")

        def worker() -> None:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(APP_DIR),
                    capture_output=True,
                    text=True,
                    timeout=20 * 60,
                    check=False,
                )
                error: str | None = None
                if completed.returncode != 0:
                    error = (completed.stderr or completed.stdout or "unknown analysis error").strip()
            except (OSError, subprocess.SubprocessError) as exc:
                error = str(exc)
            self.after(0, lambda: self._finish_doppler_analysis(run, error, automatic))

        threading.Thread(target=worker, name="pw-doppler-analysis", daemon=True).start()

    def _finish_doppler_analysis(self, run: Path, error: str | None, automatic: bool) -> None:
        self.processing_active = False
        if error is not None:
            self.doppler_analysis_status_var.set("PW Doppler分析失敗；原始BIN未被修改。")
            self.doppler_result_var.set(error[-900:])
            if not automatic:
                messagebox.showerror("PW Doppler分析失敗", error[-1600:], parent=self)
            return
        self._load_doppler_analysis_summary(run)
        if not automatic:
            messagebox.showinfo(
                "PW Doppler分析完成",
                str(run / "analysis" / "pw_doppler" / "pw_doppler_spectrogram.png"),
                parent=self,
            )

    def _load_doppler_analysis_summary(self, run: Path) -> None:
        summary_path = run / "analysis" / "pw_doppler" / "pw_doppler_summary.json"
        summary = read_json(summary_path)
        result = summary.get("result", {})
        if summary.get("status") != "complete":
            self.doppler_analysis_status_var.set("未找到完整的PW Doppler分析摘要。")
            return
        self.doppler_result_run = run
        visible = bool(result.get("cardiac_cycle_visible", False))
        periodicity = result.get("cardiac_periodicity", {})
        cardiac_text = (
            f"周期通過 · {float(periodicity.get('heart_rate_bpm', 0.0)):.1f} BPM"
            if visible
            else f"周期未通過 · {periodicity.get('reason', '證據不足')}"
        )
        self.doppler_analysis_status_var.set(f"{run.name} · {cardiac_text}")
        self.doppler_result_var.set(
            f"連續 {float(result.get('record_duration_s', 0.0)):.3f} s · "
            f"預估 {float(result.get('expected_heart_cycles', 0.0)):.2f} 周期 · "
            f"|v|max {float(result.get('peak_velocity_abs_max_m_s', 0.0)):.3f} m/s · "
            "距離零點、速度量值與正負方向仍需仿體校準"
        )

    def _open_doppler_result(self) -> None:
        run = self._latest_doppler_run()
        if run is None:
            messagebox.showinfo("沒有速度譜", "請先完成採集與PW Doppler分析。", parent=self)
            return
        target = run / "analysis" / "pw_doppler" / "pw_doppler_spectrogram.png"
        if not target.is_file():
            messagebox.showinfo("沒有速度譜", "請先點擊「分析最新PW記錄」。", parent=self)
            return
        try:
            os.startfile(target)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("無法打開速度譜", str(exc), parent=self)

    def launch_doppler_capture(self, dry_run: bool) -> None:
        calculated = self.recalculate_doppler(show_errors=True)
        if calculated is None:
            return
        doppler_config, doppler_result = calculated
        if doppler_config.capture_mode != RAW_RF_DDR_MODE:
            try:
                plan = self._doppler_plan()
            except ValueError as exc:
                messagebox.showerror("PW Doppler參數錯誤", str(exc), parent=self)
                return
            if dry_run:
                self.doppler_status_var.set(
                    "心動周期方案計算通過；尚未解鎖硬件後端，不會連接或寫入設備。"
                )
                self.doppler_command_var.set(json.dumps(plan, ensure_ascii=False, indent=2))
                return
            messagebox.showwarning(
                "心動周期硬件Gate未通過",
                "最佳方案已完成參數與容量規劃，但現有TSW14J50 raw-RF固件不能錄製數秒連續資料。\n\n"
                "必須先完成：\n"
                "• 5 kHz共同PRF與TX/AFE/TSW同步驗證\n"
                "• TSW FPGA距離門/IQ固件或匹配的AFE Demod JESD解包\n"
                "• 單調pulse index與已知流速方向校準\n\n"
                "界面不會把有缺口的多個BIN偽裝成心動波形。",
                parent=self,
            )
            return
        try:
            array_config = self._current_array_config()
            repeats = int(self.doppler_repeats_var.get())
            arguments = self._capture_arguments(
                array_config,
                [doppler_config.steering_angle_deg],
                dry_run=dry_run,
                samples=doppler_config.block_samples_per_channel,
                repeats=repeats,
                settle=0.25,
                trigger=self.doppler_trigger_var.get(),
                expected_prf_hz=doppler_config.prf_hz,
                expected_prfs_per_bin=max(1, int(math.floor(doppler_result.pulses_per_raw_block))),
            )
            plan = self._doppler_plan()
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("PW Doppler參數錯誤", str(exc), parent=self)
            return

        onboard = self.doppler_prf_source_var.get().startswith("Onboard CPLD")
        if onboard and abs(doppler_config.prf_hz - 1000.0) > 1e-6:
            messagebox.showerror("PRF來源不一致", "板載CPLD固定為1 kHz；選擇外部同步源後才能規劃其他PRF。", parent=self)
            return
        if not dry_run:
            if not PYTHON27.exists() or not AUTOMATION_SCRIPT.exists():
                messagebox.showerror("採集環境缺失", f"找不到：\n{PYTHON27}\n或\n{AUTOMATION_SCRIPT}", parent=self)
                return
            if not self.tx_plan_confirmed_var.get():
                messagebox.showwarning(
                    "TX 計畫尚未確認",
                    "請回到第一頁確認波形、cycles 與外部高壓實測值。",
                    parent=self,
                )
                self.show_page("array")
                return
            tx_plan = self._current_tx_plan()
            confirmations = (
                self.doppler_phantom_confirmed_var.get(),
                self.doppler_sync_confirmed_var.get(),
                self.doppler_gap_ack_var.get(),
            )
            if not all(confirmations):
                messagebox.showwarning("尚未完成Doppler Pre-flight", "請勾選三項Doppler採集確認。", parent=self)
                return
            proceed = messagebox.askyesno(
                "啟動固定角度PW Doppler原始RF採集",
                f"腳本會先寫入並讀回TX7316固定角度Delay Profile，再錄製原始RF。\n\n"
                f"{tx_plan.summary}\n"
                f"Level sequence：{' → '.join(tx_plan.level_sequence)}\n\n"
                f"PRF={doppler_config.prf_hz:g} Hz只是已驗證硬件條件的記錄，程式本身不會修改CPLD PRF。\n"
                f"單塊連續時長約 {doppler_result.block_duration_ms:.2f} ms；本次保存 {repeats} 個BIN，但BIN之間有長缺口。\n"
                "完成後只對單一BIN做速度譜，不會拼接成心動波形。繼續嗎？",
                parent=self,
                icon="warning",
            )
            if not proceed:
                return

        self._launch_capture_process(
            arguments=arguments,
            dry_run=dry_run,
            status_var=self.doppler_status_var,
            progress=self.doppler_progress,
            button=self.doppler_capture_button,
            title="HKUST Ultrosound collector platform - PW Doppler short block",
            plan=plan,
        )

    def _capture_arguments(
        self,
        config: ArrayConfig,
        angles: list[float],
        dry_run: bool,
        samples: int | None = None,
        repeats: int | None = None,
        settle: float | None = None,
        trigger: str | None = None,
        expected_prf_hz: float | None = None,
        expected_prfs_per_bin: int | None = None,
    ) -> list[str]:
        samples = int(self.samples_var.get()) if samples is None else int(samples)
        repeats = int(self.repeats_var.get()) if repeats is None else int(repeats)
        settle = float(self.settle_var.get()) if settle is None else float(settle)
        if samples <= 0 or samples % 4096:
            raise ValueError("Samples/channel 必須為正數且是4096的整數倍。")
        if repeats <= 0:
            raise ValueError("Repeats 必須大於0。")
        if settle < 0:
            raise ValueError("Settle seconds 不能小於0。")
        trigger = self.trigger_var.get() if trigger is None else trigger
        if trigger not in {"normal", "software", "hardware"}:
            raise ValueError("Trigger模式無效。")
        if expected_prf_hz is not None and expected_prf_hz <= 0:
            raise ValueError("Expected PRF must be positive.")
        if expected_prfs_per_bin is not None and expected_prfs_per_bin <= 0:
            raise ValueError("Expected PRFs/BIN must be positive.")

        plan = self._current_tx_plan()
        waveform_mode = plan.waveform_mode

        arguments = [
            "--dry-run" if dry_run else "--capture",
            f"--angles={format_angles_cli(angles)}",
            "--tx-elements",
            str(config.elements),
            "--rx-channels",
            ",".join(str(slot) for slot in self._current_rx_slots()),
            "--pitch-mm",
            f"{config.pitch_mm:.6g}",
            "--element-width-mm",
            f"{config.element_width_mm:.6g}",
            "--center-frequency-mhz",
            f"{config.center_frequency_mhz:.6g}",
            "--waveform-mode",
            waveform_mode,
            "--tx-cycles",
            str(plan.cycles),
            "--expected-hv-a-v",
            f"{plan.hv_a_v:.6g}",
            "--expected-hv-b-v",
            f"{plan.hv_b_v:.6g}",
            "--sound-speed-m-s",
            f"{config.sound_speed_m_s:.6g}",
            "--delay-quantum-ns",
            f"{config.delay_quantum_ns:.6g}",
            "--samples",
            str(samples),
            "--repeats",
            str(repeats),
            "--settle-seconds",
            f"{settle:.6g}",
            "--trigger",
            trigger,
            "--output-root",
            str(Path(self.output_root_var.get()).expanduser()),
        ]
        if expected_prf_hz is not None:
            arguments.extend(["--expected-prf-hz", f"{expected_prf_hz:.9g}"])
        if expected_prfs_per_bin is not None:
            arguments.extend(["--expected-prfs-per-bin", str(expected_prfs_per_bin)])
        if not dry_run:
            arguments.append("--enable-internal-bf")
            # For the three hardware-qualified presets, make the requested
            # frequency authoritative: program Profile 0 and Reg25, pulse
            # LOAD_PROF, then require a bit-for-bit readback before capture.
            # This prevents the UI frequency field from changing metadata only
            # while TX7316 is still using a pattern left by an earlier run.
            if any(
                abs(config.center_frequency_mhz - preset_mhz) < 1e-9
                for preset_mhz in (1.0, 1.5, 2.0, 2.5, 4.0)
            ):
                arguments.append("--program-known-pattern")
        if config.reverse_angle_sign:
            arguments.append("--reverse-angle-sign")
        if max(abs(value) for value in angles) > 10.0:
            arguments.append("--allow-large-steering")
        return arguments

    def _update_command_preview(self, config: ArrayConfig, angles: list[float], dry_run: bool) -> None:
        try:
            arguments = self._capture_arguments(config, angles, dry_run)
            command = subprocess.list2cmdline([str(PYTHON27), str(AUTOMATION_SCRIPT), *arguments])
        except (ValueError, OSError) as exc:
            self.command_preview_var.set(f"配置錯誤：{exc}")
            return
        self.command_preview_var.set(command)

    def _launch_capture_process(
        self,
        arguments: list[str],
        dry_run: bool,
        status_var: tk.StringVar,
        progress: ttk.Progressbar,
        button: ttk.Button,
        title: str,
        plan: dict | None = None,
    ) -> None:
        if self.capture_watch is not None:
            messagebox.showwarning("採集正在進行", "已有一個採集任務正在監控，請等待其完成。", parent=self)
            return
        if not PYTHON27.exists() or not AUTOMATION_SCRIPT.exists():
            messagebox.showerror("採集環境缺失", f"找不到：\n{PYTHON27}\n或\n{AUTOMATION_SCRIPT}", parent=self)
            return

        output_root = Path(self.output_root_var.get()).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        existing = {path.name for path in output_root.glob("capture_*")}
        command_parts = [str(PYTHON27), str(AUTOMATION_SCRIPT), *arguments]
        command_line = subprocess.list2cmdline(command_parts)
        console_title = f"{title} - Dry Run" if dry_run else title
        console_body = (
            f'title {console_title} & {command_line} & '
            'if errorlevel 1 '
            '(echo. & echo CAPTURE FAILED. Review ERROR and run.log above.) '
            'else '
            '(echo. & echo CAPTURE SUCCEEDED.) & pause'
        )
        if status_var is self.doppler_status_var:
            self.doppler_command_var.set(command_line)
        else:
            self.command_preview_var.set(command_line)

        capture_process = None
        try:
            if dry_run or is_windows_admin():
                capture_process = subprocess.Popen(
                    ["cmd.exe", "/c", console_body],
                    cwd=str(APP_DIR),
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
            else:
                parameters = subprocess.list2cmdline(["/c", console_body])
                shell_result = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", "cmd.exe", parameters, str(APP_DIR), 1,
                )
                if shell_result <= 32:
                    raise OSError(f"UAC launch failed with ShellExecute code {shell_result}")
        except OSError as exc:
            messagebox.showerror("無法啟動命令列", str(exc), parent=self)
            return

        if dry_run:
            status_var.set("Dry run已在獨立命令列窗口啟動；不會寫入硬件。")
            return
        status_var.set("採集已啟動；正在等待新manifest。請不要操作硬件GUI。")
        progress.start(12)
        button.state(["disabled"])
        self.capture_watch = {
            "root": output_root,
            "existing": existing,
            "started": time.time(),
            "run": None,
            "status_var": status_var,
            "progress": progress,
            "button": button,
            "plan": plan,
            "plan_written": False,
            "process": capture_process,
        }
        self.after(1500, self._poll_capture_manifest)

    def launch_capture(
        self,
        dry_run: bool,
        status_var: tk.StringVar | None = None,
        progress: ttk.Progressbar | None = None,
        button: ttk.Button | None = None,
        title: str = "HKUST Ultrosound collector platform - Acquisition",
        samples: int | None = None,
        repeats: int | None = None,
        trigger: str | None = None,
        expected_prf_hz: float | None = None,
        expected_prfs_per_bin: int | None = None,
    ) -> None:
        status_var = self.capture_status_var if status_var is None else status_var
        progress = self.capture_progress if progress is None else progress
        button = self.capture_button if button is None else button
        calculated = self.recalculate_delays(show_errors=True)
        if calculated is None:
            return
        config, angles = calculated
        try:
            arguments = self._capture_arguments(
                config,
                angles,
                dry_run,
                samples=samples,
                repeats=repeats,
                trigger=trigger,
                expected_prf_hz=expected_prf_hz,
                expected_prfs_per_bin=expected_prfs_per_bin,
            )
            capture_trigger = self.trigger_var.get() if trigger is None else trigger
        except ValueError as exc:
            messagebox.showerror("採集參數錯誤", str(exc), parent=self)
            return
        if not PYTHON27.exists() or not AUTOMATION_SCRIPT.exists():
            messagebox.showerror("採集環境缺失", f"找不到：\n{PYTHON27}\n或\n{AUTOMATION_SCRIPT}", parent=self)
            return
        if not dry_run and not all(variable.get() for variable in self.prerequisite_vars):
            messagebox.showwarning("尚未完成 Pre-flight", "請逐項確認五個採集前條件。", parent=self)
            return
        if not dry_run:
            if not self.tx_plan_confirmed_var.get():
                messagebox.showwarning(
                    "TX 計畫尚未確認",
                    "請回到第一頁檢查波形、cycles 與外部 ±HV_A／±HV_B 實測值，然後點擊「確認並寫入 TX」。",
                    parent=self,
                )
                self.show_page("array")
                return
            plan = self._current_tx_plan()
            if capture_trigger == "hardware":
                trigger_ready = messagebox.askyesno(
                    "確認TSW外部觸發連線",
                    "硬件觸發模式要求：\n\n"
                    "• TX7316 TP18／已核對的SYNCP引腳 → 有源緩衝／電平調理 → TSW14J50 J13 TRIG_IN\n"
                    "• AFE J25只是可選事件參考，不能代替TSW J13\n"
                    "• 1 kHz SYNCP沒有接到AFE LMK時鐘輸入\n"
                    "• 沒有把TX7316高壓OUT接到任何時鐘／觸發口\n\n"
                    "以上均已確認，繼續嗎？",
                    parent=self,
                    icon="warning",
                )
                if not trigger_ready:
                    return
            if len(angles) > HARDWARE_DELAY_PROFILES_PER_BATCH:
                batch_count = int(math.ceil(len(angles) / HARDWARE_DELAY_PROFILES_PER_BATCH))
                proceed = messagebox.askyesno(
                    "多批角度採集",
                    f"本次共有 {len(angles)} 個角度，超過TX7316的16個硬件Delay Profile。\n\n"
                    f"腳本會分 {batch_count} 批安全重寫Profile並保存 {len(angles) * int(self.repeats_var.get())} 個BIN。\n"
                    "批次切換期間 TX_BF_MODE 會保持關閉。是否繼續？",
                    parent=self,
                )
                if not proceed:
                    return
            if max(abs(value) for value in angles) > 10.0:
                proceed = messagebox.askyesno("大角度柵瓣警告", "角度超過 ±10°，目前間距將產生非常嚴重的空間混疊。仍要繼續嗎？", parent=self)
                if not proceed:
                    return
            proceed = messagebox.askyesno(
                "啟動高壓凝膠採集",
                "程式將控制已開啟的 TX7316 GUI 並觸發 HSDC Capture。\n\n"
                f"{plan.summary}\n"
                f"Level sequence：{' → '.join(plan.level_sequence)}\n\n"
                "程式會寫入並回讀 Pattern／Repeat／Delay；不會調節外部高壓電源。\n"
                "確認 CW 已關閉、外部電源與輸入值一致，而且本次只測凝膠／仿體？",
                parent=self,
                icon="warning",
            )
            if not proceed:
                return

        self._launch_capture_process(
            arguments=arguments,
            dry_run=dry_run,
            status_var=status_var,
            progress=progress,
            button=button,
            title=title,
        )

    def _poll_capture_manifest(self) -> None:
        watch = self.capture_watch
        if watch is None:
            return
        root: Path = watch["root"]
        status_var: tk.StringVar = watch["status_var"]
        progress: ttk.Progressbar = watch["progress"]
        button: ttk.Button = watch["button"]
        if watch["run"] is None:
            candidates = [
                path for path in root.glob("capture_*")
                if path.name not in watch["existing"]
            ]
            if candidates:
                watch["run"] = max(candidates, key=lambda path: path.stat().st_mtime)
        run = watch["run"]
        process = watch.get("process")
        if (
            run is None
            and process is not None
            and process.poll() is not None
            and time.time() - watch["started"] > 1.0
        ):
            progress.stop()
            button.state(["!disabled"])
            self.capture_watch = None
            status_var.set("error · 採集子進程未建立 run 目錄")
            messagebox.showerror(
                "採集未啟動",
                f"採集子進程已提前退出（exit code {process.returncode}），而且沒有建立 run 目錄。\n"
                "請檢查管理員權限、Python 2.7 路徑和命令列 ERROR。",
                parent=self,
            )
            return
        if run is not None:
            if watch.get("plan") is not None and not watch.get("plan_written"):
                try:
                    (run / "doppler_session_plan.json").write_text(
                        json.dumps(watch["plan"], indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    watch["plan_written"] = True
                except OSError:
                    pass
            manifest_path = run / "capture_manifest.json"
            manifest = read_json(manifest_path)
            if (
                not manifest_path.is_file()
                and process is not None
                and process.poll() is not None
                and time.time() - watch["started"] > 1.0
            ):
                progress.stop()
                button.state(["!disabled"])
                self.capture_watch = None
                log_path = run / "run.log"
                log_text = ""
                try:
                    log_text = log_path.read_text(encoding="utf-8", errors="replace").strip()
                except OSError:
                    pass
                error_text = (
                    "採集子進程已在建立 manifest 前退出。\n"
                    f"exit code: {process.returncode}\n"
                    f"run: {run}\n\n"
                    f"{log_text or 'run.log 沒有記錄具體錯誤；請在命令列重跑並查看 ERROR。'}"
                )
                status_var.set(f"{run.name}: error · 子進程提前退出")
                messagebox.showerror("採集未啟動", error_text, parent=self)
                return
            status = manifest.get("status", "initializing")
            captures = len(manifest.get("captures", []))
            total = len(manifest.get("array", {}).get("profiles", [])) * int(manifest.get("arguments", {}).get("repeats", 1))
            status_var.set(f"{run.name}: {status} · files {captures}/{total or '?'}")
            if status in {"complete", "error"}:
                progress.stop()
                button.state(["!disabled"])
                self.capture_watch = None
                if button is self.auto_scan_start_button:
                    self.recalculate_auto_scan(show_errors=False)
                self.refresh_capture_runs(select=run)
                if status == "complete":
                    if button is self.doppler_capture_button and watch.get("plan") is not None:
                        self.launch_doppler_analysis(run, force=True, automatic=True)
                    messagebox.showinfo("採集完成", f"已保存 {captures} 個 BIN 文件：\n{run}", parent=self)
                else:
                    messagebox.showerror("採集失敗", str(manifest.get("error", "請查看 run.log")), parent=self)
                return
        if time.time() - watch["started"] > 6 * 60 * 60:
            progress.stop()
            button.state(["!disabled"])
            self.capture_watch = None
            status_var.set("監控超時；請直接檢查命令列與output root。")
            return
        self.after(2000, self._poll_capture_manifest)

    def refresh_capture_runs(self, select: Path | None = None) -> None:
        root = Path(self.output_root_var.get()).expanduser()
        runs = complete_capture_runs(root)
        values = [str(path) for path in runs]
        if hasattr(self, "capture_combo"):
            self.capture_combo.configure(values=values)
        if select is not None:
            self.capture_folder_var.set(str(select))
        elif not self.capture_folder_var.get() and values:
            self.capture_folder_var.set(values[0])
        if self.capture_folder_var.get():
            self.load_existing_results()

    def _clear_analysis_cache(self) -> None:
        """Delete only generated analysis artifacts for the selected capture."""
        if self.processing_active:
            messagebox.showinfo("正在運算", "請等待目前的運算結束後再清除。", parent=self)
            return
        folder = Path(self.capture_folder_var.get()).expanduser().resolve()
        analysis = (folder / "analysis").resolve()
        if not folder.is_dir() or analysis.parent != folder:
            messagebox.showerror("路徑無效", "無法確認所選capture的analysis子目錄。", parent=self)
            return
        if not analysis.exists():
            self.processing_status_var.set("此capture沒有分析緩存。")
            return
        if not messagebox.askyesno(
            "清除分析緩存",
            f"只刪除以下自動生成的分析結果，不會刪除原始BIN：\n\n{analysis}",
            parent=self,
        ):
            return
        shutil.rmtree(analysis)
        self.preview_path = None
        self.preview_photo = None
        self.preview_filename = "plane_wave_das_bmode.png"
        self.current_prf_cycle_index = -1
        self.preview_label.configure(image="", text="分析緩存已清除；原始BIN保留。請點擊「強制重新運算」。")
        self.preview_source_var.set(f"Run: {folder.name} · analysis cache cleared")
        self.processing_status_var.set("分析緩存已清除；原始BIN未刪除。")
        self.result_summary_var.set("等待從原始BIN重新運算。")

    def start_processing(self) -> None:
        if self.processing_active:
            return
        folder = Path(self.capture_folder_var.get()).expanduser()
        manifest = read_json(folder / "capture_manifest.json")
        if not folder.is_dir() or manifest.get("status") != "complete":
            messagebox.showerror("無效的 Capture", "請選擇 manifest status 為 complete 的 capture_* 文件夾。", parent=self)
            return
        if not RECONSTRUCTION_SCRIPT.exists():
            messagebox.showerror("找不到處理腳本", str(RECONSTRUCTION_SCRIPT), parent=self)
            return
        try:
            rx_slots = self._current_rx_slots()
            duplicate_policy = DUPLICATE_POLICY_OPTIONS[self.duplicate_policy_var.get()]
            angle_subset_step = ANGLE_SUBSET_OPTIONS[self.reconstruction_angle_subset_var.get()]
            receive_apodization = RECEIVE_APODIZATION_OPTIONS[
                self.receive_apodization_var.get()
            ]
            coherence_factor_enabled = bool(self.coherence_factor_var.get())
            common_mode_suppression_enabled = bool(
                self.common_mode_suppression_var.get()
            )
            manual_das_slots = (
                self._current_manual_das_slots(rx_slots)
                if duplicate_policy == "manual"
                else None
            )
        except (KeyError, ValueError, tk.TclError) as exc:
            messagebox.showerror("接收槽配置無效", str(exc), parent=self)
            return
        self.processing_active = True
        self.process_button.state(["disabled"])
        self.processing_progress.start(12)
        self.processing_status_var.set("正在重新讀取BIN、驗證PRF事件、帶通、DAS並生成逐週期與時域QA圖…")

        def worker() -> None:
            command = [
                sys.executable,
                str(RECONSTRUCTION_SCRIPT),
                "--input-dir",
                str(folder),
                "--rx-channels",
                ",".join(str(slot) for slot in rx_slots),
                "--duplicate-policy",
                duplicate_policy,
                "--receive-apodization",
                receive_apodization,
            ]
            if manual_das_slots is not None:
                command.extend(
                    ["--das-rx-channels", ",".join(str(slot) for slot in manual_das_slots)]
                )
            if angle_subset_step is not None:
                command.extend(
                    ["--reconstruction-angle-step-deg", f"{angle_subset_step:g}"]
                )
            if coherence_factor_enabled:
                command.append("--coherence-factor")
            if common_mode_suppression_enabled:
                command.append("--common-mode-ringdown-suppression")
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.after(0, lambda: self._processing_finished(folder, result))

        threading.Thread(target=worker, daemon=True).start()

    def _processing_finished(self, folder: Path, result: subprocess.CompletedProcess[str]) -> None:
        self.processing_active = False
        self.process_button.state(["!disabled"])
        self.processing_progress.stop()
        if result.returncode != 0:
            self.processing_status_var.set("處理失敗。")
            messagebox.showerror("離線處理失敗", result.stderr[-2500:] or result.stdout[-2500:], parent=self)
            return
        self.processing_status_var.set(f"處理完成：{folder / 'analysis'}")
        self.load_existing_results()
        self.show_result_image("plane_wave_das_bmode.png")

    def load_existing_results(self) -> None:
        folder = Path(self.capture_folder_var.get()).expanduser()
        summary = read_json(folder / "analysis" / "analysis_summary.json")
        if not summary:
            self.result_summary_var.set("此採集尚未生成 analysis_summary.json。\n\n點擊「強制重新運算」。")
            self.preview_path = None
            self.preview_photo = None
            self.preview_source_var.set(f"Run: {folder.name or '—'} · 尚未生成分析結果")
            if hasattr(self, "preview_label"):
                self.preview_label.configure(image="", text="此採集尚未生成可預覽的結果。")
            return
        reflectors = summary.get("reflector_candidates", [])
        reflector_text = "\n".join(
            f"• {item.get('depth_mm', 0):.2f} mm  {item.get('classification', '')}"
            for item in reflectors
        ) or "• 未檢出穩定候選"
        duplicates = summary.get("exact_duplicate_channel_pairs", [])
        fingerprint = str(summary.get("capture_fingerprint_sha256", "legacy-no-fingerprint"))
        short_fingerprint = fingerprint[:12]
        recorded_source = Path(str(summary.get("input_directory", folder))).name
        source_matches = recorded_source.casefold() == folder.name.casefold()
        requested_frequency = summary.get(
            "requested_tx_center_frequency_mhz",
            summary.get("center_frequency_mhz", "—"),
        )
        received_frequency = summary.get(
            "received_pulse_ringdown_peak_mhz",
            summary.get("measured_echo_spectral_peak_mhz", "—"),
        )
        delayed_echo_frequency = summary.get("delayed_echo_window_peak_mhz", "—")
        fast_time_stability = summary.get("zero_degree_fast_time_stability", {})
        fast_time_stable = fast_time_stability.get("stable")
        fast_time_drift = fast_time_stability.get("maximum_axial_drift_mm", "—")
        fast_time_text = (
            "通過" if fast_time_stable is True else
            "失敗；移動白帶應視為偽影候選" if fast_time_stable is False else
            "尚未評估"
        )
        zero_cycle_count = summary.get("zero_degree_prf_cycle_count", 0)
        compound_cycle_count = summary.get("angle_compound_prf_index_count", 0)
        pattern_check = summary.get("tx_waveform_reference_check", {})
        reference_frequency = pattern_check.get("reference_base_pattern_repetition_mhz", "—")
        pattern_status = pattern_check.get("status", "未記錄pattern readback")
        physical_tr = summary.get("physical_tr_elements", summary.get("active_tx_elements", "—"))
        unique_rx = summary.get("unique_rx_waveforms_used", len(summary.get("receiver_channels_used_1_based", [])))
        configured_rx = summary.get("configured_rx_hsdc_slots_1_based", "舊結果未記錄")
        used_rx = summary.get("receiver_channels_used_1_based", [])
        dropped_slots = summary.get("dropped_duplicate_slots_1_based", [])
        excluded_slots = summary.get("excluded_rx_slots_1_based", dropped_slots)
        duplicate_policy = summary.get("duplicate_handling_policy", "舊結果未記錄")
        selected_rx_count = summary.get("selected_rx_slot_count", len(used_rx))
        source_angle_count = summary.get("source_angle_count", len(summary.get("angles_deg", [])))
        used_angle_count = summary.get("reconstruction_angle_subset_count", len(summary.get("angles_deg", [])))
        reconstruction_step = summary.get("reconstruction_angle_step_deg", None)
        apodization_summary = summary.get("receive_apodization", {})
        apodization_mode = apodization_summary.get("mode", "uniform")
        coherence_enabled = bool(summary.get("coherence_factor", {}).get("enabled", False))
        common_mode_summary = summary.get("common_mode_ringdown_suppression", {})
        common_mode_enabled = bool(common_mode_summary.get("enabled", False))
        common_mode_removed = float(
            common_mode_summary.get("mean_removed_rms_fraction_in_gate", 0.0) or 0.0
        )
        self.result_summary_var.set(
            f"資料來源：{recorded_source}\n"
            f"SHA-256：{short_fingerprint}…\n"
            f"來源核對：{'一致' if source_matches else '不一致，請重新運算'}\n\n"
            f"角度：使用 {used_angle_count}/{source_angle_count}；離線步進 {reconstruction_step or '全部'}\n"
            f"角度配置批次：{summary.get('angle_profile_programming_batch_count', summary.get('tx_profile_batch_count', 1))}\n"
            f"物理T/R陣元：{physical_tr}\n"
            f"HSDC數字槽：{summary.get('hsdc_output_slots', 16)}\n"
            f"配置接收槽（A1…AN）：{configured_rx}\n"
            f"本次DAS使用槽：{used_rx}\n"
            f"重複處理策略：{duplicate_policy}\n"
            f"接收窗：{apodization_mode}\n"
            f"Coherence factor：{'開' if coherence_enabled else '關'}\n"
            f"淺層共模抑制：{'開' if common_mode_enabled else '關'}"
            f"（門內移除RMS {common_mode_removed * 100:.1f}%）\n"
            f"選中槽/可區分波形：{selected_rx_count}/{unique_rx}\n"
            f"本次排除槽：{excluded_slots or '無'}\n"
            f"陣元間距：{summary.get('array_pitch_mm', '—')} mm\n"
            f"TX設定頻率：{requested_frequency} MHz\n"
            f"參考pattern基頻：{reference_frequency} MHz\n"
            f"接收振鈴峰（非TX讀回）：{received_frequency} MHz\n"
            f"延遲回波窗主峰：{delayed_echo_frequency} MHz\n"
            f"Pattern核對：{pattern_status}\n"
            f"快時間穩定性：{fast_time_text}；最大軸向漂移 {fast_time_drift} mm\n"
            f"PRF：約 {self._median_prf(summary):.3f} Hz\n"
            f"0°連續脈衝圖：{zero_cycle_count} 張\n"
            f"跨角度序號QA圖：{compound_cycle_count} 張\n"
            f"逐bit重複數字槽：{duplicates or '無'}\n\n"
            f"反射候選\n{reflector_text}\n\n"
            "注意：0 dB/強回波為白色，−45 dB/弱回波為黑色。接收振鈴峰不是TX7316端電壓頻率的直接量測。\n"
            "0°圖是同一BIN內連續PRF脈衝；跨角度QA圖的角度採集時間不同，不能當作心動週期影像。"
        )
        # Always resolve the preview against the currently selected run. The
        # previous implementation only did this when preview_path was None,
        # so switching capture folders could keep displaying the prior image.
        self.show_result_image(self.preview_filename)

    @staticmethod
    def _median_prf(summary: dict) -> float:
        values = sorted(
            float(item.get("prf_hz"))
            for item in summary.get("file_results", [])
            if item.get("prf_hz") is not None
        )
        if not values:
            return float("nan")
        middle = len(values) // 2
        return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0

    def show_result_image(self, filename: str) -> None:
        folder = Path(self.capture_folder_var.get()).expanduser()
        self.preview_filename = filename
        path = folder / "analysis" / filename
        if not path.exists():
            self.preview_label.configure(image="", text=f"尚未生成 {filename}")
            self.preview_photo = None
            self.preview_path = None
            self.preview_source_var.set(f"Run: {folder.name or '—'} · {filename} · missing")
            return
        self.preview_path = path
        summary = read_json(folder / "analysis" / "analysis_summary.json")
        fingerprint = str(summary.get("capture_fingerprint_sha256", "legacy-no-fingerprint"))[:12]
        generated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime))
        self.preview_source_var.set(
            f"Run: {folder.name}  ·  File: {filename}  ·  SHA-256: {fingerprint}…  ·  {generated}"
        )
        self._render_preview()

    def _show_prf_cycle(self, direction: int) -> None:
        """Step through consecutive 0-degree emissions from the selected run."""
        folder = Path(self.capture_folder_var.get()).expanduser()
        summary = read_json(folder / "analysis" / "analysis_summary.json")
        cycles = summary.get("zero_degree_prf_cycles", []) if summary else []
        if not cycles:
            messagebox.showinfo(
                "尚無逐週期結果",
                "請先重新執行離線處理；新版會在 analysis/prf_cycles/zero_degree 生成每個PRF週期的圖。",
                parent=self,
            )
            return
        self.current_prf_cycle_index = (self.current_prf_cycle_index + direction) % len(cycles)
        filename = str(cycles[self.current_prf_cycle_index].get("file", ""))
        if filename:
            self.show_result_image(filename)

    def _render_preview(self) -> None:
        if self.preview_path is None or not self.preview_path.exists():
            return
        width = max(480, self.preview_frame.winfo_width() - 30)
        height = max(360, self.preview_frame.winfo_height() - 30)
        with Image.open(self.preview_path) as source:
            image = ImageOps.contain(source.convert("RGB"), (width, height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_photo, text="")

    def _schedule_preview_resize(self) -> None:
        self.after(120, self._render_preview)

    def _browse_output_root(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_root_var.get(), parent=self)
        if selected:
            self.output_root_var.set(selected)
            self.refresh_capture_runs()

    def _browse_capture_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_root_var.get(), parent=self)
        if selected:
            self.capture_folder_var.set(selected)
            self.load_existing_results()

    def _poll_external_state(self) -> None:
        admin = is_windows_admin()
        titles = [title.lower() for title in visible_window_titles()]
        tx_open = any("tx7316" in title for title in titles)
        hsdc_open = any("high speed data converter pro" in title for title in titles)
        self.header_admin_var.set("Admin: yes" if admin else "Admin: no")
        self.header_tx_var.set("TX GUI: open" if tx_open else "TX GUI: not found")
        self.header_hsdc_var.set("HSDC: open" if hsdc_open else "HSDC: not found")
        self._set_chip_state(self.admin_chip, admin)
        self._set_chip_state(self.tx_chip, tx_open)
        self._set_chip_state(self.hsdc_chip, hsdc_open)
        self.after(3500, self._poll_external_state)

    @staticmethod
    def _set_chip_state(label: tk.Label, okay: bool) -> None:
        label.configure(
            bg=COLORS["success_soft"] if okay else COLORS["warning_soft"],
            fg=COLORS["success"] if okay else COLORS["warning"],
            highlightbackground="#CDE8DC" if okay else "#F0D49C",
        )

    def _schedule_background(self, _event: tk.Event | None = None) -> None:
        if self.background_job is not None:
            self.after_cancel(self.background_job)
        self.background_job = self.after(140, self._render_background)

    def _render_background(self) -> None:
        self.background_job = None
        width = max(900, self.winfo_width())
        height = max(650, self.winfo_height())
        scale = 0.5
        small = Image.new("RGB", (int(width * scale), int(height * scale)), COLORS["background"])
        overlay = Image.new("RGBA", small.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.ellipse((-90, -90, 360, 360), fill=(89, 160, 255, 70))
        draw.ellipse((small.width - 360, -40, small.width + 80, 350), fill=(100, 224, 226, 55))
        draw.ellipse((small.width // 3, small.height - 260, small.width // 3 + 420, small.height + 100), fill=(176, 138, 255, 36))
        overlay = overlay.filter(ImageFilter.GaussianBlur(70))
        small = Image.alpha_composite(small.convert("RGBA"), overlay).convert("RGB")
        image = small.resize((width, height), Image.Resampling.BILINEAR)
        self.background_photo = ImageTk.PhotoImage(image)
        self.background_label.configure(image=self.background_photo)

    def _serialize_settings(self) -> dict:
        return {
            "elements": self.elements_var.get(),
            "pitch_mm": self.pitch_var.get(),
            "element_width_mm": self.width_var.get(),
            "rx_hsdc_slots": self.rx_channels_var.get(),
            "duplicate_policy_label": self.duplicate_policy_var.get(),
            "manual_das_rx_slots": self.manual_das_rx_var.get(),
            "reconstruction_angle_subset_label": self.reconstruction_angle_subset_var.get(),
            "receive_apodization_label": self.receive_apodization_var.get(),
            "coherence_factor_enabled": self.coherence_factor_var.get(),
            "common_mode_ringdown_suppression_enabled": self.common_mode_suppression_var.get(),
            "center_frequency_mhz": self.frequency_var.get(),
            "sound_speed_m_s": self.sound_speed_var.get(),
            "delay_quantum_ns": self.quantum_var.get(),
            "min_angle": self.min_angle_var.get(),
            "max_angle": self.max_angle_var.get(),
            "angle_step": self.angle_step_var.get(),
            "reverse_angle_sign": self.reverse_var.get(),
            "samples": self.samples_var.get(),
            "repeats": self.repeats_var.get(),
            "settle_seconds": self.settle_var.get(),
            "trigger": self.trigger_var.get(),
            "waveform_mode": self.waveform_mode_var.get(),
            "tx_cycles": self.tx_cycles_var.get(),
            "tx_hv_a_v": self.tx_hv_a_var.get(),
            "tx_hv_b_v": self.tx_hv_b_var.get(),
            "output_root": self.output_root_var.get(),
            "auto_scan_mode": self.auto_scan_mode_var.get(),
            "auto_scan_prf_hz": self.auto_scan_prf_var.get(),
            "auto_scan_frames": self.auto_scan_frames_var.get(),
            "auto_scan_guard_prfs": self.auto_scan_guard_var.get(),
            "doppler_prf_source": self.doppler_prf_source_var.get(),
            "doppler_preset_key": (
                CAROTID_PHANTOM_PRESETS_BY_LABEL[self.doppler_preset_var.get()].key
                if self.doppler_preset_var.get() in CAROTID_PHANTOM_PRESETS_BY_LABEL
                else "carotid_phantom_raw_low_flow"
            ),
            "doppler_capture_mode_label": self.doppler_capture_mode_var.get(),
            "doppler_prf_hz": self.doppler_prf_var.get(),
            "doppler_steering_angle_deg": self.doppler_steering_var.get(),
            "doppler_flow_angle_deg": self.doppler_flow_angle_var.get(),
            "doppler_target_depth_mm": self.doppler_depth_var.get(),
            "doppler_gate_length_mm": self.doppler_gate_length_var.get(),
            "doppler_expected_velocity_m_s": self.doppler_velocity_var.get(),
            "doppler_duration_s": self.doppler_duration_var.get(),
            "doppler_ensemble_pulses": self.doppler_ensemble_var.get(),
            "doppler_wall_filter_hz": self.doppler_wall_filter_var.get(),
            "doppler_expected_heart_rate_bpm": self.doppler_heart_rate_var.get(),
            "doppler_block_samples": self.doppler_samples_var.get(),
            "doppler_repeats": self.doppler_repeats_var.get(),
            "doppler_trigger": self.doppler_trigger_var.get(),
            "cw_backend_label": self.cw_backend_var.get(),
            "cw_center_frequency_mhz": self.cw_frequency_var.get(),
            "cw_tx_supply_v": self.cw_tx_supply_var.get(),
            "cw_tx_test_seconds": self.cw_tx_test_seconds_var.get(),
            "cw_adc_rate_msps": self.cw_adc_rate_var.get(),
            "cw_iq_output_rate_msps": self.cw_iq_rate_var.get(),
            "cw_decimation": self.cw_decimation_var.get(),
            "cw_duration_s": self.cw_duration_var.get(),
            "cw_analysis_rate_ksps": self.cw_analysis_rate_var.get(),
            "cw_lowpass_khz": self.cw_lowpass_var.get(),
            "cw_wall_filter_hz": self.cw_wall_filter_var.get(),
            "cw_stft_samples": self.cw_stft_samples_var.get(),
            "cw_stft_overlap": self.cw_stft_overlap_var.get(),
            "cw_row_angles_deg": [variable.get() for variable in self.cw_row_angle_vars],
            "cw_afe_rx_slots": [variable.get() for variable in self.cw_row_rx_slot_vars],
            "cw_row_doppler_hz": [variable.get() for variable in self.cw_row_doppler_vars],
            **serialize_cw_capture_state(self),
        }

    def _on_close(self) -> None:
        try:
            CONFIG_PATH.write_text(json.dumps(self._serialize_settings(), indent=2), encoding="utf-8")
        except OSError:
            pass
        self.destroy()


def self_test() -> int:
    config = ArrayConfig()
    angles = build_angle_list(-10.0, 10.0, 2.0)
    profiles = calculate_profiles(angles, config)
    if len(profiles) != 11 or profiles[5].counts_a1_to_a8 != (0,) * 8:
        raise RuntimeError("delay-model self-test failed")
    fine_angles = build_angle_list(-10.0, 10.0, 1.0)
    fine_profiles = calculate_profiles(fine_angles, config)
    if len(fine_profiles) != 21 or math.ceil(len(fine_profiles) / HARDWARE_DELAY_PROFILES_PER_BATCH) != 2:
        raise RuntimeError("1-degree batched sweep self-test failed")
    rapid_plan = build_rapid_scan_plan(
        RapidScanConfig(angles_deg=tuple(fine_angles), prf_hz=1000.0, frames=1, guard_prfs=1)
    )
    if rapid_plan.bank_count != 2 or rapid_plan.banks[0].samples_per_channel != 2_043_904:
        raise RuntimeError("rapid-scan timing self-test failed")
    stock_cpld_samples = contiguous_prf_block_samples(1000.0, 32)
    if stock_cpld_samples != 3_837_952:
        raise RuntimeError("stock-CPLD 32-PRF block self-test failed")
    doppler = calculate_doppler(DopplerConfig())
    if not 170.0 < doppler.pulses_per_raw_block < 180.0:
        raise RuntimeError("PW Doppler timing self-test failed")
    cw_doppler = calculate_cw_doppler(CwDopplerConfig())
    if cw_doppler.nco_word != 0x0889 or abs(cw_doppler.iq_output_rate_hz - 15_000_000.0) > 1.0:
        raise RuntimeError("CW Doppler model self-test failed")
    missing = [path for path in (AUTOMATION_SCRIPT, RECONSTRUCTION_SCRIPT, CW_DOPPLER_STAGE_SCRIPT, CW_TX_CONTROL_SCRIPT, PYTHON27) if not path.exists()]
    print("HKUST Ultrosound collector platform self-test")
    print(f"delay profiles: {len(profiles)}")
    print(f"1-degree sweep: {len(fine_profiles)} angles / 2 hardware batches")
    print(
        f"rapid-scan plan: {rapid_plan.angle_count} angles / {rapid_plan.bank_count} BIN / "
        f"{rapid_plan.captured_time_ms:.3f} ms"
    )
    print(
        f"stock-CPLD block: 11 angles / 32 PRF per BIN / "
        f"{stock_cpld_samples:,} samples per channel"
    )
    print(f"PW Doppler default block: {doppler.block_duration_ms:.2f} ms / {doppler.pulses_per_raw_block:.1f} pulses")
    print(f"CW Doppler default: NCO=0x{cw_doppler.nco_word:04X} / I/Q={cw_doppler.iq_output_rate_hz / 1e6:.1f} MSPS")
    print(f"automation script: {AUTOMATION_SCRIPT}")
    print(f"reconstruction script: {RECONSTRUCTION_SCRIPT}")
    print(f"Python 2.7: {PYTHON27}")
    if missing:
        print("MISSING:", *missing, sep="\n  ")
        return 1
    print("SELF-TEST PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="HKUST Ultrosound collector platform desktop UI")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--start-page",
        choices=["array", "capture", "auto_scan", "doppler", "cw_doppler", "processing"],
        default="array",
        help="page displayed when the desktop UI opens",
    )
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    enable_high_dpi()
    app = CollectorApp(start_page=args.start_page)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
