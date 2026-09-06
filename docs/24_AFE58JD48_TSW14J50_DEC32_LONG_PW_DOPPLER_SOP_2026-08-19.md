# AFE58JD48 + TSW14J50 Dec=32 raw-lane短塊與PW Doppler操作流程

日期：2026-08-19；依TI 2026-08-28附件與trigger回覆再次修訂
適用平台：AFE58JD48EVM + TSW14J50 + HSDC Pro + 外部脈衝發射控制器。
目的：在不修改TSW14J50 FPGA RTL的前提下，驗證60 MHz、PLL 40x、Demod、Decimation=32的約0.56秒有限DDR raw-lane記錄及TI分離流程；多心動週期記錄改列為必須修改firmware/RTL的下一階段。

> **2026-08-21重要更正：** 先前按`60 MHz / 32`推算8.5–8.95秒是錯誤容量模型。TI確認Decimation不是以`Fs/M`的慢時鐘直接寫DDR；HSDC仍為8條lane各保存`33,554,432`個lane-output samples，時間資訊為`33,554,432 / 60,000,000 = 0.55924 s`，TI以約0.5秒描述。40x Demod時只有1-based lane 1與lane 5承載未分離raw data，其餘lane為TI預期的零資料。

> 本流程只適用於信號源、假負載、水槽、凝膠與流體仿體。裸露高壓EVM、探頭、T/R與接收鏈未經醫療電氣、聲輸出及人體安全認證，不得把本文當作人體或臨床操作授權。

## 1. 一頁結論

TI目前對這個特定use case的確認是：

- AFE採樣率`60 MHz`、`Decimation=32`、`PLL mode=40x`；
- `33,554,432`是每一條HSDC lane output的sample數；
- 40x Demod時只有8條JESD lane中的1-based lane 1與lane 5有資料，其餘6條lane為零；
- HSDC/TSW保存的是尚未分離的ADC raw-lane資料，不是已排成`Ch1_I, Ch1_Q, ...`的直接I/Q矩陣；
- 經TI提供的方法分離後，預期每個`ChN_I`與`ChN_Q`約有`524k` samples；精確長度、邊界裁切與順序以交付的`Readme.pptx`及script實測為準；
- HSDC CSV包含lane 1至lane 8，完整檔約3 GB，單次導出耗時很長。

因此，以下做法不再成立：

- 關閉一個AFE die以令DDR時間翻倍；
- 只修改HSDC INI的`Number of channels`；
- 把現有檔名中的`20x`或`40x`當成Decimation數值；
- 只改AFE的Decimation欄位而不更換匹配的CFG、INI與TSW解包配置。
- 用`60/32`作HSDC lane寫入率並由此推算8.5–8.95秒；
- 把8條HSDC lane直接解釋為16個物理通道的I/Q；
- 把lane 2–4與6–8的零資料判成converter缺失；
- 在TI separator完成前使用固定的`I1,Q1,...,I8,Q8` word layout分析BIN。

近期正確路徑是：

```text
60-MHz AFE + PLL40x + Demod + Dec=32
  -> TI成套CFG/INI/firmware與初始化流程
  -> HSDC 8 raw lanes，每lane最多33,554,432 samples
  -> 驗證lane 1/5 active、其餘lane為預期zero/padding
  -> 完整raw BIN/CSV導出
  -> TI交付separator/frame-assembly script
  -> 16組ChN_I/ChN_Q，逐通道身份與正負tone驗收
  -> 約0.56秒內的短時PW Doppler Gate
  -> 若要多心動週期：FPGA range-gated slow-time I/Q或可靠串流
```

本模式的容量帳本改為：

| 項目 | TI確認／可核算值 | 驗收含義 |
|---|---:|---|
| HSDC raw lanes | 8 | CSV保存lane 1至8 |
| samples per lane | 33,554,432 | HSDC capture depth |
| lane sample basis | 60,000,000 samples/s | 不用`60/32`代替 |
| 有效時間窗 | 0.55924 s，TI約稱0.5 s | 不是8.5–8.95 s |
| active lanes | 1、5（1-based） | 其他lane為預期zero/padding |
| raw BIN payload | 若每lane sample為16-bit，完整8-lane約512 MiB | 必須以實檔bytes核對 |
| CSV | 約3 GB | 用串流工具，不用Excel |
| 分離後每個`ChN_I/Q` | 約524k samples | 精確shape由TI script輸出驗證 |

