# 2026-08-07 AFE Demod Import與長時多普勒交接

> **2026-08-19更新：** TI後續確認TSW14J50不能只選8個AFE通道寫DDR，完整16通道都會被DDR接收；同時指出FPGA可捕獲`33,554,432`個HSDC樣點並由GUI導出。本文第7節的8通道容量解釋保留作歷史記錄，最新Dec=32容量核算、操作Gate與TI待確認項目以[Dec=32完整SOP](24_AFE58JD48_TSW14J50_DEC32_LONG_PW_DOPPLER_SOP_2026-08-19.md)和[2026-08-19總交接](25_HANDOFF_2026-08-19_SCOPE_DOPPLER_AND_TI_DEC32.md)為準。

適用平台：TX7316EVM + AFE58JD48EVM + TSW14J50/HSDC Pro。

範圍：實驗室信號源、水槽、凝膠與流體仿體。不得用於人體或臨床診斷。

本文件只記錄可公開的操作結論、檔案雜湊與測試判斷。TI安裝包、transition package、NDA資料、原始BIN和私有寄存器序列不提交到本倉庫。

## 1. 一頁結論

今天不是「沒有採集到資料」。已確認：

1. AFE的Down-conversion、Decimation和同步序列確實到達TSW14J50/HSDC。
2. HSDC保存的`ADC_Temp.bin`大小和4個transport column完全相符。
3. AFE預設同步字`0x2772`以offset-binary碼`42866`出現在兩個活動transport column中。
4. AFE GUI每次按`Import Data from HSDC Pro`都會更新`Demod Separated Data.csv`，但輸出始終為0 byte。

所以目前失敗點位於：

```text
HSDC transport BIN
  -> AFE GUI的JESD/channel decompressor與data separator
  -> Demod曲線/分離後I/Q
```

最高可信根因是軟件組合不在TI transition已驗證範圍：

| 項目 | TI transition要求 | 本機實測 |
|---|---|---|
| HSDC Pro | 5.00 | 5.31 |
| AFE58JD48 EVM GUI | 1.2.3 | 2.0.0.1 |
| AFE EVM user guide的Demodulator Plot | 原流程針對TSW14J56 | 現在使用TSW14J50 transition |

把`5.31`手動加入AFE GUI的`Supported HSDC Pro Version`只能繞過版本檢查，不能證明Automation API、臨時BIN格式或decompressor仍兼容。

短期最佳路徑是先用TI指定的舊版組合或自寫離線separator把現有M=4資料解開。長期最佳路徑仍是改TSW14J50 FPGA：在板上按共同PRF選距離門、形成慢時間I/Q，再寫DDR，而不是把連續高速I/Q全部存入DDR。

## 2. 今天實際使用的配置

### 2.1 AFE58JD48 GUI

載入本機TI transition配置：

```text
JESD 60MSPS_Subclass1_4L_Decimation=4_DownConvEn.cfg
```

GUI狀態與操作：

- `CTRL_MODE = Custom PLL Mode`
- `PLL_MODE = 80x`
- `EN_DEMOD = Enabled`
- Down-conversion enabled
- Decimation enabled
- `COMPR_FACTOR = 1`
- `MANUAL_DECIMATION_FACTOR = 4`
- coefficient preset起點為M=4對應值
- 完成`PRELOAD_COEFF_MEMORY`脈衝
- 執行一次`MANUAL_TX_SYNC`

重要區分：AFE GUI中的`MANUAL_TX_SYNC / Generate Trigger`是讓Demod/Profile設定在AFE內生效，不是叫HSDC開始一次DDR capture。

### 2.2 NCO頻率

GUI顯示`MANUAL_FSWEEP_START = 8192`，右側文字仍標成`10 MHz`。實際ADC sample rate為60 MSPS，因此真正NCO為：

```text
f_NCO = 8192 × 60 MHz / 65536 = 7.5 MHz
```

這會影響已知tone測試的中心頻率，但不是Demod Import空白的原因。

### 2.3 HSDC Pro

選擇匹配的本機transition profile：

```text
AFE58JD48_Custom_PLL_MODE_80x_Demod_SubClass1
```

觀察到：

- 4個HSDC transport column；
- `ADC Output Data Rate = 60M`；
- 每個transport column採`131072` samples；
- software trigger可以完成capture；
- BIN總大小為`1,048,576 byte`。

計算完全相符：

