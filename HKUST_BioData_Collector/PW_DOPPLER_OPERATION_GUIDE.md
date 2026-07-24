# TX7316 + AFE58JD48 + TSW14J50 PW Doppler完整操作文檔

版本：2026-07-23
適用對象：目前的8個有效TX/RX通道、1.59 mm中心間距、1 mm x 1 mm x 0.4 mm壓電陣元、TX7316 5-level EVM、AFE58JD48 EVM、TSW14J50和HSDC Pro。
目前範圍：凝膠、流體仿體和台架驗證，不用於人體。

## 1. 先說結論

1. PRF可以提高，但TX7316 GUI不能直接把板載1 kHz改成5 kHz或20 kHz。原裝TX7316EVM的CPLD在硬件復位後固定產生1 kHz `TR_BF_SYNC`和`TR_EN`。
2. `J7 pin 2`是CPLD產生的`TR_BF_SYNC`觀測輸出，不是外部PRF輸入口。不得把函數發生器直接接到該引腳，否則會與板載驅動器衝突。
3. 1 MHz PW Doppler建議先從`PRF = 5 kHz`開始，不建議一開始使用20 kHz。5 kHz對25-40 mm深的仿體有充足量程，也可覆蓋約1 m/s的流速。
4. AFE ADC不應為了PRF而簡單降低採樣率。保持120 MSPS，用它解析每次脈衝的深度；之後在AFE數字解調器或FPGA內下變頻、距離門和慢時間抽取。
5. 現有HSDC腳本能保存「單個連續原始RF短塊」，但多次Capture之間有30-60秒級保存/控制缺口，不能把多個BIN直接拼成連續心動波形。
6. 真正記錄5-10秒心動週期的合理數據是：每次發射只保留所選深度門的一個複數I/Q樣點。這樣16通道、5 kHz、6秒通常只有約1.83 MiB，而6秒全帶寬原始RF約21.46 GiB。

## 2. 必須區分的三種速率

| 名稱 | 本系統建議值 | 作用 |
|---|---:|---|
| ADC fast-time採樣率 | 120 MSPS | 決定單次脈衝內的深度取樣 |
| PRF | 先5 kHz | 決定每秒發射與慢時間取樣次數 |
| 距離門後慢時間率 | 等於PRF，即5 kS/s | 用於Doppler FFT和速度隨時間曲線 |

不要在HSDC Pro中把`ADC Output Data Rate`文字框從120M改成5k。該欄位必須與AFE/JESD實際輸出率相符；它不是PRF控制。

## 3. PRF、深度和速度的計算

無模糊深度：

```text
z_max = c / (2 * PRF)
```

Doppler頻移：

```text
f_D = 2 * f0 * v * cos(theta) / c
```

Nyquist速度：

```text
v_N = c * PRF / (4 * f0 * |cos(theta)|)
```

其中`c = 1540 m/s`，`theta`是聲束與流向夾角，不是只由TX偏轉角決定。若流向未知，速度只能報告為角度相關的投影速度。

### 1 MHz、60度夾角時的比較

| PRF | 無模糊深度 | Nyquist速度 | 建議 |
|---:|---:|---:|---|
| 1 kHz | 770 mm | 0.77 m/s | 可做慢流和初步測試，約1 m/s可能混疊 |
| 2.5 kHz | 308 mm | 1.93 m/s | 大部分仿體可用 |
| 5 kHz | 154 mm | 3.85 m/s | 本系統的推薦起點 |
| 10 kHz | 77 mm | 7.70 m/s | 深度小於約60 mm時可用 |
| 20 kHz | 38.5 mm | 15.4 m/s | 深度裕量很小，速度量程過大，不作首選 |

如果聲束與流向接近0度，5 kHz、1 MHz的Nyquist速度約1.925 m/s，仍可覆蓋常見仿體流速。

## 4. 推薦的第一套PW Doppler參數

