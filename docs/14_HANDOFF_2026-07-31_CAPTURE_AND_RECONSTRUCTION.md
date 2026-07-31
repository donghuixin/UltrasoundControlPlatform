# 2026-07-31 採集與離線重建交接

更新日期：2026-07-31  
適用平台：TX7316EVM + AFE58JD48EVM + TSW14J50/HSDC Pro  
本日主要資料：`capture_20260731_171203`（raw BIN 不提交 Git）

## 1. 結論先行

今天完成了兩件可驗收的工作：

1. A1–A8 接收陣元改接 AFE INP5–INP12 後，採集檔案中的 5–12 數字槽可作為 8 個接收輸入參與重建；這組選槽沒有保留已知的 bit-exact 重複對。
2. 修復了 `reconstruct_ultrasound.py` 對低幅度 TX 事件的誤拒絕。新的 PHV_A/MHV_A 雙極診斷波形只有約 598 codes 的平滑事件標記，舊程式固定要求至少 1200 codes，因而錯誤報出 `Could not estimate received pulse spectrum`。修復後可找出 8 個約 1 kHz 的事件並完成全部離線輸出。

尚未解決的是聲學影像品質。重建能執行不等於影像已可信。目前圖像仍以週期條紋、振鈴和柵瓣為主，沒有足夠證據把亮帶解讀為膀胱或血管結構。

## 2. 當前接線與軟體基線

### 2.1 接收映射

本日測試接線為：

| 物理陣元 | AFE 模擬輸入 | HSDC 1-based 數字槽 |
|---|---:|---:|
| A1 | INP5 | 5 |
| A2 | INP6 | 6 |
| A3 | INP7 | 7 |
| A4 | INP8 | 8 |
| A5 | INP9 | 9 |
| A6 | INP10 | 10 |
| A7 | INP11 | 11 |
| A8 | INP12 | 12 |

重建必須從 capture manifest 的 `rx_hsdc_slots_1_based` 讀取這組映射，不能回退成硬編碼前 8 列。

已知全 16 槽的固定重複 signature 仍為：

```text
[3,5] [4,6] [9,15] [10,16]
```

本次選用 5–12 時，每一對只保留其中一端，因此 `retained_exact_duplicate_pairs=[]`。這只是可用 8 路的繞行方案，不代表 JESD 16 槽複製根因已修復。

### 2.2 HSDC/JESD 狀態

- 本日曾遇到 `HSDC Select_AFE_Device code=7005`、`HSDC Connect_Board code=66` 和連板長時間阻塞。
- HSDC Pro 只在啟動時載入 ADC profile 清單；新增或改名 INI 後，必須完整退出並以管理員重新啟動。
- `JTAG_CHAIN_BROKEN_ERROR` 是 TSW FPGA firmware 下載/JTAG 鏈失敗，不是超聲回波錯誤。冷啟動、USB/供電檢查並重新下載後才可 Capture。
- 16 槽複製問題的完整證據與 Gate 流程見 `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md` 和 `docs/13_JESD_DOCUMENT_EVIDENCE_AND_DECISION_GATES.md`。

## 3. 本日 TX 波形變更

為簡化五電平波形，新增診斷模式：

```text
name: bipolar_A_1p5MHz_2cycle_diagnostic
electrical levels: PHV_A / MHV_A only
requested nominal base rate: 1.492537 MHz
Register 25: 0x00000242
Pattern registers 0x60..0x67:
  0xA1AAA2A2 0x0007A9A1 0 0 0 0 0 0
```

TX7316 每個 transition 的 period field 只有 5 bit，因此同一電平用三段 20/20/21 表示 67 個 pattern clocks。相鄰同電平段不應在高壓輸出形成額外邊緣。

但是目前 GUI 中觀察到的波形是長正平臺後接長負平臺；它不是已用示波器證明的乾淨多週期 1.5 MHz burst。程式中的 1.492537 MHz 是寄存器時序解碼值，不是聲學量測結果。下一步必須用高壓差分探頭在假負載上量測：

1. 實際邊緣間隔與 burst 週期；
2. 正、負半週是否對稱；
3. burst 總長度；
4. 末端是否回到 AVSS；
5. J5 接收端的 T/R 毛刺與恢復時間。

在示波器驗證完成前，這個 pattern 只能標記為 `diagnostic`，不能作為已校準成像波形。

