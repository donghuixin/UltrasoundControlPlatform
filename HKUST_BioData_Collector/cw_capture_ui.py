"""CW digital-I/Q DDR capture panel shared by the desktop collector."""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk


HSDC_IQ_DEVICE = "AFE58JD48_Custom_PLL_MODE_40x_Demod_SubClass1"
PROFILE_SHA256 = "F961A88CA549C6300309E710A843D1073ED0B6374798F442AC8154C07962D372"
WORDS_PER_IQ_FRAME = 16
DDR_BYTES = 512 * 1024 * 1024
SOURCE_PROFILE = Path(
    r"E:\Users\dxhui\Desktop\TI_AFE58jd48\ADS58JD48_TSW14J50_Transition"
    r"\AFE58JD48_TSW14J50 transition\TSW14J50_TSW14J50RX_FIRMWARE"
) / f"{HSDC_IQ_DEVICE}.ini"
AFE_D4_CFG = Path(
    r"E:\Users\dxhui\Desktop\TI_AFE58jd48\ADS58JD48_TSW14J50_Transition"
    r"\AFE58JD48_TSW14J50 transition\JESD 60MSPS_Subclass1_4L_Decimation=4_DownConvEn.cfg"
)
HSDC_ADC_DIRS = (
    Path(r"E:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files"),
    Path(r"C:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files"),
)


def init_cw_capture_state(app, get, app_dir: Path, capture_root: Path, python27: Path) -> None:
    app._cw_app_dir = Path(app_dir)
    app._cw_capture_root = Path(capture_root)
    app._cw_python27 = Path(python27)
    app.cw_capture_output_var = tk.StringVar(
        value=str(get("cw_capture_output_root", Path(app.output_root_var.get()) / "cw_iq"))
    )
    app.cw_capture_trigger_var = tk.StringVar(value=str(get("cw_capture_trigger", "normal")))
    app.cw_capture_profile_confirmed_var = tk.BooleanVar(value=False)
    app.cw_capture_reuse_hsdc_var = tk.BooleanVar(value=False)
    app.cw_capture_status_var = tk.StringVar(value="尚未啟動 I/Q DDR 採集。")
    app.cw_capture_detail_var = tk.StringVar(value="完成後會顯示 BIN 大小、時長、I/Q 通道與基帶頻譜。")
    app.cw_capture_profile_var = tk.StringVar(value="正在檢查 HSDC I/Q profile…")
    app.cw_capture_watch = None
    app.cw_capture_photo = None
    app.cw_capture_last_run = None
    refresh_profile_status(app)


def serialize_cw_capture_state(app) -> dict:
    return {
        "cw_capture_output_root": app.cw_capture_output_var.get(),
        "cw_capture_trigger": app.cw_capture_trigger_var.get(),
    }


def installed_profile_path() -> Path | None:
    for directory in HSDC_ADC_DIRS:
        candidate = directory / SOURCE_PROFILE.name
        if candidate.is_file():
            return candidate
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def refresh_profile_status(app) -> None:
    installed = installed_profile_path()
    if installed:
        if _sha256(installed) == PROFILE_SHA256:
            app.cw_capture_profile_var.set(f"READY · TI HSDC profile SHA-256 已核對：{installed}")
        else:
            app.cw_capture_profile_var.set(f"BLOCKED · 同名 HSDC profile 雜湊不符：{installed}")
    elif SOURCE_PROFILE.is_file():
        app.cw_capture_profile_var.set("BLOCKED · TI Demod profile 尚未複製到 HSDC ADC files")
    else:
        app.cw_capture_profile_var.set("BLOCKED · 找不到 TI Demod profile 來源檔")


