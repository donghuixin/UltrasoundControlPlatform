# PW Doppler多心動周期採集設計（2026-08-01）

適用平台：TX7316EVM + AFE58JD48EVM + TSW14J50/HSDC Pro + `HKUST_BioData_Collector`。

範圍：水槽、凝膠、流體仿體和已知流量台架。這不是人體或醫療用途授權。

## 1. 最終結論

要看出心動周期和周期內的流速變化，最佳資料路徑不是把HSDC原始RF的Samples/channel一直拉大，而是：

```text
固定TX波束角度 + 共同5 kHz PRF
  -> 每次發射只取同一個2 mm距離門
  -> FPGA完成I/Q解調、接收通道相干合成或保留8路I/Q
  -> 每個PRF輸出1個複數慢時間樣點
  -> 單次連續保存10秒
  -> wall filter + 128-pulse STFT + 75% overlap
  -> 速度譜、峰值速度、均值速度和心動周期
```

推薦的目標配置是：

| 參數 | 推薦值 | 理由 |
|---|---:|---|
| TX中心頻率 | 1.5 MHz已知pattern；1.65 MHz待電氣/聲學驗證 | 1.6–1.7 MHz只是目前探頭候選最佳響應；上位機現有白名單是1.5 MHz |
| PRF | 5 kHz | 25 mm深度裕量大，1.5 MHz、60°時Nyquist速度約2.57 m/s |
| TX burst | 先用已驗證2 cycles；SNR不足再驗證4 cycles | 周期數增加改善窄帶SNR，但不提高速度Nyquist |
| TX steering | 先0°定位；PW記錄時固定在單一角度，通常限制±4° | 1.59 mm pitch在1.5–1.65 MHz已有嚴重柵瓣風險 |
| 流束夾角 | 從B-mode/管道幾何量測，盡量45–60°且遠離90° | 速度換算使用聲束與流向夾角，不是只用TX steering |
| 距離門 | 管腔中心，長度2 mm | 抑制管壁和鄰近組織，同時保留足夠血流能量 |
| 連續時長 | 10 s | 75 BPM時約12.5個周期，足夠檢查周期一致性 |
| STFT | 128 pulses、Hann、75% overlap | 5 kHz時窗長25.6 ms，時間解析優先；可另輸出256-pulse高頻率解析版本 |
| Wall filter | 先50 Hz | 去除靜止組織；必須按仿體慢流情況驗證，不可隨意提高 |
| RX通道 | 目前物理A1–A8，HSDC槽5–12 | 避開目前已知重複對；仍是JESD 16槽故障下的降級方案 |

10秒、5 kHz、8通道、complex int16 I/Q約為：

```text
5000 pulse/s × 10 s × 8 ch × I/Q各2 byte = 1,600,000 byte ≈ 1.53 MiB
```

若FPGA先完成8通道相干合成，只保存一個beam I/Q，10秒約0.19 MiB。

10秒是首次驗收的推薦時長，不是I/Q路徑的容量上限。通過10秒無漏pulse Gate後，可把同一配置延長到30秒（75 BPM約37.5個周期，8路complex int16約4.58 MiB）或60秒（約75個周期、9.16 MiB）；此時限制通常轉為探頭穩定、仿體流量穩定和運動偽影，而不是DDR容量。

## 2. 為什麼現有原始RF不能看到心動周期

TI的TSW14J50規格是總共256M個16-bit樣點，容量由所有converter stream分攤。現有HSDC profile為M=16、文件16列、120 MSPS，因此理論上限為：

```text
每列樣點 = 256M / 16 = 16,777,216
連續時長 = 16,777,216 / 120,000,000 = 0.13981 s
```

典型心動周期約0.6–1.2秒，所以0.14秒連一個完整周期都覆蓋不到。當前8個物理接收通道只表示重建選用HSDC槽5–12；HSDC BIN仍有16列，因此不會自動得到兩倍記錄時間。

即使真正建立M=8的AFE/JESD/HSDC profile，理論時間也只有約0.280秒。不能只把INI中的`Number of channels`改為8；必須同時改變AFE傳送格式、JESD LMFS、TSW deformatter和列映射，並重新通過唯一碼transport gate。

TI資料依據：

