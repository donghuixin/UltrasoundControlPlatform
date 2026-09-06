# AFE58JD48 + TSW14J50 + TX7316：更正後的超聲測試總方案

日期：2026-08-28
適用範圍：低壓電氣測試、假負載、平面反射體、水槽與流體仿體。此鏈路不是醫療設備，不接人體、不作臨床結論。

## 1. 最終決策

現有硬件最合適的路徑不是把多個HSDC capture直接拼接，也不是立即手改成20 MSPS，而是分兩層完成：

1. **用TI已交付的60 MSPS／PLL40x／Demod／Dec=32包完成短塊閉環。** 先在低壓台架證明16個物理接收通道身份、I/Q順序、NCO正負頻率、時間軸與深度軸；再接TX7316、平面反射體和流體仿體。標準HSDC單塊約`0.55924 s`，適合鏈路與穩態流驗證，不足以證明多個心動週期。
2. **長時間PW Doppler在TSW14J50自訂firmware中只保留range-gated slow-time I/Q。** 每個PRF、每通道輸出一個複數樣點並帶pulse index/timestamp，才能保留連續相位歷史，同時把資料率降到可長時間保存的量級。

`20 MSPS / 160x`只作中間候選：若TI提供完整匹配包，理論單塊為`1.6777216 s`；目前附件沒有這套配置，不能用現有60 MHz／40x檔案拼出。即使達到1.6秒，也通常不足以覆蓋三個心動週期，因此它不是最終架構。

TI提出的外部觸發延時拼接只適用於每次都能完全重播、且與ADC clock和EXT_TRIG相位鎖定的測試信號。血流的逐脈衝相位演化本身就是Doppler信號；不同心搏的窗口不能拼成原本不存在的連續slow time。

## 2. 這次更正所依據的證據

### 2.1 歷史16通道映射故障尚未正式閉環

2026-07-25三套profile均得到相同的64-k樣點結果：

```text
HSDC slots 3=5、4=6、9=15、10=16（逐樣點bit-exact）
missing AFE converters = 3、4、15、16
observed mapping = [1,2,5,6,5,6,7,8,9,10,11,12,13,14,9,10]
distinct stable codes = 12 / 16
raw BIN SHA-256 = 141E592D1631CDC19D42680BE18477E1EB12A6E84627D3F3DC3B2ACF60EBCED3
```

TI後續修復profile下的`Test00804.bin`沒有再出現這組bit-exact複製，但它不是16個不同constant code的正式驗收。因此，在修復後的No-Demod profile重做16/16 identity Gate以前，不能聲稱16通道成像或多通道PW已經可用。

Demod模式的8條HSDC raw lanes與No-Demod的16個logical columns不是同一層。Demod下lane 2–4、6–8為零是TI定義的packing；不能拿它判定converter缺失，也不能拿lane 1、5的數量推定物理通道映射。

### 2.2 TI 2026-08-28附件的實際內容

歸檔包為`Demod_resources.zip`，SHA-256：

```text
EE07BCB2014D6558E41CAB15A822DA314163CD5626FD047AA8746EA37D680B9E
```

由附件、簡報與script靜態核對得到：

| 項目 | 實際值 |
|---|---|
| ADC sample rate | 60 MSPS |
| JESD | Subclass 1、8 lanes、PLL40x |
| Demod / Decimation | enabled / 32 |
| NCO | 約486.145 kHz |
| device名義抽取率 | `60 MHz / 32 = 1.875 MHz`，不可直接當separator輸出行率 |
| TI separator輸出cadence | 每64條raw rows輸出1條16通道complex row，即`60 MHz / 64 = 937.5 k rows/s`（由腳本推得） |
| HSDC active displayed lanes | 1與5（1-based） |
| 其餘displayed lanes | code 32768，即signed zero |
| sync | raw `0x2772 = 10098`；script加32768後搜尋`[42866,32768,42866,32768]` |
| frame | 64條HSDC CSV rows組成一條16通道I/Q row |
| separated schema | `1I,1Q,...,16I,16Q`，共32 columns |
| HSDC firmware INI | 本60M/40x包不要求替換 |