| 參數 | 初始值 |
|---|---:|
| 發射中心頻率 | 1 MHz |
| PRF | 5 kHz，外部同步後才有效 |
| 發射週期 | 4 cycles |
| TX偏轉角 | 先0度，定位後再固定到血管方向 |
| 流向校正角 | 由B-mode估計，初始可填60度但不得當作實測值 |
| 距離門中心 | 仿體管腔中心，例如25 mm |
| 距離門長度 | 1.5-3 mm |
| ADC率 | 120 MSPS |
| AFE模式 | 先Analog Input原始RF，後續再開Demod/Decimation |
| HSDC短塊 | 4,194,304 samples/channel |
| 單塊時間 | 34.95 ms |
| 5 kHz時單塊脈衝數 | 約174.8 |
| 建議STFT窗口 | 128或256 pulses，Hann窗，75%重疊 |
| 心動週期目標時長 | 6-10秒，必須使用連續I/Q慢時間路徑 |

4個1 MHz週期的發射時間約4 us，在5 kHz下占空比約2%。先保持已驗證的高壓，不用增加電壓補償低頻靈敏度。

## 5. TX7316發射波形

假設`BF_CLK = 200 MHz`：

1. 在`Device Configuration`取消勾選`TX_BF_MODE`。
2. `CLK_DIV = 2`。
3. `PAT_INV = Normal`。
4. `CW_EN_1 = OFF`、`CW_EN_2 = OFF`。
5. 在`Profile Configuration > Pattern Profile`選`PROFILE NUMBER = 0`。
6. 4個完整週期用8個transition：

| Transition | Level | Period |
|---:|---|---:|
| 1 | PHV_A或已驗證的正電平 | 23 |
| 2 | MHV_A或配對負電平 | 23 |
| 3 | 正 | 23 |
| 4 | 負 | 23 |
| 5 | 正 | 23 |
| 6 | 負 | 23 |
| 7 | 正 | 23 |
| 8 | 負 | 23 |

7. `REPEAT_COUNT = 0`，`TAIL_COUNT = 3`。
8. 按`Write to Device`。
9. 在Register 0令`LOAD_PROF = 1`，等待它自動清零並回到`Idle`。
10. 保持現有已驗證的`TX_START_DEL`、T/R switch delay和Delay Profile。
11. HSDC已經Arm/Capture後才允許`TX_BF_MODE`工作；自動腳本會在捕獲前後切換它。

頻率只由pattern時序決定；PRF由`TR_BF_SYNC/TR_EN`事件間隔決定，兩者不是同一個參數。

## 6. PRF來源和同步接線

### 6.1 保持原板不改：只能使用1 kHz

- TX7316EVM硬件復位後，板載CPLD輸出1 kHz `TR_BF_SYNC`和`TR_EN`。
- `J7 pin 2`只用高阻探頭觀察同步，不連AFE或函數發生器。
- AFE J25可暫時留空；HSDC使用Normal Capture時，採集起點相對發射是隨機的。
- 可用於檢查是否存在可重複的脈衝和低速頻移，不適合準確的深度門長時間PW Doppler。

### 6.2 需要5-20 kHz：必須改變CPLD/同步硬件

有兩條可行路線：

1. 取得TX7316EVM的CPLD工程，在J11 JTAG重新編程，使CPLD產生所需`TR_BF_SYNC`和`TR_EN`。必須保留原始bitstream，並先在低壓/假負載驗證。
2. 在自製接口板或經確認的EVM改裝中，隔離板載CPLD/SYNC buffer輸出，再由FPGA的LVDS/適當邏輯驅動TX7316同步輸入。TX7316同步是差分路徑；不能拿單端3.3 V直接碰J7 pin 2。

正式同步源應產生：

```text
Master PRF clock
  ├─ TX branch: TR_BF_SYNC differential + matching TR_EN timing
  ├─ AFE branch: J25 TX_TRG, 3.3 V pulse after verified level conversion
  └─ TSW branch: J13 capture trigger; HSDC先Arm，只使用第一個合格邊沿開始DDR捕獲
```

要求：

- 三個分支共地或經數字隔離後有明確參考。
- 使用有源扇出/緩衝，不用被動T形線把不同板卡輸入並接。
- 每個分支的電平、極性和脈寬先查板卡手冊並用示波器/邏輯分析儀驗證。
- TSW J13只負責Capture Start，不應被理解成每一個RF脈衝的ADC時鐘。
- 若未隔離板載CPLD，不得注入外部同步。

## 7. AFE58JD48：當前短塊原始RF配置

上電並打開HSDC Pro後，在AFE GUI按以下順序：

