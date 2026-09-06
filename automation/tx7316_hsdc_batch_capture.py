# -*- coding: utf-8 -*-
from __future__ import print_function

"""
TX7316 + AFE58JD48 + TSW14J50/HSDC Pro 批量角度採集腳本
=========================================================

重要：第一次使用前，請完整照以下 SETUP 流程做。不要跳步。

【0. 適用範圍與安全邊界】
1. 本腳本以目前的 8 個發射陣元 A1-A8 為基礎：
   - 中心間距 pitch = 1.59 mm
   - 單陣元尺寸 = 1.0 mm x 1.0 mm x 0.4 mm
   - 預設中心頻率 = 1.0 MHz
2. 預設掃描角為 -10, -8, ..., +10 度，共 11 個角度。亦支持 1 度步進的21角度掃描；
   TX7316一次只有16個 Delay Profile，因此腳本會在 TX_BF_MODE 關閉時自動分成16+5兩批重寫。
3. 1.59 mm 在 1.0 MHz 下仍略大於一個波長，存在柵瓣風險；腳本會計算並顯示警告。
   建議日常只用 +/-8 度，+/-10 度只作實驗上限，並把重建顯示視場限制在 +/-10 度。
4. 這不是醫療設備。腳本只用於凝膠/水槽/仿體，不得直接用於人體。
5. 腳本不改變 J1/J2/J3 外部高壓電源或PRF；只會寫入白名單Pattern Profile/週期數並讀回。
   外部電源實測值與波形計畫仍必須由操作者確認，任何寫入期間TX_BF_MODE保持關閉。

【1. 硬件接線和人工配置】
1. TX7316 J7 的 A1-A8 高壓輸出接線性陣列對應的 8 個陣元；公共電極接系統模擬地。
2. TX7316 J5 的 RX_A1-RX_A8 接 AFE58JD48 的對應 SMA 輸入；兩板 AGND 短接。
3. AFE58JD48 與 TSW14J50 通過 FMC/JESD 連接。
4. 無硬件觸發時，J7 pin 2、AFE J25、TSW J13 仍可留空；但這只能做“非相干/軟對齊”採集。
   若要真正相干的多角度平面波複合，必須用同一個有緩衝和電平轉換的觸發源同步 TX 與 TSW。
5. TX7316 GUI 中先人工設定好 Pattern Profile 0：1.0 MHz、短脈衝、低 PRF 起步，CW 必須關閉。
6. AFE GUI 中完成 LMK/AFE 初始化；選 Analog Input、120M 8L Subclass 1、Active Termination Disable，
   第一次採集先用較低增益，確認 ADC 不削頂後再增加。

【2. 三個程序必須使用相同權限】
以下三者全部右鍵選“以管理員身份運行”，不能混用普通權限和管理員權限：
1. TX7316 EVM GUI：以管理員身份運行，保持 CONNECTED，GUI 本身保持打開。
2. High Speed Data Converter Pro：以管理員身份運行，保持 CONNECTED。
3. 本採集腳本：在“以管理員身份運行”的 CMD 中，用 32-bit Python 2.7 執行。

原因：TX7316 的 Device GUI.dll 是 32-bit LabVIEW 接口，而且 LabVIEW VI Server 不允許跨用戶權限控制。
不要使用 64-bit Python 執行本文件。

【3. GUI 啟動次序】
1. 先啟動 TX7316 EVM GUI，確認綠色 CONNECTED；完成 Pattern Profile、Delay/TR switch 基本設定。
2. 再啟動 HSDC Pro，確認 TSW14J50 板名 TIAOPCAW 能連接。
3. AFE GUI 完成 DUT RESET -> INITIALIZE LMK -> AFE RESET -> INITIALIZE AFE。
4. Normal capture 的 HSDC Pro AFE RX profile 必須為 TI 通道映射修復版
   AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1，數據率120 MSPS。
   舊MANUAL文件把JESD M錯寫成5，會造成固定的重複/錯位通道，腳本會拒絕使用。
5. 最後才執行本腳本。腳本在 HSDC 準備好前會暫停 TX 的 Internal BF，採集前再打開，結束後恢復原值。

【4. 先做完全不接觸硬件的 Dry Run】
在管理員 CMD 中：

  "C:\\Python27\\python.exe" "E:\\Users\\dxhui\\Desktop\\TI_AFE58jd48\\UltrasoundImagingData_Capture\\automation\\tx7316_hsdc_batch_capture.py" --dry-run

Dry Run 會列出每個角度的 8 路延時、量化後角度、相鄰陣元相位差和柵瓣位置，不會連 GUI、不會發射、不會建文件。

【5. 正式批量採集】
確認凝膠、探頭、接收增益與 TX 電源後，在管理員 CMD 中：

  "C:\\Python27\\python.exe" "E:\\Users\\dxhui\\Desktop\\TI_AFE58jd48\\UltrasoundImagingData_Capture\\automation\\tx7316_hsdc_batch_capture.py" --capture --enable-internal-bf

預設行為：
1. 計算並寫入 Profile 0-10；P0=-10 度，P5=0 度，P10=+10 度。
2. 每個角度採集 1,048,576 samples/channel、16 channels、uint16。
3. 每個 BIN 預期 33,554,432 bytes。
4. 自動建立時間戳文件夾，保存 11 個 BIN、capture_manifest.json 和 run.log。
5. 結束或出錯時，恢復原來的 Profile 選擇和 TX_BF_MODE；已寫入的 Delay Profile 內容保留，原值記在 manifest。

`--reuse-hsdc-state` 只保留作診斷用途。目前這塊 TSW14J50 必須由自動化流程
使用正確板名 TIAOPCAW 完成 Connect/Select AFE/Reload INI，否則 Automation DLL
內部 ports 不會被配置，Pass_Capture_Event 會失敗。因此正常採集不要增加：

  --reuse-hsdc-state

若只想採集 +/-8 度，可用（等號不可省略）：

  --angles=-8,-6,-4,-2,0,2,4,6,8

若要 -10...+10 度、1度步進，共21個BIN，可用：

  --angles=-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,0,1,2,3,4,5,6,7,8,9,10

腳本會自動把 sequence 00..15 寫入第一批 P00..P15，再把 sequence 16..20
寫入第二批 P00..P04；文件名中的 P16..P20 是全局掃描序號，manifest另記錄實際硬件Profile。

若物理 A1-A8 的左右方向與圖像定義相反，可增加：

  --reverse-angle-sign

【6. 硬件觸發模式】
只有在 TSW14J50 J13 已接入正確電平、與 TX 共源的單次觸發後，才使用：

  --trigger hardware

未接觸發線時保持預設 --trigger normal。Normal 模式可用於靜止凝膠的軟對齊重建，
但各角度沒有共同時間零點，不應把它當成真正的相干平面波複合。

【7. 自動寫入與人工設定的邊界】
腳本只會寫入白名單 Pattern Profile、1..12 cycles、Delay Profile，並逐項回讀。
它不會修改外部高壓電源、PRF、AFE LNA/PGA/TGC 增益或人體安全參數。
--expected-hv-a-v/--expected-hv-b-v 只是保存操作者量測值；SPI 不會調節外部電源。
"""

import argparse
import array
try:
    import ConfigParser
except ImportError:  # Python 3 test/import compatibility; production uses Python 2.7.
    import configparser as ConfigParser
import ctypes
import datetime
import hashlib
try:
    import imp
except ImportError:  # Python 3.12+ dry-run/test compatibility; production is Python 2.7.
    imp = None
    import importlib.util
import json
import math
import os
import struct
import sys
import threading
import time


# --------------------------- 用戶/硬件固定配置 ---------------------------

# 2026-07-23 已用只讀診斷器在本機實測：這一版 Device GUI.dll 必須使用
# Application="TX7316 EVM" 且 PortNumber=NaN（本機 ActiveX）。GUI ini 中的
# TCP VI Server 6640 不是這個 DLL 的正確接口端口。
TX_GUI_APPLICATION_CANDIDATES = [
    "TX7316 EVM",
    "TX7316 EVM GUI",
    "TX7316 5LVL EVM",
]
TX_GUI_PORT = float("nan")
TX_GUI_PORT_LABEL = "NaN (local ActiveX)"
TX_PYTHON_MODULE = r"E:\Program Files (x86)\Texas Instruments\TX7316 EVM\Scripts\TX7316 EVM.py"

HSDC_DLL = r"E:\Program Files\Texas Instruments\High Speed Data Converter Pro\HSDCPro Automation DLL\32Bit DLL\HSDCProAutomation.dll"
HSDC_BOARD_SERIAL = "TIAOPCAW"
HSDC_AFE_RX_DEVICE = "AFE58JD48_120M_8L_M16_FIXED"
HSDC_AFE_RX_TRIGGER_DEVICE = "AFE58JD48_120M_8L_M16_FIXED_TRIG"
HSDC_AFE_RX_TI_VENDOR_DEVICE = "AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1"
HSDC_AFE_RX_TI_VENDOR_SHA256 = "78923A1787DC6794274398B5457DF1EE2F40852B0E9854DDC6AED41E9CDC8E67"
HSDC_AFE_RX_NORMAL_DEVICE = HSDC_AFE_RX_TI_VENDOR_DEVICE
# Historical experimental profiles used JESD M=5 with Group-128 disabled.
# They are not capture-qualified after the M=16 transport repair, but a normal
# full setup may safely replace them by explicitly selecting/reloading the
# qualified M=16 profile before any TX access.  Reuse mode must still fail.
HSDC_LEGACY_RESELECT_DEVICES = (
    "AFE58JD48_S1_K8_G128OFF",
    "AFE58JD48_TI_8L_S1_K8_GROUP128_OFF_EXPERIMENTAL",
)
HSDC_ADC_FILES_DIRS = (
    r"E:\Program Files\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files",
    r"E:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files",
)
HSDC_DEFAULT_CONTROLS_INI = r"C:\Users\Public\Documents\Texas Instruments\High Speed Data Converter Pro\Default_controls.ini"

DEFAULT_OUTPUT_ROOT = r"E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture\auto_runs"

SOUND_SPEED_M_S = 1540.0
CENTER_FREQUENCY_HZ = 1.0e6
ADC_SAMPLE_RATE_HZ = 120e6
SAMPLES_PER_CHANNEL = 1048576
RX_CHANNELS_IN_FILE = 16
BYTES_PER_SAMPLE = 2

TX_ELEMENTS = 8
ELEMENT_PITCH_M = 1.59e-3
ELEMENT_WIDTH_M = 1.00e-3
ELEMENT_HEIGHT_M = 1.00e-3
ELEMENT_THICKNESS_M = 0.40e-3

# TX7316 Delay Profile 每個 count 的時間量化。依目前 GUI/時鐘配置採用 5 ns。
# 如果未來改 BF_CLK，必須先重新核對此值，不能只改中心頻率。
TX_DELAY_QUANTUM_S = 5e-9
TX_DELAY_MAX_COUNT = 8191       # 13 bit
HARDWARE_DELAY_PROFILES_PER_BATCH = 16
MAX_SWEEP_ANGLES = 64

DEFAULT_ANGLES_DEG = [-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10]
RECOMMENDED_MAX_STEER_DEG = 10.0
RECOMMENDED_ROUTINE_STEER_DEG = 8.0

HSDC_DEFAULT_TIMEOUT_MS = 120000

LOG_HANDLE = None


