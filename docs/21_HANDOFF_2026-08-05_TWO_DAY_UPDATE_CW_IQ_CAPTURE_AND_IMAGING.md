# 2026-08-04—2026-08-05 兩日更新總交接

> **2026-08-21更正：** 本文的`I1,Q1,...,I8,Q8`與有限DDR秒數是當時尚未由TI閉環的direct-I/Q目標，不適用於新交付的`60 MHz + PLL40x + Demod + Dec=32`模式。TI確認該模式輸出8條unseparated raw lanes、只有1-based lane 1與5 active，單塊約0.559秒；必須先用TI separator取得每個`ChN_I/Q`。相關capture/preview程式在完成新格式整合前只保留作舊原型，不得用於本次raw-lane資料。最新流程見[Dec=32 raw-lane SOP](24_AFE58JD48_TSW14J50_DEC32_LONG_PW_DOPPLER_SOP_2026-08-19.md)。

更新日期：2026-08-05

適用平台：TX7316EVM + AFE58JD48EVM + TSW14J50 + HSDC Pro 5.31

上位機：`HKUST_BioData_Collector`

用途：凝膠、水槽、靜態反射體和已知流量仿體研究；不接人體、不作診斷。

## 1. 一頁結論

這兩天完成了四件核心工作：

1. 把 TI 提供的 120 MSPS、8-lane、Subclass 1 修復配置納入 normal raw-RF 基線，並讓自動採集拒絕舊的錯誤 HSDC device。
2. 修復 TX7316 Pattern Profile 的生成、寫入、回讀和 Fail-Closed 流程；上位機可規劃 1/1.5/2/2.5/4 MHz 有限 burst，但外部高壓仍必須人工設定和量測。
3. 在離線成像加入 Hann/Tukey 接收加權、coherence factor 和可選淺層共模振鈴抑制，用於區分數字通道問題與水波紋／振鈴／柵瓣問題。
4. 新增 CW Doppler／三傾角 DBUD 頁和有限 DDR complex-I/Q 採集預覽；修正 AFE DownConv 的速率關係，並把 5 MSPS、8 complex channels 的理論記錄時間算清楚。

目前可以做：

- 120 MSPS raw RF 的自動有限塊採集、通道診斷和 B-mode 離線重建；
- TX7316 白名單有限 burst 的配置、讀回和逐角度採集；
- TI `D=4 / 15 MSPS` Demod 配置的下一輪 I/Q 實機驗證；
- 在 AFE/HSDC 已手動載入匹配 Demod 配置後，由上位機抓一個有限 DDR I/Q 塊並自動預覽。

目前不能宣稱：

- 5 MSPS／`D=12` 已完成端到端硬體驗收；
- stock TSW14J50/HSDC 可連續無縫記錄 10 秒 raw RF 或 PW slow-time I/Q；
- 關閉 8 個 AFE 類比通道會自動把 HSDC 16-slot BIN 縮短一半；
- stock TX7316EVM 的 200 MHz BF_CLK 能產生精確 1/2/4 MHz CW；
- 單組 CW 總和 I/Q 可以代替三行同時獨立 DBUD 測量；
- 現有影像或流速結果可用於人體或臨床判讀。

## 2. 先把三條資料路徑分開

### 2.1 B-mode / raw RF

```text
TX7316 finite burst
  -> PZT / T-R switch
  -> AFE58JD48 120 MSPS raw ADC
  -> 8 physical JESD lanes / 16 converter columns
  -> TSW14J50 DDR
  -> HSDC BIN
  -> 軟對齊、帶通、RX-DAS、角度複合
```

這是目前最成熟的路徑。HSDC 的 `ADC Input Target Frequency` 只影響顯示／分析標記，不會設定 TX 頻率。

### 2.2 PW Doppler

```text
固定 TX 角度 + 固定 PRF
  -> 每個 pulse 在固定深度取 gate
  -> complex demod / matched filter
  -> 每 pulse、每通道保留少量 I/Q
  -> slow-time wall filter / Kasai / STFT
```