約0.56秒通常不足一個完整心動週期，因此本模式只作短時相干ensemble、lane packing、I/Q方向與已知流驗證，不能再作「多心動週期單塊記錄」方案。

## 2. 三個不同的時間域

操作前必須把三個概念分開：

1. **JESD device/reference clock**：建立和維持AFE至TSW的高速鏈路。
2. **PRF**：標記每一次超聲發射/接收事件；目前目標為10 kHz。
3. **HSDC capture trigger**：只啟動一次DDR記錄，不會讓HSDC每個PRF自動re-arm。

不能因為接頭名稱含`CLK`、`SYNC`或`TRIG`就互相短接。若一個FPGA事件需要送到TX、AFE與TSW，必須用經驗證的fan-out/buffer、邏輯電平、極性與阻抗。

## 3. 目標配置

### 3.1 AFE/JESD

| 項目 | 目標 |
|---|---|
| AFE/JESD基準率 | 60 MSPS |
| JESD subclass | 依TI交付Readme與成套profile，不跨Subclass混用 |
| PLL mode | 40x |
| 數字下變頻 | Enabled |
| NCO | 附件基線約486.145 kHz；先原封不動驗證，再改到實測探頭中心頻率 |
| Decimation | 32；本交付只適用此use case |
| HSDC raw lane layout | 8 lanes；1-based lane 1、5 active，其餘為zero/padding |
| 分離後目標 | 16個物理AFE通道，各自I與Q，約524k samples/component |
| 單塊有效時間 | 約0.55924 s |
| FIR/係數 | 只使用TI交付的匹配preset或配置 |
| Compression、PLL、LMFS/K | 完全依照TI的成套CFG/INI，不手改 |

AFE58JD48公開資料支持數字I/Q demodulator與1–63的分數抽取，但公開資料不足以定義私有HSDC解包表。因此不能自行猜`Channel Pattern`、`Group128`或converter lookup。

### 3.2 初始模擬接收設定

首次仿體聯調以不削頂為優先：

- LNA與PGA從較低增益開始；
- 不用全時段最大TGC增益；
- 在發射後早期保持較高衰減，再在目標深度窗口逐步增加增益；
- 13 mm前壁的往返時間約16.9 us，18 mm後壁約23.4 us，因此主要觀察17–24 us接收窗口；
- LPF選擇必須保留2-MHz短burst頻帶，且不能把噪聲帶無限制放寬；
- 在假負載和已知反射體上確認AFE輸入、ADC及輸出均不削頂後，才逐步加增益。

示波器30 V/0 V資料顯示單極性發射存在明顯過衝和長振鈴。後續優先使用對稱雙極性短burst或經驗證的主動放電/阻尼，而不是繼續提高接收增益。

### 3.3 發射與PW參數

| 項目 | 初始值 |
|---|---:|
| 中心頻率 | 2 MHz |
| Burst | 3–4 cycles |
| PRF | 10 kHz |
| 波束/探頭角 | 固定，不在PW ensemble內掃角 |
| 管腔初始深度 | 約15.5–15.9 mm中心 |
| 距離門 | 約1.0–1.5 mm，按仿體校準 |
| Wall filter | 先50 Hz，再比較100 Hz |
| 聲速 | 1540 m/s，或使用仿體實測值 |

10-kHz PRF、2-MHz載波的未校正軸向Nyquist速度約為：

```text
v_N = c * PRF / (4 * f0) = 1540 * 10000 / (4 * 2e6) = 1.925 m/s
```

所以目前約0.6–0.8 m/s的頸動脈樣流速並不受PRF上限限制。現階段優先解決的是振鈴、接收動態範圍、距離門和方向性SNR。

## 4. TI交付包核對結果

### 4.1 2026-08-28已收到的附件

本機私有歸檔已保存`Demod_resources.zip`及全部解壓文件，ZIP SHA-256為：

```text
EE07BCB2014D6558E41CAB15A822DA314163CD5626FD047AA8746EA37D680B9E
```

附件閉環了以下格式：