1. `DUT RESET`
2. `INITIALIZE LMK`
3. `AFE RESET`
4. `INITIALIZE AFE`
5. `ADC FORMAT = Analog Input`
6. `JESD = 120M 8L Subclass 1`，保持與目前可工作profile一致
7. `LNA/PGA = Min Gain`起步
8. `LPF = 15 MHz`或`20 MHz`
9. `Active Termination = Disable`
10. `Digital HPF = Disable`起步，避免把低頻Doppler成分誤濾掉
11. 檢查16個數字通道無重複、無ADC削頂，再提高增益

外部同步模式下，把經驗證的3.3 V PRF/同步脈衝接到`AFE J25 TX_TRG`。AFE手冊的外部觸發示例也把同一外部源送至AFE與TSW。

## 8. HSDC Pro：短塊捕獲

### 8.1 Normal模式，先驗證波形

1. 選擇`AFE58JD48_120M_8L_M16_FIXED`；不要使用會造成重複通道的舊`MANUAL/M=5`文件。
2. `ADC Output Data Rate = 120M`。
3. `ADC Input Target Frequency = 1.0M`，它只影響分析標記。
4. `Average Time Domain = OFF`。
5. `Average FFT = OFF`。
6. `Continuous Capture = OFF`。
7. `Write Captured Data to File/Streaming = OFF`；現有腳本在DDR捕獲完成後調用Save Binary。
8. `# samples/channel = 4194304`作為5 kHz短塊起點。
9. Trigger設`Normal`，點Capture或由腳本調`Pass_Capture_Event`。

### 8.2 Hardware trigger模式

1. 在`Data Capture Options > Trigger Option`打開Trigger mode。
2. 選擇外部/Arm on next類型。
3. HSDC先Arm。
4. 外部主同步源送一個符合TSW輸入規格的Start邊沿到J13。
5. TSW開始把隨後的連續ADC資料寫入DDR；PRF脈衝仍由主同步源持續產生。
6. 如果一直等待，先停止高壓發射，再檢查J13邏輯電平、邊沿、極性和HSDC trigger選項。

### 常用短塊數據量

以120 MSPS、16通道、uint16計算：

| Samples/channel | 連續時間 | 5 kHz脈衝數 | 單BIN大小 |
|---:|---:|---:|---:|
| 1,048,576 | 8.74 ms | 43.7 | 32 MiB |
| 4,194,304 | 34.95 ms | 174.8 | 128 MiB |
| 8,388,608 | 69.91 ms | 349.5 | 256 MiB |

實際可接受的最大sample數取決於TSW固件、DDR和HSDC DLL；每次只提高一級並確認保存成功。

## 9. 為什麼多個Capture不能代表幾個心動週期

現有自動腳本每個文件的流程是：

```text
選profile → 開TX → HSDC捕獲DDR → 關TX → Save Binary → 下一個Capture
```

`Save Binary`本身可能花30-60秒。因此即使保存100個34.95 ms文件，也只是100段短片，中間存在未知長缺口。不能：

- 把文件直接首尾相接後畫心動速度波形；
- 用文件序號當作均勻時間軸；
- 從這些文件推算心率或收縮/舒張時間。

這些短塊可用於：

- 證明頻移方向和大小；
- 驗證流速公式；
- 比較不同距離門、角度和增益；
- 確認128/256-pulse ensemble是否能形成穩定頻譜。

## 10. 真正5-10秒連續PW Doppler的兩條路

### 10.1 推薦：FPGA距離門和慢時間流

每一個PRF週期：

1. 用共同Trigger定義`t = 0`。
2. 在`t_gate = 2z/c`附近保留1.5-3 mm距離門。
3. 對1 MHz RF乘`exp(-j2*pi*f0*t)`做I/Q解調。
4. 對距離門內樣點匹配濾波/積分。
5. 按RX通道延時校正並相干求和。
6. 每個PRF只輸出一個或少數複數I/Q樣點。
7. 以5 kS/s連續傳輸6-10秒到PC。

這是最乾淨的長時間方案，也最接近臨床PW Doppler資料結構。

### 10.2 AFE數字Demod + Decimation

AFE58JD48具有數字I/Q demodulator和可編程decimation：

- ADC時鐘仍保持120 MHz；
- 在AFE內數字下變頻到基帶；
- 再用decimation降低JESD輸出數據率；
- HSDC必須選擇相符的Demod/JESD解包profile。