最大raw lane深度與時間為：

```text
33,554,432 samples/lane / 60,000,000 samples/s = 0.559240533 s
33,554,432 raw rows / 64 rows/frame = 524,288 theoretical frames
```

實際分離行數可能因script從row 1000後找sync、frame對齊和末尾不完整frame而略少，必須由報告記錄裁切原因，不能為湊到524,288而補點。

## 3. 系統角色和不可混淆的三種時序

```text
TX7316 -> 短burst -> 探頭/仿體 -> T/R保護輸出(J5 RX) -> AFE58JD48
                                                        |
                                                        v
                                             JESD -> TSW14J50 DDR
                                                        |
                                                        v
                                             HSDC raw lanes / export
```

必須分開記錄：

- **ADC/JESD clock**：決定採樣、lane rate與DDC時間基準；
- **TX PRF marker**：定義每個pulse的slow-time index和fast-time零點；
- **TSW14J50 EXT_TRIG/J13 capture start**：只啟動一個DDR block，不是每個PRF都re-arm。

不要因接頭名含`SYNC`、`CLK`或`TRIG`便直接相連。EXT_TRIG的邏輯電平、極性、最小脈寬與阻抗在未獲TI確認或實測前保持待定，先用隔離/限流和示波器驗證。

## 4. 從上電開始的嚴格Gate

每個Gate只改一類變量；未PASS就停止，不把後級現象解釋成超聲結果。

### Gate 0：歸檔、回退與安全狀態

1. 保持TX高壓OFF、CW OFF、`TX_BF_MODE=0`，不接受試者。
2. 保存當前No-Demod可工作CFG/INI、AFE GUI/HSDC版本、TSW firmware版本和SHA-256。
3. TI原始ZIP、PPTX、CFG、filter、mapping與script保存在本機私有歸檔；只在工作副本上操作。
4. GitHub只保存去識別化雜湊、推導結果與驗證流程；未取得TI公開授權前不提交原始支持包。

PASS：原始附件雜湊與`diagnostics/ti_demod_trigger_packet_20260828.json`一致，並可回退No-Demod基線。

### Gate 1：No-Demod 16/16 transport identity

1. TX保持關閉，載入TI修復後的No-Demod成套profile。
2. 為16個AFE converter配置16個不同、穩定的digital constant code。
3. HSDC關閉averaging與external trigger，採集至少65,536 samples/column。
4. 保存BIN、配置readback、檔案hash與QA JSON。
5. 執行`python automation/jesd_transport_qa.py <capture.bin>`。

PASS必須同時滿足：16個穩定且不同的modal code、無bit-exact duplicate group、每個預期code只出現一次、映射一一對應。歷史的`3=5、4=6、9=15、10=16`任一重現便停止。

### Gate 2：原封不動驗證TI 60M/40x/M32 demod包

1. 仍保持TX高壓OFF；用限流低壓信號源只激勵一個AFE input。
2. 先以約486.145 kHz已知tone測試，暫不改NCO或filter。
3. AFE GUI載入`JESD 60MSPS_Subclass1_8L_40x_demod.CFG`。
4. 完成clock/AFE初始化；在`DEMOD -> Manual Setup -> Filter Coefficient RAM`從address 0載入M=32 coefficient工作副本。
5. 此包不替換HSDC firmware INI；記錄實際device/profile與firmware version，確保不是`0.0`。
6. 先採65,536 raw rows，保存`Integer Codes as CSV`。
7. 驗證HSDC Ch1/Ch5 active，其他顯示通道為32768。
8. 在隔離工作目錄運行TI separator副本；歸檔原始CSV、sync起始row、完整frame數、餘數與輸出shape。

PASS：輸出32 columns，對應16組I/Q；長度可由64-row frame與裁切精確解釋；無NaN、無意外固定碼、無無法解釋的frame slip。