- CFG固定為60 MSPS、Subclass 1、PLL40x、Demod enabled、Dec=32、compression factor 3；
- NCO約486.145 kHz；`60 MHz / 32 = 1.875 MHz`只表示器件抽取名義率，不能直接當作TI分離CSV的行率。TI腳本每64條raw rows輸出一條`1I,1Q,...,16I,16Q`，因此分離後每通道complex row cadence由腳本推得為`60 MHz / 64 = 937.5 k rows/s`；
- M=32 filter有32個係數，需在AFE GUI的Filter Coefficient RAM由address 0手動載入；
- 本包不要求更換HSDC firmware INI；
- HSDC CSV至少8 columns，TI script只取1-based columns 1與5；其餘通道的32768表示signed zero；
- script把signed integer code加32768，從row 1000後尋找`[42866,32768,42866,32768]`；
- 64條serialized rows重建一條`1I,1Q,...,16I,16Q`，共32 columns；
- 理論最大完整frame數為`33,554,432 / 64 = 524,288`，實際值須扣除sync前資料與末尾不完整frame。

TI script已作靜態安全檢查但尚未對使用者capture執行。它在載入時直接讀寫檔案，且函數內使用global路徑；必須在隔離工作目錄運行副本，保留原CSV與原script不變。

仍待TI或實測閉環：精確GUI/HSDC版本、LMFS/K/lane rate readback、first-valid sample、group delay、可用baseband bandwidth，以及將NCO調到約1.6–2.0 MHz探頭實測中心時能否沿用M=32 filter。

### 4.2 凍結目前可工作的raw-RF基線

保存：

- TI 2026-08-03提供的正常模式CFG名稱、大小與SHA-256；
- 修復後No-Demod INI名稱、大小與SHA-256；
- AFE GUI、HSDC Pro版本；
- TSW board name、firmware type、firmware version；
- 一次已知可捕獲的raw-RF BIN及QA JSON雜湊。

不要用新Demod檔案覆蓋唯一可工作的No-Demod基線。

## 5. 收到TI檔案後的保存和安裝

### 5.1 保存附件

在不受Git管理的本機支援資料夾建立日期目錄：

```text
TI_Support_Materials/2026-08-28_demod_trigger_stitching/
  original/Demod_resources.zip
  extracted/Demod_resources/
  MANIFEST.sha256
  SOURCE_EMAIL_2026-08-28.md
  README.md
```

原始附件不改名、不打開後另存。計算雜湊：

```powershell
Get-FileHash -Algorithm SHA256 'C:\path\to\file.cfg'
Get-FileHash -Algorithm SHA256 'C:\path\to\file.ini'
```

私有CFG、INI、transition package、NDA文件和寄存器序列不得提交到公開GitHub；Git只保存檔名、大小、雜湊和公開安全流程。

### 5.2 安裝策略

1. 關閉AFE GUI、HSDC Pro和所有Automation程序。
2. TX高壓關閉，CW關閉，`TX_BF_MODE=0`。
3. 找到AFE GUI實際使用的Firmware INI目錄，不要假定一定在C槽。
4. 完整備份同名舊INI。
5. 優先把新profile以可辨識的新名稱安裝；若GUI硬性要求原basename，必須先保存舊檔雜湊和可恢復副本。
6. 不混用Subclass 1 CFG與Subclass 2 INI。
7. 不從既有Dec=4/Dec=16或20x/80x配置拼湊本次Dec=32、40x組合。
8. separator與`Readme.pptx`視為配置的一部分；未歸檔與核對前不把raw lane檔標成I/Q資料。

## 6. 冷啟動與建鏈

以下順序每次更換profile後完整執行：

1. 保持TX高壓/CW關閉。
2. 斷電後等待各EVM電源充分放電。
3. 檢查FMC/transition連接器、外部時鐘和USB連接。
4. 上電AFE/clock及TSW；確認電源狀態正常。
5. 以管理員權限啟動AFE58JD48 GUI。
6. 用頂部`Open Configuration`載入TI匹配CFG。
7. 依TI指示初始化LMK和AFE，保存關鍵readback。
8. 啟動HSDC Pro，選擇TI指定的TSW14J50RX device/profile。
9. 確認firmware version不是`0.0`；若為`0.0`或出現`JTAG_CHAIN_BROKEN`，停止測試並先恢復firmware下載。
10. 確認JESD link、device clock、DDR初始化/校準狀態正常。
11. HSDC中的`ADC Output Data Rate`只填TI Readme指定值；郵件的時間核算使用60 MHz lane basis，不能填`60/32`來換取虛構的長時窗。
12. 首次建鏈不使用external trigger和averaging。

