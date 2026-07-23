# Ultrasound Control Platform

面向 TX7316EVM、AFE58JD48EVM、TSW14J50 與 HSDC Pro 的實驗室超聲控制、採集與離線重建平台。工程包含：

- 8 陣元（可配置 2–8）TX7316 Delay Profile 計算與多角度自動採集；
- HKUST Bio-data collector 白色桌面 UI；
- HSDC raw BIN 離線檢查、軟對齊、帶通、DAS、角度複合與 2D/3D 圖；
- 1 MHz B-mode 成像、PW Doppler 可行性計算及短塊採集入口；
- 5-level / Appendix C 3-level 接線、觸發、冷啟動、關機與排障文檔；
- 本機已驗證的 HSDC 16 通道 INI 和 TX7316 1 MHz preset。

> 實驗室仿體專用。這套開放式高壓 EVM 連線未經醫療安全認證，不得貼人體或用於診斷。

## 文檔入口

1. [系統與模式總覽](docs/00_SYSTEM_OVERVIEW.md)
2. [完整電氣連線與通道映射](docs/01_HARDWARE_CONNECTIONS.md)
3. [從完全斷電開始的冷啟動與關機](docs/02_COLD_START_AND_SHUTDOWN.md)
4. [1 MHz B-mode 成像操作](docs/03_BMODE_IMAGING.md)
5. [PW Doppler 與多個心動週期方案](docs/04_PW_DOPPLER.md)
6. [同步與觸發模式](docs/05_TRIGGER_AND_SYNC.md)
7. [配置文件與寄存器核對](docs/06_CONFIGURATION_REFERENCE.md)
8. [故障排查與驗收](docs/07_TROUBLESHOOTING.md)
9. [本機TI軟件、CPLD工程與資料來源](docs/08_LOCAL_SOFTWARE_AND_SOURCES.md)
10. [1.59 mm 陣列、柵瓣與超分辨率思路](automation/ARRAY_1P59MM_AND_SUPERRESOLUTION.md)

## 目前硬件基線

| 項目 | 基線 |
|---|---|
| 有效 TX/RX | A1–A8，共 8 個物理陣元 |
| 陣元 | `1.0 × 1.0 × 0.4 mm` |
| 中心間距 | `1.59 mm` |
| AFE/HSDC | 16 數字通道、120 MSPS、8 lanes、Subclass 1 |
| B-mode 起步頻率 | 1 MHz；實際聲學頻率須由回波頻譜或水聽器驗證 |
| 掃描 | `-10°…+10°`，1°或2°步進，超過16角度自動分批 |
| 原板 PRF | CPLD 固定約1 kHz；GUI不能改成20 kHz |
| 安全範圍 | 凝膠、水槽、流體仿體，不接人體 |

## 快速開始

完整流程見冷啟動文檔。軟件端最短流程：

```powershell
cd HKUST_BioData_Collector
python -m pip install -r requirements.txt
python app.py --self-test
python -m unittest discover -s tests -v
```

硬件就緒後，右鍵或雙擊：

```text
HKUST_BioData_Collector\Run_HKUST_BioData_Collector_as_admin.cmd
```

在 UI 中先做 `Dry run`。真實採集由 UI 啟動 32-bit Python 2.7 腳本；TX7316 GUI、HSDC Pro 與採集腳本必須保持相同的管理員權限。

## 配置安裝

- 把 [AFE58JD48_120M_8L_M16_FIXED.ini](configs/hsdc/AFE58JD48_120M_8L_M16_FIXED.ini) 複製到：
  `E:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files`
- 不使用`AFE58JD48_120M_8L_MANUAL`：該舊文件的`JESD IP Core_M=5`，與16通道輸出不一致；`M16_FIXED`使用`M=16`。
- TX7316 1 MHz preset 位於 [1MHz_5pulses.cfg](configs/tx7316/1MHz_5pulses.cfg)。它是目前 TI EVM 安裝包中的 preset 快照；載入後仍須核對實際輸出頻譜、週期數、Reg24/Reg25 與 CW OFF。
- 第一次啟動 UI 會讀取 `collector_config.example.json`，退出時把本機設置寫入被 Git 忽略的 `collector_config.json`。

若 TI 軟件安裝位置不同，可在啟動採集前設置：

```powershell
$env:TX7316_EVM_PYTHON_MODULE = 'C:\Program Files (x86)\Texas Instruments\TX7316 EVM\Scripts\TX7316 EVM.py'
$env:HSDCPRO_AUTOMATION_DLL = 'C:\Program Files\Texas Instruments\High Speed Data Converter Pro\HSDCPro Automation DLL\32Bit DLL\HSDCProAutomation.dll'
$env:ULTRASOUND_OUTPUT_ROOT = 'D:\UltrasoundCaptures'
```

## 倉庫結構

```text
automation/                    TX7316/HSDC 控制、診斷和批量採集
HKUST_BioData_Collector/       Python 3 桌面 UI、模型和測試
configs/hsdc/                  HSDC Pro ADC/JESD profile
configs/tx7316/                TX7316 1 MHz preset
docs/                          硬件和操作文檔
reconstruct_ultrasound.py      HSDC BIN 離線分析與成像
auto_runs/                     本機採集輸出；不會提交到 Git
```

## 數據政策

本倉庫故意排除所有 `.bin`、`capture_*`、`auto_runs/`、分析圖片、日誌和本機狀態。克隆倉庫不包含任何採集資料；需要分析時把資料放入本機 `auto_runs/` 或在 UI 選擇外部資料夾。

## 已知邊界

- UI 中的中心頻率只參與延時、波長、檔名和重建參數；它不會自動改寫 TX7316 Pattern Profile。
- HSDC 的 `ADC Input Target Frequency`只影響 FFT/標記，不控制 TX 頻率。
- 原板 `J7 pin 2 SYNCP`是 CPLD 的約2.5 V、1 kHz輸出，不是外部20 kHz輸入口。
- 無共同硬件觸發時，多角度資料只能做靜態軟對齊，不是嚴格相干複合。
- 多次 HSDC Capture 之間存在保存空檔，不能拼成連續心動週期。
