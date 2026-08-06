# 本機TI軟件、CPLD工程與資料來源

本倉庫只提交自行編寫的控制/重建代碼、操作文檔和兩個必要配置快照。TI安裝包、手冊、硬件設計zip、Quartus資料庫和二進制固件不重新分發。

## 本機已安裝/保存的位置

| 資料 | 本機位置 | 用途 |
|---|---|---|
| TX7316 EVM User Guide `SBOU224` | `<workspace>\TX7316\TX7316EVM_User_Guide_sbou224_.pdf` | J1/J2/J3、J5/J7、GUI、Appendix C |
| AFE58JD48EVM User Guide `SLOU521` | `<workspace>\AFE58JD48EVM_User_Guide__SLOU521_.pdf` | SMA、J25、JESD、AFE/LMK GUI |
| TX7316 EVM GUI | `E:\Program Files (x86)\Texas Instruments\TX7316 EVM` | TX配置和32-bit Device GUI接口 |
| HSDC Pro 5.31 | `E:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro`及`E:\Program Files\Texas Instruments\High Speed Data Converter Pro` | TSW14J50捕獲與Automation DLL |
| HSDC ADC profiles | `E:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files` | `AFE58JD48_120M_8L_M16_FIXED.ini`安裝位置 |
| TX7316 CPLD工程 | `%USERPROFILE%\Texas Instruments\TX7316CPLDFW-1.0` | Quartus工程、Sync_Gen/TR_Gen/Pat_Gen源碼與POF |

## TX7316CPLDFW-1.0是什麼

該installer安裝了完整Quartus工程，而不只是GUI插件。目錄包含`Sync_Gen.vhd`、`TR_Gen.vhd`、`Pat_Gen_5lvl.vhd`、`Top_CPLD_EVM.vhd`、`.qpf/.qsf`與`output_files/CPLD_EVM.pof`。因此理論上可修改PRF divider並經J11/JTAG重新編程CPLD。

但這不是GUI中改一個寄存器：重新編譯/燒錄會改變TR switch、發射同步和使能時序。實施前必須保存原始POF、建立版本控制、在J1/J2關閉與假負載下用示波器驗證SYNCP/TR_EN，再逐級上電。本倉庫目前沒有自動燒錄CPLD。

## TSW_controller與HSDC Pro

`TSW_controller v1.3.0.2 / TCP 5600`是另一個命令/腳本控制界面，可向TSW服務發INIT/CONFIG/STATUS等命令。標準流程不需要手動操作它：

- HSDC Pro GUI保持打開；
- 本倉庫通過TI `HSDCProAutomation.dll`控制HSDC Pro；
- 不在採集過程中同時用TSW_controller發命令，避免兩個控制端改同一板卡狀態；
- HSDC GUI與Automation DLL不是互斥的，DLL本來就是用來自動控制該GUI/服務，但三者權限必須一致。

如果只做TCP協議研究，先關高壓與TX_BF，在單獨時段使用TSW_controller並保存命令日誌，不把它混入正式採集。

## 2026-08-07 Demod軟件相容性紀錄

本機目前實際版本是：

| 軟件 | 本機版本 |
|---|---:|
| AFE58JD48 EVM GUI | 2.0.0.1 |
| HSDC Pro | 5.31 |

本機TI transition instructions明確指定的測試組合則是`HSDC Pro 5.00 + AFE58JD48 EVM GUI 1.2.3`，而AFE58JD48 EVM user guide的Demodulator Plot原流程以TSW14J56為對象。2026-08-07的M=4測試已證明AFE同步字到達TSW14J50/HSDC，但AFE GUI的Import callback只生成0-byte `Demod Separated Data.csv`。

AFE GUI原始設定只列出HSDC `4.7, 4.8, 4.9, 5, 5.10`。把`5.31`追加到supported list只會繞過版本檢查，不代表Automation、臨時BIN或decompressor相容。後續優先取得TI指定的舊版軟件在隔離環境復測；若無法取得，應以既有BIN實作離線separator。完整證據與長時採集決策見[2026-08-07交接](22_HANDOFF_2026-08-07_AFE_DEMOD_IMPORT_AND_LONG_DOPPLER.md)。

## 倉庫配置的來源

- `configs/hsdc/AFE58JD48_120M_8L_M16_FIXED.ini`：使用 literal M=16 的實驗 profile，不是已修復基線。2026-07-25 的唯一數位碼測試顯示它、matched S2/M16 與 TI 安裝包原始 M=5 profile 都產生相同四組複製通道；必須等待 TI 更新的 TSW14J50 firmware INI/firmware，並以 `automation/jesd_transport_qa.py` 做 16/16 驗收。詳見 `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md`。
- `configs/tx7316/1MHz_5pulses.cfg`：從TX7316 EVM安裝包Quick Start/Internal目錄複製。

兩者都是可追溯快照。當TI版本升級時，先比較diff、重做JESD/頻譜驗收，再替換倉庫版本。