成功CGS/ILA或link燈只證明鏈路建立，不證明converter-to-column解包正確。

## 7. Gate A：raw-RF基線與Dec=32 lane佔用驗收

### 7.1 No-Demod 16/16基線

通道身份的數字transport Gate仍應在已修復的No-Demod profile下執行，不能把Demod模式的6條預期zero lane套入舊的16-column QA：

1. 每個AFE converter輸出不同的穩定constant code；
2. HSDC採至少65,536 samples/column，關閉averaging和external trigger；
3. 保存原始BIN、AFE readback、profile/firmware資訊和檔案雜湊；
4. 在倉庫根目錄執行：

```powershell
python automation/jesd_transport_qa.py 'C:\path\to\unique_code_capture.bin'
```

PASS條件：無bit-exact duplicate group、16個穩定且不同的modal code、每個預期AFE converter code只出現一次、converter與HSDC slot一一對應。

### 7.2 Dec=32、40x Demod lane佔用

使用TI成套檔後先做短capture，按1-based lane編號驗證：

- lane 1與lane 5為active raw data；
- lane 2–4與lane 6–8為TI定義的zero/padding表示；
- 每條lane長度一致，沒有中途截斷、重複區塊或frame slip；
- raw檔不是`I1,Q1,...`直接矩陣，manifest明確標記`unseparated_raw_lanes`；
- 其餘6條lane為零是本模式PASS條件之一，不是converter missing證據。

No-Demod 16/16基線或Demod lane佔用任一不通過，就不能進入聲學或血流測試。關閉未用類比通道不能修復converter身份，也不會增加本模式約0.56秒的時間窗。

現有`automation/hsdc_iq_capture.py`與`HKUST_BioData_Collector/cw_iq_analysis.py`固定假設`I1,Q1,...,I8,Q8`，只保留作舊direct-I/Q原型。在TI separator、raw-lane manifest與合成fixture接入前，禁止把本次Dec=32 capture交給這兩個程式。

## 8. Gate B：DDC、I/Q與正負頻率驗收

先用TI script把raw lane資料分離成16個物理通道的I/Q。沒有separator、script hash與輸出shape報告時，本Gate直接FAIL CLOSED。

在無高壓狀態，用信號源向單一接收通道注入已知tone。若交付配置讀回的NCO為`f_NCO`，依次測：

```text
f_NCO - 50 kHz -> 一個符號的50-kHz基帶tone
f_NCO          -> 預期接近DC
f_NCO + 50 kHz -> 相反符號的50-kHz基帶tone
```

逐通道或至少逐converter group驗證：

- I/Q都不是全零、固定碼或彼此bit-exact複製；
- 頻率偏移符號穩定；
- I/Q order與共軛規則固定；
- 16個物理通道身份固定；
- 每個`ChN_I`與`ChN_Q`的長度接近TI說明的524k，精確差值可由同步/濾波裁切解釋；
- 實測輸出sample rate符合TI說明；
- filter group delay可由tone burst/impulse量測並保存。

逐個物理RX激勵，或使用能為各converter提供可辨識標記的TI測試模式，證明16/16身份和I/Q配對。不得從lane 1/5的數量直接推定通道映射。

## 9. Gate C：捕獲深度與完整導出

關閉高壓，以穩定tone或數字測試碼依次捕獲：

1. `1,048,576` samples/lane；
2. `8,388,608` samples/lane；
3. `33,554,432` samples/lane。

每個大小都記錄：

- HSDC顯示的8條raw lane及1/5 active佔用；
- 輸入的samples/lane與GUI實際取整後數值；
- capture開始/完成時間；
- BIN/CSV數量、bytes和每檔rows；
- 第一段、中間段、最後一段是否連續；
- 由samples/lane除以60 MHz得到的秒數；
- separator輸出的32個`ChN_I/Q`向量、各自長度與丟棄原因；
- active lane是否有重複/缺失段，預期zero lane是否保持規定表示。

HSDC圖窗只顯示較短Analysis Window是正常現象。不要把GUI圖窗長度當作DDR捕獲長度。

