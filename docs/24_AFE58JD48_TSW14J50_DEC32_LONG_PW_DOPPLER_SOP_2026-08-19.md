# AFE58JD48 + TSW14J50 Dec=32 長時PW Doppler完整操作流程

日期：2026-08-19
適用平台：AFE58JD48EVM + TSW14J50 + HSDC Pro + 外部脈衝發射控制器。
目的：在不修改TSW14J50 FPGA RTL的前提下，先完成一個約8.5–8.95秒的有限DDR I/Q記錄，用於多心動週期PW Doppler鏈路驗證。

> 本流程只適用於信號源、假負載、水槽、凝膠與流體仿體。裸露高壓EVM、探頭、T/R與接收鏈未經醫療電氣、聲輸出及人體安全認證，不得把本文當作人體或臨床操作授權。

## 1. 一頁結論

TI已明確回覆：TSW14J50不能只把8個AFE通道送入DDR，DDR會接收完整16通道資料；FPGA最多可捕獲`33,554,432`個HSDC樣點，完整資料即使不全部顯示在GUI圖窗中，仍可由GUI導出。

因此，以下做法不再成立：

- 關閉一個AFE die以令DDR時間翻倍；
- 只修改HSDC INI的`Number of channels`；
- 把現有檔名中的`20x`或`40x`當成Decimation數值；
- 只改AFE的Decimation欄位而不更換匹配的CFG、INI與TSW解包配置。

近期正確路徑是：

```text
60-MSPS AFE基準
  -> 2-MHz數字下變頻
  -> TI驗證的Dec=32濾波/抽取與channel compression
  -> 匹配的TSW14J50/HSDC INI與firmware
  -> 33,554,432 samples/channel單次DDR捕獲
  -> 完整BIN/CSV導出
  -> PRF分段、FIR延遲校正、管腔距離門
  -> slow-time wall filter、STFT/Kasai、有效性Gate
```

在目前已觀察到的Dec=4 transport資料率上按抽取倍率外推：

| AFE抽取 | 估計總資料率 | 512 MiB理論時間 | 用途 |
|---:|---:|---:|---|
| Dec=4 | 約480 MB/s | 約1.12 s | I/Q解包基線 |
| Dec=16 | 約120 MB/s | 約4.47 s | 深度定位與備用長記錄 |
| Dec=32 | 約60 MB/s | 約8.95 s | 推薦多周期單塊記錄 |

`8.5 s`是合理保守值，`8.95 s`是忽略header、對齊和保留空間的理論值。最終時間必須用TI交付配置的實際transport column數、每列輸出率與導出行數驗證。

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
| JESD subclass | Subclass 1 |
| 數字下變頻 | Enabled |
| NCO | 目前2 MHz；4 MHz另建TI驗證配置 |
| Decimation | 先Dec=16，通過後Dec=32 |
| 實體AFE通道 | 16通道transport完整保留 |
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

## 4. 收到TI配置檔前

### 4.1 回覆TI並確認八項資訊

要求TI在交付CFG/INI時同時確認：

1. `33,554,432`是否為HSDC Pro的`# samples per channel`；
2. Dec=32 INI在HSDC中顯示多少logical channels；
3. 16個物理AFE通道如何映射/壓縮到logical columns；
4. HSDC `ADC Output Data Rate`應填多少；
5. 60 MSPS、Dec=32的預期記錄秒數；
6. I/Q順序、通道順序、offset-binary/two's-complement格式；
7. 完整捕獲能否直接保存raw binary，而不是只導出CSV；
8. 匹配的GUI版本、PLL mode、LMFS/K、lane rate、初始化順序與2-MHz NCO配置。

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
TI_Support_Materials/YYYY-MM-DD_afe58jd48_dec32/
  attachments/
  installed_backup_before_replace/
  validation/
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
7. 不混用Dec=16 CFG與Dec=32 INI。

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
11. HSDC中的`ADC Output Data Rate`只填TI指定值，不用`60/32`自行推測。
12. 首次建鏈不使用external trigger和averaging。