# Known, finite B-mode patterns derived from the already-used 1 MHz tapered
# five-level profile.  The level sequence is unchanged; only the duration of
# each transition changes.  TX7316 holds a transition for PER+2 divided
# pattern clocks (datasheet section 8.3.4.3.1.2).  CLK_DIV remains zero, so the
# pattern clock is 200 MHz.  REPEAT_COUNT=3 and TAIL_COUNT=9 match the existing
# 1MHz_5pulses.cfg setup.  The 1.5 and 2 MHz entries keep the same symmetric
# five-level sequence and change duration fields only; their sums are 134 and
# 100 pattern clocks, respectively.  These are deliberately the only
# frequencies that --program-known-pattern accepts; arbitrary high-voltage
# patterns are refused.
KNOWN_PATTERN_PROFILES = {
    1.0: {
        "name": "tapered_1MHz_reference",
        "register25": 0x00000246,
        "registers": [
            0x839A836E, 0x836D836E, 0x836D8399, 0x00000007,
            0x00000000, 0x00000000, 0x00000000, 0x00000000,
        ],
        "nominal_base_pattern_hz": 200000000.0 / 210.0,
    },
    1.5: {
        "name": "tapered_1p5MHz_scaled",
        "register25": 0x00000246,
        "registers": [
            0x4B624B46, 0x4B454B46, 0x4B454B61, 0x00000007,
            0x00000000, 0x00000000, 0x00000000, 0x00000000,
        ],
        # 134 integer pattern clocks is the nearest symmetric realization.
        "nominal_base_pattern_hz": 200000000.0 / 134.0,
    },
    2.0: {
        "name": "tapered_2MHz_scaled",
        "register25": 0x00000246,
        "registers": [
            0x33423336, 0x33353336, 0x33353341, 0x00000007,
            0x00000000, 0x00000000, 0x00000000, 0x00000000,
        ],
        "nominal_base_pattern_hz": 2000000.0,
    },
    2.5: {
        "name": "tapered_2p5MHz_scaled",
        "register25": 0x00000246,
        "registers": [
            0x2B2A2B26, 0x2B252B26, 0x2B252B29, 0x00000007,
            0x00000000, 0x00000000, 0x00000000, 0x00000000,
        ],
        "nominal_base_pattern_hz": 2500000.0,
    },
    4.0: {
        "name": "tapered_4MHz_scaled",
        "register25": 0x00000246,
        "registers": [
            0x131A1316, 0x13151316, 0x13151319, 0x00000007,
            0x00000000, 0x00000000, 0x00000000, 0x00000000,
        ],
        "nominal_base_pattern_hz": 4000000.0,
    },
}

# Diagnostic A-rail-only waveform.  TX7316 transition duration is PER+2
# pattern clocks and PER is only five bits, so each 67-clock half-cycle is
# represented by three consecutive entries at the same electrical level.
# The adjacent entries do not create extra output edges: the resulting output
# is a plain PHV_A <-> MHV_A bipolar square wave.  Reg25 REPEAT_COUNT=1 emits
# two acoustic cycles; TAIL_COUNT=9 is retained from the qualified profiles.
BIPOLAR_A_PATTERN_PROFILES = {
    1.5: {
        "name": "bipolar_A_1p5MHz_2cycle_diagnostic",
        "register25": 0x00000242,
        "registers": [
            0xA1AAA2A2, 0x0007A9A1,
            0x00000000, 0x00000000, 0x00000000, 0x00000000,
            0x00000000, 0x00000000,
        ],
        "nominal_base_pattern_hz": 200000000.0 / 134.0,
        "electrical_levels": ["PHV_A", "MHV_A"],
        "acoustic_cycles": 2,
    },
}


class AutomationError(RuntimeError):
    pass


def log(message):
    """同時寫到終端和 run.log；Dry Run 時只輸出到終端。"""
    global LOG_HANDLE
    text = str(message)
    print(text)
    if LOG_HANDLE is not None:
        LOG_HANDLE.write((text + "\n").encode("utf-8"))
        LOG_HANDLE.flush()


def utc_now_text():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def local_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_angles(text):
    try:
        values = [float(x.strip()) for x in text.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("angles must be comma-separated numbers")
    if not values:
        raise argparse.ArgumentTypeError("angles cannot be empty")
    if len(values) > MAX_SWEEP_ANGLES:
        raise argparse.ArgumentTypeError(
            "at most %d sweep angles are allowed; hardware profiles are loaded in batches of 16"
            % MAX_SWEEP_ANGLES
        )
    return values


def parse_rx_channels(text):
    try:
        values = [int(token.strip()) for token in text.split(",") if token.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("RX channels must be comma-separated integers")
    if not values:
        raise argparse.ArgumentTypeError("RX channels cannot be empty")
    return values


def is_windows_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def disable_console_quick_edit():
    """Prevent a mouse click/selection from pausing the acquisition process.

    Windows legacy consoles enable QuickEdit by default.  While text is selected
    the console title is prefixed with "Select" (or the localized equivalent)
    and the attached process is suspended.  This previously looked exactly like
    a blocked HSDC/TX API call.  Keep extended flags enabled while clearing only
    the QuickEdit bit so normal keyboard input and Ctrl+C handling still work.
    """
    if os.name != "nt":
        return False
    try:
        std_input_handle = -10
        enable_quick_edit_mode = 0x0040
        enable_extended_flags = 0x0080
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(std_input_handle)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        new_mode = (mode.value | enable_extended_flags) & ~enable_quick_edit_mode
        return bool(kernel32.SetConsoleMode(handle, ctypes.c_uint32(new_mode)))
    except Exception:
        return False


class ConsoleHeartbeat(object):
    """Show that a blocking vendor API call is alive without touching hardware."""

    def __init__(self, label, progress_path=None, expected_bytes=None, interval=1.0):
        self.label = label
        self.progress_path = progress_path
        self.expected_bytes = expected_bytes
        self.interval = interval
        self.started = time.time()
        self.stop_event = threading.Event()
        self.thread = None
        self.printed = False
        self.max_width = 0

    def start(self):
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def _run(self):
        frames = "|/-\\"
        frame_index = 0
        while not self.stop_event.wait(self.interval):
            elapsed = time.time() - self.started
            progress = ""
            if self.progress_path and os.path.exists(self.progress_path):
                try:
                    size = os.path.getsize(self.progress_path)
                    if self.expected_bytes:
                        percent = min(100.0, 100.0 * size / float(self.expected_bytes))
                        progress = " file %.1f/%.1f MB (%5.1f%%)" % (
                            size / 1e6, self.expected_bytes / 1e6, percent,
                        )
                    else:
                        progress = " file %.1f MB" % (size / 1e6)
                except OSError:
                    pass
            text = "[%s] %s: alive, elapsed %.1f s%s" % (
                frames[frame_index % len(frames)], self.label, elapsed, progress,
            )
            frame_index += 1
            self.max_width = max(self.max_width, len(text))
            sys.stdout.write("\r" + text.ljust(self.max_width))
            sys.stdout.flush()
            self.printed = True

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(1.5)
        if self.printed:
            sys.stdout.write("\r" + (" " * self.max_width) + "\r")
            sys.stdout.flush()


def file_can_open_exclusively(path):
    """Return True when no HSDC writer still owns the file on Windows."""
    if os.name != "nt":
        return True
    try:
        create_file = ctypes.windll.kernel32.CreateFileW
        create_file.restype = ctypes.c_void_p
        if isinstance(path, unicode):
            wide_path = path
        else:
            wide_path = path.decode("mbcs")
        handle = create_file(
            ctypes.c_wchar_p(wide_path),
            ctypes.c_uint32(0x80000000),  # GENERIC_READ
            ctypes.c_uint32(0),           # no sharing
            None,
            ctypes.c_uint32(3),           # OPEN_EXISTING
            ctypes.c_uint32(0x80),        # FILE_ATTRIBUTE_NORMAL
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in (None, invalid_handle):
            return False
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        return True
    except Exception:
        return False


def wait_for_completed_file(
    path, expected_bytes, timeout_seconds, stable_seconds=8.0, poll_seconds=1.0,
):
    """Wait for an asynchronous HSDC save to finish after its API returns.

    HSDC Pro 5.31 can return Automation code 5000 while its LabVIEW GUI keeps
    writing a large BIN in the background.  File size alone is not sufficient:
    some writers preallocate the final length, so require both the expected
    length and an unchanged size/mtime signature for a short stability window.
    """
    if not expected_bytes:
        return False

    deadline = time.time() + max(0.0, float(timeout_seconds))
    stable_since = None
    previous_signature = None
    while time.time() <= deadline:
        try:
            stat_result = os.stat(path)
            signature = (int(stat_result.st_size), float(stat_result.st_mtime))
        except OSError:
            signature = None

        if signature is not None and signature[0] == int(expected_bytes):
            if signature == previous_signature:
                if stable_since is None:
                    stable_since = time.time()
                elif (
                    time.time() - stable_since >= float(stable_seconds)
                    and file_can_open_exclusively(path)
                ):
                    return True
            else:
                stable_since = time.time()
        else:
            stable_since = None

        previous_signature = signature
        time.sleep(max(0.01, float(poll_seconds)))
    return False


def require_32bit_python():
    if struct.calcsize("P") * 8 != 32:
        raise AutomationError(
            "This script must run with 32-bit Python 2.7 because TX7316 Device GUI.dll is 32-bit. "
            "Use C:\\Python27\\python.exe."
        )


def json_write_atomic(path, value):
    """先寫 .tmp 再替換，避免中途掉電留下半個 manifest。"""
    tmp = path + ".tmp"
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)
    with open(tmp, "wb") as handle:
        handle.write(payload.encode("ascii"))
        handle.write(b"\n")
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)


def write_bytes_atomic(path, payload):
    """Write a small reproducibility artifact without exposing a partial file."""
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)


def cfg_line(block, address, value):
    return "%s|0x%X\t0x%08X\r\n" % (
        block, int(address), int(value) & 0xffffffff,
    )


def save_verified_tx_cfg_files(
    run_dir, report, profile_batches, original_reg22, active_reg24,
    active_reg25, waveform_readback, requested_frequency_mhz, tx_cycles,
    expected_hv_a_v, expected_hv_b_v,
):
    """Save standalone, GUI-loadable CFG snapshots for every profile batch.

    TX7316 exposes only sixteen delay-profile slots.  A 21-angle sweep therefore
    has two different hardware states.  Saving one merged CFG would be
    misleading, so the capture folder receives one loadable CFG per batch.  The
    final GLOBAL 0x18 write always leaves TX_BF_MODE off; transmitting remains an
    explicit later action.
    """
    pattern_values = [int(text, 16) for text in waveform_readback["registers"][:8]]
    profile_slot_state = {}
    artifacts = []
    frequency_token = ("%.3f" % requested_frequency_mhz).rstrip("0").rstrip(".")
    frequency_token = frequency_token.replace(".", "p")

    for batch_number, batch_profiles in enumerate(profile_batches):
        for profile in batch_profiles:
            slot = int(profile["hardware_profile_number"])
            profile_slot_state[slot] = {
                int(address_text, 16): int(value_text, 16)
                for address_text, value_text in profile["registers"].items()
            }

        first_angle = batch_profiles[0]["requested_angle_deg"]
        last_angle = batch_profiles[-1]["requested_angle_deg"]
        filename = "TX7316_%sMHz_%02dcy_batch%02d_verified.cfg" % (
            frequency_token, int(tx_cycles), batch_number + 1,
        )
        path = os.path.join(run_dir, filename)
        lines = []
        # Match the vendor Quick Start scripts, but never enable TX_BF_MODE.
        lines.append(cfg_line("GLOBAL", 0x06, 0x00000010))
        lines.append(cfg_line("GLOBAL", 0x0F, 0x00000010))
        lines.append(cfg_line("GLOBAL", 0x18, int(active_reg24) & ~0x1))
        for offset, value in enumerate(pattern_values):
            lines.append(cfg_line("PATTERN-PROFILE", 0x60 + offset, value))
        for slot in sorted(profile_slot_state):
            for address, value in sorted(profile_slot_state[slot].items()):
                lines.append(cfg_line("DELAY-PROFILE", address, value))
        # Select profile 0, pulse LOAD_PROF, then restore Repeat/Tail because the
        # EVM GUI load path can overwrite the low fields of Register 25.
        lines.append(cfg_line("GLOBAL", 0x16, int(original_reg22) & 0x0fffffff))
        lines.append(cfg_line("GLOBAL", 0x00, 0x00000008))
        lines.append(cfg_line("GLOBAL", 0x19, active_reg25))
        lines.append(cfg_line("GLOBAL", 0x18, int(active_reg24) & ~0x1))
        payload = "".join(lines).encode("ascii")
        write_bytes_atomic(path, payload)
        artifacts.append({
            "filename": filename,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "profile_batch_number": batch_number,
            "captured_sequence_numbers": [
                int(profile["profile_number"]) for profile in batch_profiles
            ],
            "captured_angles_deg": [
                float(profile["requested_angle_deg"]) for profile in batch_profiles
            ],
            "first_angle_deg": float(first_angle),
            "last_angle_deg": float(last_angle),
            "tx_bf_mode_saved_off": True,
        })

    index_path = os.path.join(run_dir, "TX7316_verified_cfg_index.json")
    index = {
        "requested_frequency_mhz": float(requested_frequency_mhz),
        "pattern_reference": waveform_readback.get("reference_name"),
        "pattern_nominal_base_hz": waveform_readback.get("nominal_base_pattern_hz"),
        "tx_cycles": int(tx_cycles),
        "external_supply_is_metadata_only": True,
        "expected_external_supply_magnitude_v": {
            "hv_a": float(expected_hv_a_v) if expected_hv_a_v else None,
            "hv_b": float(expected_hv_b_v) if expected_hv_b_v else None,
        },
        "register25": "0x%08X" % (int(active_reg25) & 0xffffffff),
        "profile_capacity_per_cfg": HARDWARE_DELAY_PROFILES_PER_BATCH,
        "reason_for_multiple_cfg_files": (
            "%d angles exceed the 16 hardware delay-profile slots; later batches reuse P00..P15."
            % len(report.get("profiles", []))
            if len(report.get("profiles", [])) > HARDWARE_DELAY_PROFILES_PER_BATCH
            else "A single verified CFG contains all requested delay profiles."
        ),
        "cfg_files": artifacts,
    }
    json_write_atomic(index_path, index)
    return artifacts