HSDC external trigger 只定義一個 DDR block 的開始，並不會替每個 PRF 建立一筆記錄。真正 5–10 秒 PW Doppler 的推薦後端仍是自訂 FPGA：`PRF event -> depth gate -> DDC/IQ -> decimate -> DDR/stream`。

### 2.3 CW Doppler / DBUD

```text
TX7316 continuous wave
  -> 三個物理傾角的 TX/RX row
  -> AFE analog CW I/Q 或 AFE digital DDC I/Q
  -> 三行同時、獨立、帶符號 Doppler frequency
  -> DBUD least-squares velocity / direction
```

CW 沒有深度門，整個 TX/RX 重疊體積都會進入頻譜。若 AFE 類比 CW 路徑只輸出一組內部總和，不能把它當成三行獨立資料。

## 3. 通道映射：已改善的證據與仍需保留的 Gate

### 3.1 歷史故障

2026-07-25 distinct-code 測試曾穩定得到：

```text
duplicate slots: [3,5] [4,6] [9,15] [10,16]
missing converters: 3,4,15,16
```

這是數字 transport／deformatter 問題，不是探頭串擾、增益、凝膠或 beamforming 問題。

### 3.2 TI 修復基線

normal raw-RF 現採用：

| 端點 | 配置 | 公開記錄 SHA-256 |
|---|---|---|
| AFE GUI | `JESD 120MSPS_Subclass1_8L.CFG` | `FC5A7093E21D816B7063D826759109C60BC1E31D294C7898B26808109ABAA344` |
| HSDC Pro | `AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1` | `78923A1787DC6794274398B5457DF1EE2F40852B0E9854DDC6AED41E9CDC8E67` |

供應商 CFG/INI 的內容屬本機支援材料，不提交到公開倉庫；倉庫只保留檔名、雜湊、安裝步驟和去識別化測試結果。

### 3.3 2026-08-04 資料點

`Test00804.bin`：

| 項目 | 值 |
|---|---|
| bytes | `2,097,152` |
| SHA-256 | `F4BDB7844898C223FD98186157B4D56A37AFD9BC33DAA3A44634BCEC4CDF816D` |
| 觀察 | 未再看到歷史故障的位元級複製組；16 列不是簡單複製 |

這一點支持「TI 修復 profile 已解除目前的 deterministic-copy 阻塞」，但若本次檔案不是 16 個獨立穩定 code 的 digital test，就不能把它取代正式的 16/16 unique-code acceptance。後續 Demod/IQ profile 也必須獨立重跑同樣 Gate；No-Demod 通過不代表 I/Q unpack 一定正確。

## 4. TX7316 更新與遇到的問題

### 4.1 Pattern 為空／沒有波形

症狀：TX GUI 的 Pattern Profile 顯示 `TOTAL TRANSITIONS = 0`，曲線只停在 AVSS。

含義：配置沒有寫入、寫入了錯誤 profile，或上位機產生了無效計畫；這不是正常 1 MHz 波形。

目前處理：

- 上位機第一頁新增 TX pattern plan、cycles、符號電平和波形預覽；
- 正式採集在 `TX_BF_MODE=0` 時寫入白名單 Pattern/Repeat/Delay；
- 每一欄寄存器讀回必須等於預期值，否則 Fail Closed；
- run 內保存可回載 GUI 的 verified CFG 和索引 JSON；
- 任何 plan 欄位改變都會撤銷舊確認。

### 4.2 5-level 電平命名曾被理解反了

`HV_A/HV_B` 是外部電源軌，不是可由 SPI 寫入的 DAC 電壓。現有上位機按實際 GUI/pattern 使用：

- `HV_A`：外層較高幅值；
- `HV_B`：靠近 AVSS 的內層幅值；
- 必須滿足 `|HV_A| > |HV_B|`，例如 100 V / 50 V；
- 軟件只選 `P_HV_A/P_HV_B/AVSS/M_HV_A/M_HV_B` 路徑，不能修改實際供電。

### 4.3 頻率與陣列幾何

