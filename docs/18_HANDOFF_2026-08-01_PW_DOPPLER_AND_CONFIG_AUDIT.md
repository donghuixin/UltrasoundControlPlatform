# 2026-08-01 PW Doppler 與配置審計交接

更新日期：2026-08-01

適用平台：TX7316EVM + AFE58JD48EVM + TSW14J50/HSDC Pro

上位機：`HKUST_BioData_Collector`

> 僅限假負載、水槽、凝膠與已知流量仿體。平台尚未完成醫療電氣、聲學輸出、MI/TI 或人體安全驗證，不得接觸人體或用於診斷。

## 1. 本次交接結論

本次已把 PW Doppler 規劃、短塊採集、離線分析、流量仿體預設與配置審計整合到上位機。當前可以一鍵執行的是 `1 kHz / 70 ms` raw-RF 短塊，用來驗證距離門、頻移方向與分析鏈；它不足以覆蓋一個心動周期。

要穩定看出多個周期內的流速變化，推薦的最終資料路徑是：

```text
固定單一TX角度 + 共同5 kHz PRF
  -> FPGA按同一深度門做I/Q解調
  -> 保留8路I/Q或先相干合成為1路beam I/Q
  -> 單次連續記錄10秒，帶單調pulse_index/timestamp
  -> wall filter + 128-pulse STFT
  -> 速度譜、包絡、周期可信度和CSV
```

10 秒、5 kHz、8 路 complex int16 I/Q 約 `1.53 MiB`，75 BPM 時可覆蓋約 12.5 個周期。10 秒通過無漏 pulse Gate 後，才擴展到 30 秒長記錄。

## 2. 必須保留的硬件事實

1. 現有 HSDC raw profile 是 `M=16、120 MSPS`，TSW14J50 的 256M 個 16-bit 樣點由 16 個 converter stream 分攤，理論單塊上限約 `0.13981 s`。
2. 物理上只接 A1–A8，或離線只選 HSDC 槽 5–12，不會讓 raw BIN 從 16 列變成 8 列，因此不能自動把記錄時間加倍。
3. 若要建立真正的 M=8 transport，必須同步修改 AFE 輸出格式、JESD LMFS、TSW deformatter 和列映射，再通過唯一碼 Gate；不能只改 INI 的通道數。
4. 全 16 槽仍穩定存在 exact duplicate signature：`[3,5] [4,6] [9,15] [10,16]`。槽 5–12 只是避開完整重複對的 8 路降級映射，不代表 JESD 根因已修復。
5. 現有 CPLD PRF 約 1 kHz，不能由 Collector GUI 直接改成 5 kHz。多周期 I/Q 預設在共同 PRF 與後端固件完成前會 Fail Closed。
6. TX7316 的接收開啟/blanking 必須依 J7 發射、J5 接收毛刺和 AFE 恢復的示波器結果設定。軟件丟棄早期樣點不能挽救已飽和的 AFE。

## 3. 已整合的軟件能力

### 3.1 PW Doppler 頁面

`HKUST_BioData_Collector/app.py` 的 `PW多普勒 Doppler` 頁面現在包含：

- raw RF、FPGA range-gated I/Q、AFE demod I/Q 三種路徑；
- 固定 TX steering、流束角、PRF、深度門、門長、期望速度、心率、wall filter 和 STFT 配置；
- TSW 容量、單塊時長、pulse 數、速度 Nyquist、無模糊深度和預估周期數；
- 五個頸動脈樣流量仿體預設；
- 當前 raw 模式的一鍵採集與自動分析；
- 目標 I/Q 模式的一鍵載入、Session Plan 與硬件 Gate；
- 連續 I/Q NPZ 的直接分析入口。

推薦後端輸出 `pw_doppler_input_iq.npz`，其中 `iq` 是形狀為 `(continuous_pulses, active_iq_channels)` 的 complex64 陣列，並包含 `prf_hz`。固件還必須提供可核對的單調 `pulse_index` 或 hardware timestamp。

### 3.2 分析輸出

`HKUST_BioData_Collector/pw_doppler_analysis.py` 可由單一 raw BIN 或連續 I/Q NPZ 生成：

- `analysis/pw_doppler/pw_doppler_spectrogram.png`
- `analysis/pw_doppler/pw_doppler_velocity.csv`
- `analysis/pw_doppler/pw_doppler_summary.json`
- 距離門慢時間 I/Q NPZ

只有單一連續記錄不少於 3 秒、覆蓋至少 3 個周期，且包絡周期性檢查通過時，摘要才會標記 `cardiac_cycle_visible=true`。程序不會把多個有保存空檔的 HSDC BIN 拼成連續心動周期。

### 3.3 配置審計

`HKUST_BioData_Collector/config_audit.py` 對以下內容做唯讀檢查：

- repository HSDC INI；
- AFE/TX snapshot 語法和配對邊界；
- Collector example/local JSON；
- PW 預設的深度、速度、時長、容量與周期數。

本次結果：`PASS`，`8 pass / 7 warning / 0 error`。7 個 warning 是尚未通過硬件 Gate 的已知狀態，不是語法錯誤：3 個 HSDC transport 未驗證、3 個 AFE overlay 只可與指定實驗 profile 配對，以及 TX quick-start 文件名與實際內容不一致。

