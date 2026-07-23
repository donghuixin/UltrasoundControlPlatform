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
   - 預設中心頻率 = 1 MHz（必須先在TX GUI載入同頻Pattern）
2. 預設掃描角為 -10, -8, ..., +10 度，共 11 個角度。亦支持 1 度步進的21角度掃描；
   TX7316一次只有16個 Delay Profile，因此腳本會在 TX_BF_MODE 關閉時自動分成16+5兩批重寫。
3. 1.59 mm 在1 MHz下約為1.03 lambda，仍可能產生柵瓣；更高頻率時更嚴重。
   建議日常只用 +/-8 度，+/-10 度只作實驗上限，並把重建顯示視場限制在 +/-10 度。
4. 這不是醫療設備。腳本只用於凝膠/水槽/仿體，不得直接用於人體。
5. 腳本不改變 J1/J2/J3 電源，也不改寫高壓幅值和 Pattern Profile 波形。
   Pattern Profile 0、PRF、發射週期數與電源必須先在 TX7316 GUI 中人工確認。

【1. 硬件接線和人工配置】
1. TX7316 J7 的 A1-A8 高壓輸出接線性陣列對應的 8 個陣元；公共電極接系統模擬地。
2. TX7316 J5 的 RX_A1-RX_A8 接 AFE58JD48 的對應 SMA 輸入；兩板 AGND 短接。
3. AFE58JD48 與 TSW14J50 通過 FMC/JESD 連接。
4. 無硬件觸發時，J7 pin 2、AFE J25、TSW J13仍可留空；但這只能做“非相干/軟對齊”採集。
   原板1 kHz硬件起始觸發可把J7 pin2 SYNCP輸出接TSW J13；J7不是外部PRF輸入口。
5. TX7316 GUI 中先人工設定好 Pattern Profile 0：1 MHz、短脈衝、低 PRF起步，CW必須關閉。
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
4. HSDC Pro 的 AFE RX profile 應為 AFE58JD48_120M_8L_MANUAL，數據率 120 MSPS。
5. 最後才執行本腳本。腳本在 HSDC 準備好前會暫停 TX 的 Internal BF，採集前再打開，結束後恢復原值。

【4. 先做完全不接觸硬件的 Dry Run】
在管理員 CMD 中：

  C:\\Python27\\python.exe automation\\tx7316_hsdc_batch_capture.py --dry-run

Dry Run 會列出每個角度的 8 路延時、量化後角度、相鄰陣元相位差和柵瓣位置，不會連 GUI、不會發射、不會建文件。

【5. 正式批量採集】
確認凝膠、探頭、接收增益與 TX 電源後，在管理員 CMD 中：

  C:\\Python27\\python.exe automation\\tx7316_hsdc_batch_capture.py --capture --enable-internal-bf

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

【7. 本腳本刻意不自動修改的項目】
1. TX7316 的高壓電源和 5-level 電壓；
2. Pattern Profile 的1 MHz波形、脈衝週期數、PRF；
3. AFE 的 LNA/PGA/TGC 增益；
4. 人體安全參數。

