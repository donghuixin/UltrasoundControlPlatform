# 2026-07-24 採集與重建軟件更新

## 已整合功能

- HSDC固定使用`AFE58JD48_120M_8L_M16_FIXED`，manifest保存board、firmware、device與16槽映射。
- TX頻率白名單擴展到1、1.5、2、2.5、4 MHz；Pattern Profile/Reg25寫入後回讀，不匹配即拒絕高壓採集。
- 每次完成run可輸出實際已驗證的TX7316 cfg快照及索引，頻率比較/夜間批量腳本逐組Fail Closed。
- 角度超過16時自動分bank；profile只在`TX_BF_MODE=OFF`時寫入，`LOAD_PROF`必須自清零。
- HSDC阻塞調用加入心跳、elapsed time和保存進度；Windows Console QuickEdit被關閉，避免點選文字令程序暫停。
- UI新增`逐PRF掃描 Auto Scan`頁：11角/2°單bank與21角/1°雙bank時序規劃、4096樣本量化、容量估算、JSON導出與Fail-Closed固件門檻。
- UI同一時間只允許監控一個採集任務，避免重複點擊造成HSDC Automation code 66。
- RX槽映射、重複槽處理和1°/2°離線角度抽樣均可配置，不再把目前未驗證映射寫死成永久規則。
- 重建增加PRF事件模板驗證、通道QA、逐PRF影像、週期合成QA、回波時域、Pattern讀回與來源SHA-256。
- 修正manifest中`expected_prf_hz=null`時`float(None)`崩潰；缺值會安全回退至1 kHz。
- TX設定頻率、Pattern基頻、接收振鈴峰與延遲回波窗峰分開報告，避免把約1.45–1.6 MHz的換能器振鈴誤當成任何TX設定都相同。

## 新增工具

- `diagnose_prf_alignment.py`：獨立檢查事件間隔、模板相關性和時零抖動。
- `automation/export_tx_cfg_from_manifest.py`：由完成run導出TX7316配置快照。
- `automation/comparison_*_frequency_capture.py`：多頻率順序採集與報告。
- `automation/overnight_multifrequency_capture.py`：多組夜間採集、每組完整保存後再進下一組。
- `HKUST_BioData_Collector/rapid_scan_model.py`：逐PRF bank、event offset、samples和容量模型。

## 已知硬件/軟件邊界

- `Admin/TX GUI/HSDC open`只是進程檢查，不等於HSDC Automation session健康；正式判定看`Connect_Board OK`。
- TSW14J50/HSDC Pro是DDR block capture，不是120 MSPS×16槽的無限無縫USB streaming。120 MSPS、16-bit、16槽原始率約3.84 GB/s；多個Capture之間有保存空檔。
- HSDC `Continuous Capture`是重複DDR捕獲，不保證捕獲間零間隙。幾秒心動週期需FPGA距離門、IQ/降採樣或專用streaming資料路徑。
- 原廠TX7316EVM CPLD只提供約1 kHz自由運行事件，沒有逐PRF profile sequencer。Auto Scan的真正單BIN快速掃描需自定義、可讀回版本的CPLD/FPGA固件。
- Pattern寄存器回讀驗證數字時序，不等於聲壓或聲學中心頻率驗證；仍需示波器/水聽器。
- 目前A1–A8→HSDC 9–16是軟件配置，不是最終量測證書；逐SMA注入/示波器排查完成前保留可配置性與警告。