## 4. 離線重建崩潰：症狀、根因、修復

### 4.1 症狀

對下列資料按「強制重新運算」：

```text
E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture\
auto_runs\New0730\capture_20260731_171203
```

原程式拋出：

```text
RuntimeError: Could not estimate received pulse spectrum from
gel_1p5MHz_angle_p00_P5_R00.bin
```

11 個 BIN 實際均完整，每檔 `33,554,432` bytes；錯誤不是檔案截斷。

### 4.2 根因

`detect_events_validated()` 原先使用：

```python
threshold = max(1200.0, percentile_99_5 * 0.55)
```

新 PHV_A/MHV_A 波形在 5–12 槽上的指標為：

```text
smoothed event peak: 約 598.22 codes
noise median: 約 14.34 codes
robust noise sigma: 約 2.97 codes
```

真實事件低於固定 1200-code 門檻，因此 8 個週期事件全部被拒絕，後續頻譜函式得到空集合並報錯。

### 4.3 程式修復

`reconstruct_ultrasound.py` 現改為：

- 以 `median + 8 × robust sigma`、20-code 下限及 99.5 percentile 的 0.35 倍建立自適應門檻；
- 以預期 PRF 建立週期格點；
- 將前 64 個強候選逐一當作相位種子；
- 在每個預測格點附近搜尋局部最大值；
- 以格點累積強度選擇最佳事件列，避免偶發噪聲峰破壞直線擬合；
- 在 QA 中新增 noise、搜尋半徑及 grid score。

這個修復不降低 PRF 驗證要求，也不把任意高電平當作 TX。候選仍須形成與 `expected_prf_hz` 相符、誤差不超過 2% 的週期列。

## 5. 修復驗證

### 5.1 事件檢測

零度檔案修復後得到：

```text
markers:
109139, 229215, 349240, 469316,
589450, 709468, 829642, 949620

accepted events: 8
measured PRF: 999.373409 Hz
adaptive threshold: 38.065 codes
noise sigma: 2.965 codes
PRF-grid score: 4432.125
```

### 5.2 完整重建

- 完整處理退出碼：0
- 約 23 秒完成
- UI 預設輸出：`capture_20260731_171203\analysis`
- 額外驗證輸出：`capture_20260731_171203\analysis_recovered`
- 主要 B-mode：`analysis\plane_wave_das_bmode.png`
- 共生成約 25 張 PNG，另有 SVG/JSON QA

`analysis_summary.json` 的重要值：

| 項目 | 結果 |
|---|---:|
| 設定 TX 頻率 | 1.5 MHz |
| 零度紀錄 PRF | 999.373 Hz |
| 頻譜事件數 | 8 |
| 配置/使用槽 | 5–12 / 5–12 |
| 本次保留 exact duplicate pairs | 空 |
| 早期接收/直耦診斷峰 | 0.5127 MHz |
| 延遲窗峰值 | 4.541 MHz |
| 5–42 mm 對 late quiet power | 0.0354 dB |
| noise-subtracted echo SNR | -20.87 dB |
| 深層窗 noise-subtracted SNR | -9.46 dB |
| timing boundary hits | 2/97 |
| 反射候選 | 約 21.5 mm |

0.5127 MHz 只能稱為早期接收/直耦診斷峰，不能單獨證明換能器共振或 TX 電氣頻率。

## 6. 為何重建仍不像有效 B-mode

### 6.1 幾何上必然有柵瓣

聲速取 1540 m/s，1.5 MHz 波長約 1.027 mm。1.59 mm pitch 約為 `1.55 λ`。對 ±10° 掃描，要避免第一階柵瓣，pitch 約需不大於 0.875 mm。現有 pitch 超出約 82%，弧形水波紋和假目標不是後處理可以完全消除的。

### 6.2 回波功率不足

本次內部/深部窗相對 late quiet 的 SNR 接近或低於 0 dB。強紋理更可能是直耦、T/R 振鈴、共模、柵瓣和多重反射，而不是可靠散射體。

### 6.3 尚無完整通道校準

目前只有軟 PRF marker 對齊，尚未完成：

- 8 路線纜/AFE/陣元的固定時間偏移；
- 每路增益和極性；
- 元件實際中心位置；
- PDMS/凝膠分層聲速；
- 已知平面反射體的相位與深度校準。