### Gate 3：Demod後的16個物理通道身份與I/Q方向

依次只激勵一個物理RX，至少測：

```text
fNCO - 50 kHz
fNCO
fNCO + 50 kHz
```

對每次capture記錄哪一組`ChN_I/Q`響應、相位、幅值與基帶頻率。正負offset必須產生相反頻率符號；未激勵通道不得bit-exact複製被激勵通道。建立並保存「物理AFE input -> separated ChN I/Q」實測映射。

完成486.145-kHz原包閉環後，才把NCO改到探頭的**實測回波中心**。不要直接把名義2 MHz寫成唯一答案：先用假負載與平面反射體比較約1.5、1.65、2.0、2.5 MHz的實際burst、探頭響應、ring-down與SNR，再選中心頻率。NCO與M=32 filter通帶須獲TI確認或以正負tone sweep實測。

### Gate 4：TX7316電氣波形與T/R恢復

1. 先接額定假負載，不接探頭；低壓、單通道、0°開始。
2. 使用3–4 cycles的對稱雙極性burst作首選；單極性30 V/0 V曾量到約+42.5 V與-21 V過衝，不再作默認基線。
3. 用合適的差分高壓探頭量測實際頻率、峰值、過衝、ring-down和PRF；普通接地探棒不得直接夾TX高壓輸出。
4. 確認J5保護接收輸出到AFE的幅度不超限，發射後目標深度窗口不削頂。
5. 固定一個通道、固定TX/RX狀態；未完成回讀時不啟用CW或beamforming。

PASS：TX readback與實測一致；無持續CW；AFE input/ADC不削頂；T/R恢復早於目標深度窗口。

### Gate 5：已知深度與通道校準

1. 單element、0°、平面反射體，先10 mm再20 mm。
2. 在No-Demod raw RF與Demod輸出都量測`2z/c`、first-valid sample與固定group delay。
3. 逐通道量測gain、noise、polarity與delay；未校正前不做多通道合成。
4. 只在單通道深度正確後開16通道；再依次做0°、正角、負角。正負steering不應得到完全相同的多通道延時結果。

PASS：深度斜率與聲速一致，10/20-mm兩點能分開；每個通道有唯一且可解釋的響應；無歷史duplicate映射。

### Gate 6：0.559秒短塊流體仿體PW

1. 先用No-Demod/B-mode定位管腔，固定探頭、角度與sample volume；PW ensemble內不掃角。
2. 建議從約2 MHz、3–4 cycles、10 kHz PRF開始，再按Gate 3/4的實測中心頻率修正。
3. HSDC先arm，再送一個capture-start edge；PRF在同一DDR block中持續運行。
4. 保存零流、正向低/中/高流和反向流，每組至少三個獨立block，但不把block相接冒充連續時間。
5. separator後先按PRF marker切段、扣除group delay、取固定fast-time gate；每個PRF形成一個complex slow-time sample，再做wall filter、Kasai/STFT。

10-kHz PRF時0.55924秒約含5,592個pulse，足以做已知穩態流的方向性與速度比例驗證。它通常不足一個完整心動週期，因此只報短時表觀軸向速度。

短時結果需同時滿足：管腔中心gate、flow-band SNR≥3 dB、`|directionality|≥0.15`、零流回到noise floor、反向流頻譜符號反轉、沒有alias或削頂。未通過則PSV/EDV留空。

## 5. 外部觸發拼接的正確用途

只在函數發生器、digital pattern或固定反射體的**確定性重播**中使用：

1. input pattern、ADC clock關係與EXT_TRIG使用同一相位參考；
2. HSDC啟用Trigger mode，關閉Software Trigger，選`Arm on next capture button press`；
3. 每次按Capture先arm，再送一個上升沿；
4. 改變trigger delay重播下一窗；相鄰窗保留多個pulse重疊；
5. 先分離I/Q，再核對重疊區的sample index、幅值、相位和pulse count；
6. 任一重疊不一致便拒絕拼接。

