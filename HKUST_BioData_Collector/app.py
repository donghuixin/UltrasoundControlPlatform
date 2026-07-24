"""HKUST Bio-data collector desktop UI.

This application provides a safe front end for the existing TX7316/HSDC Pro
automation and offline reconstruction scripts. It never changes high-voltage
rails, TX pattern voltage levels, PRF, pulse count, or AFE gain.
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

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageTk

from delay_model import (
    ArrayConfig,
    HARDWARE_DELAY_PROFILES_PER_BATCH,
    build_angle_list,
    calculate_profiles,
    format_angles_cli,
)
from doppler_model import DopplerConfig, DopplerResult, calculate_doppler, result_as_dict
from rapid_scan_model import (
    RapidScanConfig,
    build_rapid_scan_plan,
    contiguous_prf_block_samples,
    plan_as_dict,
)


APP_DIR = Path(__file__).resolve().parent
CAPTURE_ROOT = APP_DIR.parent
AUTOMATION_SCRIPT = CAPTURE_ROOT / "automation" / "tx7316_hsdc_batch_capture.py"
RECONSTRUCTION_SCRIPT = CAPTURE_ROOT / "reconstruct_ultrasound.py"
DEFAULT_AUTO_RUNS = CAPTURE_ROOT / "auto_runs"
PYTHON27 = Path(r"C:\Python27\python.exe")
CONFIG_PATH = APP_DIR / "collector_config.json"
DOPPLER_GUIDE = APP_DIR / "PW_DOPPLER_OPERATION_GUIDE.md"
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
        self.title("HKUST Bio-data collector")
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
        self.capture_watch: dict | None = None
        self.pages: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, ttk.Button] = {}

        self._configure_styles()
        self._create_variables()
        self._build_shell()
        self._build_array_page()
        self._build_capture_page()
        self._build_auto_scan_page()
        self._build_doppler_page()
        self._build_processing_page()
        self.show_page(start_page if start_page in self.pages else "array")
        self.recalculate_delays(show_errors=False)
        self.recalculate_auto_scan(show_errors=False)
        self.recalculate_doppler(show_errors=False)
        self.refresh_capture_runs()
        self._poll_external_state()

        self.bind("<Alt-Key-1>", lambda _event: self.show_page("array"))
        self.bind("<Alt-Key-2>", lambda _event: self.show_page("capture"))
        self.bind("<Alt-Key-3>", lambda _event: self.show_page("auto_scan"))
        self.bind("<Alt-Key-4>", lambda _event: self.show_page("doppler"))
        self.bind("<Alt-Key-5>", lambda _event: self.show_page("processing"))
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
            value=str(get("rx_hsdc_slots", "9,10,11,12,13,14,15,16"))
        )
        self.frequency_var = tk.StringVar(value=str(get("center_frequency_mhz", 2.5)))
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
            value=str(get("manual_das_rx_slots", "9,10,11,12,13,14"))
        )
        self.reconstruction_angle_subset_var = tk.StringVar(
            value=str(get("reconstruction_angle_subset_label", "使用全部已採集角度"))
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
        self.doppler_prf_var = tk.StringVar(value=str(get("doppler_prf_hz", 1000.0)))
        self.doppler_steering_var = tk.StringVar(value=str(get("doppler_steering_angle_deg", 0.0)))
        self.doppler_flow_angle_var = tk.StringVar(value=str(get("doppler_flow_angle_deg", 60.0)))
        self.doppler_depth_var = tk.StringVar(value=str(get("doppler_target_depth_mm", 25.0)))
        self.doppler_velocity_var = tk.StringVar(value=str(get("doppler_expected_velocity_m_s", 1.0)))
        self.doppler_duration_var = tk.StringVar(value=str(get("doppler_duration_s", 6.0)))
        self.doppler_ensemble_var = tk.StringVar(value=str(get("doppler_ensemble_pulses", 256)))
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
        tk.Label(title_stack, text="HKUST Bio-data collector", bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI Semibold", 19)).pack(anchor="w")
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

    def _build_array_page(self) -> None:
        page = self._new_page("array")
        self._page_heading(page, "陣列幾何與角度延時", "輸入實際陣元參數；計算值會與正式 Python 2.7 採集腳本使用同一套公式。")

        top_row = tk.Frame(page, bg=COLORS["background"])
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

        summary_card = self._card(page)
        summary_card._shadow_wrapper.pack(fill="x", pady=(0, 12))  # type: ignore[attr-defined]
        summary_line = tk.Frame(summary_card, bg=COLORS["surface"])
        summary_line.pack(fill="x", padx=18, pady=13)
        ttk.Label(summary_line, text="Array check", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(summary_line, textvariable=self.array_summary_var, style="Metric.TLabel").pack(side="left", padx=(18, 0))
        self.array_warning_label = tk.Label(summary_line, textvariable=self.array_warning_var, bg=COLORS["surface"], fg=COLORS["warning"], font=("Segoe UI Semibold", 9))
        self.array_warning_label.pack(side="right")

        table_card = self._card(page)
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
        tk.Label(prereq_card, text="UI 不會修改 TX 高壓或 AFE 增益。", bg=COLORS["warning_soft"], fg=COLORS["warning"], padx=10, pady=7, font=("Segoe UI Semibold", 9)).pack(fill="x", padx=18, pady=(8, 16))

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
            "把PRF、深度、速度Nyquist與存儲量放在同一頁；目前可執行固定角度短塊採集，連續心動週期需要I/Q抽取或FPGA距離門。",
        )

        body = tk.Frame(page, bg=COLORS["background"])
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(2, weight=1)

        settings_card = self._card(body)
        settings_card._shadow_wrapper.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))  # type: ignore[attr-defined]
        header = tk.Frame(settings_card, bg=COLORS["surface"])
        header.pack(fill="x", padx=18, pady=(15, 10))
        ttk.Label(header, text="Acquisition & flow model", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(header, text="載入 1 MHz / 5 kHz 建議值", style="Secondary.TButton", command=self._load_doppler_preset).pack(side="right")

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
        doppler_entries.append(self._labeled_entry(row2, "Block samples/ch", self.doppler_samples_var))

        row3 = tk.Frame(settings_card, bg=COLORS["surface"])
        row3.pack(fill="x", padx=18, pady=(0, 15))
        doppler_entries.append(self._labeled_entry(row3, "Block repeats", self.doppler_repeats_var))
        tk.Label(
            row3,
            text="ADC/JESD stays at 120 MSPS. PRF is a physical trigger rate and is not programmed by this UI.",
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
        ttk.Label(current, text="NOW · validated short-block path", style="CardTitle.TLabel").pack(anchor="w")
        tk.Label(
            current,
            text="TX固定角度 → AFE 120 MSPS原始RF → TSW DDR → 單個BIN。每個BIN內連續；BIN之間因保存與重新Capture存在長缺口。",
            bg=COLORS["surface"], fg=COLORS["muted"], justify="left", anchor="w", wraplength=530, font=("Segoe UI", 9),
        ).pack(fill="x", pady=(5, 0))
        ttk.Label(future, text="NEXT · gap-free cardiac path", style="CardTitle.TLabel").pack(anchor="w")
        tk.Label(
            future,
            text="共同PRF時鐘 → AFE數字下變頻/抽取或FPGA距離門 → 每脈衝一個複數I/Q樣點 → 5–10秒慢時間流。HSDC capture-to-file streaming仍保留為實驗接口。",
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
        ttk.Checkbutton(checks, text="理解多個BIN不構成連續心動資料", variable=self.doppler_gap_ack_var).pack(anchor="w")
        tk.Label(launch_card, textvariable=self.doppler_status_var, bg=COLORS["surface"], fg=COLORS["text"], anchor="w", font=("Segoe UI Semibold", 10)).grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 0))
        tk.Label(
            launch_card,
            textvariable=self.doppler_command_var,
            bg="#F3F7FC", fg="#38516C", justify="left", anchor="nw", padx=12, pady=9,
            wraplength=1000, font=("Cascadia Mono", 9), highlightbackground=COLORS["border"], highlightthickness=1,
        ).grid(row=3, column=0, sticky="nsew", padx=18, pady=8)
        actions = tk.Frame(launch_card, bg=COLORS["surface"])
        actions.grid(row=4, column=0, sticky="e", padx=18, pady=(0, 14))
        ttk.Button(actions, text="打開完整操作文檔", style="Secondary.TButton", command=self._open_doppler_guide).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="導出Session Plan", style="Secondary.TButton", command=self.export_doppler_plan).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Doppler dry run", style="Secondary.TButton", command=lambda: self.launch_doppler_capture(True)).pack(side="left", padx=(0, 8))
        self.doppler_capture_button = ttk.Button(actions, text="開始固定角度短塊採集", style="Danger.TButton", command=lambda: self.launch_doppler_capture(False))
        self.doppler_capture_button.pack(side="left")

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
        self.process_button = ttk.Button(controls, text="強制重新運算", style="Primary.TButton", command=self.start_processing)
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

    def _current_rx_slots(self) -> list[int]:
        text = self.rx_channels_var.get().strip()
        try:
            slots = [int(token.strip()) for token in text.split(",") if token.strip()]
        except ValueError as exc:
            raise ValueError("HSDC接收槽必須是逗號分隔的整數，例如 9,10,11,12,13,14,15,16。") from exc
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
        self.processing_option_help_var.set(f"{duplicate_text}  {angle_text}")

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
                title="HKUST Bio-data Collector - Stock CPLD synchronized block scan",
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
                title="HKUST Bio-data Collector - Verified angle scan",
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

    def _load_doppler_preset(self) -> None:
        self.frequency_var.set("1.0")
        self.doppler_prf_source_var.set("External synchronized source - manual wiring")
        self.doppler_prf_var.set("5000")
        self.doppler_steering_var.set("0")
        self.doppler_flow_angle_var.set("60")
        self.doppler_depth_var.set("25")
        self.doppler_velocity_var.set("1.0")
        self.doppler_duration_var.set("6")
        self.doppler_ensemble_var.set("256")
        self.doppler_samples_var.set("4194304")
        self.doppler_repeats_var.set("1")
        self.doppler_trigger_var.set("hardware")
        self.recalculate_delays(show_errors=False)
        self.recalculate_doppler(show_errors=False)

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
            adc_rate_msps=120.0,
            block_samples_per_channel=int(self.doppler_samples_var.get()),
            rx_channels=RX_CHANNELS_IN_CAPTURE_FILE,
            bytes_per_adc_sample=BYTES_PER_ADC_SAMPLE,
            sound_speed_m_s=float(self.sound_speed_var.get()),
        )

    @staticmethod
    def _localize_doppler_warning(warning: str) -> str:
        translations = {
            "Target depth uses more than 80%": "目標深度已使用超過80%的無模糊量程，請降低PRF或增加餘量。",
            "Expected velocity is close": "預期速度接近Nyquist上限，請提高PRF或降低發射頻率。",
            "One raw HSDC block": "單個HSDC原始塊的脈衝數少於所選FFT ensemble。",
            "The desired cardiac duration": "期望心動時長超過單個原始塊；多次Capture之間存在缺口。",
            "Gap-free full-duration raw RF": "全時長原始RF超過1 GiB；應改用AFE I/Q抽取或FPGA距離門。",
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
            f"Minimum PRF     {result.minimum_prf_for_expected_velocity_hz:8.0f} Hz"
        )
        self.doppler_storage_var.set(
            f"One raw block    {result.block_duration_ms:7.2f} ms / {result.pulses_per_raw_block:.1f} pulses\n"
            f"One BIN          {result.raw_block_gib:7.3f} GiB\n"
            f"{config.desired_duration_s:g}s raw RF      {result.full_duration_raw_gib:7.2f} GiB\n"
            f"Range-gated I/Q  {result.range_gated_iq_mib:7.2f} MiB\n"
            f"FFT window       {result.ensemble_duration_ms:7.2f} ms / {result.velocity_bin_m_s:.4f} m/s bin"
        )
        warnings = [self._localize_doppler_warning(item) for item in result.warnings]
        if self.doppler_prf_source_var.get().startswith("Onboard CPLD"):
            warnings.insert(0, "板載CPLD的PRF固定為1 kHz；GUI數值不能改變硬件PRF。")
        else:
            warnings.insert(0, "外部PRF需要隔離板載CPLD驅動並同步TX、AFE與TSW；J7 pin 2只是觀測輸出。")
        self.doppler_warning_var.set("\n".join(f"• {item}" for item in warnings))

        try:
            arguments = self._capture_arguments(
                array_config,
                [config.steering_angle_deg],
                dry_run=False,
                samples=config.block_samples_per_channel,
                repeats=repeats,
                settle=0.25,
                trigger=self.doppler_trigger_var.get(),
            )
            self.doppler_command_var.set(
                subprocess.list2cmdline([str(PYTHON27), str(AUTOMATION_SCRIPT), *arguments])
            )
        except ValueError:
            pass
        return config, result

    def _doppler_plan(self) -> dict:
        calculated = self.recalculate_doppler(show_errors=True)
        if calculated is None:
            raise ValueError("PW Doppler parameters are invalid.")
        config, result = calculated
        plan = result_as_dict(config, result)
        plan["prf_source"] = self.doppler_prf_source_var.get()
        plan["hsdc_trigger"] = self.doppler_trigger_var.get()
        plan["block_repeats"] = int(self.doppler_repeats_var.get())
        plan["prf_programmed_by_ui"] = False
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

    def launch_doppler_capture(self, dry_run: bool) -> None:
        calculated = self.recalculate_doppler(show_errors=True)
        if calculated is None:
            return
        doppler_config, _result = calculated
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
            confirmations = (
                self.doppler_phantom_confirmed_var.get(),
                self.doppler_sync_confirmed_var.get(),
                self.doppler_gap_ack_var.get(),
            )
            if not all(confirmations):
                messagebox.showwarning("尚未完成Doppler Pre-flight", "請勾選三項Doppler採集確認。", parent=self)
                return
            proceed = messagebox.askyesno(
                "啟動固定角度PW Doppler短塊採集",
                f"PRF={doppler_config.prf_hz:g} Hz只是已驗證硬件條件的記錄，程式本身不會修改CPLD PRF。\n\n"
                f"本次保存 {repeats} 個短塊；每個BIN內連續，但BIN之間有長缺口，不能拼成心動波形。繼續嗎？",
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
            title="HKUST Bio-data Collector - PW Doppler short block",
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
        except (ValueError, OSError):
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

        try:
            if dry_run or is_windows_admin():
                subprocess.Popen(
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
        }
        self.after(1500, self._poll_capture_manifest)

    def launch_capture(
        self,
        dry_run: bool,
        status_var: tk.StringVar | None = None,
        progress: ttk.Progressbar | None = None,
        button: ttk.Button | None = None,
        title: str = "HKUST Bio-data Collector - Acquisition",
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
            if trigger == "hardware":
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
                "程式將控制已開啟的 TX7316 GUI 並觸發 HSDC Capture。\n\n確認 CW 已關閉，而且本次只測凝膠／仿體？",
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
            manifest = read_json(run / "capture_manifest.json")
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
            ]
            if manual_das_slots is not None:
                command.extend(
                    ["--das-rx-channels", ",".join(str(slot) for slot in manual_das_slots)]
                )
            if angle_subset_step is not None:
                command.extend(
                    ["--reconstruction-angle-step-deg", f"{angle_subset_step:g}"]
                )
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
            "output_root": self.output_root_var.get(),
            "auto_scan_mode": self.auto_scan_mode_var.get(),
            "auto_scan_prf_hz": self.auto_scan_prf_var.get(),
            "auto_scan_frames": self.auto_scan_frames_var.get(),
            "auto_scan_guard_prfs": self.auto_scan_guard_var.get(),
            "doppler_prf_source": self.doppler_prf_source_var.get(),
            "doppler_prf_hz": self.doppler_prf_var.get(),
            "doppler_steering_angle_deg": self.doppler_steering_var.get(),
            "doppler_flow_angle_deg": self.doppler_flow_angle_var.get(),
            "doppler_target_depth_mm": self.doppler_depth_var.get(),
            "doppler_expected_velocity_m_s": self.doppler_velocity_var.get(),
            "doppler_duration_s": self.doppler_duration_var.get(),
            "doppler_ensemble_pulses": self.doppler_ensemble_var.get(),
            "doppler_block_samples": self.doppler_samples_var.get(),
            "doppler_repeats": self.doppler_repeats_var.get(),
            "doppler_trigger": self.doppler_trigger_var.get(),
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
    missing = [path for path in (AUTOMATION_SCRIPT, RECONSTRUCTION_SCRIPT, PYTHON27) if not path.exists()]
    print("HKUST Bio-data collector self-test")
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
    print(f"automation script: {AUTOMATION_SCRIPT}")
    print(f"reconstruction script: {RECONSTRUCTION_SCRIPT}")
    print(f"Python 2.7: {PYTHON27}")
    if missing:
        print("MISSING:", *missing, sep="\n  ")
        return 1
    print("SELF-TEST PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="HKUST Bio-data collector desktop UI")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--start-page",
        choices=["array", "capture", "auto_scan", "doppler", "processing"],
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