### 6.4 TX 波形仍需儀器確認

寄存器讀回只證明寫入值與白名單一致。它不能證明 J7 高壓輸出及聲場真的以 1.5 MHz 正確發射。本次 0.5127 MHz 早期接收峰與低 SNR 都要求回到示波器/水聽器 Gate。

## 7. 下一位調試者的最短閉環

### 7.1 2026-07-31 探頭頻響補充

操作者實測目前探頭／整機響應的最佳頻點約在 `1.6–1.7 MHz`。後續可先以
`1.65 MHz` 作為示波器與聲學標定的候選中心頻率，但必須把三種頻率分開記錄：

1. **TX 設定頻率**：由 TX7316 pattern 寄存器解碼得到，只證明數位時序設定。
2. **電氣輸出頻率**：由 J7 假負載上的高壓差分探頭量得，證明實際 burst 邊緣與週期。
3. **聲學／接收峰值**：由水聽器或已知反射體回波的去振鈴時間窗量得，代表探頭、匹配層、PDMS、耦合與接收鏈的聯合響應。

「1.6–1.7 MHz 最好」目前屬於操作者的實測結論；下一次紀錄必須補上測量位置、負載、
窗長、探頭接觸狀態與原始波形。不要把 HSDC 早期串擾峰或 GUI 的
`ADC Input Target Frequency` 當成聲學中心頻率。

在 `c=1540 m/s`、`fc=1.65 MHz` 時，波長約 `0.933 mm`，現有 `1.59 mm`
pitch 約為 `1.70λ`。這會比 1.5 MHz 更容易產生柵瓣；頻響較高不等於橫向成像較好。
本代探頭應把 1.65 MHz 用於通道與回波標定，成像角度先限制在 `-4°/0°/+4°`，
再依實測點擴散函數決定是否擴大掃描。

請依次執行，不能跳步：

1. **電氣波形 Gate**：假負載、差分高壓探頭驗證 PHV_A/MHV_A burst；若頻率/邊緣/回零不符，先修 pattern，不採凝膠。
2. **單通道脈衝回波 Gate**：固定 0°，只用一個 TX/RX，平面反射體放在已知深度；確認時域中有可重複、隨深度移動的回波。
3. **逐通道校準 Gate**：對 INP5–12 記錄 delay、gain、polarity；任何一路需單獨敲擊/注入，HSDC 只能有對應槽明顯變化。
4. **8 通道平面 Gate**：不掃角，做 0° DAS；平面應在已知深度水平聚焦，不能隨 PRF 幀跳動。
5. **小角度 Gate**：先用 -4°、0°、+4°，再擴展至 11 角。1.59 mm pitch 下不要期待無柵瓣扇掃。
6. **聲學設計修正**：下一版優先把 pitch 降到 0.5–0.8 mm，增加匹配層、吸聲背襯和陣元間隔離槽；軟體超分辨率不能恢復物理上未採樣的空間資訊。

每個 Gate 保存：TX cfg、AFE/HSDC profile 名稱和 hash、示波器截圖、raw BIN hash、manifest、channel QA JSON。失敗時只改一個變量。

## 8. 相關程式與文檔

- `reconstruct_ultrasound.py`：本次自適應事件檢測修復
- `automation/tx7316_hsdc_batch_capture.py`：雙極 A 診斷 pattern 與 TX_BF_MODE OFF 安全重試
- `HKUST_BioData_Collector/app.py`：波形模式選擇入口
- `docs/10_CHANNEL_QA_AND_IMAGING_DIAGNOSIS.md`：通道 QA 與成像失敗診斷
- `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md`：固定複製 signature
- `docs/13_JESD_DOCUMENT_EVIDENCE_AND_DECISION_GATES.md`：JESD 後續 Gate

## 9. 安全與資料政策

- 僅限凝膠、仿體、水槽及假負載，不接人體。
- 本文不授權提高 TX 高壓或 AFE 增益；出現 ADC rail codes 時先降增益/幅度。
- Git 倉庫不提交 raw BIN、capture 資料夾、HSDC runtime log 或患者/人體資料。
- TX7316 GUI、AFE GUI、HSDC Pro 和自動化程式保持相同管理員權限；同一硬體一次只允許一個控制端。