```text
131072 sample/column × 4 columns × 2 byte = 1,048,576 byte
```

HSDC顯示4個channel只表示4個transport column，不表示只啟用了4個物理RX，也不能直接宣稱已得到4路或8路正確I/Q。物理通道身份必須在channel decompression之後用唯一碼驗證。

## 3. `ADC_Temp.bin`的可重現證據

本機檔案，不提交Git：

```text
E:\Users\dxhui\Desktop\TI_AFE58jd48\tmp\afe_demod_import\ADC_Temp.bin
```

SHA-256：

```text
99951621AB6AB676D40227FEC05E19817459A7188CDB9950194563C92A230549
```

按4個little-endian uint16 transport column重排後：

| column | min | max | standard deviation | unique values | 初步判斷 |
|---:|---:|---:|---:|---:|---|
| 1 | 32655 | 42866 | 114.639 | 200 | 活動，有同步burst |
| 2 | 32768 | 32768 | 0 | 1 | 常數/padding候選 |
| 3 | 32687 | 42866 | 114.817 | 141 | 活動，有同步burst |
| 4 | 32768 | 32768 | 0 | 1 | 常數/padding候選 |

HSDC碼是offset binary。同步峰值的有效signed值為：

```text
42866 - 32768 = 10098 = 0x2772
```

這證明AFE已執行Demod同步，且同步資料到達TSW/HSDC。兩個常數column可能是padding或packing結果；在separator完成前不能把它解釋成壞通道。

曾建立高位XOR診斷副本`ADC_Temp_sync10098.bin`，SHA-256為：

```text
CE467D5789935B45230E18117FBB834A0E9BE9A930CC2DF841406F7E91881705
```

它沒有令AFE GUI產生曲線。此副本只作診斷，後續解析必須回到原始`ADC_Temp.bin`，不能把XOR副本當採集原始檔。

## 4. 為什麼AFE Demodulator Plot沒有曲線

### 4.1 已排除

- 不是capture沒有完成：BIN大小、transport數與sample數一致。
- 不是AFE沒有同步：原始transport中存在`0x2772`同步burst。
- 不是純路徑拼寫錯誤：AFE GUI點擊Import後會更新目標CSV的時間戳。
- 不是等待時間不足：等待15秒仍無輸出。
- 不是「必須彈窗」：user guide只描述內嵌raw graph與HSDC FFT更新，沒有承諾另開彈窗。

### 4.2 仍需解決

按優先級排列：

1. **版本不兼容**：HSDC 5.31 + AFE GUI 2.0.0.1不等於transition驗證的5.00 + 1.2.3。
2. **TSW14J50 transition decompressor不匹配**：AFE EVM主手冊的Plot功能明確以TSW14J56為對象；TSW14J50依賴transition提供的額外適配。
3. **BIN/transport packing識別失敗**：AFE GUI callback有執行，但separator沒有產生任何row，符合header、column count或firmware metadata未被識別的表現。
4. **次要可能**：目前HSDC profile、Firmware INI或AFE GUI內部對board/firmware名稱的匹配仍不完整。

今天不再把`ADC_Temp.bin`反覆改名、XOR或換路徑。這些操作已證明不能修復底層separator。

## 5. 三個GUI各自能做什麼

| 軟件 | 能做 | 不能做 |
|---|---|---|
| TX7316 EVM GUI | pattern、burst/CW、delay profile、T/R switch與TX寄存器配置 | 不能改AFE sample rate、不能讓TSW按距離門寫DDR |
| AFE58JD48 EVM GUI | VCA/ADC/LMK、數字DDC、NCO、FIR/decimation、compression與Demod測試 | 不能直接把HSDC變成無限串流器；Plot仍依賴匹配的TSW/HSDC decompressor |
| HSDC Pro | 載入TSW FPGA firmware/ADC INI、設定JESD transport、一次性寫DDR、讀回與保存BIN | trigger只決定capture起點；不能自動按每個PRF切距離門，也不會僅因AFE關通道就縮小既定transport |
| TSW_controller | 透過腳本/TCP執行既有TSW INIT/CONFIG/STATUS命令 | 不會生成新的FPGA datapath，不能用GUI腳本實現range gate、I/Q或慢時間記錄 |

## 6. 「15 MHz採樣」的正確含義

目前配置不是把AFE實體ADC降到15 MSPS，而是：