PZT-5H 厚度 1 mm 的自由厚度共振仍需以阻抗分析／水聽器實測確認。軟件預設改為 1 MHz 是為了目前低頻回波和安全聯調，不代表材料的精確厚度共振已由公式唯一決定。

對 1.2 mm 或 1.59 mm pitch：

- 1 MHz 水/軟組織波長約 1.54 mm；
- 1.2 mm 約 `0.78 λ`，1.59 mm 約 `1.03 λ`；
- 均大於 `λ/2`，掃角時必然有柵瓣風險；
- delay programming 只能形成主波束，不能消除空間混疊。

因此先用 `-4° / 0° / +4°` 和已知平面反射體驗證，再擴角；不要把更多角度當成修復物理 pitch 的手段。

### 4.4 CW 頻率邊界

TX7316 關係為：

```text
fCW = BF_CLK / (16 × 2^CLK_DIV)
```

stock 200 MHz BF_CLK 可直接得到 12.5、6.25、3.125、1.5625 MHz。精確 1/2/4 MHz CW 需要先建立並驗證 128 MHz BF_CLK 硬體路徑。上位機目前只允許 3.125 MHz 進入限時 CW；1/2/4 MHz 只做有限 Pattern 或配置計畫，不會冒充已驗證 continuous wave。

## 5. HSDC 採集：問題、根因和軟件修復

| 症狀 | 判讀 | 目前處理 |
|---|---|---|
| `Start of Packet was not found` | firmware/profile/JESD 初始化不匹配，DDR 沒收到合法 packet | 冷啟動 AFE/HSDC，重新選擇匹配 profile 並下載 firmware；不要在錯誤 device 上繼續 Capture |
| selected device 是舊 `AFE58JD48_S1_K8_G128OFF` | 自動腳本期望 TI 修復 profile，但 GUI 仍停在舊項目 | normal 採集只接受 TI No-Demod profile 或明確白名單；錯誤時直接提示先選 profile |
| `ADC_Save_Raw_Data_As_Binary_File` code 5000 | TI DLL 可能在背景仍寫檔，API 已先返回錯誤 | 按預期 bytes 等待檔案大小穩定，不立即重試或中止 |
| 點採集看似沒反應 | 可能按了 Dry Run、子命令窗被遮住、或主 UI 等待新的 manifest | 子命令獨立視窗、manifest polling、進度／心跳與狀態文字 |
| HSDC trigger 一直等待 | J13 無合法 start edge、Trigger Option 錯或電平／極性錯 | 先關 TX 高壓，示波器確認 J13，再 Arm；J25 不是 HSDC trigger |

`Trigger mode enable` 只讓 TSW 等待一個 capture-start edge。AFE/JESD 初始化後本來就持續輸出，不需要每個 PRF 重新 arm。`Auto Re-Arm Trigger` 也不會把多個有保存空檔的 BIN 變成無縫心動週期。

## 6. 成像變化與水波紋的判讀

兩次採集的 B-mode 結構有可見差異，影像內還有週期性水平／弧形波紋。由於後續 16 列沒有再呈現歷史 bit-exact copy，這些現象不應首先歸因為 JESD 通道複製。更可能的來源是：

- TX feedthrough、T/R recovery 和淺層 ring-down；
- 水槽多重反射、表面波或探頭／反射體位置微小變化；
- 1.2/1.59 mm pitch 在 1 MHz 下的柵瓣；
- 通道增益、延時、極性或物理順序尚未逐通道校準；
- 無共同硬體觸發時，以串擾峰做軟對齊的殘餘抖動。

處理頁已新增三類可選項，均不改寫 raw BIN：

1. RX apodization：Uniform、Hann、Tukey `α=0.5`；
2. coherence factor：保守使用 `sqrt(CF)`；
3. 共模振鈴抑制：只在 TX 後淺層 0–12 mm 逐漸退場，避免全深度相減刪除真實平面反射。

建議 A/B 順序：

```text
Uniform
  -> Tukey
  -> Tukey + sqrt(CF)
  -> 只在確認淺層共模污染時，再加 common-mode suppression
```