def nearest_existing_directory(path):
    current = os.path.abspath(path)
    while not os.path.isdir(current):
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return current


def free_bytes_for_path(path):
    """Python 2.7 沒有 shutil.disk_usage，直接調 Windows API。"""
    directory = nearest_existing_directory(path)
    if directory is None:
        return None
    free_available = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    total_free = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        unicode(directory),
        ctypes.byref(free_available),
        ctypes.byref(total),
        ctypes.byref(total_free),
    )
    return free_available.value if ok else None


def resolve_hsdc_capture_device(device, trigger_mode="normal", allow_reselect=False):
    """Resolve the profile that full HSDC setup must actually load.

    A legacy Group-128-off selection may be replaced only when the caller will
    perform Connect_Board -> Select_AFE_Device -> Reload_Device_INI.  It must
    never be accepted as the already-configured state in reuse mode.
    """
    if device == "AFE58JD48_120M_8L_MANUAL":
        raise AutomationError(
            "Known-bad HSDC profile selected: AFE58JD48_120M_8L_MANUAL uses JESD M=5. "
            "Load TI's JESD 120MSPS_Subclass1_8L.CFG in the AFE GUI, select "
            "AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1 in HSDC Pro, "
            "reload the device INI, and recapture."
        )
    supported_devices = (
        HSDC_AFE_RX_DEVICE,
        HSDC_AFE_RX_TRIGGER_DEVICE,
        HSDC_AFE_RX_TI_VENDOR_DEVICE,
    )
    trigger_required = trigger_mode in ("hardware", "software")
    target_device = (
        HSDC_AFE_RX_TRIGGER_DEVICE if trigger_required else HSDC_AFE_RX_NORMAL_DEVICE
    )
    if device not in supported_devices:
        if allow_reselect and device in HSDC_LEGACY_RESELECT_DEVICES:
            return target_device
        raise AutomationError(
            "HSDC GUI selected device is %r, expected one of %r. "
            "Select the correct AFE RX profile first." % (
                device, supported_devices
            )
        )
    if trigger_required and device != HSDC_AFE_RX_TRIGGER_DEVICE:
        if allow_reselect:
            return HSDC_AFE_RX_TRIGGER_DEVICE
        raise AutomationError(
            "%s J13 capture requires HSDC profile %r; selected %r has "
            "'Is Capture Trigger SMA' commented out. Install/select the _TRIG "
            "profile, reload its INI/firmware, and retry." % (
                trigger_mode.capitalize(), HSDC_AFE_RX_TRIGGER_DEVICE, device
            )
        )
    if allow_reselect and not trigger_required and device != HSDC_AFE_RX_NORMAL_DEVICE:
        return HSDC_AFE_RX_NORMAL_DEVICE
    return device


def read_hsdc_persisted_settings(trigger_mode="normal", allow_reselect=False):
    """
    HSDC GUI 會把最後成功連接的板名/Device Profile 保存到 Default_controls.ini。
    直接讀這個文件比從 GUI 字體辨認序號可靠；本機實測板名為 TIAOPCAW。
    """
    board = HSDC_BOARD_SERIAL
    device = HSDC_AFE_RX_NORMAL_DEVICE
    firmware = None
    if os.path.isfile(HSDC_DEFAULT_CONTROLS_INI):
        parser = ConfigParser.RawConfigParser()
        parser.read(HSDC_DEFAULT_CONTROLS_INI)
        try:
            board = parser.get("Board Parameters", "Board Name").strip().strip('"')
            device = parser.get("Board Parameters", "ADC/DAC selected").strip().strip('"')
            firmware = parser.get("Board Parameters", "Firmware Type").strip().strip('"')
        except Exception as exc:
            log("WARNING: unable to parse HSDC Default_controls.ini: %r" % exc)
    if not board:
        raise AutomationError("HSDC persisted Board Name is empty")
    persisted_device = device
    device = resolve_hsdc_capture_device(
        persisted_device, trigger_mode, allow_reselect
    )
    if device != persisted_device:
        log(
            "HSDC persisted device is %r; full setup will explicitly select "
            "and reload qualified profile %r before capture." % (
                persisted_device, device
            )
        )
    if device == HSDC_AFE_RX_TI_VENDOR_DEVICE:
        found_hashes = []
        approved = False
        for directory in HSDC_ADC_FILES_DIRS:
            ini_path = os.path.join(directory, device + ".ini")
            if not os.path.isfile(ini_path):
                continue
            digest = hashlib.sha256()
            with open(ini_path, "rb") as handle:
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
            actual_hash = digest.hexdigest().upper()
            found_hashes.append("%s=%s" % (ini_path, actual_hash))
            if actual_hash == HSDC_AFE_RX_TI_VENDOR_SHA256:
                approved = True
        if not approved:
            raise AutomationError(
                "Selected TI vendor HSDC profile did not match the approved SHA-256 %s; "
                "found %s. Reinstall the exact TI-supplied INI before capture." % (
                    HSDC_AFE_RX_TI_VENDOR_SHA256,
                    "; ".join(found_hashes) if found_hashes else "no installed INI",
                )
            )
        log(
            "HSDC TI vendor profile hash approved: %s" %
            HSDC_AFE_RX_TI_VENDOR_SHA256
        )
    log("HSDC settings: board=%s firmware=%s persisted_device=%s capture_device=%s" % (
        board, firmware, persisted_device, device))
    return board, firmware, device, persisted_device


def scan_u16_file(path):
    """
    不依賴 NumPy，分塊檢查 HSDC uint16 BIN 的極值和 ADC rail 樣本。

    出現 0 或 65535 通常表示削頂、數字鏈路錯碼或捕獲切換瞬態；對相位型高分辨率
    算法尤其有害。這個檢查不替代逐通道映射與相關性檢查。
    """
    minimum = 65535
    maximum = 0
    zero_count = 0
    full_scale_count = 0
    sample_count = 0
    with open(path, "rb") as handle:
        while True:
            raw = handle.read(2 * 1024 * 1024)
            if not raw:
                break
            if len(raw) % 2:
                raise AutomationError("Odd byte count in uint16 BIN: " + path)
            values = array.array("H")
            values.fromstring(raw)
            if sys.byteorder != "little":
                values.byteswap()
            if values:
                minimum = min(minimum, min(values))
                maximum = max(maximum, max(values))
                zero_count += values.count(0)
                full_scale_count += values.count(65535)
                sample_count += len(values)
    return {
        "minimum_code": minimum,
        "maximum_code": maximum,
        "zero_code_count": zero_count,
        "full_scale_code_count": full_scale_count,
        "rail_sample_count": zero_count + full_scale_count,
        "uint16_sample_count_all_channels": sample_count,
    }


def sinc_unscaled(x):
    if abs(x) < 1e-12:
        return 1.0
    return math.sin(x) / x


def grating_lobes_deg(steer_deg, wavelength_m, pitch_m):
    """返回 m != 0 且落在可見角度 [-90,90] 的空間混疊副本。"""
    s0 = math.sin(math.radians(steer_deg))
    lobes = []
    for order in range(-8, 9):
        if order == 0:
            continue
        value = s0 + order * wavelength_m / pitch_m
        if -1.0 <= value <= 1.0:
            lobes.append({
                "order": order,
                "angle_deg": math.degrees(math.asin(value)),
            })
    lobes.sort(key=lambda item: abs(item["angle_deg"] - steer_deg))
    return lobes


def linear_slope(xs, ys):
    x_mean = sum(xs) / float(len(xs))
    y_mean = sum(ys) / float(len(ys))
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom


def build_delay_profile(angle_deg, reverse_sign=False):
    """
    產生 A1-A8 的“真時間延時”，不是把相位取模到 0...360 度。

    正號的約定：A1 最早、A8 最晚。若探頭實際左右接反，用 --reverse-angle-sign。
    為避免負延時，整個延時向量平移，使最小值為 0；這不改變波束方向。
    """
    sign = -1.0 if reverse_sign else 1.0
    theta = math.radians(angle_deg)
    x = [i * ELEMENT_PITCH_M for i in range(TX_ELEMENTS)]
    raw = [sign * xi * math.sin(theta) / SOUND_SPEED_M_S for xi in x]
    minimum = min(raw)
    shifted = [value - minimum for value in raw]
    active_counts = [int(math.floor(value / TX_DELAY_QUANTUM_S + 0.5)) for value in shifted]
    if max(active_counts) > TX_DELAY_MAX_COUNT:
        raise AutomationError("Delay count exceeds TX7316 13-bit range: %r" % active_counts)
    active_quantized = [count * TX_DELAY_QUANTUM_S for count in active_counts]
    slope = linear_slope(x, active_quantized)
    sine_value = max(-1.0, min(1.0, SOUND_SPEED_M_S * slope))
    realized_gradient_deg = math.degrees(math.asin(sine_value))
    adjacent_delays = [
        active_quantized[i + 1] - active_quantized[i]
        for i in range(TX_ELEMENTS - 1)
    ]
    mean_adjacent_s = sum(adjacent_delays) / float(len(adjacent_delays))
    phase_step_deg_unwrapped = 360.0 * CENTER_FREQUENCY_HZ * mean_adjacent_s
    total_cycles = (
        max(active_quantized) - min(active_quantized)
    ) * CENTER_FREQUENCY_HZ

    # TX7316 G1 Delay Profile registers always contain A1-A8. When fewer than
    # eight physical elements are selected, only A1..AN are used for the delay
    # law and the unused fields are written as zero. Those unused outputs must
    # be physically unconnected or separately powered down in the TX GUI.
    counts = active_counts + [0] * (8 - TX_ELEMENTS)
    quantized = [count * TX_DELAY_QUANTUM_S for count in counts]
    return {
        "requested_angle_deg": angle_deg,
        "active_tx_elements": TX_ELEMENTS,
        "delay_sign_reversed": bool(reverse_sign),
        "delay_counts_A1_to_A8": counts,
        "delay_ns_A1_to_A8": [round(value * 1e9, 3) for value in quantized],
        "realized_delay_gradient_angle_deg": realized_gradient_deg,
        "mean_adjacent_delay_ns": mean_adjacent_s * 1e9,
        "mean_adjacent_phase_step_deg_unwrapped": phase_step_deg_unwrapped,
        "aperture_delay_cycles_at_fc": total_cycles,
    }


def pack_delay_profile_registers(profile_number, counts):
    """
    已由 TX7316 5LVLvE3 Register Map.xml 核對：

      base+0: bits 12:0=A7, bits 28:16=A8
      base+1: bits 12:0=A5, bits 28:16=A6
      base+2: bits 12:0=A3, bits 28:16=A4
      base+3: bits 12:0=A1, bits 28:16=A2

    GUI 的 Profile 0 對應寄存器字段後綴 _1；base address = 0x20 + 4*profile。
    """
    if not (0 <= profile_number <= 15):
        raise AutomationError("Profile number must be 0..15")
    if len(counts) != 8:
        raise AutomationError("Exactly 8 delay counts are required")
    for count in counts:
        if not (0 <= count <= TX_DELAY_MAX_COUNT):
            raise AutomationError("Invalid 13-bit delay count: %r" % count)

    def pack(low, high):
        return (low & 0x1fff) | ((high & 0x1fff) << 16)

    base = 0x20 + 4 * profile_number
    return {
        base + 0: pack(counts[6], counts[7]),
        base + 1: pack(counts[4], counts[5]),
        base + 2: pack(counts[2], counts[3]),
        base + 3: pack(counts[0], counts[1]),
    }


