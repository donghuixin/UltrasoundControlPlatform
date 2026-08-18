# Ultrasound Control Platform

面向 TX7316EVM、AFE58JD48EVM、TSW14J50 與 HSDC Pro 的實驗室超聲控制、採集與離線重建平台。工程包含：

- 8 陣元（可配置 2–8）TX7316 Delay Profile 計算與多角度自動採集；
- HKUST Ultrosound collector platform 白色桌面 UI；
- HSDC raw BIN 離線檢查、軟對齊、帶通、DAS、角度複合與 2D/3D 圖；
- 1 MHz B-mode 成像、PW Doppler 短塊採集、連續 I/Q 分析與流量仿體預設；
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
11. [2026-07-24 採集與重建軟件更新](docs/09_RECENT_SOFTWARE_UPDATES.md)
12. [通道QA、成像失敗原因與三級排查](docs/10_CHANNEL_QA_AND_IMAGING_DIAGNOSIS.md)
13. [JESD 通道複製故障報告與三組閉環證據](docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md)
14. [可直接交給 Opus 的 JESD 去幀求助包](docs/12_OPUS_HELP_REQUEST_JESD_DEFRAMING.md)
15. [2026-07-26 項目交接與恢復開發順序](docs/13_PROJECT_HANDOFF_2026-07-26.md)
16. [JESD PDF/RTL 證據、適用邊界與下一步 Gate](docs/13_JESD_DOCUMENT_EVIDENCE_AND_DECISION_GATES.md)
17. [2026-07-31 採集、低幅事件修復與成像交接](docs/14_HANDOFF_2026-07-31_CAPTURE_AND_RECONSTRUCTION.md)
18. [開源工程、架構與可遷移知識庫](docs/15_OPEN_SOURCE_ARCHITECTURE_AND_KNOWLEDGE_BASE.md)
19. [PW Doppler 多心動周期採集設計](docs/16_PW_DOPPLER_MULTI_CYCLE_DESIGN_2026-08-01.md)
20. [頸動脈樣流量仿體預設與配置審計](docs/17_CAROTID_FLOW_PHANTOM_PRESETS_2026-08-01.md)
21. [2026-08-01 PW Doppler 與配置審計總交接](docs/18_HANDOFF_2026-08-01_PW_DOPPLER_AND_CONFIG_AUDIT.md)
22. [TSW14J50 J13 外部觸發修正與驗證](docs/19_HSDC_J13_EXTERNAL_TRIGGER_FIX_2026-08-01.md)
23. [2026-08-03 TI AFE58JD48 通道複製修復包](docs/20_TI_AFE58JD48_CHANNEL_COPY_FIX_2026-08-03.md)
24. [2026-08-04—05 CW/IQ、採集與成像兩日總交接](docs/21_HANDOFF_2026-08-05_TWO_DAY_UPDATE_CW_IQ_CAPTURE_AND_IMAGING.md)
25. [2026-08-07 AFE Demod Import與長時多普勒交接](docs/22_HANDOFF_2026-08-07_AFE_DEMOD_IMPORT_AND_LONG_DOPPLER.md)
26. [AFE58JD48 + TSW14J50 Dec=32長時PW Doppler完整SOP](docs/24_AFE58JD48_TSW14J50_DEC32_LONG_PW_DOPPLER_SOP_2026-08-19.md)
27. [2026-08-19示波器Doppler與TI Dec=32總交接](docs/25_HANDOFF_2026-08-19_SCOPE_DOPPLER_AND_TI_DEC32.md)

## 目前硬件基線

| 項目 | 基線 |
|---|---|
| 有效 TX/RX | A1–A8，共 8 個物理陣元 |
| 陣元 | `1.0 × 1.0 × 0.4 mm` |
| 中心間距 | `1.59 mm` |
| AFE/HSDC | 16 數字通道、120 MSPS、8 lanes、Subclass 1 |
| B-mode候選頻率 | 1、1.5、2、2.5 MHz；寄存器讀回驗證數字pattern，聲學輸出仍須示波器/水聽器驗證 |
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

正式採集命令窗會禁用Windows Console QuickEdit，避免點擊/拖選文字後整個程序被系統暫停。HSDC阻塞調用會顯示旋轉心跳、已等待時間；保存BIN時另顯示文件大小和百分比。看到心跳持續更新即代表程序仍在運行，不要用`Ctrl+C`催促API。

在 UI 中先做 `Dry run`。真實採集由 UI 啟動 32-bit Python 2.7 腳本；TX7316 GUI、HSDC Pro 與採集腳本必須保持相同的管理員權限。

## 配置安裝

- [AFE58JD48_120M_8L_M16_FIXED.ini](configs/hsdc/AFE58JD48_120M_8L_M16_FIXED.ini) 與 S2 版本只保留作實驗／觸發對照；normal raw-RF 現以 TI 2026-08-03 提供的 `JESD 120MSPS_Subclass1_8L.CFG` + `AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1` 為基線。
- 2026-07-25 舊 profile 曾穩定出現 `3=5、4=6、9=15、10=16`。2026-08-04 的 `Test00804.bin` 未再看到該 bit-exact copy signature，但仍應用 16 個 distinct digital codes 完成最終 16/16 acceptance；Demod/IQ profile 必須另外重跑 Gate。詳見 [修復包](docs/20_TI_AFE58JD48_CHANNEL_COPY_FIX_2026-08-03.md)與[最新交接](docs/21_HANDOFF_2026-08-05_TWO_DAY_UPDATE_CW_IQ_CAPTURE_AND_IMAGING.md)。
- TX7316 1 MHz preset 位於 [1MHz_5pulses.cfg](configs/tx7316/1MHz_5pulses.cfg)。自動採集現已支持1、1.5、2、2.5、4 MHz白名單pattern寫入與寄存器回讀；回讀不匹配時Fail Closed。載入任何cfg後仍須確認`TX_BF_MODE`與CW OFF。
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
diagnostics/                   去識別化 QA 摘要（不含 raw BIN）
docs/                          硬件和操作文檔
skills/                        可重用的 Codex JESD 排障技能與安全診斷工具
reconstruct_ultrasound.py      HSDC BIN 離線分析與成像
auto_runs/                     本機採集輸出；不會提交到 Git
```

## 數據政策

本倉庫故意排除所有 `.bin`、`capture_*`、`auto_runs/`、分析圖片、日誌和本機狀態。克隆倉庫不包含任何採集資料；需要分析時把資料放入本機 `auto_runs/` 或在 UI 選擇外部資料夾。

## 已知邊界

- UI 中選擇白名單頻率（1、1.5、2、2.5、4 MHz）並啟用已知pattern寫入時，採集腳本會在`TX_BF_MODE=OFF`期間寫入TX7316 Pattern Profile並做寄存器回讀；不在白名單或回讀不匹配時會Fail Closed。中心頻率仍同時用於延時、波長、檔名和重建參數。
- HSDC 的 `ADC Input Target Frequency`只影響 FFT/標記，不控制 TX 頻率。
- 原板 `J7 pin 2 SYNCP`是 CPLD 的約2.5 V、1 kHz輸出，不是外部20 kHz輸入口。
- 無共同硬件觸發時，多角度資料只能做靜態軟對齊，不是嚴格相干複合。
- 多次 HSDC Capture 之間存在保存空檔，不能拼成連續心動週期。