這些項目若自動誤設會直接造成削頂、過熱或高壓風險，所以保留在 GUI 中人工確認。
"""

import argparse
import array
import ConfigParser
import ctypes
import datetime
import imp
import json
import math
import os
import struct
import sys
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
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPOSITORY_ROOT = os.path.dirname(SCRIPT_DIR)


def first_existing_path(environment_name, candidates):
    """Return an environment override or the first installed candidate.

    The laboratory computer uses an E: installation, while a standard TI
    installation normally uses C:.  Keeping both candidates makes a clone of
    this repository usable without editing source code.
    """
    override = os.environ.get(environment_name)
    if override:
        return os.path.abspath(override)
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


TX_PYTHON_MODULE = first_existing_path(
    "TX7316_EVM_PYTHON_MODULE",
    [
        r"E:\Program Files (x86)\Texas Instruments\TX7316 EVM\Scripts\TX7316 EVM.py",
        r"C:\Program Files (x86)\Texas Instruments\TX7316 EVM\Scripts\TX7316 EVM.py",
    ],
)

HSDC_DLL = first_existing_path(
    "HSDCPRO_AUTOMATION_DLL",
    [
        r"E:\Program Files\Texas Instruments\High Speed Data Converter Pro\HSDCPro Automation DLL\32Bit DLL\HSDCProAutomation.dll",
        r"C:\Program Files\Texas Instruments\High Speed Data Converter Pro\HSDCPro Automation DLL\32Bit DLL\HSDCProAutomation.dll",
        r"C:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\HSDCPro Automation DLL\32Bit DLL\HSDCProAutomation.dll",
    ],
)
HSDC_BOARD_SERIAL = "TIAOPCAW"
HSDC_AFE_RX_DEVICE = "AFE58JD48_120M_8L_MANUAL"
HSDC_DEFAULT_CONTROLS_INI = r"C:\Users\Public\Documents\Texas Instruments\High Speed Data Converter Pro\Default_controls.ini"

DEFAULT_OUTPUT_ROOT = os.environ.get(
    "ULTRASOUND_OUTPUT_ROOT", os.path.join(REPOSITORY_ROOT, "auto_runs")
)

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


def is_windows_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
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


def read_hsdc_persisted_settings():
    """
    HSDC GUI 會把最後成功連接的板名/Device Profile 保存到 Default_controls.ini。
    直接讀這個文件比從 GUI 字體辨認序號可靠；本機實測板名為 TIAOPCAW。
    """
    board = HSDC_BOARD_SERIAL
    device = HSDC_AFE_RX_DEVICE
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
    if device != HSDC_AFE_RX_DEVICE:
        raise AutomationError(
            "HSDC GUI selected device is %r, expected %r. Select the correct AFE RX profile first." % (
                device, HSDC_AFE_RX_DEVICE
            )
        )
    log("HSDC persisted settings: board=%s firmware=%s device=%s" % (
        board, firmware, device))
    return board, firmware, device


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
        module = imp.load_source("ti_tx7316_device_gui", TX_PYTHON_MODULE)
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

    def set_internal_bf(self, enabled):
        reg24 = self.read("GLOBAL", 0x18)
        new_value = reg24 | 0x1 if enabled else reg24 & 0xfffffffe
        if new_value != reg24:
            self.write_verified("GLOBAL", 0x18, new_value)
        return new_value

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

    def call(self, name, *args):
        function = getattr(self.dll, name)
        code = int(function(*args))
        if code != 0:
            raise AutomationError("HSDC %s failed, code=%d: %s" % (
                name, code, self.error_text()))
        log("HSDC %-44s OK" % name)

    def configure(
        self, samples, trigger_mode, full_setup, board_serial, device_name,
        enable_capture_to_file_streaming=False,
    ):
        timeout = ctypes.c_int32(self.timeout_ms)
        if full_setup:
            self.call(
                "Connect_Board",
                ctypes.c_char_p(self._bytes(board_serial)),
                timeout,
            )
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
            ctypes.c_double(ADC_SAMPLE_RATE_HZ),
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
        if trigger_mode == "normal" and not full_setup:
            # HSDC GUI 已由用戶設為可手動 Capture 的 Normal 模式。復用 GUI 狀態時
            # 不再調 Trigger_Option，避免該 API 重新配置 TSW ports；下一步直接用
            # Pass_Capture_Event，行為等同手工點擊 Capture。
            log("HSDC reusing current GUI Normal Trigger state.")
        else:
            self.set_trigger(trigger_mode)

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
            self.call("Read_DDR_Memory", ctypes.c_int32(1), timeout)
        else:
            raise AutomationError("Unknown trigger mode: " + trigger_mode)

    def save_binary(self, path):
        self.call(
            "ADC_Save_Raw_Data_As_Binary_File",
            ctypes.c_char_p(self._bytes(os.path.abspath(path))),
            ctypes.c_int32(self.timeout_ms),
        )


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
        "--sound-speed-m-s", type=float, default=SOUND_SPEED_M_S,
        help="assumed propagation speed for delay-law calculation",
    )
    parser.add_argument(
        "--delay-quantum-ns", type=float, default=TX_DELAY_QUANTUM_S * 1e9,
        help="TX7316 beamforming delay count duration; verify after BF clock changes",
    )
    parser.add_argument("--samples", type=int, default=SAMPLES_PER_CHANNEL)
    parser.add_argument("--repeats", type=int, default=1)
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
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--skip-file-qa", action="store_true",
        help="skip post-save uint16 min/max and rail-code scan",
    )
    return parser


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
    if args.pitch_mm <= 0:
        raise AutomationError("--pitch-mm must be positive")
    if args.element_width_mm <= 0 or args.element_width_mm > args.pitch_mm:
        raise AutomationError("--element-width-mm must be positive and no larger than pitch")
    if args.center_frequency_mhz <= 0:
        raise AutomationError("--center-frequency-mhz must be positive")
    if not (1000.0 <= args.sound_speed_m_s <= 2000.0):
        raise AutomationError("--sound-speed-m-s must be between 1000 and 2000")
    if args.delay_quantum_ns <= 0:
        raise AutomationError("--delay-quantum-ns must be positive")
    if args.samples <= 0 or args.samples % 4096 != 0:
        raise AutomationError("--samples must be a positive multiple of 4096")
    if args.repeats <= 0:
        raise AutomationError("--repeats must be positive")
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


def main(argv=None):
    global LOG_HANDLE
    args = make_parser().parse_args(argv)
    # 沒寫模式時，默認安全的 Dry Run。
    if not args.capture:
        args.dry_run = True
    validate_arguments(args)
    apply_runtime_array_configuration(args)

    report = array_report(args.angles, args.reverse_angle_sign)
    if args.dry_run:
        log("DRY RUN COMPLETE: no GUI connection, no TX write, no capture.")
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
    if free_bytes is not None and free_bytes < expected_total_bytes + 512 * 1024 * 1024:
        raise AutomationError("Not enough disk space with 512 MiB safety margin")

    hsdc_board_serial, hsdc_firmware, hsdc_device = read_hsdc_persisted_settings()

    manifest_path = os.path.join(run_dir, "capture_manifest.json")
    manifest = {
        "status": "initializing",
        "created_utc": utc_now_text(),
        "script": os.path.abspath(__file__),
        "python": sys.executable,
        "arguments": vars(args),
        "array": report,
        "hsdc": {
            "board_serial": hsdc_board_serial,
            "firmware": hsdc_firmware,
            "device": hsdc_device,
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
    error = None
    try:
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

                    # 嚴格複製人工 GUI 操作順序：改延時/LOAD_PROF 時保持 BF 關閉。
                    tx.set_internal_bf(False)
                    tx.select_g1_profile(hardware_profile_number)
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
                    # Pass_Capture_Event 等價於在 HSDC Pro 中點擊 Capture。
                    hsdc.capture(args.trigger)
                    # DDR 捕獲完成後立刻停止內部發射；保存文件時無需繼續發射。
                    tx.set_internal_bf(False)
                    log("HSDC capture complete; TX_BF_MODE disabled before file save.")
                    # ADC_Save_Raw_Data_As_Binary_File 等價於保存 raw binary；path 已包含
                    # 角度、Profile 和 repeat 編號，因此不需要事後手工重命名。
                    log(
                        "Saving 33.5 MB HSDC raw BIN; this TI API may take 30-60 seconds. "
                        "Do not close the window or click the GUIs..."
                    )
                    hsdc.save_binary(path)
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
                        "capture_started_utc": started,
                        "capture_finished_utc": finished,
                        "file_bytes": actual_bytes,
                        "file_qa": file_qa,
                    }
                    manifest["captures"].append(entry)
                    json_write_atomic(manifest_path, manifest)
                    log("Saved %-40s %d bytes" % (filename, actual_bytes))

        manifest["status"] = "complete"
        manifest["completed_utc"] = utc_now_text()
        json_write_atomic(manifest_path, manifest)
        log("CAPTURE COMPLETE: %d files" % len(manifest["captures"]))
        return 0

    except Exception as exc:
        error = exc
        manifest["status"] = "error"
        manifest["error"] = repr(exc)
        manifest["failed_utc"] = utc_now_text()
        try:
            json_write_atomic(manifest_path, manifest)
        except Exception:
            pass
        raise

    finally:
        if tx is not None and not args.keep_tx_state:
            try:
                restored = []
                if original_reg22 is not None:
                    tx.write_verified("GLOBAL", 0x16, original_reg22)
                    tx.pulse_load_profile()
                    restored.append("Reg22/profile selection")
                if original_reg24 is not None:
                    tx.write_verified("GLOBAL", 0x18, original_reg24)
                    restored.append("Reg24/TX_BF_MODE")
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