def array_report(angles, reverse_sign):
    wavelength = SOUND_SPEED_M_S / CENTER_FREQUENCY_HZ
    d_over_lambda = ELEMENT_PITCH_M / wavelength
    kerf = ELEMENT_PITCH_M - ELEMENT_WIDTH_M
    broadside_first = None
    ratio = wavelength / ELEMENT_PITCH_M
    if ratio <= 1.0:
        broadside_first = math.degrees(math.asin(ratio))

    # 不同“無柵瓣”定義的頻率上限。
    f_broadside = SOUND_SPEED_M_S / ELEMENT_PITCH_M
    f_for_10deg_fov = SOUND_SPEED_M_S / (
        ELEMENT_PITCH_M * (1.0 + math.sin(math.radians(10.0)))
    )
    f_half_lambda = SOUND_SPEED_M_S / (2.0 * ELEMENT_PITCH_M)

    report = {
        "sound_speed_m_s": SOUND_SPEED_M_S,
        "center_frequency_hz": CENTER_FREQUENCY_HZ,
        "active_tx_elements": TX_ELEMENTS,
        "delay_quantum_ns": TX_DELAY_QUANTUM_S * 1e9,
        "wavelength_mm": wavelength * 1e3,
        "pitch_mm": ELEMENT_PITCH_M * 1e3,
        "element_width_mm": ELEMENT_WIDTH_M * 1e3,
        "kerf_mm": kerf * 1e3,
        "pitch_over_wavelength": d_over_lambda,
        "broadside_first_grating_lobe_deg": broadside_first,
        "max_frequency_no_broadside_grating_hz": f_broadside,
        "max_frequency_no_grating_over_plus_minus_10deg_hz": f_for_10deg_fov,
        "max_frequency_for_half_wavelength_pitch_hz": f_half_lambda,
        "hardware_delay_profiles_per_batch": HARDWARE_DELAY_PROFILES_PER_BATCH,
        "profile_batch_count": int(math.ceil(len(angles) / float(HARDWARE_DELAY_PROFILES_PER_BATCH))),
        "profiles": [],
    }

    log("=" * 78)
    log("ARRAY CHECK: pitch=%.3f mm, width=%.3f mm, kerf=%.3f mm" % (
        ELEMENT_PITCH_M * 1e3, ELEMENT_WIDTH_M * 1e3, kerf * 1e3))
    log("fc=%.3f MHz, lambda=%.3f mm, pitch/lambda=%.3f" % (
        CENTER_FREQUENCY_HZ / 1e6, wavelength * 1e3, d_over_lambda))
    if broadside_first is not None:
        log("WARNING: broadside first grating lobes are at about +/-%.2f deg." % broadside_first)
    log("No-broadside-grating requires fc <= %.3f MHz." % (f_broadside / 1e6))
    log("No-grating over +/-10 deg requires fc <= %.3f MHz." % (f_for_10deg_fov / 1e6))
    log("Half-wavelength pitch at %.3f mm requires fc <= %.3f MHz." % (
        ELEMENT_PITCH_M * 1e3, f_half_lambda / 1e6))
    if d_over_lambda > 0.5:
        log(
            "WARNING: at %.3f MHz this aperture exceeds lambda/2; delay programming "
            "cannot remove spatial aliases." % (CENTER_FREQUENCY_HZ / 1e6)
        )
    else:
        log("Pitch is <= lambda/2 at the configured centre frequency.")
    log("=" * 78)

    for profile_number, angle in enumerate(angles):
        batch_number = profile_number // HARDWARE_DELAY_PROFILES_PER_BATCH
        hardware_profile_number = profile_number % HARDWARE_DELAY_PROFILES_PER_BATCH
        profile = build_delay_profile(angle, reverse_sign)
        # profile_number remains the global sweep/file sequence. The hardware
        # slot is reused after every 16 angles and is recorded separately.
        profile["profile_number"] = profile_number
        profile["profile_batch_number"] = batch_number
        profile["hardware_profile_number"] = hardware_profile_number
        profile["registers"] = {
            "0x%02X" % address: "0x%08X" % value
            for address, value in sorted(pack_delay_profile_registers(
                hardware_profile_number, profile["delay_counts_A1_to_A8"]
            ).items())
        }
        lobes = grating_lobes_deg(angle, wavelength, ELEMENT_PITCH_M)
        profile["visible_grating_lobes"] = lobes
        nearest_text = "none"
        if lobes:
            nearest = lobes[0]
            element_argument = (
                math.pi * ELEMENT_WIDTH_M / wavelength *
                math.sin(math.radians(nearest["angle_deg"]))
            )
            one_way = abs(sinc_unscaled(element_argument))
            nearest["element_factor_one_way_amplitude"] = one_way
            nearest["element_factor_one_way_db"] = 20.0 * math.log10(max(one_way, 1e-12))
            nearest["estimated_pulse_echo_element_factor_db"] = 40.0 * math.log10(max(one_way, 1e-12))
            nearest_text = "%+.2f deg (m=%+d)" % (nearest["angle_deg"], nearest["order"])
        report["profiles"].append(profile)
        log(
            "S%02d B%02d/P%02d angle=%+5.1f deg counts=%-34s realized-gradient=%+6.2f deg "
            "adj-phase=%+7.2f deg nearest-GL=%s" % (
                profile_number,
                batch_number + 1,
                hardware_profile_number,
                angle,
                str(profile["delay_counts_A1_to_A8"]),
                profile["realized_delay_gradient_angle_deg"],
                profile["mean_adjacent_phase_step_deg_unwrapped"],
                nearest_text,
            )
        )
    return report