若TI流程允許，優先保存raw binary；8 lanes × 33,554,432 × 16-bit的理論payload為512 MiB，必須與實檔格式核對。完整CSV約3 GB，導出時間很長，且不能用Excel檢查33M rows；使用TI script或Python/MATLAB串流讀取。保存API可能長時間阻塞，應監看檔案增長，不要因GUI暫停更新就立即中斷。

## 10. Gate D：已知深度反射體與Decimation延遲

1. 恢復analog input，仍保持低發射電壓。
2. 使用單通道、0°、平面反射體。
3. 在至少兩個已知深度採集，例如10 mm和20 mm。
4. 驗證回波延遲隨`2z/c`移動。
5. 分別量測No-Demod與TI Dec=32分離輸出的固定延遲。
6. 將FIR/group delay寫入manifest，不可直接沿用raw-RF的zero-depth sample。
7. 驗證Dec=32仍能分開目標前後界面；若不足，先用已驗證的No-Demod/B-mode路徑定位，再切Dec=32固定門。

## 11. Gate E：流體仿體PW Doppler

### 11.1 採集前

- 探頭固定，角度和壓力不變；
- 先以B-mode/No-Demod raw RF定位管腔；
- PW ensemble內不掃角；
- 記錄中心頻率、PRF、burst、電壓、角度、深度門、聲速與溫度；
- 用已知零流、低流、中流、高流和反向流做校準。

### 11.2 Trigger

1. HSDC先arm。
2. 給TSW一個經驗證的capture-start邊緣。
3. 外部FPGA繼續產生10-kHz PRF給發射/AFE同步。
4. TSW在一次DDR capture內連續寫入約0.56秒；它不會對每個PRF重新arm。
5. 不使用HSDC `Continuous Capture`把多個有空檔的block冒充一段連續心動資料。

TI 2026-08-28建議的trigger-delay拼接，只能用於與ADC clock及EXT_TRIG相位鎖定、每次可完全重播的函數發生器或固定pattern。相鄰窗必須保留多個pulse overlap並在分離I/Q後核對sample index、幅值與相位。它不能重建非重播的脈動流或活體PW slow time。

### 11.3 離線處理

```text
8-lane raw transport導出
  -> 驗證lane 1/5 active與其餘zero/padding
  -> 用TI separator解包16個物理通道I/Q
  -> 檢查pulse index/PRF連續性
  -> 扣除Decimation固定group delay
  -> 在管腔中心設fast-time range gate
  -> 每個PRF形成1個complex slow-time I/Q
  -> 去DC/50-Hz與100-Hz wall-filter對照
  -> STFT與Kasai
  -> noise-floor、方向性和alias Gate
  -> 短時表觀軸向速度；多周期PSV/EDV留給連續後端
```

Wall filter必須在距離門之後沿slow time使用。它的目的是去除靜止或低速組織雜波，不能修復AFE削頂、converter缺失或距離門錯置。

## 12. 血流結果的驗收門檻

約0.56秒的TI Dec=32標準HSDC block可用於短時速度驗證，但不足以滿足本項目原定的「至少3個心動週期」Gate。只有同時滿足以下條件才報告短時表觀軸向速度：

- 距離門位於前後壁之間的管腔中心，而不是前壁強回波；
- flow-band SNR至少3 dB；
- 全局或穩定frame的`|directionality|`至少0.15；
- 反轉流向時頻譜符號反轉；
- 零流時血流包絡回到noise floor附近；
- lane佔用、TI separator、16通道I/Q身份與sample-time mapping全部PASS；
- 頻譜包絡而不只是總功率隨已知穩態泵速變化；
- 角度由幾何或校準量測，不能用預期速度反推後再循環驗證；
- 無alias，且多個STFT/window設定下峰值穩定。

正式PSV/EDV與心動週期變化還必須由單一連續記錄覆蓋至少3個周期；標準Dec=32 block不能滿足這一條。未通過時允許報：`apparent axial spectral envelope, diagnostic only`，PSV/EDV保留空值。

## 13. 建議manifest

每次有效capture至少保存：