成功CGS/ILA或link燈只證明鏈路建立，不證明converter-to-column解包正確。

## 7. Gate A：16通道數字transport驗收

### 7.1 測試

1. 每個AFE converter輸出不同的穩定constant code。
2. HSDC採至少65,536 samples/column。
3. 關閉averaging和external trigger。
4. 保存原始BIN、AFE readback、profile/firmware資訊和檔案雜湊。
5. 在倉庫根目錄執行：

```powershell
python automation/jesd_transport_qa.py 'C:\path\to\unique_code_capture.bin'
```

### 7.2 PASS條件

- 無bit-exact duplicate group；
- 16個穩定且不同的modal code；
- 每個預期AFE converter code只出現一次；
- AFE converter與HSDC slot一一對應。

只要這個Gate不通過，就不能進入超聲、血流或人體相關測試。關閉未用類比通道不能修復丟失的converter，也不會減少固定transport的DDR佔用。

## 8. Gate B：DDC、I/Q與正負頻率驗收

在無高壓狀態，用信號源向單一接收通道注入已知tone。NCO為2 MHz時依次測：

```text
1.950 MHz -> 預期約-50 kHz
2.000 MHz -> 預期接近DC
2.050 MHz -> 預期約+50 kHz
```

逐通道或至少逐converter group驗證：

- I/Q都不是全零、固定碼或彼此bit-exact複製；
- 頻率偏移符號穩定；
- I/Q order與共軛規則固定；
- 16個物理通道身份固定；
- 實測輸出sample rate符合TI說明；
- Dec=16與Dec=32切換後不會改變通道身份；
- filter group delay可由tone burst/impulse量測並保存。

先完成Dec=16，再測Dec=32。若M=16通過而M=32失敗，保持硬件不變，將CFG、INI、firmware和QA報告作一變量A/B比較。

## 9. Gate C：捕獲深度與完整導出

關閉高壓，以穩定tone或數字測試碼依次捕獲：

1. `1,048,576` samples/channel；
2. `8,388,608` samples/channel；
3. `33,554,432` samples/channel。

每個大小都記錄：

- HSDC顯示的logical channel數；
- 輸入的samples/channel與GUI實際取整後數值；
- capture開始/完成時間；
- BIN/CSV數量、bytes和每檔rows；
- 第一段、中間段、最後一段是否連續；
- 由行數和實測sample rate得到的秒數；
- 是否有全零、重複或缺失段。

HSDC圖窗只顯示較短Analysis Window是正常現象。不要把GUI圖窗長度當作DDR捕獲長度。

優先保存raw binary。完整CSV可能達數GB，導出時間很長，且不能用Excel檢查33M rows；使用Python或MATLAB串流讀取。保存API在大檔案時可阻塞數十秒，應監看檔案大小和超時，不要因GUI暫停更新就立即中斷。

## 10. Gate D：已知深度反射體與Decimation延遲

1. 恢復analog input，仍保持低發射電壓。
2. 使用單通道、0°、平面反射體。
3. 在至少兩個已知深度採集，例如10 mm和20 mm。
4. 驗證回波延遲隨`2z/c`移動。
5. 分別量測No-Demod、Dec=16、Dec=32的固定延遲。
6. 將FIR/group delay寫入manifest，不可直接沿用raw-RF的zero-depth sample。
7. 驗證Dec=32仍能分開目標前後界面；若深度解析不足，用Dec=16定位，再切Dec=32固定門。

## 11. Gate E：流體仿體PW Doppler

### 11.1 採集前

- 探頭固定，角度和壓力不變；
- 先以B-mode/raw RF或Dec=16定位管腔；
- PW ensemble內不掃角；
- 記錄中心頻率、PRF、burst、電壓、角度、深度門、聲速與溫度；
- 用已知零流、低流、中流、高流和反向流做校準。

### 11.2 Trigger

1. HSDC先arm。
2. 給TSW一個經驗證的capture-start邊緣。
3. 外部FPGA繼續產生10-kHz PRF給發射/AFE同步。
4. TSW在一次DDR capture內連續寫入；它不會也不需要對每個PRF重新arm。
5. 不使用HSDC `Continuous Capture`把多個有空檔的block冒充一段連續心動資料。