class TX7316Controller(object):
    """使用 TI 安裝包自帶的 Device GUI.dll，控制已經打開的 TX7316 GUI。"""

    def __init__(self):
        if not os.path.isfile(TX_PYTHON_MODULE):
            raise AutomationError("TX7316 Python module not found: " + TX_PYTHON_MODULE)
        if imp is not None:
            module = imp.load_source("ti_tx7316_device_gui", TX_PYTHON_MODULE)
        else:
            spec = importlib.util.spec_from_file_location(
                "ti_tx7316_device_gui", TX_PYTHON_MODULE
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.gui = None
        self.application_name = None
        failures = []
        # 先用一次純讀取探測名稱；成功前絕不執行寄存器寫入。
        for application_name in TX_GUI_APPLICATION_CANDIDATES:
            candidate = module.Device_GUI(application_name, TX_GUI_PORT)
            try:
                probe = int(candidate.read_register("GLOBAL", "Register 22")) & 0xffffffff
            except Exception as exc:
                failures.append("%s -> %r" % (application_name, exc))
                continue
            self.gui = candidate
            self.application_name = application_name
            log("TX GUI register tree matched application name %r; Reg22=0x%08X" % (
                application_name, probe))
            break
        if self.gui is None:
            raise AutomationError(
                "Unable to match the TX7316 GUI register tree. Read-only probes failed: " +
                " | ".join(failures)
            )

    @staticmethod
    def reg_name(address):
        return "Register %d" % address

    def read(self, block, address):
        value = self.gui.read_register(block, self.reg_name(address))
        return int(value) & 0xffffffff

    def write(self, block, address, value):
        self.gui.write_register(block, self.reg_name(address), int(value) & 0xffffffff)

    def write_verified(self, block, address, value):
        self.write(block, address, value)
        actual = self.read(block, address)
        expected = int(value) & 0xffffffff
        if actual != expected:
            raise AutomationError(
                "TX register verify failed: %s/%s expected 0x%08X got 0x%08X" % (
                    block, self.reg_name(address), expected, actual
                )
            )

    def pulse_load_profile(self):
        old = self.read("GLOBAL", 0x00)
        self.write("GLOBAL", 0x00, old | 0x00000008)
        # LOAD_PROF 字段值 0x1 位於 Register 0 bit 3，因此整個寄存器寫入的是
        # old|0x8。該位應由芯片自清零；輪詢到清零比固定 sleep 更可靠，也對應
        # GUI 左下角由忙碌回到 Idle 的硬件完成點。
        deadline = time.time() + 2.0
        while time.time() < deadline:
            current = self.read("GLOBAL", 0x00)
            if (current & 0x00000008) == 0:
                time.sleep(0.05)
                return
            time.sleep(0.02)
        raise AutomationError("TX LOAD_PROF did not self-clear within 2 seconds")

    def check_cw_disabled(self):
        reg24 = self.read("GLOBAL", 0x18)
        cw_en_2 = bool(reg24 & (1 << 13))
        cw_en_1 = bool(reg24 & (1 << 14))
        if cw_en_1 or cw_en_2:
            raise AutomationError(
                "Refusing to continue: CW_EN_1 or CW_EN_2 is enabled in GLOBAL/Register 24 "
                "(value=0x%08X). Disable CW in the GUI first." % reg24
            )
        return reg24

    def snapshot_pattern_profile(self, profile_number, reg24, reg25):
        """Read back one 5-level pattern profile and decode its transition timing."""
        if not (0 <= profile_number <= 15):
            raise AutomationError("Pattern profile number must be 0..15")
        base = 0x60 + 8 * profile_number
        # Always read all eight words for bit-for-bit safety verification.
        # Decoding may stop at LVL=7, but the unused trailing words still have
        # to match the qualified reference (normally all zeros).
        registers = [
            self.read("PATTERN-PROFILE", base + offset) for offset in range(8)
        ]
        transitions = []
        ended = False
        for value in registers:
            for byte_index in range(4):
                encoded = (value >> (8 * byte_index)) & 0xff
                level = encoded & 0x7
                period_field = (encoded >> 3) & 0x1f
                transitions.append({
                    "transition": len(transitions) + 1,
                    "level_code": level,
                    "period_field": period_field,
                    "duration_pattern_clocks": period_field + 2,
                })
                if level == 7:
                    ended = True
                    break
            if ended:
                break
        active = [item for item in transitions if item["level_code"] != 7]
        base_pattern_clocks = sum(item["duration_pattern_clocks"] for item in active)
        clk_div = (reg24 >> 3) & 0x7
        pattern_clock_hz = 200000000.0 / float(2 ** clk_div)
        nominal_hz = pattern_clock_hz / float(base_pattern_clocks) if base_pattern_clocks else None
        return {
            "profile_number": profile_number,
            "register_start": "0x%02X" % base,
            "registers": ["0x%08X" % value for value in registers],
            "transitions": transitions,
            "base_pattern_clocks": base_pattern_clocks,
            "pattern_clock_hz": pattern_clock_hz,
            "nominal_base_pattern_hz": nominal_hz,
            "repeat_count_field": (reg25 >> 1) & 0x1f,
            "acoustic_cycles_from_repeat": ((reg25 >> 1) & 0x1f) + 1,
            "tail_count_field": (reg25 >> 6) & 0x1f,
            "register24": "0x%08X" % reg24,
            "register25": "0x%08X" % reg25,
        }

    def program_known_pattern_profile0(self, profile):
        """Program and bit-for-bit verify one whitelisted five-level profile.

        The caller must have made sure that the transmitter is idle.  This
        method additionally forces TX_BF_MODE off before touching profile RAM,
        keeps the existing TX_START_DEL/TR switch controls, selects CLK_DIV=0,
        disables elastography mode, then pulses LOAD_PROF and reads everything
        back.  It returns the previous pattern registers for cleanup.
        """
        self.set_internal_bf(False)
        original_pattern_registers = [
            self.read("PATTERN-PROFILE", 0x60 + offset) for offset in range(8)
        ]
        reg24 = self.read("GLOBAL", 0x18)
        reg25 = self.read("GLOBAL", 0x19)

        # CLK_DIV is bits 5:3.  Preserve TX_START_DEL, TR switch mode, drive
        # settings and all unrelated controls; TX_BF_MODE stays off here.
        programmed_reg24 = (reg24 & ~0x39) & 0xffffffff
        # Replace REPEAT_COUNT/TAIL_COUNT (bits 10:1), force elastography off
        # (bit 11), and preserve all other power-control fields.  On this EVM's
        # GUI/ActiveX path a LOAD_PROF operation is observed to restore Reg25's
        # low fields to the GUI's prior value, so Reg25 is deliberately written
        # *after* LOAD_PROF and verified again before any transmit is enabled.
        programmed_reg25 = (
            (reg25 & ~0x00000ffe) | (profile["register25"] & 0x000007fe)
        ) & 0xffffffff
        self.write_verified("GLOBAL", 0x18, programmed_reg24)
        for offset, value in enumerate(profile["registers"]):
            self.write_verified("PATTERN-PROFILE", 0x60 + offset, value)
        self.pulse_load_profile()
        self.write_verified("GLOBAL", 0x19, programmed_reg25)

        actual_reg24 = self.read("GLOBAL", 0x18)
        actual_reg25 = self.read("GLOBAL", 0x19)
        actual_registers = [
            self.read("PATTERN-PROFILE", 0x60 + offset) for offset in range(8)
        ]
        if (actual_reg24 & 0x38) != 0:
            raise AutomationError(
                "TX pattern verify failed: CLK_DIV is not zero (Reg24=0x%08X)" %
                actual_reg24
            )
        if (actual_reg25 & 0x000007fe) != (profile["register25"] & 0x000007fe):
            raise AutomationError(
                "TX pattern verify failed: Reg25 expected low fields 0x%03X got 0x%03X" % (
                    profile["register25"] & 0x000007fe,
                    actual_reg25 & 0x000007fe,
                )
            )
        if actual_registers != profile["registers"]:
            raise AutomationError(
                "TX pattern verify failed: profile0 readback does not match programmed words"
            )
        return {
            "original_pattern_registers": original_pattern_registers,
            "programmed_register24": actual_reg24,
            "programmed_register25": actual_reg25,
            "programmed_pattern_registers": actual_registers,
        }

    def set_internal_bf(self, enabled):
        reg24 = self.read("GLOBAL", 0x18)
        new_value = reg24 | 0x1 if enabled else reg24 & 0xfffffffe
        if new_value != reg24:
            self.write_verified("GLOBAL", 0x18, new_value)
        return new_value

    def force_internal_bf_off(self, attempts=3):
        """Fail closed, while tolerating one transient FTDI readback error.

        Enabling transmit is never retried.  Disabling is safe to retry because
        the first write may already have succeeded even when its readback
        raised an FTDI I/O exception.
        """
        failures = []
        for attempt in range(1, int(attempts) + 1):
            try:
                value = self.set_internal_bf(False)
                if failures:
                    log("TX_BF_MODE OFF verified on retry %d/%d." % (
                        attempt, attempts
                    ))
                return value
            except Exception as exc:
                failures.append(repr(exc))
                if attempt < attempts:
                    log("WARNING: TX_BF_MODE OFF attempt %d/%d failed; retrying readback..." % (
                        attempt, attempts
                    ))
                    time.sleep(0.15)
        raise AutomationError(
            "Unable to verify TX_BF_MODE OFF after %d attempts: %s" % (
                attempts, " | ".join(failures)
            )
        )

    def select_g1_profile(self, profile_number):
        if not (0 <= profile_number <= 15):
            raise AutomationError("Profile number must be 0..15")
        reg22 = self.read("GLOBAL", 0x16)
        new_value = (reg22 & 0x0fffffff) | ((profile_number & 0xf) << 28)
        self.write_verified("GLOBAL", 0x16, new_value)
        self.pulse_load_profile()
        return new_value

    def program_profiles(self, profiles):
        originals = {}
        for profile in profiles:
            hardware_profile_number = profile.get(
                "hardware_profile_number", profile["profile_number"]
            )
            registers = pack_delay_profile_registers(
                hardware_profile_number, profile["delay_counts_A1_to_A8"]
            )
            for address, value in sorted(registers.items()):
                if address not in originals:
                    originals[address] = self.read("DELAY-PROFILE", address)
                self.write_verified("DELAY-PROFILE", address, value)
                log("TX wrote sequence %02d -> hardware P%02d Register %d = 0x%08X" % (
                    profile["profile_number"], hardware_profile_number, address, value))
        self.pulse_load_profile()
        return originals


class HSDCController(object):
    """HSDC Pro 32-bit Automation DLL 的最小、可檢錯封裝。"""

    def __init__(self, timeout_ms):
        if not os.path.isfile(HSDC_DLL):
            raise AutomationError("HSDC automation DLL not found: " + HSDC_DLL)
        self.timeout_ms = int(timeout_ms)
        self.connected_by_this_process = False
        self.dll = ctypes.cdll.LoadLibrary(HSDC_DLL)
        self._configure_return_types()
        try:
            version = self.dll.Automation_DLL_Version()
            log("HSDC Automation DLL version: %s" % version)
        except Exception:
            pass

    def _configure_return_types(self):
        names = [
            "Pass_ADC_Output_Data_Rate", "Set_Number_of_Samples", "Trigger_Option",
            "Pass_Capture_Event", "Generate_Software_Trigger", "Read_DDR_Memory",
            "HSDC_Ready", "Connect_Board", "Disconnect_Board", "Select_AFE_Device",
            "Reload_Device_INI", "ADC_Average_Settings_with_Average_TimeDomain",
            "Set_Write_Capture_to_File", "ADC_Save_Raw_Data_As_Binary_File",
            "ADC_Test_Selection", "Get_Number_of_Samples_Per_Channel", "Get_Error_Status",
        ]
        for name in names:
            if hasattr(self.dll, name):
                getattr(self.dll, name).restype = ctypes.c_int32
        if hasattr(self.dll, "Automation_DLL_Version"):
            self.dll.Automation_DLL_Version.restype = ctypes.c_double

    @staticmethod
    def _bytes(text):
        if isinstance(text, unicode):
            return text.encode("mbcs")
        return str(text)

    def error_text(self):
        buffer_value = ctypes.create_string_buffer(2048)
        try:
            self.dll.Get_Error_Status(
                ctypes.c_int32(len(buffer_value)),
                ctypes.c_int32(self.timeout_ms),
                buffer_value,
            )
            return buffer_value.value.decode("mbcs", "replace")
        except Exception as exc:
            return "unable to read HSDC error text: %s" % exc

    def call(self, name, *args, **kwargs):
        progress_path = kwargs.pop("progress_path", None)
        expected_bytes = kwargs.pop("expected_bytes", None)
        if kwargs:
            raise TypeError("Unexpected HSDC call options: %r" % sorted(kwargs.keys()))
        function = getattr(self.dll, name)
        heartbeat = ConsoleHeartbeat(
            "HSDC " + name,
            progress_path=progress_path,
            expected_bytes=expected_bytes,
        )
        heartbeat.start()
        try:
            code = int(function(*args))
        finally:
            heartbeat.stop()
        if code != 0:
            raise AutomationError("HSDC %s failed, code=%d: %s" % (
                name, code, self.error_text()))
        log("HSDC %-44s OK" % name)

    def configure(
        self, samples, trigger_mode, full_setup, board_serial, device_name,
        enable_capture_to_file_streaming=False, sample_rate_hz=ADC_SAMPLE_RATE_HZ,
    ):
        timeout = ctypes.c_int32(self.timeout_ms)
        if full_setup:
            self.call(
                "Connect_Board",
                ctypes.c_char_p(self._bytes(board_serial)),
                timeout,
            )
            self.connected_by_this_process = True
            # RXTX=0 代表 AFE RX。
            self.call(
                "Select_AFE_Device",
                ctypes.c_char_p(self._bytes(device_name)),
                ctypes.c_uint16(0),
                ctypes.c_int32(max(self.timeout_ms, 120000)),
            )
            self.call("Reload_Device_INI", timeout)
        self.call("HSDC_Ready", ctypes.c_int32(max(self.timeout_ms, 120000)))
        self.call(
            "Pass_ADC_Output_Data_Rate",
            ctypes.c_double(float(sample_rate_hz)),
            timeout,
        )
        self.call(
            "Set_Number_of_Samples",
            ctypes.c_ulonglong(int(samples)),
            timeout,
        )
        # 關閉 HSDC 平均；超聲 RF 原始數據必須逐次保留。
        self.call(
            "ADC_Average_Settings_with_Average_TimeDomain",
            ctypes.c_int32(0), ctypes.c_int32(0), ctypes.c_int32(1), timeout,
        )
        # 不調用 Set_Write_Capture_to_File：在 TSW14J50/目前 HSDC 狀態下，該 API
        # 會嘗試配置不需要的 capture-to-file streaming ports，並返回
        # PORTS_NOT_CONFIGURED_ERROR。逐角度捕獲後我們會顯式調用
        # ADC_Save_Raw_Data_As_Binary_File，因此不需要這個 GUI 選項。
        #
        # 也不切換 ADC_Test_Selection；Capture 和保存 DDR raw data 不依賴當前
        # 顯示頁面，保留用戶目前的 Time Domain 畫面更安全。
        if enable_capture_to_file_streaming:
            # 預留給下一版連續/近實時數據管線。這不是當前逐角度離線保存所需的
            # API；只有 Board/Device INI 已完成 ports 配置、且未來的文件輪轉與
            # 消費者速度控制已實現後才應顯式開啟。
            self.call("Set_Write_Capture_to_File", ctypes.c_ubyte(1), timeout)
            log("HSDC capture-to-file streaming ENABLED (experimental future mode).")
        if trigger_mode == "hardware":
            # SYNCP from the stock TX7316EVM CPLD is free-running even while
            # TX_BF_MODE is OFF. Arming here could capture before an angle
            # profile is selected. Keep HSDC disarmed until capture().
            self.set_trigger("normal")
            log("HSDC external trigger left DISARMED during setup.")
        elif trigger_mode == "normal" and not full_setup:
            # HSDC GUI 已由用戶設為可手動 Capture 的 Normal 模式。復用 GUI 狀態時
            # 不再調 Trigger_Option，避免該 API 重新配置 TSW ports；下一步直接用
            # Pass_Capture_Event，行為等同手工點擊 Capture。
            log("HSDC reusing current GUI Normal Trigger state.")
        else:
            self.set_trigger(trigger_mode)

    def disconnect(self):
        """Release only the HSDC session opened by this process.

        The GUI remains open.  Releasing the Automation DLL connection avoids
        leaving a stale client behind, which otherwise makes a later run fail
        at Connect_Board with TI error 66 (Connection Closed/restart GUI).
        """
        if not self.connected_by_this_process:
            return
        try:
            self.call("Disconnect_Board", ctypes.c_int32(self.timeout_ms))
        finally:
            self.connected_by_this_process = False

    def set_trigger(self, trigger_mode):
        timeout = ctypes.c_int32(self.timeout_ms)
        if trigger_mode == "normal":
            values = (0, 0, 0, 0)
        elif trigger_mode == "software":
            values = (1, 1, 0, 0)
        elif trigger_mode == "hardware":
            values = (1, 0, 0, 0)
        else:
            raise AutomationError("Unknown trigger mode: " + trigger_mode)
        self.call(
            "Trigger_Option",
            ctypes.c_int32(values[0]), ctypes.c_int32(values[1]),
            ctypes.c_int32(values[2]), ctypes.c_ubyte(values[3]), timeout,
        )

    def capture(self, trigger_mode):
        timeout = ctypes.c_int32(self.timeout_ms)
        if trigger_mode == "normal":
            self.call("Pass_Capture_Event", timeout)
        elif trigger_mode == "software":
            self.call("Generate_Software_Trigger", ctypes.c_int32(1), timeout)
        elif trigger_mode == "hardware":
            # 這個調用會等待 TSW J13 的外部觸發；未接線會超時。
            # Arm only after the caller has selected the angle profile,
            # enabled TX_BF_MODE and allowed the transmitter to settle. The
            # next SYNCP rising edge starts one contiguous N-sample DDR block.
            self.set_trigger("hardware")
            try:
                self.call("Read_DDR_Memory", ctypes.c_int32(1), timeout)
            finally:
                # Free-running SYNCP must not start a record during profile
                # changes or the slow BIN save operation.
                self.set_trigger("normal")
        else:
            raise AutomationError("Unknown trigger mode: " + trigger_mode)

    def save_binary(self, path, expected_bytes=None):
        try:
            self.call(
                "ADC_Save_Raw_Data_As_Binary_File",
                ctypes.c_char_p(self._bytes(os.path.abspath(path))),
                ctypes.c_int32(self.timeout_ms),
                progress_path=path,
                expected_bytes=expected_bytes,
            )
            return {
                "api_returned_ok": True,
                "completed_after_api_error": False,
            }
        except AutomationError as exc:
            # Observed with HSDC Pro 5.31 / Automation DLL 3.7: for 256 MiB and
            # larger files the call can return code 5000 (LabVIEW Variant To
            # Data conversion) before the GUI's background writer is done.  Do
            # not retry the save because that can start a second writer against
            # the same path.  Accept only an exact, stable final file.
            if not expected_bytes:
                raise
            expected_mib = expected_bytes / float(1024 ** 2)
            recovery_timeout = min(900.0, max(180.0, expected_mib * 3.0))
            log(
                "WARNING: HSDC save API returned an error, but HSDC Pro may still "
                "be writing in the background: %r" % exc
            )
            log(
                "Waiting up to %.0f seconds for an exact, stable %.1f MiB BIN; "
                "do not close or click HSDC Pro..." % (
                    recovery_timeout, expected_mib,
                )
            )
            heartbeat = ConsoleHeartbeat(
                "HSDC background BIN completion",
                progress_path=path,
                expected_bytes=expected_bytes,
            )
            heartbeat.start()
            try:
                completed = wait_for_completed_file(
                    path,
                    expected_bytes,
                    recovery_timeout,
                )
            finally:
                heartbeat.stop()
            if not completed:
                raise
            log(
                "RECOVERED: HSDC completed the BIN after its Automation API "
                "returned an error; exact size and write stability verified."
            )
            return {
                "api_returned_ok": False,
                "completed_after_api_error": True,
                "api_error": repr(exc),
            }


def make_filename(angle_deg, profile_number, repeat_index):
    if abs(angle_deg - round(angle_deg)) < 1e-9:
        angle_value = "%02d" % abs(int(round(angle_deg)))
    else:
        angle_value = ("%05.2f" % abs(angle_deg)).replace(".", "p")
    sign = "m" if angle_deg < 0 else "p"
    if abs(angle_deg) < 1e-12:
        sign = "p"
    frequency_mhz = CENTER_FREQUENCY_HZ / 1e6
    frequency_text = ("%.3f" % frequency_mhz).rstrip("0").rstrip(".").replace(".", "p")
    return "gel_%sMHz_angle_%s%s_P%d_R%02d.bin" % (
        frequency_text, sign, angle_value, profile_number, repeat_index)


def make_parser():
    parser = argparse.ArgumentParser(
        description="Automate TX7316 delay profiles and HSDC Pro angle captures."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="calculate only; touch no hardware")
    mode.add_argument("--capture", action="store_true", help="perform real hardware capture")
    mode.add_argument(
        "--program-tx-only",
        action="store_true",
        help=(
            "program and verify the selected whitelisted Pattern Profile 0, "
            "leave TX_BF_MODE off, and do not connect to HSDC or capture data"
        ),
    )
    parser.add_argument(
        "--angles", type=parse_angles,
        default=list(DEFAULT_ANGLES_DEG),
        help="comma-separated degrees; use --angles=-8,-6,...,+8",
    )
    parser.add_argument("--reverse-angle-sign", action="store_true")
    parser.add_argument("--allow-large-steering", action="store_true")
    parser.add_argument(
        "--tx-elements", type=int, default=TX_ELEMENTS,
        help="active physical elements connected consecutively to A1..AN (2..8)",
    )
    parser.add_argument(
        "--rx-channels", type=parse_rx_channels,
        default=list(range(1, 9)),
        help="1-based HSDC slots connected in order to physical A1..AN",
    )
    parser.add_argument(
        "--pitch-mm", type=float, default=ELEMENT_PITCH_M * 1e3,
        help="physical center-to-center element pitch in millimetres",
    )
    parser.add_argument(
        "--element-width-mm", type=float, default=ELEMENT_WIDTH_M * 1e3,
        help="active element width in the steering direction",
    )
    parser.add_argument(
        "--center-frequency-mhz", type=float, default=CENTER_FREQUENCY_HZ / 1e6,
        help="transmit/receive centre frequency used for wavelength and phase reports",
    )
    parser.add_argument(
        "--waveform-mode",
        choices=["tapered-5level", "bipolar-a"],
        default="tapered-5level",
        help="TX Profile 0 waveform library; bipolar-a is the 1.493 MHz PHV_A/MHV_A diagnostic",
    )
    parser.add_argument(
        "--tx-cycles", type=int, default=4,
        help="verified burst cycles; allowed values are 1,2,4,6,8,10,12",
    )
    parser.add_argument(
        "--expected-hv-a-v", type=float, default=0.0,
        help="operator-measured external +/-HV_A magnitude; metadata only, never programmed",
    )
    parser.add_argument(
        "--expected-hv-b-v", type=float, default=0.0,
        help="operator-measured external +/-HV_B magnitude; metadata only, never programmed",
    )
    parser.add_argument(
        "--sound-speed-m-s", type=float, default=SOUND_SPEED_M_S,
        help="assumed propagation speed for delay-law calculation",
    )
    parser.add_argument(
        "--delay-quantum-ns", type=float, default=TX_DELAY_QUANTUM_S * 1e9,
        help="TX7316 beamforming delay count duration; verify after BF clock changes",
    )
    parser.add_argument("--samples", type=int, default=SAMPLES_PER_CHANNEL)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--expected-prf-hz", type=float, default=0.0,
        help="metadata/QA value for the pulse repetition frequency",
    )
    parser.add_argument(
        "--expected-prfs-per-bin", type=int, default=0,
        help="metadata/QA count of complete PRF emissions expected in each BIN",
    )
    parser.add_argument("--settle-seconds", type=float, default=0.25)
    parser.add_argument("--timeout-ms", type=int, default=HSDC_DEFAULT_TIMEOUT_MS)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--trigger", choices=["normal", "software", "hardware"], default="normal"
    )
    parser.add_argument(
        "--reuse-hsdc-state", action="store_true",
        help="do not reconnect/reselect HSDC device; still set rate, samples and trigger",
    )
    parser.add_argument(
        "--enable-hsdc-capture-to-file-streaming", action="store_true",
        help="reserved experimental mode; default OFF for current offline captures",
    )
    parser.add_argument(
        "--no-program-profiles", action="store_false", dest="program_profiles", default=True,
        help="use delay profile contents already present in TX7316",
    )
    parser.add_argument(
        "--enable-internal-bf", action="store_true",
        help="allow script to enable TX_BF_MODE for capture; value is restored at exit",
    )
    parser.add_argument(
        "--keep-tx-state", action="store_true",
        help="leave final profile and TX_BF_MODE active; not recommended",
    )
    parser.add_argument(
        "--allow-pattern-mismatch", action="store_true",
        help="diagnostic override: capture even when the known-frequency pattern readback differs",
    )
    parser.add_argument(
        "--program-known-pattern", action="store_true",
        help="with TX idle, write and verify the whitelisted 1/1.5/2/2.5/4 MHz profile0 before capture",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--skip-file-qa", action="store_true",
        help="skip post-save uint16 min/max and rail-code scan",
    )
    return parser


