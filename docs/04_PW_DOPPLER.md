# PW Doppler與多個心動週期

## 核心結論

- 1 kHz也能算Doppler，適合慢流；延長burst或多發週期只提高SNR/窄化頻譜，不提高Nyquist速度。
- 提高無混疊速度靠提高PRF或降低發射頻率，不是把一個burst拉長。
- 原裝TX7316EVM CPLD約1 kHz，GUI無可用的PRF參數；J7 SYNCP是輸出，不能直接灌20 kHz。
- 多個HSDC BIN之間有保存空檔，不能拼成連續心動週期。真正6–10秒需要一次不間斷的距離門I/Q慢時間流或足夠長的單次DDR資料。

## Doppler公式

```text
fD = 2 f0 v cos(theta) / c
v = fD c / (2 f0 cos(theta))
vNyquist = c PRF / (4 f0 |cos(theta)|)
zUnambiguous = c / (2 PRF)
```

以1 MHz、流束夾角60°：1 kHz的Nyquist速度約0.77 m/s，5 kHz約3.85 m/s。流束夾角不是TX steering angle本身；必須從B-mode中估計管道方向再校正。

## A. 用現有原板做短塊1 kHz PW Doppler

1. 先用B-mode定位管腔中心和深度。
2. 固定一個TX偏轉角；一個ensemble內不掃角。
3. TX頻率1 MHz，4–8 cycles，CPLD約1 kHz。
4. SYNCP可接TSW J13以固定單個block的開始；raw AFE模式J25可留空。
5. HSDC 120 MSPS、4,194,304 samples/channel，包含約35個1 kHz脈衝；若要256-pulse FFT，需更長單次block且確認DDR容量。
6. 按每1 ms切幀，以`t=2z/c`取距離門，I/Q解調、通道合成、wall filter，再做慢時間FFT。
7. 這個模式能驗證流向/大致頻移，不能用多次Save拼出心動時間軸。

## B. 連續6–10秒的推薦架構

```text
共同PRF時基
  ├─ TX控制接口：TR_BF_SYNC/TR_EN（不是J7輸出回灌）
  ├─ AFE J25或FPGA幀同步
  └─ TSW J13：只觸發一次Capture Start

每個PRF週期的120 MSPS RF
  → 1 MHz I/Q解調
  → 指定深度的1.5–3 mm距離門
  → RX延時校正與相干求和
  → 每個PRF保留1個複數I/Q
  → 以PRF慢時間率連續存6–10秒
```

推薦先5 kHz而不是20 kHz：對25–40 mm仿體深度裕量大，1 MHz速度量程也足夠。20 kHz無模糊深度只有38.5 mm，且必須有自製CPLD/FPGA同步控制與低壓驗證。

## C. 20 kHz外部源如何接

不能把函數發生器接到J7 pin2。需要以下任一方式：

1. 修改並重新燒錄TX7316 EVM CPLD工程，使它產生20 kHz的正確差分/使能時序；或
2. 在接口板上隔離原CPLD驅動後，用FPGA按TX7316電氣規格驅動真正的同步控制輸入。

同一主時基經有源扇出送到TX控制、AFE J25（若用TGC/demod）和TSW J13。先在低壓假負載用示波器驗證電平、極性、脈寬、延時和沒有總線衝突，再上高壓。

## D. AFE/TSW配置

### 原始RF短塊

- AFE：Analog Input、120M 8L Subclass1、Min Gain起步、LPF15/20 MHz、Active Termination Disable。
- HSDC：120M、average OFF、continuous OFF、capture-to-file streaming OFF。
- `ADC Input Target Frequency=1M`只供顯示。

### 連續I/Q

優先在FPGA做距離門；AFE的數字demod/decimation也可用，但需相符的JESD profile、LO/FIR、抽取率和PC解包。不要只把HSDC的120M文字改成5k；ADC fast-time採樣率和PRF是兩種不同速率。

## E. 慢時間處理

1. 每個PRF切一個fast-time frame；
2. 帶通0.6–1.4 MHz（按實測頻譜調）；
3. Hilbert或數字混頻得到I/Q；
4. 深度門積分，RX相位校正與求和；
5. 去均值/50–100 Hz wall filter；
6. 128或256 pulse Hann窗STFT，75%重疊；
7. 用實測PRF、f0和流束角轉速度；
8. 保存原始I/Q、濾波I/Q、時間戳、配置JSON、spectrogram和包絡。

## F. UI現狀

UI的PW Doppler頁能計算PRF/深度/速度/容量並啟動固定角度短塊採集。它另有`TI EXT_TRIG 分塊重播 · 非連續`卡片，可按TI建議為相位鎖定、每次完全相同的測試序列規劃trigger-delay窗口，逐段保存exact-size BIN、SHA-256與manifest；詳見[TI EXT_TRIG分塊重播指南](../HKUST_BioData_Collector/TI_EXT_TRIGGER_REPLAY_GUIDE.md)。

UI不會把原板PRF改成5或20 kHz，也不會把有保存缺口的BIN宣稱為連續心動資料。完整連續模式需新增FPGA/AFE抽取資料入口後再啟用真正可持續的資料流後端。