### 11.3 離線處理

```text
完整transport導出
  -> 解包16個物理通道I/Q
  -> 檢查pulse index/PRF連續性
  -> 扣除Decimation固定group delay
  -> 在管腔中心設fast-time range gate
  -> 每個PRF形成1個complex slow-time I/Q
  -> 去DC/50-Hz與100-Hz wall-filter對照
  -> STFT與Kasai
  -> noise-floor、方向性、alias和周期性Gate
  -> 角度校正後PSV/EDV
```

Wall filter必須在距離門之後沿slow time使用。它的目的是去除靜止或低速組織雜波，不能修復AFE削頂、converter缺失或距離門錯置。

## 12. 血流結果的驗收門檻

只有同時滿足以下條件才報告PSV/EDV：

- 距離門位於前後壁之間的管腔中心，而不是前壁強回波；
- flow-band SNR至少3 dB；
- 全局或穩定frame的`|directionality|`至少0.15；
- 反轉流向時頻譜符號反轉；
- 零流時血流包絡回到noise floor附近；
- 頻譜包絡而不只是功率隨已知泵周期/心動周期變化；
- 至少連續3個周期；
- 角度由幾何或校準量測，不能用預期速度反推後再循環驗證；
- 無alias，且多個STFT/window設定下峰值穩定。

未通過時允許報：`apparent axial spectral envelope, diagnostic only`，但PSV/EDV必須保留空值。

## 13. 建議manifest

每次有效capture至少保存：

```text
capture_id
timestamp/timezone
AFE GUI version
HSDC Pro version
CFG/INI/firmware names and SHA-256
TSW board and firmware version
JESD subclass/LMFS/K/lane rate
logical columns and physical-channel map
ADC/transport/output sample rates
decimation/NCO/IQ order/group delay
requested and actual samples per channel
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
| 16通道又出現固定duplicate | 停止聲學測試，回到unique-code Gate並比較CFG/INI雜湊 |
| Dec=32建鏈失敗 | 不改其他項，回退Dec=16；把完整readback和lane狀態交TI |
| GUI只畫出少量點 | 檢查Capture Options和導出檔案，不改Analysis Window冒充捕獲深度 |
| CSV導出很慢 | 監看檔案增長；優先詢問raw BIN接口，不用Excel打開 |
| I/Q只有零或固定碼 | 檢查sync、separator、packing和版本相容性，不調模擬增益 |
| 零速附近對稱條紋很強 | 檢查發射振鈴、削頂、range gate和wall-filter；不要直接取外包絡算PSV |
| 脈搏功率可見但速度不隨周期 | 可能是探頭/組織共同運動；要求方向性血流包絡和反向流驗證 |

## 15. 成功後的下一階段

Dec=32有限DDR適合先證明8.5秒多周期鏈路。若需要30秒、分鐘級或無空檔監測，最終仍應在FPGA加入：

```text
PRF pulse index + timestamp
  -> 固定fast-time range gate
  -> NCO/匹配積分/低通
  -> 每PRF每通道1個complex sample
  -> DDR或host低速連續輸出
```

例如10-kHz PRF、8通道complex int16只需320 kB/s；512 MiB可記錄約28分鐘。這與HSDC標準firmware的「完整連續fast-time transport寫DDR」是不同架構，不能靠GUI選項代替RTL。

## 16. 公開參考

- [AFE58JD48產品頁與datasheet](https://www.ti.com/product/AFE58JD48)
- [TSW14J50 User's Guide](https://www.ti.com/lit/ug/slau576a/slau576a.pdf)
- [HSDC Pro User's Guide](https://www.ti.com/lit/ug/slwu087e/slwu087e.pdf)
- [TI 2026-08-03通道修復交接](20_TI_AFE58JD48_CHANNEL_COPY_FIX_2026-08-03.md)
- [2026-08-07 Demod Import交接](22_HANDOFF_2026-08-07_AFE_DEMOD_IMPORT_AND_LONG_DOPPLER.md)