def pattern_library_for_mode(waveform_mode):
    if waveform_mode == "bipolar-a":
        return BIPOLAR_A_PATTERN_PROFILES
    return KNOWN_PATTERN_PROFILES


def pattern_profile_with_cycles(profile, cycles):
    """Return a copy of a qualified base pattern with a safe repeat count."""
    cycles = int(cycles)
    result = dict(profile)
    result["registers"] = list(profile["registers"])
    repeat_field = cycles - 1
    result["register25"] = (
        (int(profile["register25"]) & ~0x0000003e) |
        ((repeat_field & 0x1f) << 1)
    ) & 0xffffffff
    result["acoustic_cycles"] = cycles
    result["name"] = "%s_%dcycles" % (profile["name"], cycles)
    return result


def known_pattern_key_for_frequency(frequency_mhz, waveform_mode="tapered-5level"):
    """Return the exact whitelisted pattern key for a requested MHz value."""
    library = pattern_library_for_mode(waveform_mode)
    for candidate in sorted(library):
        if abs(float(frequency_mhz) - candidate) < 1e-9:
            return candidate
    return None


def validate_arguments(args):
    if not args.angles:
        raise AutomationError("--angles must contain at least one value")
    if len(args.angles) > MAX_SWEEP_ANGLES:
        raise AutomationError("--angles exceeds the %d-angle safety limit" % MAX_SWEEP_ANGLES)
    if any(args.angles[index] >= args.angles[index + 1] for index in range(len(args.angles) - 1)):
        raise AutomationError("--angles must be unique and strictly increasing")
    if len(args.angles) > HARDWARE_DELAY_PROFILES_PER_BATCH and not args.program_profiles:
        raise AutomationError(
            "More than 16 angles requires automatic profile batching; remove --no-program-profiles"
        )
    if not (2 <= args.tx_elements <= 8):
        raise AutomationError("--tx-elements must be in the range 2..8 for TX7316 G1/A1-A8")
    if len(args.rx_channels) != args.tx_elements:
        raise AutomationError("--rx-channels count must equal --tx-elements")
    if len(set(args.rx_channels)) != len(args.rx_channels) or any(
            slot < 1 or slot > RX_CHANNELS_IN_FILE for slot in args.rx_channels):
        raise AutomationError("--rx-channels must be unique 1-based HSDC slots in 1..16")
    if args.pitch_mm <= 0:
        raise AutomationError("--pitch-mm must be positive")
    if args.element_width_mm <= 0 or args.element_width_mm > args.pitch_mm:
        raise AutomationError("--element-width-mm must be positive and no larger than pitch")
    if args.center_frequency_mhz <= 0:
        raise AutomationError("--center-frequency-mhz must be positive")
    known_pattern_key = known_pattern_key_for_frequency(
        args.center_frequency_mhz, args.waveform_mode
    )
    if args.program_known_pattern and known_pattern_key is None:
        if args.waveform_mode == "bipolar-a":
            raise AutomationError(
                "--waveform-mode bipolar-a currently supports exactly 1.5 MHz"
            )
        raise AutomationError(
            "--program-known-pattern with tapered-5level supports exactly "
            "1, 1.5, 2, 2.5 or 4 MHz"
        )
    if args.tx_cycles not in (1, 2, 4, 6, 8, 10, 12):
        raise AutomationError("--tx-cycles must be one of 1,2,4,6,8,10,12")
    supply_values = (args.expected_hv_a_v, args.expected_hv_b_v)
    if any(value != 0.0 for value in supply_values):
        if not all(1.5 <= value <= 100.0 for value in supply_values):
            raise AutomationError(
                "--expected-hv-a-v and --expected-hv-b-v must both be in 1.5..100 V"
            )
        if (
            args.waveform_mode == "tapered-5level" and
            args.expected_hv_a_v <= args.expected_hv_b_v
        ):
            raise AutomationError(
                "expected external HV_A (outer rail) magnitude must be greater than HV_B (inner rail)"
            )
    if not (1000.0 <= args.sound_speed_m_s <= 2000.0):
        raise AutomationError("--sound-speed-m-s must be between 1000 and 2000")
    if args.delay_quantum_ns <= 0:
        raise AutomationError("--delay-quantum-ns must be positive")
    if args.samples <= 0 or args.samples % 4096 != 0:
        raise AutomationError("--samples must be a positive multiple of 4096")
    if args.repeats <= 0:
        raise AutomationError("--repeats must be positive")
    if args.expected_prf_hz < 0:
        raise AutomationError("--expected-prf-hz cannot be negative")
    if args.expected_prfs_per_bin < 0:
        raise AutomationError("--expected-prfs-per-bin cannot be negative")
    if args.settle_seconds < 0:
        raise AutomationError("--settle-seconds cannot be negative")
    if max(abs(x) for x in args.angles) > RECOMMENDED_MAX_STEER_DEG and not args.allow_large_steering:
        raise AutomationError(
            "Requested steering exceeds +/-%.1f deg. With 1.59 mm pitch this has severe aliasing. "
            "Use --allow-large-steering only for a deliberate experiment." % RECOMMENDED_MAX_STEER_DEG
        )