```text
capture_id
timestamp/timezone
AFE GUI version
HSDC Pro version
CFG/INI/firmware names and SHA-256
TSW board and firmware version
JESD subclass/LMFS/K/lane rate and PLL40x readback
raw lane count and active lanes (1,5; 1-based)
raw lane sample basis (60 MHz) and capture duration
decimation/NCO/FIR/compression readbacks
requested and actual samples per lane
raw layout: unseparated_raw_lanes
separator name/version/SHA-256/command
separated Ch1..Ch16 I/Q order, lengths, sample interval and group delay
file names, bytes, rows and SHA-256
TX frequency/burst/voltage/PRF
probe/phantom/flow/temperature/angle
range gate, sound speed, wall filter and STFT settings
transport, I/Q, duration and flow-validation PASS/FAIL
```

## 14. 常見故障

| 現象 | 首要處理 |
|---|---|
| Firmware version `0.0`、`JTAG_CHAIN_BROKEN` | 恢復TSW供電、USB/JTAG與匹配firmware下載 |
| `DATA_READ_FAILED`、DDR timeout | 檢查AFE初始化、clock、profile/firmware匹配和capture trigger |
| No-Demod 16通道又出現固定duplicate | 停止聲學測試，回到unique-code Gate並比較CFG/INI雜湊 |
| Demod lane 2–4、6–8為零 | 若lane 1、5正常，這是TI 40x Demod預期結果；進入separator Gate |
| Demod lane 1或5為零 | 停止；核對40x CFG/INI/firmware、初始化與sync，不調聲學鏈 |
| Dec=32建鏈失敗 | 不混配或手改其他Decimation；保存readback、lane狀態與檔案雜湊交TI |
| GUI只畫出少量點 | 檢查Capture Options和導出檔案，不改Analysis Window冒充捕獲深度 |
| CSV導出很慢 | 監看檔案增長；優先詢問raw BIN接口，不用Excel打開 |
| I/Q只有零或固定碼 | 檢查sync、separator、packing和版本相容性，不調模擬增益 |
| 零速附近對稱條紋很強 | 檢查發射振鈴、削頂、range gate和wall-filter；不要直接取外包絡算PSV |
| 脈搏功率可見但速度不隨周期 | 可能是探頭/組織共同運動；要求方向性血流包絡和反向流驗證 |

## 15. 成功後的下一階段

Dec=32標準HSDC有限DDR只適合驗證約0.56秒的raw-lane、separator與短時Doppler鏈路。要得到至少3個心動週期、10秒或無空檔監測，必須在FPGA/firmware加入：

在進入自訂FPGA前，可向TI申請20 MSPS中間方案。若每條lane仍保存33,554,432 samples，理論時間為1.6777秒，可把1.5秒列為驗收目標；但現有60 MHz／PLL40x包不能直接修改，必須取得匹配的clock tree、PLL mode、CFG、INI、RBF、lane mapping與separator。完整要求見[20 MSPS／1.5秒候選方案](26_AFE58JD48_20MSPS_1P5S_PLAN_2026-08-27.md)。

```text
PRF pulse index + timestamp
  -> 固定fast-time range gate
  -> NCO/匹配積分/低通
  -> 每PRF每通道1個complex sample
  -> DDR或host低速連續輸出
```

例如10-kHz PRF、16通道complex int16只需640 kB/s，10秒只有6.4 MB；即使只用8個接收通道也只是320 kB/s。這與HSDC標準firmware的「完整連續fast-time transport寫DDR」是不同架構，不能靠GUI選項代替RTL。

若暫時只能使用標準HSDC，可採多個0.56秒block做重複性診斷，但每塊必須有獨立時間戳，塊間空檔不得拼接或用於心動週期、PSV/EDV連續曲線。

## 16. 公開參考

- [AFE58JD48產品頁與datasheet](https://www.ti.com/product/AFE58JD48)
- [TSW14J50 User's Guide](https://www.ti.com/lit/ug/slau576a/slau576a.pdf)
- [HSDC Pro User's Guide](https://www.ti.com/lit/ug/slwu087e/slwu087e.pdf)
- [TI 2026-08-03通道修復交接](20_TI_AFE58JD48_CHANNEL_COPY_FIX_2026-08-03.md)
- [2026-08-07 Demod Import交接](22_HANDOFF_2026-08-07_AFE_DEMOD_IMPORT_AND_LONG_DOPPLER.md)
- [2026-08-28三板系統更正後總方案](27_AFE58JD48_TSW14J50_TX7316_CORRECTED_ULTRASOUND_TEST_PLAN_2026-08-28.md)