若一個選項讓反射體位置漂移、深層訊號消失或僅留下漂亮但不可重複的紋理，應拒收。最終仍需逐通道 planar-reflector 校準，而不是靠濾波遮蓋硬體問題。

## 7. AFE I/Q 解調：本次最重要的速率修正

AFE GUI 的 `MANUAL_DECIMATION_FACTOR` 是低通抽取器的硬體 `D`。Down-conversion 後 complex-I/Q rate 為：

```text
fIQ = fADC / (2D)
```

在 `fADC = 120 MSPS` 時：

| complex I/Q rate | AFE hardware D | 8 complex channels 資料率 | 512 MiB 理論時間 |
|---:|---:|---:|---:|
| 15 MSPS | 4 | 480 MB/s | 1.118 s |
| 10 MSPS | 6 | 320 MB/s | 1.678 s |
| 7.5 MSPS | 8 | 240 MB/s | 2.237 s |
| 6 MSPS | 10 | 192 MB/s | 2.796 s |
| 5 MSPS | 12 | 160 MB/s | 3.355 s |

計算使用每個 sample instant 的 `I1,Q1,...,I8,Q8`，共 16 個 int16 word。不能再乘一次 complex factor，否則會把資料率錯算兩倍。

重要區分：

- AFE 實體 ADC/JESD clock 仍是 120 MSPS；
- 5 MSPS 是數位 DDC + decimation 後的 complex I/Q rate；
- 只改 HSDC 顯示欄不會改變硬體輸出；
- TI 過渡包直接可追溯的是 `D=4 / 15 MSPS`；
- `D=12 / 5 MSPS` 要另建 AFE CFG、匹配 HSDC unpack profile，再通過 I/Q 和通道 Gate。

本機已把 Demod HSDC profile 安裝到 HSDC Pro ADC files 目錄；公開交接只記錄：

```text
device: AFE58JD48_Custom_PLL_MODE_40x_Demod_SubClass1
SHA-256: F961A88CA549C6300309E710A843D1073ED0B6374798F442AC8154C07962D372
layout target: I1,Q1,I2,Q2,...,I8,Q8
```

供應商 INI 本體不提交。此 profile 已能作為實驗入口，但仍須用 matching AFE CFG 完成實機驗收。

## 8. 新增的 CW DDR I/Q 採集頁

上位機 `CW多普勒 DBUD` 頁現在包括：

- 1/2/3.125/4 MHz TX/NCO 計畫；
- 15/10/7.5/6/5 MSPS I/Q 選擇和對應 D；
- 8 個邏輯貼片和三個物理傾角 row；
- Snell 折射角、NCO word、DDR 時長、DBUD least-squares；
- profile 安裝／雜湊狀態；
- finite DDR `Dry run`、normal/software trigger、進度和 manifest；
- 自動輸出 CH1–CH3 complex magnitude 與基帶頻譜預覽。

完成資料結構：

```text
cw_capture_YYYYMMDD_HHMMSS/
  cw_iq.bin
  cw_capture_manifest.json
  cw_iq_summary.json
  cw_iq_preview.png
```

硬體採集腳本會檢查：

- Python 2.7 / 32-bit DLL / Administrator；
- samples 為 4096 的整數倍；
- 預期 bytes = `samples × 16 words × 2 bytes`；
- 最終 BIN 大小必須精確相等；
- 失敗時 manifest 寫入 `status=error` 和錯誤原因。

它不會自動猜測 AFE 未驗證寄存器。操作者必須先在 AFE GUI 載入與所選 D 相符的 DownConv CFG，並在 HSDC 選到匹配 Demod device。

## 9. 明確的下一次實驗流程

### Phase A：保留 raw-RF 回歸基線

1. TX 高壓 OFF、CW OFF。
2. AFE GUI 載入 TI `JESD 120MSPS_Subclass1_8L.CFG`。
3. HSDC 選 TI `AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1`。
4. 先跑 16 個 distinct code；驗收 duplicate groups 為空、16 codes 各一次。
5. 再用 Analog Input 和已知平面反射體確認回波、通道順序、削頂和延時。

### Phase B：第一個數位 I/Q 實驗，只做 D=4 / 15 MSPS