```text
AFE ADC/JESD基準：60 MSPS
DDC decimation：M = 4
每個物理通道的complex I/Q rate：60 / 4 = 15 MSPS
```

所以HSDC仍顯示`60M`是合理的。4個60-MSPS transport column承載壓縮/交錯後的資料。只有matched decompressor才能還原成物理通道I/Q。

## 7. TSW14J50 DDR能記多久

TSW14J50有最多256M個16-bit sample，即512 MiB資料容量。下表是假設8個物理通道、每通道complex int16 I/Q、忽略header與保留空間的理論值；所有高M模式都必須先取得匹配AFE CFG、HSDC INI/firmware並通過解包Gate。

| 路徑 | 每通道有效率 | 總資料率 | 512 MiB理論時長 | 目前狀態 |
|---|---:|---:|---:|---|
| raw RF，16 transport，120 MSPS | 120 MSPS real | 3.84 GB/s | 0.140 s | 已知基線 |
| AFE DDC M=4，8路complex I/Q | 15 MSPS | 480 MB/s | 1.12 s | transport已捕獲，separator未通 |
| AFE DDC M=8，8路complex I/Q | 7.5 MSPS | 240 MB/s | 2.24 s | 需匹配profile與驗收 |
| AFE DDC M=12，8路complex I/Q | 5 MSPS | 160 MB/s | 3.36 s | 需匹配profile與驗收 |
| AFE DDC M=20，8路complex I/Q | 3 MSPS | 96 MB/s | 5.59 s | 預設FIR上限候選；需匹配profile與驗收 |
| FPGA PW gate，5 kHz PRF，8路complex | 5 kSPS slow-time | 160 kB/s | 約55.9 min | 需自訂FPGA |
| FPGA CW baseband，50 kSPS，8路complex | 50 kSPS | 1.6 MB/s | 約5.59 min | 需自訂FPGA |

AFE內建DDC只能把資料率從數十GB級降到數GB/秒級的記錄量；真正令10秒、60秒變容易的是再做距離門或窄帶baseband抽取。

## 8. 最推薦的長時血流方案

### 8.1 最近可完成：AFE DDC + 有限DDR block

目的：先得到至少一個完整心動周期，且不改FPGA。

1. 用TI transition指定的HSDC 5.00 + AFE GUI 1.2.3重跑M=4。
2. 若TI舊版本取得困難，直接開發離線separator解析今天的4-column BIN。
3. 先完成7.5 MHz附近的known-tone正負頻移驗證。
4. 完成8個物理通道unique-code與I/Q方向驗證。
5. 再請TI提供或自行建立匹配的M=8、M=12 profile；先M=8，再M=12。
6. M=12理論3.36秒，已足以覆蓋約3至5個常見心動周期，但仍需以實際可用DDR長度為準。

這條路的優點是修改少。缺點是一次仍是有限DDR block，而且多次Capture與Save之間有空檔，不能把多個BIN直接拼成連續心動周期。

### 8.2 最終推薦：AFE DDC或FPGA DDC + PRF距離門 + 慢時間I/Q

PW Doppler的理想TSW14J50 FPGA資料流：

```text
共同TX/PRF marker
  -> pulse_index與hardware timestamp
  -> 等待2z/c到目標深度
  -> 只取固定2 mm左右range gate
  -> 複數解調/匹配積分/低通
  -> 保留8路I/Q或先做相干beam sum
  -> 每個PRF寫1個complex slow-time sample
  -> DDR一次連續記10至60秒
```

以5 kHz PRF、8路complex int16計算：

```text
10秒：1.60 MB（約1.53 MiB）
60秒：9.60 MB（約9.16 MiB）
```

這是同一套板卡真正適合長時間PW Doppler的方案。HSDC GUI與TSW_controller無法靠配置實現，必須在Quartus工程中增加RTL與host讀出協議。

### 8.3 如果接受CW沒有深度分辨率

CW Doppler不需要每個PRF距離門，可在AFE/FPGA做NCO、低通後，把每路complex I/Q降到20至50 kSPS，再寫DDR。50 kSPS、8路、complex int16時，60秒約96 MB，板載DDR有足夠裕量。

代價是整條聲束上的移動散射體都混合在一起，不能像PW一樣選定頸動脈管腔深度。若最終目標是定深、排除近場或其他血管，仍優先PW方案。

## 9. 明天的最短恢復流程

### Gate 0：安全與版本凍結