def apply_runtime_array_configuration(args):
    """Apply UI/CLI array parameters before any delay or grating-lobe calculation."""
    global TX_ELEMENTS
    global ELEMENT_PITCH_M
    global ELEMENT_WIDTH_M
    global CENTER_FREQUENCY_HZ
    global SOUND_SPEED_M_S
    global TX_DELAY_QUANTUM_S

    TX_ELEMENTS = int(args.tx_elements)
    ELEMENT_PITCH_M = float(args.pitch_mm) * 1e-3
    ELEMENT_WIDTH_M = float(args.element_width_mm) * 1e-3
    CENTER_FREQUENCY_HZ = float(args.center_frequency_mhz) * 1e6
    SOUND_SPEED_M_S = float(args.sound_speed_m_s)
    TX_DELAY_QUANTUM_S = float(args.delay_quantum_ns) * 1e-9


def program_tx_pattern_only(args, known_profile):
    """Persist one verified pattern in TX7316 RAM without enabling transmit."""
    require_32bit_python()
    if not is_windows_admin():
        raise AutomationError(
            "TX pattern programming requires Administrator. Run TX7316 GUI and "
            "the Collector with the same elevated privilege."
        )
    if known_profile is None:
        raise AutomationError("No whitelisted TX pattern matches the requested plan")

    tx = None
    try:
        log("PROGRAM TX ONLY: connecting to TX7316 GUI; HSDC will not be opened.")
        tx = TX7316Controller()
        tx.force_internal_bf_off()
        tx.check_cw_disabled()
        programmed = tx.program_known_pattern_profile0(known_profile)
        reg24 = tx.force_internal_bf_off()
        reg25 = tx.read("GLOBAL", 0x19)
        snapshot = tx.snapshot_pattern_profile(0, reg24, reg25)
        expected_registers = [
            "0x%08X" % value for value in known_profile["registers"]
        ]
        matches = (
            (reg24 & 0x1) == 0 and
            (reg24 & 0x38) == 0 and
            (reg25 & 0x000007fe) ==
            (known_profile["register25"] & 0x000007fe) and
            snapshot["registers"] == expected_registers
        )
        if not matches:
            raise AutomationError(
                "TX program-only final readback failed; TX_BF_MODE remains forced OFF"
            )
        active_transitions = [
            item for item in snapshot["transitions"] if item["level_code"] != 7
        ]
        log("PROGRAM TX ONLY COMPLETE: %s" % known_profile["name"])
        log("Profile 0 registers 0x60..0x67: %s" % " ".join(snapshot["registers"]))
        log(
            "Decoded: transitions=%d repeat_field=%d acoustic_cycles=%d "
            "tail_field=%d nominal=%.6f MHz" % (
                len(active_transitions),
                snapshot["repeat_count_field"],
                snapshot["acoustic_cycles_from_repeat"],
                snapshot["tail_count_field"],
                (snapshot["nominal_base_pattern_hz"] or 0.0) / 1e6,
            )
        )
        log("SAFETY: TX_BF_MODE=OFF verified; pattern is stored but not transmitting.")
        return programmed
    finally:
        if tx is not None:
            tx.force_internal_bf_off()