1. 保留 No-Demod 配置和 hashes，不覆寫。
2. AFE GUI 載入 TI 過渡包的 `JESD 60MSPS_Subclass1_4L_Decimation=4_DownConvEn.cfg`。
3. DEMOD 設 NCO 為測試正弦中心；確認 Down Conversion 與 Decimation 均啟用。
4. HSDC 選 `AFE58JD48_Custom_PLL_MODE_40x_Demod_SubClass1`，顯示率設 15M。
5. 依次輸入：

   - `fNCO`：頻譜接近 DC；
   - `fNCO + 1 kHz`：輸出約 `+1 kHz`；
   - `fNCO - 10 kHz`：輸出約 `-10 kHz`。

6. 對 8 個 complex channels 分別給唯一 tone/code，確認 I/Q order、正負頻率和通道沒有複製。
7. 在上位機先 `Dry run`，再抓 0.1–0.5 秒有限塊；檢查 BIN 精確大小、manifest 和 preview。

### Phase C：5 MSPS / D=12

只有 Phase B 通過後才進行：

1. 從 AFE GUI／正式寄存器工具生成獨立 `D=12` CFG；不要直接改 TI No-Demod 基線。
2. 確認 FIR coefficient、shift/scale、compression/JESD output packing。
3. HSDC 端建立匹配 profile；不要只把 displayed rate 改成 5M。
4. 重跑 `DC / +1 kHz / -10 kHz / 8-channel unique` Gate。
5. 最後才抓約 3.35 秒 DDR 塊，檢查至少覆蓋一個仿體脈動週期。

### Phase D：已知流量仿體

1. 先做 zero-flow，wall filter 後中心應接近 0。
2. 做穩態低／中／高三個已知速度，確認頻率符號與泵方向一致。
3. 三行必須同時獨立取樣，才能執行 DBUD。
4. 保存 row angles、聲速、實測泵速、TX/NCO、I/Q rate、所有 hashes 和原始 I/Q。
5. 工程 Gate 先採相對誤差 `≤10%` 和重複性；未通過前不宣稱論文級性能。

## 10. PW Doppler 的最佳長時方向

對頸動脈樣仿體，先從 `PRF = 5 kHz` 而非 20 kHz 開始：

- 5 kHz 無模糊深度約 154 mm；
- 20 kHz 無模糊深度約 38.5 mm；
- 20 kHz 會增加不必要的 TX duty、資料事件率和深度限制。

最終 FPGA 記錄格式建議：

```text
pulse_index
timestamp
profile_index
I/Q[channel, gate]
quality/status flags
```

每 PRF 只保留固定深度 gate 的 complex I/Q，才能把 10 秒資料從數十 GB 降到數 MB。逐 PRF 掃角不屬於 PW ensemble；先用 B-mode 定位血管，再固定波束角度記錄 slow-time。

## 11. 開發工具邊界

- TSW14J50 主 FPGA 是 Intel/Altera Arria V：使用 Quartus Prime 和 Intel USB-Blaster II；J-Link 不適用。
- TSW14J50 上 5M570 CPLD 同樣屬 Intel/Altera JTAG 生態。
- HSDC Pro 的 `.rbf` 是每次上電後載入 FPGA 的 runtime image，不是可由 GUI 修改的 register-only CFG。
- TSW_controller 是 TCP/腳本控制層，不會自動新增 FPGA 內不存在的 depth-gate/DDC/streaming datapath。
- TX7316 CPLD firmware installer 只安裝 runtime/工具；只看到 Uninstall 不等於取得可修改的 CPLD source project。

## 12. 本次代碼範圍

主要新增／修改：