- 高壓關閉，以信號源或流體仿體測試；
- 不覆寫今天的原始`ADC_Temp.bin`；
- 記錄AFE GUI、HSDC Pro、AFE CFG、HSDC profile和TSW firmware名稱；
- 不把transition package或NDA資料提交Git。

### Gate 1：先修separator，不再重做同一Capture

優先方案：向TI取得並隔離安裝`HSDC Pro 5.00`與`AFE58JD48 EVM GUI 1.2.3`。不要直接覆蓋目前可工作的5.31/2.0.0.1環境，建議使用另一台PC、虛擬機或完整備份後的獨立安裝目錄。

按transition說明核對Demod測試連接：

```text
AFE J25 TX_TRIG -> TSW14J50 J7
TSW14J50 J8 -> TSW14J50 J13
```

如果無法取得舊版，下一個開發任務改為：以今天的BIN和同步burst為fixture，實作離線JESD/channel separator。不要繼續靠修改GUI路徑或等待彈窗。

### Gate 2：known-tone驗證

在目前60 MSPS、NCO=7.5 MHz配置下依次輸入：

```text
7.500 MHz -> 解調後接近DC
7.501 MHz -> 約+1 kHz
7.499 MHz -> 約-1 kHz
```

驗收：正負頻率方向穩定，I/Q不是複製、全零或固定碼。

### Gate 3：8通道身份

依次只激勵一個物理RX，或給8路不同的數位唯一碼。解包後必須證明：

- 8/8物理通道都存在；
- 無bit-exact duplicate；
- 通道順序固定；
- I/Q配對固定；
- 兩個活動transport column與padding的解釋已閉環。

### Gate 4：再降低有效率

只有M=4通過Gate 2與Gate 3後，才依次測M=8、M=12。每次更換都要同步更新AFE CFG、HSDC INI/firmware與separator，不能只在AFE GUI把decimation數字改大。

### Gate 5：流體仿體

- 先固定單一波束角度，不逐PRF掃角；
- PW模式用共同PRF、固定range gate；
- 流向反轉時Doppler符號必須反轉；
- 已知泵速變化時頻譜包絡跟隨；
- 單一連續記錄至少覆蓋3個周期，不能拼接有保存缺口的BIN。

## 10. 決策記錄

| 問題 | 結論 |
|---|---|
| 今天是否採到資料 | 是，transport和同步字均有證據 |
| 沒有AFE Plot是否等於無資料 | 否，問題在separator/compatibility層 |
| HSDC的4 channel是否等於4個RX | 否，是transport column |
| 目前是否已證明8路I/Q正確 | 尚未，需separator與unique-code Gate |
| 15 MSPS是否是實體ADC rate | 否，是60 MSPS經M=4後的每通道complex I/Q rate |
| software trigger能否長時間連續錄 | 不能，它只開始一次有限DDR capture |
| Auto Re-Arm能否消除保存空檔 | 不能，資料率與USB/保存空檔仍存在 |
| GUI能否完成PRF range-gated慢時間I/Q | 不能，需要FPGA RTL |
| 不改FPGA的近期最佳值 | 先修M=4解包，再驗M=8/M=12；M=12理論約3.36秒 |
| 真正10至60秒最佳方案 | TSW FPGA按PRF距離門並只存slow-time I/Q |

## 11. 來源

公開資料：

- [AFE58JD48EVM User's Guide (SLOU521)](https://www.ti.com/lit/ug/slou521/slou521.pdf)
- [TSW14J50 User's Guide (SLAU576A)](https://www.ti.com/lit/ug/slau576a/slau576a.pdf)
- [TSW14J50EVM product page](https://www.ti.com/tool/TSW14J50EVM)
- [AFE58JD48 product page](https://www.ti.com/product/AFE58JD48)

本機但不提交的TI資料：AFE58JD48 datasheet/register reference、AFE58JD48-to-TSW14J50 transition instructions、transition firmware/INI/CFG與安裝包。

相關倉庫文檔：

- [PW Doppler多心動周期採集設計](16_PW_DOPPLER_MULTI_CYCLE_DESIGN_2026-08-01.md)
- [2026-08-04—05 CW/IQ、採集與成像兩日總交接](21_HANDOFF_2026-08-05_TWO_DAY_UPDATE_CW_IQ_CAPTURE_AND_IMAGING.md)
- [本機TI軟件、CPLD工程與資料來源](08_LOCAL_SOFTWARE_AND_SOURCES.md)
