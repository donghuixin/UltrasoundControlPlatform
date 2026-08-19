# CW Doppler三傾角DBUD操作指南

本頁依據 Wang 等人在 *Science Advances* 2021 發表的 [Flexible Doppler ultrasound device for the monitoring of blood flow velocity](https://www.science.org/doi/10.1126/sciadv.abi9283) 設計。論文使用三行物理傾斜貼片消除傳統單波束Doppler對人工角度校正的依賴。現有TX7316EVM板載BF_CLK為200 MHz，寄存器直接可得的CW測試頻率是3.125 MHz；精確1、2、4 MHz需先把BF_CLK硬件改為並驗證128 MHz。這些都不是論文原始5 MHz參數。

## 1. 八通道硬體適配

現有硬體以8個有效通道適配三行幾何：

| 行 | 物理角度 | TX邏輯貼片 | RX邏輯貼片 | 預設AFE RX slot |
|---|---:|---|---:|---:|
| Row 1 | 17° | 1、3 | 2 | 1 |
| Row 2 | 20° | 4、6 | 5 | 2 |
| Row 3 | 23° | 7 | 8 | 3 |

因此使用五個TX7316發射輸出和三個AFE接收輸入。JESD的converter數、lane mapping與HSDC channel pattern是一整套傳輸協議；只啟用8個類比通道不會自動縮短既有raw-RF 16-slot記錄，必須使用匹配且驗收過的demod/compression傳輸profile才會真正節省DDR。

## 2. 幾何與DBUD算法

論文的預設物理傾角為17°、20°、23°。Ecoflex與組織聲速分別取1000 m/s與1540 m/s時，Snell定律為：

```text
sin(theta_i) / sin(beta_i) = c_substrate / c_tissue
beta_i = asin(sin(theta_i) * c_tissue / c_substrate)
```

得到組織內波束角約26.76°、31.78°、36.99°。每行量到的帶符號Doppler頻移為：

```text
fD_i = (2 f0 / c) * v * sin(beta_i - alpha)
```

頁面模型把它展開成線性最小二乘，用三行一起估計`v`與流向角`alpha`，並保留每行預測頻移及殘差RMS。分析時也應輸出三組兩行配對結果；若配對結果分散很大，通常代表貼片角、通道映射、頻譜峰或聲速設定有問題。

## 3. TX CW頻率、5–15 MSPS I/Q與50 kSPS不是同一層

- AFE高速ADC仍是120 MSPS。
- 上位機可選1、2、3.125、4 MHz供NCO與方案計算；只有3.125 MHz可在現有200 MHz BF_CLK硬件上直接啟動TX CW。
- TX7316關係式為`fCW = BF_CLK / (16 × 2^CLK_DIV)`。因此200 MHz時可得12.5、6.25、3.125、1.5625 MHz；若要精確1、2、4 MHz，應先提供並驗證128 MHz BF_CLK，再分別使用CLK_DIV=3、2、1。
- 目標數位I/Q率可選15、10、7.5、6、5 MSPS。AFE GUI 的硬體抽取欄位是 `D=4、6、8、10、12`，因為 DownConv 後的 complex I/Q 率為 `120 MSPS / (2D)`；不要把總速率除數8、12、16、20、24誤當成寄存器D值。
- TI過渡包直接提供的是`D=4 / 15 MSPS`的DownConv配置。`D=12 / 5 MSPS`在抽取範圍內，但仍須生成、載入並驗證相符AFE CFG；不能只把HSDC畫面上的rate改成5 MHz。
- AFE類比CW路徑在晶片內混頻並求和，輸出的是低頻CW I/Q；建議在外部以同時取樣ADC記錄50 kSPS、每路16或24 bit。
- 論文的15 MHz來自外部量測儀器，不等於本板只要把HSDC顯示率改成15 MHz就能重現。

以TSW14J50的512 MiB DDR估算，8通道complex I/Q等於每個取樣時刻16個int16 word。15 MSPS約480 MB/s，可存約1.12秒；5 MSPS約160 MB/s，可存約3.36秒。外部50 kSPS雙路I/Q、10秒、int16只約1.91 MiB。

## 4. 兩條硬體路徑

### A. 推薦：AFE類比CW I/Q + 外部同步ADC

1. 首次聯調使用板載200 MHz BF_CLK與3.125 MHz TX CW；若後續需要精確1/2/4 MHz，再設計128 MHz外部BF_CLK硬件改裝。接線、端接與電平必須依原理圖並用示波器驗證。
2. AFE GUI先載入官方CW 16x quick-start作為功能基線。安裝包內範例不是經本平台驗證的4 MHz時鐘配置，因此必須先在低電平下以示波器確認1x/16x時鐘、I/Q相位與輸出頻差。
3. 將三個RX貼片分別接到三個AFE接收slot；若AFE類比CW硬體只輸出內部總和，三行需分時量測或使用三套相干接收鏈，不能把一個總和訊號冒充三行獨立頻移。
4. 在CW類比輸出後加入抗混疊／wall濾波和同時取樣I/Q ADC，持續串流到PC。
5. 完成仿體、限流、溫升與聲輸出驗證後，才允許短時間低壓CW；逐步增加到所需電平。

這條路最適合10秒以上心動周期觀察，但現有單顆AFE類比CW「內部求和」架構是否能同時提供三行獨立訊號，必須先以實機輸出與原理圖確認。若只能得到一組總和I/Q，DBUD三行要分時量測；分時資料只能用於穩態流，不適合逐拍心動波形。

### B. 研究：AFE數位DDC + TSW14J50

1. 保留TI修復通道映射的raw-RF基線：AFE GUI載入`JESD 120MSPS_Subclass1_8L.CFG`，HSDC選`AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1`。
2. 先用raw RF和Ramp/獨立輸入完成16通道唯一性、lane穩定性和回波驗證。
3. 另建實驗性AFE配置：120 MSPS、NCO為所選1/2/4 MHz、所選decimation、complex I/Q。不能直接修改或覆蓋TI的No-Demod配置。
4. 配套建立TSW14J50/HSDC demod解包profile，完成I/Q順序、正負頻率、16 converter和三個目標RX slot的通道Gate。
5. 只有在15 MSPS輸出和HSDC解包都通過後，才可短塊測試。TSW DDR仍不足10秒；長時需自訂FPGA抽取／串流或改用外部低速ADC。

## 5. 上位機按鈕實際做什麼

- 三行`實測 fD (Hz)`必須填入同一時刻、同一穩態流量下取得的帶符號頻移；`計算DBUD速度`會輸出帶符號流速、流向角、三行擬合頻移和殘差RMS。正負號必須先用已知流向校準，不能只輸入頻譜幅值。
- `導出配置方案`：保存角度、RX slot、頻率、I/Q率、抽取值、NCO量化、濾波/STFT參數、容量估算與所有硬體Gate到JSON。
- `寫入寄存器／配置`：選3.125 MHz時，讀取並驗證本機TI TX7316 GUI安裝包的官方CW quick-start，再以CW OFF狀態寫入並讀回；選1/2/4 MHz時只寫有限Pattern。兩條路最後均確認`CW_EN_1=0`、`CW_EN_2=0`、`TX_BF_MODE=0`。
- 同一按鈕會保存AFE/HSDC目標配置；在相配CFG/INI未通過通道唯一性驗收前，不會誤寫AFE或改動TI修復的HSDC基線。
- `啟動限時3.125 MHz CW`：只在3.125 MHz下解鎖；要求四項安全確認、J1正／負高壓軌實測絕對值4.9至5.1 V、測試時長0.05至5秒。腳本結束或異常時都會清除CW_EN與TX_BF_MODE並讀回。
- `立即停止CW`：獨立執行三次關閉／讀回重試；若軟件停止失敗，立即切斷TX高壓供電。

## 6. 推薦測試流程

1. 不接高壓，打開三個TI GUI並完成現有raw-RF基線驗證。
2. 在CW頁面套用17°／20°／23°，填寫實際AFE RX slots，首次選擇3.125 MHz與目標I/Q率。
3. 點`導出配置方案`，確認JSON中的抽取值、FIR狀態與硬體Gate。
4. 將J1正負高壓供應均降為±5 V，依TI指南把所有5 V供電限流提高至500 mA；用萬用表實測後勾選四項安全確認。
5. 點`寫入寄存器／配置`；在TX GUI確認3.125 MHz CW配置已載入但CW仍OFF。
6. 先把測試時長設為0.1秒，點`啟動限時3.125 MHz CW`並以示波器確認B側CW輸出；5-level EVM的CW只使用B側通道。確認可自動關閉後再逐步增至1秒、3秒，單次不得超過5秒。
7. 頁面下方的`DDR I/Q capture & preview`可在AFE與HSDC已載入匹配Demod配置後擷取一個有限DDR塊；完成後自動保存BIN、manifest、I/Q幅度圖與基帶頻譜。它不會替你猜測或自動生成未驗證的AFE D=6/8/10/12寄存器配置。
8. 先用15 MSPS / D=4完成TI過渡配置、I/Q正負頻率與8通道唯一性驗證，再逐步驗證5 MSPS / D=12。確認接收後端後，用穩態流仿體依次測0、低、中、高四個已知泵速。
8. 處理順序：去DC → 150 Hz wall filter → 20 kHz低通 → STFT 1024、overlap 900 → 每行帶符號峰／包絡 → 三行DBUD解算。
9. 驗收：零流接近0；三行頻移符號與流向一致；配對速度一致；重複測量穩定。先把相對誤差≤10%作為工程Gate，不能直接宣稱達到論文結果。

## 7. 重要限制

- CW沒有深度門，所有TX/RX重疊區的散射都會進入頻譜。
- 只有一行或只有一組內部總和I/Q時，無法執行三傾角DBUD。
- 三行若不是同時採集，不能把不同心動時刻的頻移當成同一時刻聯立。
- 本系統仍是研究與仿體平台，不是人體診斷設備。