這只能驗證capture alignment。固定仿體可作repeatability診斷；脈動流、活體或任何非重播slow-time資料均不得使用此方法重建5–10秒。

## 6. 長時間PW的最終TSW14J50 firmware架構

標準HSDC把完整fast-time transport寫入DDR，浪費在非目標深度與padding上。自訂firmware應在lane/frame解包通過後執行：

```text
JESD frame decode + 16-channel identity map
  -> PRF edge counter / timestamp
  -> per-channel complex stream
  -> calibrated first-valid sample + fixed range gate
  -> windowed integration / matched filter
  -> one complex sample per channel per PRF
  -> optional wall-filter copy kept separate from raw slow-time I/Q
  -> DDR ring buffer or host streaming with gap/error counters
```

以10 kHz PRF、16 channels、complex int16計算：

```text
16 channels * 4 bytes/complex * 10,000 pulses/s = 640,000 bytes/s
10 seconds = 6.4 MB
```

這比完整raw lane低數個數量級。每筆必須帶`pulse_index`或可恢復的連續counter；任何丟pulse、clock reset、FIFO overflow或timestamp逆序都要fail closed。至少先保留未做wall filter的range-gated I/Q，避免firmware濾波錯誤不可逆。

按TI separator的64-row frame，60M模式輸出cadence為937.5 k complex rows/s；10 kHz PRF時每PRI平均93.75 rows，不能假設每個PRI固定93或94點。優先用硬件PRF marker與相位累加器；若所有時鐘可由同一基準整數分頻，可評估9.375 kHz PRF，使每PRI正好100 rows，同時重新核算速度Nyquist。

## 7. 20 MSPS／160×候選的正確位置

僅當TI交付完整CFG、clock tree、PLL160x、匹配HSDC profile/firmware、lane mapping、separator與最大深度驗證後再測：

```text
33,554,432 / 20,000,000 = 1.6777216 s
```

驗收目標可設為≥1.6秒。`20M/32=625 kHz`只能作器件抽取名義值；TI未交付20 MHz／160x的frame mapping與separator，分離後complex row rate及距離sample spacing均不得先行假設。必須重新測量filter通帶、group delay和sample-volume解析度。它可延長單塊，但不取代長時間slow-time firmware。

## 8. 最短執行順序與停止條件

```text
16/16 No-Demod identity
  -> TI 486.145-kHz demod原包
  -> 16-channel I/Q identity and sign
  -> TX dummy load / T/R recovery
  -> 10/20-mm planar reflector
  -> single element 0°
  -> all channels 0°
  -> positive / negative steering
  -> zero / forward / reverse steady flow, 0.559-s blocks
  -> custom range-gated slow-time firmware
  -> only then multi-cycle pulsatile-flow metrics
```

以下任一發生立即停止：16通道duplicate/missing、lane 1或5缺失、separator sync/shape無法解釋、I/Q正負tone不反轉、firmware version為0.0、TX/CW/readback與命令不符、AFE削頂、深度斜率錯誤、反向流不反轉、pulse index不連續。

## 9. 每次有效測試必存的證據

- CFG/profile/firmware、TI separator與filter的名稱和SHA-256；
- AFE GUI、HSDC Pro版本與clock/PLL/LMFS/K/readback；
- TX頻率、cycles、電壓、PRF、角度、通道和安全狀態；
- requested/actual raw rows、8-lane bytes、capture duration與file hash；
- active lanes、sync rows、complete frame count、discarded rows與32-column output shape；
- 實測物理input到`ChN_I/Q`映射、I/Q符號、complex rate和group delay；
- PRF marker、pulse count、gap/overflow/error counters；
- reflector/phantom/flow/temperature、range gate、wall filter與結果Gate。

這套證據鏈的目的，是把「鏈路有資料」「通道身份正確」「聲學深度正確」「方向性血流成立」四件事分開驗收，避免再用一個現象替代另一個結論。