- [TSW14J50EVM產品頁](https://www.ti.com/tool/TSW14J50EVM)：4-Gbit DDR3，最多256M個16-bit樣點。
- [TSW14J50 User's Guide](https://www.ti.com/lit/ug/slau576a/slau576a.pdf)：總樣點容量按converter/channel分攤。
- [HSDC Pro User's Guide](https://www.ti.com/lit/ug/slwu087d/slwu087d.pdf)：TSW14J50先寫DDR，再由USB/SPI讀回PC；不是持續的高速host streaming。

## 3. 三條實現路徑的取捨

### A. 現有HSDC原始RF單塊

- 優點：現有軟件可以直接配置TX7316固定角度並採集；每個BIN內連續。
- 缺點：理論最大約0.14秒；多個BIN之間有保存缺口。
- 用途：驗證頻移方向、距離門、wall filter、64/128-pulse短時速度譜。
- 禁止聲明：不能聲稱看到心動周期，不能把多個BIN首尾拼接。

### B. AFE58JD48 Demod/Decimation

AFE58JD48官方資料支持數字I/Q demodulator和1–63的fractional decimation。這能顯著降低資料率，但輸出是經channel compression打包的I/Q，FPGA必須有匹配的JESD decompressor/channel decompressor。

本平台暫不把它列為最佳首選，原因是：

1. 現有TSW profile是原始ADC 16列解包，不是DEMOD I/Q解包。
2. 當前已有固定converter重複/缺失事故，不能再猜測private HSDC列映射。
3. 高decimation需要正確LO、FIR係數、compression、lane配置和I/Q方向驗證。
4. 即使理論容量增加，也必須先證明每個pulse index和I/Q通道都沒有重複、遺失或填零。

TI公開產品資料：[AFE58JD48產品頁](https://www.ti.com/product/AFE58JD48)。

### C. TSW FPGA距離門I/Q（推薦）

這條路直接在高速資料仍在FPGA時，按PRF pulse index做以下工作：

1. 以共同PRF標記每個fast-time frame。
2. 在`t = 2z/c`附近選取距離門。
3. 對實測中心頻率做複數下變頻和低通/匹配積分。
4. 使用已校準的RX delay/gain/polarity做8通道相干合成，或保留8路I/Q給PC。
5. 為每個pulse保存單調`pulse_index`、hardware timestamp和I/Q。
6. 連續錄製10秒，不在記錄中途讀DDR或保存BIN。

它的資料量最小、時間軸最可靠，也最容易驗證文件邊界不存在缺口。缺點是必須有新的Quartus/FPGA固件和host backend；現有HSDC GUI不能自動提供此模式。

## 4. PRF、深度和速度配置

公式：

```text
z_max = c / (2 PRF)
v_N = c PRF / (4 f0 |cos(theta)|)
v = f_D c / (2 f0 cos(theta))
```

以`c=1540 m/s`、`f0=1.5 MHz`計算：

| PRF | 無模糊深度 | 0°速度Nyquist | 60°速度Nyquist |
|---:|---:|---:|---:|
| 1 kHz | 770 mm | 0.257 m/s | 0.513 m/s |
| 2.5 kHz | 308 mm | 0.642 m/s | 1.283 m/s |
| 5 kHz | 154 mm | 1.283 m/s | 2.567 m/s |
| 10 kHz | 77 mm | 2.567 m/s | 5.133 m/s |

5 kHz是目前25 mm仿體的平衡點。20 kHz沒有必要：深度上限只剩38.5 mm，而且速度量程遠超目前需求。

## 5. TX/RX blanking與距離門

25 mm回波到達時間約為：

```text
t = 2 × 0.025 / 1540 = 32.47 us
```

TX7316應使用發射結束後的T/R switch turn-on delay屏蔽最早的直接串擾和恢復段，但延遲值必須由J7發射、J5接收毛刺和AFE恢復示波器結果決定。軟件在距離門前丟棄樣點不能修復已經發生的AFE飽和。

驗收要求：硬件blanking結束後，J5和AFE已回到不削頂狀態；同時最淺目標回波仍保留。不要用固定的「幾微秒」替代示波器量測。

## 6. 上位機集成狀態

`HKUST_BioData_Collector`的PW頁現在提供：

- 三種路徑明確分層：現有raw RF、推薦FPGA I/Q、研究AFE Demod I/Q。
- PRF、固定TX steering、流束角、深度門、門長、期望速度、HR、wall filter、STFT ensemble配置。
- TSW總容量分攤、單塊秒數、pulse數和可覆蓋心動周期數。
- 現有模式一鍵寫入/讀回固定角度Delay Profile後採集。
- 採集完成後自動執行：事件檢測、距離門複數解調、通道相干合成、wall filter、STFT、速度CSV和周期檢測。
- 分析輸出：`analysis/pw_doppler/pw_doppler_spectrogram.png`、`pw_doppler_velocity.csv`、`pw_doppler_summary.json`和慢時間I/Q NPZ。
- 只有單一連續記錄不少於3秒、覆蓋至少3個周期且速度包絡自相關通過時，摘要才標記`cardiac_cycle_visible=true`。

推薦後端和上位機之間的最小接口是：在capture目錄寫入`pw_doppler_input_iq.npz`，其中`iq`為`(continuous_pulses, active_iq_channels)`的complex64陣列，`prf_hz`與Session Plan一致；固件還必須用單調pulse index或timestamp證明沒有漏脈衝、重複脈衝和文件內缺口。上位機已能直接分析這種連續I/Q輸入。

速度譜成功生成不等於量值已校準。正式比較流速前，仍須用示波器/已知深度反射體校準range zero，並用已知泵速和流向校準速度比例及正負號。

推薦FPGA/AFE模式在相應後端通過之前會被硬件Gate阻止；這是設計行為，不是UI故障。

## 7. 最短驗收路徑

1. **數字transport Gate**：唯一碼無重複、無缺失；目前16槽尚未通過，5–12只能作8路降級模式。
2. **TX電氣Gate**：假負載驗證1.5 MHz pattern的邊沿、周期、回零和T/R恢復。
3. **單通道已知深度Gate**：反射體移動時，距離門回波延時按`2z/c`移動。
4. **短塊Doppler Gate**：已知流向反轉後，頻移符號反轉；已知泵速與估算速度一致。
5. **共同PRF Gate**：5 kHz pulse index無缺失/重複，TX、AFE/FPGA與capture start來自同一時基。
6. **連續I/Q Gate**：10秒文件的pulse index和timestamp單調，沒有保存間隙。
7. **周期Gate**：已知周期泵的速度譜週期與設定一致，至少連續3個周期；再擴展到更長記錄。

在以上Gate完成前，不把任何凝膠紋理、直接串擾或多BIN拼接曲線解釋為血流心動周期。