def install_hsdc_profile(app) -> None:
    if not SOURCE_PROFILE.is_file():
        messagebox.showerror("找不到來源 profile", str(SOURCE_PROFILE), parent=app)
        return
    destination_dir = next((path for path in HSDC_ADC_DIRS if path.is_dir()), None)
    if destination_dir is None:
        messagebox.showerror("找不到 HSDC 安裝目錄", "\n".join(map(str, HSDC_ADC_DIRS)), parent=app)
        return
    destination = destination_dir / SOURCE_PROFILE.name
    if not messagebox.askyesno(
        "安裝 HSDC I/Q profile",
        f"將 TI 提供的檔案複製到：\n{destination}\n\n"
        "這只安裝 HSDC 解包描述，不會改寫已驗證的 No-Demod profile，也不會寫 AFE 寄存器。繼續嗎？",
        parent=app,
        icon="warning",
    ):
        return
    try:
        shutil.copy2(SOURCE_PROFILE, destination)
    except OSError as exc:
        messagebox.showerror("profile 安裝失敗", f"請以管理員執行平台。\n\n{exc}", parent=app)
        return
    refresh_profile_status(app)
    messagebox.showinfo("profile 已安裝", "請重新啟動 HSDC Pro，然後選擇 Demod profile。", parent=app)


def _capture_geometry(app) -> tuple[float, int, float, int]:
    rate_hz = float(app.cw_iq_rate_var.get()) * 1e6
    requested_s = float(app.cw_duration_var.get())
    if rate_hz <= 0 or requested_s <= 0:
        raise ValueError("I/Q 率與採集時長必須大於 0。")
    max_frames = DDR_BYTES // (WORDS_PER_IQ_FRAME * 2)
    requested_frames = int(math.floor(rate_hz * requested_s))
    frames = min(requested_frames, max_frames)
    frames -= frames % 4096
    if frames < 4096:
        raise ValueError("採集時長太短；至少需要 4096 個 I/Q samples。")
    actual_s = frames / rate_hz
    expected_bytes = frames * WORDS_PER_IQ_FRAME * 2
    return rate_hz, frames, actual_s, expected_bytes


def update_capture_estimate(app) -> None:
    try:
        rate_hz, frames, actual_s, expected_bytes = _capture_geometry(app)
        requested_s = float(app.cw_duration_var.get())
        clipped = actual_s + 1e-9 < requested_s
        app.cw_capture_detail_var.set(
            f"本次 DDR：{frames:,} samples/word · {expected_bytes / 1048576:.1f} MiB · "
            f"連續 {actual_s:.3f} s" + ("（已按 512 MiB 上限截短）" if clipped else "")
        )
    except ValueError as exc:
        app.cw_capture_detail_var.set(f"參數錯誤：{exc}")


def _browse_output(app) -> None:
    selected = filedialog.askdirectory(initialdir=app.cw_capture_output_var.get(), parent=app)
    if selected:
        app.cw_capture_output_var.set(selected)


def _open_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(path)  # type: ignore[attr-defined]


def _open_afe_cfg(app) -> None:
    if not AFE_D4_CFG.is_file():
        messagebox.showerror("找不到 AFE DDC 配置", str(AFE_D4_CFG), parent=app)
        return
    os.startfile(AFE_D4_CFG.parent)  # type: ignore[attr-defined]