def main(argv=None):
    global LOG_HANDLE
    args = make_parser().parse_args(argv)
    if disable_console_quick_edit():
        print("Console QuickEdit disabled: mouse clicks can no longer pause acquisition.")
    else:
        print("WARNING: unable to disable Console QuickEdit; do not click inside the acquisition console.")
    # 沒寫模式時，默認安全的 Dry Run。
    if not args.capture and not args.program_tx_only:
        args.dry_run = True
    if args.program_tx_only:
        # This explicit mode is itself the authorization to use the whitelist.
        # It never enables TX_BF_MODE and never connects to HSDC.
        args.program_known_pattern = True
    validate_arguments(args)
    # This value is needed later, after the run directory and manifest have
    # been created.  Keep it in main's scope; validate_arguments intentionally
    # performs validation only and does not export local state.
    known_pattern_key = known_pattern_key_for_frequency(
        args.center_frequency_mhz, args.waveform_mode
    )
    pattern_library = pattern_library_for_mode(args.waveform_mode)
    apply_runtime_array_configuration(args)

    report = array_report(args.angles, args.reverse_angle_sign)
    report["rx_hsdc_slots_1_based"] = list(args.rx_channels)
    if args.dry_run:
        if known_pattern_key is not None:
            dry_profile = pattern_profile_with_cycles(
                pattern_library[known_pattern_key], args.tx_cycles
            )
            log(
                "TX PLAN: %s, frequency=%.6f MHz, cycles=%d, Reg25 low fields=0x%03X" % (
                    dry_profile["name"],
                    args.center_frequency_mhz,
                    args.tx_cycles,
                    dry_profile["register25"] & 0x000007fe,
                )
            )
        log(
            "EXTERNAL SUPPLY RECORD ONLY: +/-HV_A=%s V, +/-HV_B=%s V; not programmed by SPI." % (
                str(args.expected_hv_a_v or "not provided"),
                str(args.expected_hv_b_v or "not provided"),
            )
        )
        log("DRY RUN COMPLETE: no GUI connection, no TX write, no capture.")
        return 0

    if args.program_tx_only:
        known_profile = (
            pattern_library.get(known_pattern_key)
            if known_pattern_key is not None else None
        )
        if known_profile is not None:
            known_profile = pattern_profile_with_cycles(
                known_profile, args.tx_cycles
            )
        program_tx_pattern_only(args, known_profile)
        return 0

    require_32bit_python()
    if not is_windows_admin():
        raise AutomationError(
            "Capture mode requires Administrator. Run TX7316 GUI, HSDC Pro, and this script "
            "all as Administrator."
        )

    output_root = os.path.abspath(args.output_root)
    run_dir = os.path.join(output_root, "capture_" + local_stamp())
    if os.path.exists(run_dir) and not args.overwrite:
        raise AutomationError("Output directory already exists: " + run_dir)
    if not os.path.isdir(run_dir):
        os.makedirs(run_dir)

    LOG_HANDLE = open(os.path.join(run_dir, "run.log"), "ab")
    log("Run directory: " + run_dir)

    expected_file_bytes = args.samples * RX_CHANNELS_IN_FILE * BYTES_PER_SAMPLE
    expected_total_bytes = expected_file_bytes * len(args.angles) * args.repeats
    free_bytes = free_bytes_for_path(run_dir)
    log("Expected data: %d files, %.3f GiB total" % (
        len(args.angles) * args.repeats,
        expected_total_bytes / float(1024 ** 3),
    ))
    manifest_path = os.path.join(run_dir, "capture_manifest.json")
    manifest = {
        "status": "initializing",
        "created_utc": utc_now_text(),
        "script": os.path.abspath(__file__),
        "python": sys.executable,
        "arguments": vars(args),
        "expected_prf_hz": args.expected_prf_hz or None,
        "expected_prfs_per_bin": args.expected_prfs_per_bin or None,
        "tx_plan": {
            "waveform_mode": args.waveform_mode,
            "requested_frequency_mhz": args.center_frequency_mhz,
            "requested_cycles": args.tx_cycles,
            "external_supply_is_metadata_only": True,
            "expected_external_supply_magnitude_v": {
                "hv_a": args.expected_hv_a_v or None,
                "hv_b": args.expected_hv_b_v or None,
            },
        },
        "array": report,
        "hsdc": {
            "board_serial": None,
            "firmware": None,
            "device": None,
            "persisted_device_before_setup": None,
            "device_ini_sha256": None,
            "sample_rate_hz": ADC_SAMPLE_RATE_HZ,
            "samples_per_channel": args.samples,
            "channels_in_file": RX_CHANNELS_IN_FILE,
            "bytes_per_sample": BYTES_PER_SAMPLE,
            "expected_file_bytes": expected_file_bytes,
            "trigger": args.trigger,
            "capture_to_file_streaming_enabled": bool(
                args.enable_hsdc_capture_to_file_streaming
            ),
        },
        "tx_original": {},
        "tx_delay_registers_before_programming": {},
        "captures": [],
    }
    json_write_atomic(manifest_path, manifest)

    tx = None
    hsdc = None
    original_reg22 = None
    original_reg24 = None
    original_reg25 = None
    original_pattern_registers = None
    active_pattern_reg25 = None
    error = None
    try:
        if free_bytes is not None and free_bytes < expected_total_bytes + 512 * 1024 * 1024:
            raise AutomationError("Not enough disk space with 512 MiB safety margin")
        (
            hsdc_board_serial,
            hsdc_firmware,
            hsdc_device,
            hsdc_persisted_device,
        ) = read_hsdc_persisted_settings(
            args.trigger, allow_reselect=not args.reuse_hsdc_state
        )
        manifest["hsdc"].update({
            "board_serial": hsdc_board_serial,
            "firmware": hsdc_firmware,
            "device": hsdc_device,
            "persisted_device_before_setup": hsdc_persisted_device,
            "device_ini_sha256": (
                HSDC_AFE_RX_TI_VENDOR_SHA256
                if hsdc_device == HSDC_AFE_RX_TI_VENDOR_DEVICE else None
            ),
        })
        json_write_atomic(manifest_path, manifest)
        log("Connecting to TX7316 GUI using %s..." % TX_GUI_PORT_LABEL)
        tx = TX7316Controller()
        original_reg22 = tx.read("GLOBAL", 0x16)
        original_reg24 = tx.check_cw_disabled()
        original_reg25 = tx.read("GLOBAL", 0x19)
        manifest["tx_original"] = {
            "gui_application_name": tx.application_name,
            "register22": "0x%08X" % original_reg22,
            "register24": "0x%08X" % original_reg24,
            "register25": "0x%08X" % original_reg25,
            "selected_g1_profile": (original_reg22 >> 28) & 0xf,
            "internal_bf_enabled": bool(original_reg24 & 0x1),
        }
        known_profile = (
            pattern_library.get(known_pattern_key)
            if known_pattern_key is not None else None
        )
        if known_profile is not None:
            known_profile = pattern_profile_with_cycles(known_profile, args.tx_cycles)
        if args.program_known_pattern:
            log(
                "External supply record only (not SPI-programmable): +/-HV_A=%s V, +/-HV_B=%s V" % (
                    str(args.expected_hv_a_v or "not provided"),
                    str(args.expected_hv_b_v or "not provided"),
                )
            )
            log("TX pattern programming requested for %s" % known_profile["name"])
            # Take the cleanup snapshot before the first profile-memory write.
            # If programming or verification fails halfway through, finally
            # can still restore the original eight words and Reg25.
            original_pattern_registers = [
                tx.read("PATTERN-PROFILE", 0x60 + offset) for offset in range(8)
            ]
            programmed = tx.program_known_pattern_profile0(known_profile)
            active_pattern_reg25 = programmed["programmed_register25"]
            manifest["tx_pattern_programming"] = {
                "requested": True,
                "reference_name": known_profile["name"],
                "requested_cycles": args.tx_cycles,
                "register24_after": "0x%08X" % programmed["programmed_register24"],
                "register25_after": "0x%08X" % programmed["programmed_register25"],
                "profile0_after": [
                    "0x%08X" % value
                    for value in programmed["programmed_pattern_registers"]
                ],
            }

        active_reg24 = tx.read("GLOBAL", 0x18)
        active_reg25 = tx.read("GLOBAL", 0x19)
        waveform_readback = tx.snapshot_pattern_profile(0, active_reg24, active_reg25)
        manifest["tx_waveform_readback"] = waveform_readback
        if known_profile is not None:
            expected_registers = [
                "0x%08X" % value for value in known_profile["registers"]
            ]
            actual_registers = waveform_readback["registers"][:8]
            pattern_matches = (
                (active_reg24 & 0x38) == 0 and
                (active_reg25 & 0x000007fe) ==
                (known_profile["register25"] & 0x000007fe) and
                actual_registers == expected_registers
            )
            waveform_readback["reference_name"] = known_profile["name"]
            waveform_readback["reference_register25"] = (
                "0x%08X" % known_profile["register25"]
            )
            waveform_readback["reference_registers_0x60_to_0x67"] = expected_registers
            waveform_readback["reference_matches"] = bool(pattern_matches)
            waveform_readback["requested_frequency_mhz"] = args.center_frequency_mhz
            waveform_readback["requested_acoustic_cycles"] = args.tx_cycles
            waveform_readback["expected_nominal_base_pattern_hz"] = known_profile[
                "nominal_base_pattern_hz"
            ]
            json_write_atomic(manifest_path, manifest)
            log(
                "TX waveform readback: reference=%s Reg25=0x%08X nominal=%.6f MHz match=%s" % (
                    known_profile["name"],
                    active_reg25,
                    (waveform_readback["nominal_base_pattern_hz"] or 0.0) / 1e6,
                    str(bool(pattern_matches)),
                )
            )
            if not pattern_matches and not args.allow_pattern_mismatch:
                raise AutomationError(
                    "TX %.3f MHz pattern readback does not match the whitelisted reference; "
                    "capture refused." % args.center_frequency_mhz
                )
        json_write_atomic(manifest_path, manifest)
        log("TX original Reg22=0x%08X Reg24=0x%08X Reg25=0x%08X" % (
            original_reg22, original_reg24, original_reg25))

        want_internal_bf = bool(original_reg24 & 0x1) or args.enable_internal_bf
        if not want_internal_bf:
            raise AutomationError(
                "TX_BF_MODE is currently off. Re-run with --enable-internal-bf after confirming "
                "the gel, probe, power rails and Pattern Profile."
            )

        # 配置和下載 HSDC firmware 前先暫停內部發射。
        tx.set_internal_bf(False)
        log("TX internal BF temporarily disabled during setup.")

        profile_batches = [
            report["profiles"][start:start + HARDWARE_DELAY_PROFILES_PER_BATCH]
            for start in range(0, len(report["profiles"]), HARDWARE_DELAY_PROFILES_PER_BATCH)
        ]
        manifest["tx_profile_batches"] = [
            {
                "batch_number": batch_number,
                "sequence_numbers": [profile["profile_number"] for profile in batch_profiles],
                "hardware_profile_numbers": [
                    profile["hardware_profile_number"] for profile in batch_profiles
                ],
                "angles_deg": [profile["requested_angle_deg"] for profile in batch_profiles],
            }
            for batch_number, batch_profiles in enumerate(profile_batches)
        ]
        json_write_atomic(manifest_path, manifest)
        if args.program_profiles:
            log("Angle sweep will use %d TX profile batch(es), capacity %d each." % (
                len(profile_batches), HARDWARE_DELAY_PROFILES_PER_BATCH))
        else:
            log("WARNING: --no-program-profiles selected; script cannot verify angle contents.")

        log("Connecting to HSDC Pro automation...")
        hsdc = HSDCController(args.timeout_ms)
        hsdc.configure(
            args.samples,
            args.trigger,
            not args.reuse_hsdc_state,
            hsdc_board_serial,
            hsdc_device,
            args.enable_hsdc_capture_to_file_streaming,
        )

        manifest["status"] = "capturing"
        json_write_atomic(manifest_path, manifest)

        capture_ordinal = 0
        capture_total = args.repeats * len(report["profiles"])
        for batch_number, batch_profiles in enumerate(profile_batches):
            # Never rewrite delay registers while the internal transmitter is active.
            tx.set_internal_bf(False)
            if args.program_profiles:
                log("=" * 72)
                log("PROGRAMMING TX PROFILE BATCH %d/%d: sequence %02d..%02d -> hardware P00..P%02d" % (
                    batch_number + 1,
                    len(profile_batches),
                    batch_profiles[0]["profile_number"],
                    batch_profiles[-1]["profile_number"],
                    len(batch_profiles) - 1,
                ))
                originals = tx.program_profiles(batch_profiles)
                # Preserve the values that existed before the first write to an
                # address. Later batches intentionally reuse P00..P15.
                for address, value in sorted(originals.items()):
                    key = "0x%02X" % address
                    if key not in manifest["tx_delay_registers_before_programming"]:
                        manifest["tx_delay_registers_before_programming"][key] = "0x%08X" % value
                json_write_atomic(manifest_path, manifest)

            for repeat_index in range(args.repeats):
                for profile in batch_profiles:
                    profile_number = profile["profile_number"]
                    hardware_profile_number = profile["hardware_profile_number"]
                    angle = profile["requested_angle_deg"]
                    capture_ordinal += 1
                    log("=" * 72)
                    log("CAPTURE PROGRESS %d/%d: sequence %02d -> batch %02d/P%02d, angle %+.2f deg" % (
                        capture_ordinal, capture_total, profile_number,
                            batch_number + 1, hardware_profile_number, angle))

                    log("Preparing TX profile with internal BF forced OFF...")
                    # 嚴格複製人工 GUI 操作順序：改延時/LOAD_PROF 時保持 BF 關閉。
                    tx.set_internal_bf(False)
                    tx.select_g1_profile(hardware_profile_number)
                    if args.program_known_pattern:
                        # LOAD_PROF above can restore Reg25's low fields in the
                        # EVM GUI path.  Reassert and verify Repeat/Tail while
                        # TX_BF_MODE is still OFF, immediately before transmit.
                        tx.write_verified(
                            "GLOBAL", 0x19,
                            int(active_pattern_reg25) & 0xffffffff,
                        )
                    log("Selected batch %02d/P%02d for sequence %02d; LOAD_PROF self-cleared; "
                        "TX GUI/hardware is idle." % (
                            batch_number + 1, hardware_profile_number, profile_number))

                    # 只有在 HSDC 已準備好、當前 Profile 已完全裝載後才開始發射。
                    tx.set_internal_bf(True)
                    log("TX_BF_MODE enabled for angle %+.2f deg; settling %.3f s" % (
                        angle, args.settle_seconds))
                    time.sleep(args.settle_seconds)

                    filename = make_filename(angle, profile_number, repeat_index)
                    path = os.path.join(run_dir, filename)
                    if os.path.exists(path) and not args.overwrite:
                        raise AutomationError("Refusing to overwrite: " + path)

                    started = utc_now_text()
                    if args.trigger == "hardware":
                        log(
                            "Arming TSW14J50 now; next SYNCP rising edge starts a contiguous "
                            "%d-sample/channel DDR record." % args.samples
                        )
                    # Pass_Capture_Event 等價於在 HSDC Pro 中點擊 Capture。
                    hsdc.capture(args.trigger)
                    # DDR 捕獲完成後立刻停止內部發射；保存文件時無需繼續發射。
                    tx.force_internal_bf_off()
                    log("HSDC capture complete; TX_BF_MODE disabled before file save.")
                    # ADC_Save_Raw_Data_As_Binary_File 等價於保存 raw binary；path 已包含
                    # 角度、Profile 和 repeat 編號，因此不需要事後手工重命名。
                    log(
                        "Saving %.1f MiB HSDC raw BIN; this TI API may take 30-60 seconds. "
                        "Do not close the window or click the GUIs..." % (
                            expected_file_bytes / float(1024 ** 2)
                        )
                    )
                    hsdc_save = hsdc.save_binary(path, expected_file_bytes)
                    finished = utc_now_text()
                    actual_bytes = os.path.getsize(path)
                    if actual_bytes != expected_file_bytes:
                        raise AutomationError(
                            "Unexpected BIN size for %s: got %d expected %d. "
                            "Check HSDC channel profile and sample count." % (
                                filename, actual_bytes, expected_file_bytes
                            )
                        )
                    file_qa = None
                    if not args.skip_file_qa:
                        file_qa = scan_u16_file(path)
                        log("QA %s: min=%d max=%d rail_samples=%d" % (
                            filename,
                            file_qa["minimum_code"],
                            file_qa["maximum_code"],
                            file_qa["rail_sample_count"],
                        ))
                        if file_qa["rail_sample_count"]:
                            log(
                                "WARNING: ADC rail codes detected. Reduce AFE gain/TGC or TX amplitude "
                                "before using coherent/adaptive beamforming."
                            )
                    entry = {
                        "filename": filename,
                        "profile_number": profile_number,
                        "profile_batch_number": batch_number,
                        "hardware_profile_number": hardware_profile_number,
                        "requested_angle_deg": angle,
                        "realized_delay_gradient_angle_deg": profile[
                            "realized_delay_gradient_angle_deg"
                        ],
                        "delay_counts_A1_to_A8": profile["delay_counts_A1_to_A8"],
                        "repeat_index": repeat_index,
                        "expected_prf_hz": args.expected_prf_hz or None,
                        "expected_prfs_in_bin": args.expected_prfs_per_bin or None,
                        "capture_started_utc": started,
                        "capture_finished_utc": finished,
                        "file_bytes": actual_bytes,
                        "file_qa": file_qa,
                        "hsdc_save": hsdc_save,
                    }
                    manifest["captures"].append(entry)
                    json_write_atomic(manifest_path, manifest)
                    log("Saved %-40s %d bytes" % (filename, actual_bytes))

        manifest["tx_cfg_files"] = save_verified_tx_cfg_files(
            run_dir,
            report,
            profile_batches,
            original_reg22,
            active_reg24,
            active_reg25,
            waveform_readback,
            args.center_frequency_mhz,
            args.tx_cycles,
            args.expected_hv_a_v,
            args.expected_hv_b_v,
        )
        log("Saved %d verified TX7316 CFG batch file(s)." % len(
            manifest["tx_cfg_files"]
        ))
        manifest["status"] = "complete"
        manifest["completed_utc"] = utc_now_text()
        json_write_atomic(manifest_path, manifest)
        log("CAPTURE COMPLETE: %d files" % len(manifest["captures"]))
        return 0

    except Exception as exc:
        error = exc
        log("ERROR: %r" % exc)
        manifest["status"] = "error"
        manifest["error"] = repr(exc)
        manifest["failed_utc"] = utc_now_text()
        try:
            json_write_atomic(manifest_path, manifest)
        except Exception:
            pass
        raise

    finally:
        if hsdc is not None:
            try:
                hsdc.disconnect()
            except Exception as disconnect_exc:
                # Capture data and the TX fail-safe cleanup are more important
                # than a best-effort DLL disconnect.  Report it explicitly so
                # the next run can restart HSDC Pro if code 66 occurs.
                log("WARNING: failed to disconnect HSDC Automation session: %r" % disconnect_exc)
        if tx is not None and not args.keep_tx_state:
            try:
                restored = []
                # Restore pattern memory before restoring the original global
                # timing fields.  TX_BF_MODE remains forced off throughout.
                if original_pattern_registers is not None:
                    tx.set_internal_bf(False)
                    for offset, value in enumerate(original_pattern_registers):
                        tx.write_verified("PATTERN-PROFILE", 0x60 + offset, value)
                    tx.pulse_load_profile()
                    restored.append("pattern profile0")
                if original_reg22 is not None:
                    tx.write_verified("GLOBAL", 0x16, original_reg22)
                    tx.pulse_load_profile()
                    restored.append("Reg22/profile selection")
                # Restore Reg25 only after every LOAD_PROF operation; the EVM
                # GUI path can otherwise overwrite its low Repeat/Tail fields.
                if original_reg25 is not None:
                    tx.write_verified("GLOBAL", 0x19, original_reg25)
                    restored.append("Reg25")
                if original_reg24 is not None:
                    # Never re-enable high-voltage pulsing during automatic cleanup,
                    # even if TX_BF_MODE happened to be ON before the run.  Restore
                    # every other Reg24 field but force bit 0 OFF; a later transmit
                    # must always be an explicit user action/new capture step.
                    tx.write_verified("GLOBAL", 0x18, original_reg24 & ~0x1)
                    restored.append("Reg24 restored with TX_BF_MODE forced OFF")
                if restored:
                    log("TX state restored: " + ", ".join(restored))
            except Exception as restore_exc:
                log("WARNING: failed to restore TX state: %r" % restore_exc)
                if error is None:
                    raise
        if LOG_HANDLE is not None:
            LOG_HANDLE.close()
            LOG_HANDLE = None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        print("ERROR: %s" % exc)
        sys.exit(1)