TI EVM手冊驗證的簡單入口是：

1. `JESD: 120M 4L Subclass1 Dec=4`
2. `ADC FORMAT = Analog Input`
3. `VCA = Min Gain`
4. `LPF = 20 MHz`
5. `DEMOD > Manual Setup`
6. `Preload Coefficient Memory`先ON再OFF
7. `Generate Trigger (MANUAL_TX_SYNC)`

但`Dec=4`仍不足以把數據量降到幾秒心動記錄。更高抽取需要正確的LO、FIR係數、compression mapping、JESD lane profile和PC端解包驗證。當前UI只預留該路徑，不會自動寫AFE demod寄存器，也不會默認打開HSDC capture-to-file streaming。

## 11. 離線Doppler處理順序

對具有共同Trigger且時間連續的資料：

1. 以每個PRF週期分幀。
2. 用`t = 2z/c`選距離門。
3. 1 MHz帶通，例如0.6-1.4 MHz。
4. I/Q解調和低通。
5. 通道相位校正與相干合成。
6. 慢時間去均值或50-100 Hz wall filter，避免固定壁反射壓過血流。
7. 128或256 pulses的Hann窗STFT，75%重疊。
8. 將頻率轉為速度：`v = f_D*c/(2*f0*cos(theta))`。
9. 同時保存原始I/Q、wall-filter後I/Q、頻譜、峰值速度、均值速度和配置JSON。

在1 MHz、5 kHz、60度、256 pulses下：

- 每個STFT窗約51.2 ms；
- 頻率bin約19.53 Hz；
- 理想速度bin約0.030 m/s。

## 12. 分階段驗收

### Phase A：1 kHz、靜態反射物

- 使用板載CPLD，不改PRF。
- 驗證每個RF塊中脈衝間距約1 ms。
- 靜態反射物經wall filter後應大幅下降。

### Phase B：5 kHz、已知泵速仿體

- 完成外部同步硬件並先在低壓驗證。
- 4,194,304 samples/channel應看到約175個等間隔發射事件。
- 同一距離門內頻移方向隨流向反轉。
- 計算速度與泵設定/流量計在可接受誤差內。

### Phase C：連續6-10秒

- 只有AFE高抽取或FPGA距離門路徑通過後才進行。
- 文件內必須有單調硬件時間戳或固定PRF索引。
- 人為改變泵速時，頻譜包絡必須隨時間連續變化，不得在文件邊界跳時。

## 13. HKUST Bio-data collector新選項卡

左側點`PW多普勒 Doppler`或按`Alt+3`：

1. 選PRF source。
2. 輸入PRF、TX steer、flow angle、gate depth、預期速度和期望時長。
3. 查看無模糊深度、Nyquist速度、預期頻移和存儲估算。
4. 點`載入 1 MHz / 5 kHz 建議值`快速填入初始方案。
5. 點`導出Session Plan`保存JSON；其中明確記錄`prf_programmed_by_ui = false`。
6. 點`Doppler dry run`只計算延時和命令，不動硬件。
7. 完成三項Pre-flight後，點`開始固定角度短塊採集`。
8. 採集目錄會額外生成`doppler_session_plan.json`。

## 14. 官方資料依據

- `TX7316EVM_User_Guide_sbou224_.pdf`：第8、11、40、44、51、57頁。板載CPLD產生1 kHz同步；J7 pin 2用於探測同步；TP18/TP20為CPLD同步/TR_EN測試點。
- `AFE58JD48EVM_User_Guide__SLOU521_.pdf`：第15-20、53、56-57、64頁。Demod/Decimation示例、J25 TX_TRG和外部3.3 V trigger拓撲。
- `sbas881a.pdf`：數字I/Q demodulator、decimation factor、JESD compression和TX_TRIG要求。

## 15. 最終安全邊界

- 未驗證外部同步時，只用原板1 kHz。
- 不把J7 pin 2當輸入。
- 不在高壓上電時改線、拆0歐電阻或更換同步源。
- PRF、週期數、電壓每次只改一項，並監測TX7316溫度/熱保護LED和AFE削頂。
- 目前EVM/開放線束只作凝膠或仿體測試，不作人體測量。