def build_cw_capture_panel(app, body, row: int = 4) -> None:
    card = app._card(body)
    card._shadow_wrapper.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=(12, 20))  # type: ignore[attr-defined]
    header = tk.Frame(card, bg=app.COLORS["surface"] if hasattr(app, "COLORS") else "#FFFFFF")
    # app.COLORS is not an instance member in older deployments.
    surface = "#FFFFFF"
    muted = "#60738A"
    text = "#10233F"
    border = "#DDE7F2"
    soft = "#F8FAFD"
    header.configure(bg=surface)
    header.pack(fill="x", padx=18, pady=(14, 8))
    ttk.Label(header, text="DDR I/Q capture & preview", style="CardTitle.TLabel").pack(side="left")
    app.cw_capture_progress = ttk.Progressbar(header, mode="indeterminate", length=180)
    app.cw_capture_progress.pack(side="right")

    profile = tk.Frame(card, bg=soft, highlightbackground=border, highlightthickness=1)
    profile.pack(fill="x", padx=18, pady=(0, 10))
    tk.Label(profile, textvariable=app.cw_capture_profile_var, bg=soft, fg=text, anchor="w", padx=10, pady=8,
             font=("Segoe UI Semibold", 9)).pack(side="left", fill="x", expand=True)
    ttk.Button(profile, text="安裝 HSDC I/Q profile", style="Secondary.TButton",
               command=lambda: install_hsdc_profile(app)).pack(side="right", padx=6, pady=5)
    ttk.Button(profile, text="打開 AFE DDC CFG", style="Secondary.TButton",
               command=lambda: _open_afe_cfg(app)).pack(side="right", padx=6, pady=5)

    output = tk.Frame(card, bg=surface)
    output.pack(fill="x", padx=18, pady=(0, 10))
    left = tk.Frame(output, bg=surface)
    left.pack(side="left", fill="x", expand=True, padx=(0, 10))
    tk.Label(left, text="I/Q 輸出根目錄", bg=surface, fg=muted, font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
    ttk.Entry(left, textvariable=app.cw_capture_output_var).pack(fill="x")
    ttk.Button(output, text="選擇目錄", style="Secondary.TButton", command=lambda: _browse_output(app)).pack(side="left", pady=(20, 0))
    trigger = tk.Frame(output, bg=surface)
    trigger.pack(side="left", padx=(10, 0))
    tk.Label(trigger, text="HSDC trigger", bg=surface, fg=muted, font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 5))
    ttk.Combobox(trigger, textvariable=app.cw_capture_trigger_var, values=("normal", "software"),
                 state="readonly", width=12).pack(fill="x")

    confirmations = tk.Frame(card, bg=surface)
    confirmations.pack(fill="x", padx=18, pady=(0, 8))
    ttk.Checkbutton(
        confirmations,
        text="AFE GUI 已載入與所選 D 值相符的 DownConv 配置；HSDC 已顯示 Demod profile 且 I/Q mapping 已核對",
        variable=app.cw_capture_profile_confirmed_var,
    ).pack(anchor="w")
    ttk.Checkbutton(
        confirmations,
        text="沿用目前 HSDC 選擇（不重新 Connect/Select profile；僅在手動 Capture 已成功時使用）",
        variable=app.cw_capture_reuse_hsdc_var,
    ).pack(anchor="w")

    tk.Label(card, textvariable=app.cw_capture_detail_var, bg=soft, fg=text, anchor="w", padx=10, pady=8,
             font=("Cascadia Mono", 9), highlightbackground=border, highlightthickness=1).pack(fill="x", padx=18)
    app.cw_iq_rate_var.trace_add("write", lambda *_args: update_capture_estimate(app))
    app.cw_duration_var.trace_add("write", lambda *_args: update_capture_estimate(app))

    actions = tk.Frame(card, bg=surface)
    actions.pack(fill="x", padx=18, pady=10)
    ttk.Button(actions, text="Dry run", style="Secondary.TButton",
               command=lambda: launch_cw_iq_capture(app, True)).pack(side="left")
    app.cw_capture_button = ttk.Button(actions, text="開始 DDR I/Q 採集", style="Danger.TButton",
                                       command=lambda: launch_cw_iq_capture(app, False))
    app.cw_capture_button.pack(side="left", padx=(8, 0))
    ttk.Button(actions, text="打開輸出目錄", style="Secondary.TButton",
               command=lambda: _open_path(Path(app.cw_capture_output_var.get()))).pack(side="left", padx=(8, 0))
    tk.Label(actions, textvariable=app.cw_capture_status_var, bg=surface, fg=text,
             anchor="e", font=("Segoe UI Semibold", 9)).pack(side="right", fill="x", expand=True)

    preview = tk.Frame(card, bg=soft, highlightbackground=border, highlightthickness=1)
    preview.pack(fill="both", expand=True, padx=18, pady=(0, 16))
    app.cw_capture_preview_label = tk.Label(
        preview,
        text="尚未有 I/Q 資料。採集完成後在此顯示 CH1–CH3 複數幅度與 ±100 kHz 基帶頻譜。",
        bg=soft,
        fg=muted,
        padx=12,
        pady=18,
    )
    app.cw_capture_preview_label.pack(fill="both", expand=True)
    update_capture_estimate(app)