## 4. 一鍵流量仿體預設

| 預設 | PRF / 時長 | 期望速度 | 用途 | 當前狀態 |
|---|---:|---:|---|---|
| 低速短塊 | 1 kHz / 0.07 s | 0.25 m/s | 距離門、頻移方向、64-pulse STFT | 可用現有 raw 後端執行 |
| 常規波形 | 5 kHz / 10 s | 1.5 m/s | 約 12.5 個 75 BPM 周期 | 需連續 I/Q 固件 |
| 低速/舒張流 | 2.5 kHz / 15 s | 0.6 m/s | 低流速與較長觀察 | 需連續 I/Q 固件 |
| 高速射流 | 7.5 kHz / 10 s | 3.0 m/s | 已知狹窄管/泵速仿體 | 需連續 I/Q 固件 |
| 長記錄 | 5 kHz / 30 s | 1.5 m/s | 約 37.5 個 75 BPM 周期 | 10 秒 Gate 通過後使用 |

所有預設默認為 8 路物理孔徑、HSDC 槽 5–12、1.0 MHz、0° TX steering、60° flow angle 和 25 mm 門中心。實際深度與流束角必須按仿體幾何修改；預設名稱不代表速度量值已校準。

## 5. 配置修正與變更範圍

本次相關變更包括：

- `HKUST_BioData_Collector/app.py`：PW 頁面、一鍵預設、採集後分析和硬件 Gate；
- `doppler_model.py`：raw/IQ 容量、PRF、速度與周期模型；
- `doppler_presets.py`：五個流量仿體預設；
- `pw_doppler_analysis.py`：raw/IQ 分析、速度譜和周期 Gate；
- `config_audit.py`：repository 配置唯讀審計；
- `collector_config.example.json`：統一 1.0 MHz、8 陣元和槽 5–12 基線；
- `automation/tx7316_hsdc_batch_capture.py`：白名單 help 與實際 1/1.5/2/2.5/4 MHz 一致；
- 兩個 HSDC 實驗 INI：損壞的 `Menu Enable` 文字恢復為 `Trigger Option`；
- 對應單元測試、PW 操作指南和配置參考文檔。

本機運行配置 `collector_config.json` 被 Git 忽略，不提交；raw BIN、capture 目錄、日誌、患者/人體資料和專有資料也不進倉庫。

## 6. 已完成的驗證

在 repository 根目錄執行：

```powershell
python HKUST_BioData_Collector\config_audit.py
python -m unittest discover -s HKUST_BioData_Collector\tests -v
python HKUST_BioData_Collector\app.py --self-test
```

本次驗證結果：

- 配置審計：`PASS`，8 pass、7 warning、0 error；
- Python 3 單元測試：22 項全部通過；
- Collector self-test：`PASS`；
- app/model/presets/analyzer/audit Python 3 語法編譯：通過；
- Python 2 採集自動化語法編譯：通過；
- example/local JSON：可解析；
- 1.0 MHz、0°、槽 5–12、8,388,608 samples、1 kHz dry run：通過，未啟動 GUI、TX 或採集。

## 7. 下一次上機的最短閉環

必須按順序通過，失敗時只改一個變量：

1. **16/16 transport Gate**：唯一碼逐槽無重複、無缺失；未通過前把槽 5–12 明確標成降級模式。
2. **TX/blanking Gate**：假負載量測 burst 周期、回零、J5 毛刺與 AFE 恢復，決定最早可接收時間。
3. **單通道深度 Gate**：已知反射體移動時，回波延時按 `2z/c` 移動且沒有削頂。
4. **raw 短塊 Gate**：1 kHz/70 ms 一鍵採集；流向反轉後頻移符號反轉，已知泵速與估算速度趨勢一致。
5. **共同 PRF Gate**：5 kHz TX、AFE/FPGA 與 capture 使用同一時基，pulse index 無遺失或重複。
6. **10 秒 I/Q Gate**：單一文件 timestamp/pulse index 嚴格單調，無保存間隙；周期泵至少連續 3 個周期可見。
7. **30 秒擴展 Gate**：只有 10 秒穩定後才啟用，檢查長時間流量、探頭和時間軸穩定性。

每個 Gate 應保存去識別化的配置 hash、manifest、QA JSON 和量測摘要；raw 資料留在 Git 之外。

## 8. 開始與延伸閱讀

啟動前先做：

```powershell
cd HKUST_BioData_Collector
python config_audit.py
python app.py --self-test
python -m unittest discover -s tests -v
```

然後以管理員啟動 Collector，按 `Alt+4` 進入 PW 頁面。第一次台架試驗只選「低速短塊」，完成 Pre-flight 後再一鍵採集並分析。

詳細設計與操作：

- `docs/16_PW_DOPPLER_MULTI_CYCLE_DESIGN_2026-08-01.md`
- `docs/17_CAROTID_FLOW_PHANTOM_PRESETS_2026-08-01.md`
- `HKUST_BioData_Collector/PW_DOPPLER_OPERATION_GUIDE.md`
- `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md`
- `docs/13_JESD_DOCUMENT_EVIDENCE_AND_DECISION_GATES.md`