- `HKUST_BioData_Collector/app.py`：CW DBUD、TX plan、採集監控、成像選項與 UI 整合；
- `HKUST_BioData_Collector/cw_doppler_model.py`：角度、NCO、D、DDR、DBUD 模型；
- `HKUST_BioData_Collector/cw_capture_ui.py`：有限 DDR I/Q 控制和預覽；
- `HKUST_BioData_Collector/cw_iq_analysis.py`：I/Q 拆包、摘要和頻譜圖；
- `automation/hsdc_iq_capture.py`：Python 2.7 HSDC I/Q finite-block backend；
- `automation/tx7316_cw_control.py`：限時 CW 和 fail-safe stop；
- `automation/stage_cw_doppler.py`：安全 staging；
- `automation/tx7316_hsdc_batch_capture.py`：profile 驗證、TX pattern/readback、HSDC save 完整性；
- `reconstruct_ultrasound.py`：RX apodization、CF、common-mode ringdown suppression；
- 對應 operation guides、configuration audit 和單元測試。

本機 runtime copy 位於：

```text
E:\Users\dxhui\Desktop\TI_AFE58jd48\UltrasoundImagingData_Capture\HKUST_BioData_Collector
```

Git 倉庫內的 `HKUST_BioData_Collector` 是 canonical source；修改後要重新同步 runtime copy，不能只改其中一份。

## 13. 已完成的軟件驗證

最近一次完整回歸：

```text
python -m unittest discover -s HKUST_BioData_Collector/tests -p "test_*.py"
-> 48 tests passed

python HKUST_BioData_Collector/app.py --self-test
-> PASS
```

另外完成：

- Python 2.7 `hsdc_iq_capture.py` 5 MSPS / 16,777,216 samples dry run：預期 512 MiB；
- synthetic complex-I/Q：+1/+2/+3 kHz 峰恢復約 991.8/1983.6/3013.6 Hz；
- 自動生成 `cw_iq_summary.json` 和 `cw_iq_preview.png`。

這些是軟件 Gate，不等於 AFE/TSW 實機 I/Q Gate。

## 14. 不要做的事

- 不要把 J7 SYNCP 輸出當成外部 PRF 輸入口。
- 不要把 AFE J25 當成 HSDC J13 capture trigger。
- 不要用一條未緩衝線直接並接多塊板卡的 clock/sync 輸入。
- 不要只修改 HSDC `ADC Output Data Rate` 來宣稱已降低硬體資料率。
- 不要因為 AFE 關閉 8 個通道，就假設 raw BIN 自動只剩 8 列。
- 不要在 No-Demod profile 通過後跳過 Demod profile 的 I/Q/channel Gate。
- 不要把多個保存間有長空檔的 BIN 拼成連續心動週期。
- 不要用濾波後影像替代 distinct-code transport acceptance。
- 不要在高壓上電時改接線、pattern、clock 或 trigger。
- 不要把供應商私有 CFG/INI、完整寄存器表、raw BIN 或人體資料提交到公開 GitHub。

## 15. 接手者的最短清單

```text
[ ] git checkout agent/pw-doppler-handoff
[ ] python HKUST_BioData_Collector/app.py --self-test
[ ] python -m unittest discover -s HKUST_BioData_Collector/tests -v
[ ] 核對 normal raw-RF AFE/HSDC profile 名稱與 SHA-256
[ ] TX HV OFF / CW OFF，重跑 16/16 distinct-code Gate
[ ] D=4 / 15 MSPS 做 DC、+1 kHz、-10 kHz 和 8-channel I/Q Gate
[ ] 上位機抓 0.1–0.5 s I/Q，核對 exact bytes / manifest / preview
[ ] 通過後才建立 D=12 / 5 MSPS 配置
[ ] 最後才做 ±5 V、限流、仿體上的限時 CW／已知流速測試
```

相關文檔：

- `docs/16_PW_DOPPLER_MULTI_CYCLE_DESIGN_2026-08-01.md`
- `docs/18_HANDOFF_2026-08-01_PW_DOPPLER_AND_CONFIG_AUDIT.md`
- `docs/19_HSDC_J13_EXTERNAL_TRIGGER_FIX_2026-08-01.md`
- `docs/20_TI_AFE58JD48_CHANNEL_COPY_FIX_2026-08-03.md`
- `HKUST_BioData_Collector/PW_DOPPLER_OPERATION_GUIDE.md`
- `HKUST_BioData_Collector/CW_DOPPLER_OPERATION_GUIDE.md`