def launch_cw_iq_capture(app, dry_run: bool) -> None:
    if app.cw_capture_watch is not None or getattr(app, "capture_watch", None) is not None:
        messagebox.showwarning("已有採集任務", "請等待目前採集完成。", parent=app)
        return
    try:
        rate_hz, frames, actual_s, expected_bytes = _capture_geometry(app)
    except ValueError as exc:
        messagebox.showerror("I/Q 採集參數錯誤", str(exc), parent=app)
        return
    capture_script = app._cw_capture_root / "automation" / "hsdc_iq_capture.py"
    python27 = app._cw_python27
    if not capture_script.is_file() or not python27.is_file():
        messagebox.showerror("採集環境缺失", f"找不到：\n{python27}\n或\n{capture_script}", parent=app)
        return
    if not dry_run:
        installed = installed_profile_path()
        if installed is None or _sha256(installed) != PROFILE_SHA256:
            messagebox.showwarning("HSDC I/Q profile 未就緒", "請先安裝並核對 TI Demod profile。", parent=app)
            return
        if not app.cw_capture_profile_confirmed_var.get():
            messagebox.showwarning("尚未確認 I/Q 鏈路", "請先載入匹配的 AFE DDC 配置與 HSDC Demod profile，再勾選確認。", parent=app)
            return
        if not all((app.cw_phantom_confirmed_var.get(), app.cw_thermal_confirmed_var.get(), app.cw_path_confirmed_var.get())):
            messagebox.showwarning("尚未完成 CW 安全確認", "請先完成上方仿體、限流／溫升與資料路徑確認。", parent=app)
            return
        d_value = int(app.cw_decimation_var.get())
        warning = (
            f"將擷取一個連續 DDR I/Q 塊：\n\n"
            f"I/Q rate: {rate_hz / 1e6:g} MSPS\nAFE hardware decimation D: {d_value}\n"
            f"實際時長: {actual_s:.3f} s\nBIN: {expected_bytes / 1048576:.1f} MiB\n\n"
        )
        if d_value != 4:
            warning += "TI 套件只直接提供 D=4/15 MSPS CFG；你已確認目前 AFE GUI 載入的是相符 D 值的配置。\n\n"
        warning += "採集只讀取目前 AFE/JESD 輸出，不會自動啟動 TX。繼續嗎？"
        if not messagebox.askyesno("開始 I/Q DDR 採集", warning, parent=app, icon="warning"):
            return

    output_root = Path(app.cw_capture_output_var.get()).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in output_root.glob("cw_capture_*")}
    arguments = [
        "--dry-run" if dry_run else "--capture",
        "--output-root", str(output_root),
        "--output-rate-hz", f"{rate_hz:.9g}",
        "--samples", str(frames),
        "--device", HSDC_IQ_DEVICE,
        "--trigger", app.cw_capture_trigger_var.get(),
    ]
    if app.cw_capture_reuse_hsdc_var.get():
        arguments.append("--reuse-current-hsdc")
    command = [str(python27), str(capture_script), *arguments]
    command_line = subprocess.list2cmdline(command)
    console = f'title HKUST CW I-Q Capture & {command_line} & pause'
    try:
        if dry_run or _is_admin():
            process = subprocess.Popen(["cmd.exe", "/c", console], cwd=str(app._cw_app_dir),
                                       creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        else:
            parameters = subprocess.list2cmdline(["/c", console])
            result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", parameters, str(app._cw_app_dir), 1)
            if result <= 32:
                raise OSError(f"UAC launch failed: {result}")
            process = None
    except OSError as exc:
        messagebox.showerror("無法啟動 I/Q 採集", str(exc), parent=app)
        return
    if dry_run:
        app.cw_capture_status_var.set("Dry run 已啟動；不連接硬體。")
        return
    app.cw_capture_status_var.set("正在等待 HSDC 建立 I/Q manifest…")
    app.cw_capture_progress.start(12)
    app.cw_capture_button.state(["disabled"])
    app.cw_capture_watch = {
        "root": output_root,
        "existing": existing,
        "started": time.time(),
        "run": None,
        "process": process,
        "rate_hz": rate_hz,
    }
    app.after(1000, lambda: poll_cw_iq_capture(app))


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def poll_cw_iq_capture(app) -> None:
    watch = app.cw_capture_watch
    if watch is None:
        return
    if watch["run"] is None:
        candidates = [path for path in watch["root"].glob("cw_capture_*") if path.name not in watch["existing"]]
        if candidates:
            watch["run"] = max(candidates, key=lambda path: path.stat().st_mtime)
    run = watch["run"]
    process = watch.get("process")
    if run is None and process is not None and process.poll() is not None and time.time() - watch["started"] > 1:
        _finish_watch(app)
        app.cw_capture_status_var.set(f"採集未啟動 · exit {process.returncode}")
        messagebox.showerror("I/Q 採集未啟動", "子進程未建立 cw_capture_* 目錄，請查看命令列錯誤。", parent=app)
        return
    if run is not None:
        manifest_path = run / "cw_capture_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {"status": "initializing"}
        status = manifest.get("status", "initializing")
        app.cw_capture_status_var.set(f"{run.name} · {status}")
        if status == "complete":
            _finish_watch(app)
            app.cw_capture_last_run = run
            app.cw_capture_detail_var.set(
                f"完成 · {manifest.get('actual_bytes', 0) / 1048576:.1f} MiB · "
                f"{manifest.get('duration_s', 0):.3f} s · I1,Q1,…,I8,Q8"
            )
            analyze_and_show(app, run, float(watch["rate_hz"]))
            return
        if status == "error":
            _finish_watch(app)
            messagebox.showerror("I/Q 採集失敗", str(manifest.get("error", "未知錯誤")), parent=app)
            return
    app.after(1500, lambda: poll_cw_iq_capture(app))


def _finish_watch(app) -> None:
    app.cw_capture_progress.stop()
    app.cw_capture_button.state(["!disabled"])
    app.cw_capture_watch = None


def analyze_and_show(app, run: Path, rate_hz: float) -> None:
    script = app._cw_app_dir / "cw_iq_analysis.py"
    bin_path = run / "cw_iq.bin"
    output_dir = run / "analysis" / "cw_iq"
    slots = ",".join(variable.get().strip() for variable in app.cw_row_rx_slot_vars)
    app.cw_capture_status_var.set("BIN 已保存，正在建立 I/Q／頻譜預覽…")

    def worker() -> None:
        completed = subprocess.run(
            [sys.executable, str(script), str(bin_path), "--output-rate-hz", str(rate_hz),
             "--output-dir", str(output_dir), "--rx-channels", slots],
            capture_output=True,
            text=True,
            errors="replace",
        )
        app.after(0, lambda: _analysis_finished(app, run, output_dir, completed))

    import threading
    threading.Thread(target=worker, daemon=True).start()


def _analysis_finished(app, run: Path, output_dir: Path, completed: subprocess.CompletedProcess) -> None:
    if completed.returncode:
        app.cw_capture_status_var.set("I/Q BIN 已保存，但預覽分析失敗。")
        messagebox.showerror("I/Q 預覽失敗", (completed.stderr or completed.stdout)[-3000:], parent=app)
        return
    image_path = output_dir / "cw_iq_preview.png"
    summary_path = output_dir / "cw_iq_summary.json"
    try:
        image = Image.open(image_path).convert("RGB")
        image.thumbnail((1050, 520), Image.Resampling.LANCZOS)
        image = ImageOps.expand(image, border=1, fill="#DDE7F2")
        app.cw_capture_photo = ImageTk.PhotoImage(image)
        app.cw_capture_preview_label.configure(image=app.cw_capture_photo, text="")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        channel_text = " · ".join(
            f"CH{item['channel']} peak {item['peak_baseband_hz']:+.1f} Hz"
            for item in summary.get("channels", [])
        )
        app.cw_capture_status_var.set(f"預覽完成 · {channel_text}")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        app.cw_capture_status_var.set(f"預覽檔讀取失敗：{exc}")
        return
    messagebox.showinfo("I/Q 採集完成", f"BIN、manifest 與預覽已保存：\n{run}", parent=app)
