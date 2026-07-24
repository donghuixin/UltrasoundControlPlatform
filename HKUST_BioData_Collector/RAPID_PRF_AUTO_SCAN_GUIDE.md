# TX7316逐PRF自動掃描：接線、時序與UI操作

## 2026-07-24 已實現的推薦模式

目前先使用原廠TX7316EVM板載CPLD，不假設它能逐PRF切換Delay Profile：

- 角度：`-10°…+10°`，步進`2°`，共11角，裝入單一Profile bank。
- PRF：板載CPLD固定約`1 kHz`；SYNCP在`TX_BF_MODE=0`時仍會自由運行，這是正常行為。
- 每角一個BIN；每個BIN從下一個SYNCP上升沿開始，連續記錄32個同角度PRF。
- 120 MSPS時每通道使用`3,837,952` samples（從第33個PRF邊界向下取整至4096倍數），約`31.9829 ms`；包含`t=0...31 ms`的32次發射，但在`t=32 ms`第33次發射前停止。
- 16個uint16數字槽時每BIN為`122,814,464 bytes`（約117.125 MiB）；11角約1.258 GiB。
- 文件保存完成後，軟件關閉`TX_BF_MODE`、切換下一個Profile，再重新武裝TSW。這不是32輪交錯角度掃描；對靜態仿體可用作每角32次平均。

可靠的每角時序為：

```text
TX_BF_MODE=0 → 選Profile/LOAD_PROF → TX_BF_MODE=1 → settle
→ 武裝TSW下一個SYNCP上升沿 → 連續DDR記錄32 PRF
→ TX_BF_MODE=0 → 保存BIN → 下一角
```

接線只把PRF事件送到觸發口，不送到高頻時鐘口：

```text
TX7316 TP18／經斷電導通確認的SYNCP焊盤
  → 有源高輸入阻抗緩衝／電平調理
  ├→ TSW14J50 J13 TRIG_IN（必需，HSDC上升沿捕獲起點）
  └→ AFE58JD48 J25 TX_TRG（可選，接收事件/TGC參考）

AFE J60/FMC ↔ TSW J4/FMC（JESD204B、ADC資料時鐘與SYSREF）
```

禁止把SYNCP接到AFE LMK時鐘輸入；也禁止把TX7316高壓OUT接到任何LMK、Trigger或Sync口。只接AFE J25而未接TSW J13時，HSDC硬件觸發會等待超時。HSDC的`Continuous Capture`和`Number of Captures`均保持關閉；一次外部上升沿啟動整個3,837,952-sample連續DDR塊。

## 1. 結論

可以把「一個文件一個角度」改成「一個1 kHz PRF/SYNC週期一個角度」，但這裡的「週期」是每隔1 ms的一次發射事件，不是TX7316的200 MHz BF clock cycle。

原廠TX7316EVM GUI和原廠CPLD沒有「每個SYNC自動將`BF_PROF_SEL_G1`加一」的功能。Windows GUI/ActiveX逐次寫寄存器也不是硬實時控制，不能保證在每個1 ms邊界前完成。因此：

- 現有硬件/固件：可繼續使用每角度一個BIN的已驗證流程。
- 逐PRF掃描：需要自定義CPLD/FPGA sequencer；UI可以先生成完整時序JSON，但在讀回已驗證固件版本前保持Fail Closed。

對靜態凝膠，逐PRF掃描可大幅縮短不同角度間的時間間隔。這不等於自動獲得RF相位相干：RF相干還要求TX載波、BF clock、ADC sample clock及frame-start具有確定相位關係。當前硬件可先採用「每角度獨立RX-DAS → envelope → 非相干角度複合」，不要直接把不同角度的未校準RF逐點相加。

## 2. 建議的第一版掃描規格

先做單bank方案：

- 角度：`-10°…+10°`，步進`2°`，共11角。
- PRF：1 kHz，每1 ms換下一角。
- 一輪掃描：11 ms；理想掃描率約90.9 sweep/s。
- TX profile：P0…P10，無需在掃描中重寫Delay RAM。
- HSDC：一個BIN包含整輪11次發射，另加1個guard PRF。
- 120 MSPS時Samples/channel：`1,441,792`，已向上取整到4096的整數倍。
- 16個uint16數字槽的BIN大小：`46,137,344 bytes`，約44.0 MiB。

`-10°…+10° / 1°`共有21角，超過TX7316的16個Delay Profile。第一版應拆成：

- Bank 1：16角，`2,043,904 samples/channel`，約62.4 MiB。
- Bank 2：5角，`720,896 samples/channel`，約22.0 MiB。

兩個bank之間需要停止發射、重寫profile並重新arm HSDC，因此不是無縫21角。若一定要每1 ms連續循環21角，需要更高階的rolling profile rewrite固件；必須證明所有SPI寫入位於安全空閒窗，且不與HV pulse或profile read window重疊。

## 3. 三種「同步」不要混接

### 3.1 PRF / 發射事件同步

決定每次超聲burst何時發生。TX7316EVM板載CPLD目前產生約1 kHz TR/BF時序。J7 pin 2是板載`SYNC_Probe/SYNCP`輸出觀測點，不是外部輸入口，不可把函數發生器輸出反灌到它。

### 3.2 HSDC Capture Start

TSW14J50 J13只定義DDR捕獲從哪一刻開始；它不是ADC sample clock，也不需要在每個PRF都重新arm。推薦由sequencer產生單次`SCAN_START`：

1. HSDC先進入hardware-trigger armed狀態。
2. sequencer復位beam index至P0。
3. 第一個PRF邊沿同時啟動P0發射與單次TSW J13 Start。
4. HSDC持續記錄整個BIN；後續PRF只切角度，不重新開始DDR。

如果暫時以J7 pin 2的第一個1 kHz邊沿作J13 Start，必須使用高輸入阻抗、有源緩衝/電平轉換和共地，並先驗證J7電平與TSW J13容限。不要用被動T形接頭把多塊板的輸入直接並聯。

### 3.3 ADC/JESD時鐘與SYSREF

AFE58JD48到TSW14J50的120 MSPS數據時鐘、JESD204B lanes和SYSREF已經經FMC/transition硬件傳遞。TSW的Sync A/B不是1 kHz PRF輸入口，不應為了逐PRF掃描而接入J7 SYNCP。

因此不是「所有Sync SMA都要接」。第一版raw RF逐PRF掃描只需：

- AFE ↔ TSW：保持FMC/JESD連接。
- Sequencer/TX：產生並計數1 kHz發射事件。
- Sequencer → TSW J13：一個掃描開始邊沿。
- AFE J25 TX_TRG：固定增益raw Analog Input可留空；只有使用與發射同步的TGC/VCAT序列時才接經驗證的觸發分支。

## 4. 推薦接線拓撲

```text
TX7316EVM custom CPLD / external FPGA sequencer
  ├─ internal TX timing: TR_BF_SYNC + TR_EN
  ├─ internal SPI: BF_PROF_SEL_G1 → LOAD_PROF → verify/self-clear
  ├─ frame reset: beam_index = 0
  └─ one-shot SCAN_START ── level buffer/translator ── TSW14J50 J13

TX7316 J7 OUT_A1…A8 ── transducer ── TX7316 T/R switch
TX7316 J5 RX_A1…A8 ── AFE INP9…INP16 (按實際映射)
AFE J60/FMC ── JESD204B + sample clock + SYSREF ── TSW14J50 J4/FMC

Optional only for synchronized TGC:
sequencer TX event ── verified 3.3 V branch ── AFE J25 TX_TRG
```

外部FPGA若要接管TX7316 SPI，必須解決與板載CPLD/FTDI的總線仲裁或物理隔離；兩個master不能同時驅動。較乾淨的做法是修改並重新燒錄板載CPLD，使它同時保留USB配置和硬實時profile sequencer。

## 5. Sequencer必須實現的狀態機

```text
IDLE
  → CONFIGURED: P0…PN延時已寫入，LOAD_PROF已自清零，TX_BF_MODE=0
  → ARM: HSDC已armed；beam_index=0；frame counter=0
  → START: 選P0並產生第一個PRF；同時輸出一次SCAN_START
  → RUN:
       等本次profile read/HV pulse安全結束
       beam_index = (beam_index + 1) mod N
       寫BF_PROF_SEL_G1
       pulse LOAD_PROF並確認self-clear
       下一個1 ms PRF使用新profile
  → DONE: 完成N×frames次發射後TX_BF_MODE=0，等待HSDC保存
  → IDLE
```

每一幀都必須有明確的P0復位標誌。若上位機只看到連續1 kHz、卻不知道捕獲從P3還是P8開始，離線角度表會循環錯位。

## 6. GUI配置順序

### 6.1 TX7316 GUI

1. 以管理員身份開啟，確認`CONNECTED`；CW保持OFF。
2. 載入/寫入已驗證的Pattern Profile與發射頻率。
3. 寫入11個2° Delay Profiles（第一版）或當前bank的profiles。
4. 將初始profile設為P0，令`LOAD_PROF=1`，確認自動清零。
5. 保持`TX_BF_MODE=0`，直到HSDC完成arm。
6. 快速掃描期間不要再用GUI或ActiveX寫寄存器；sequencer是唯一實時profile控制者。

### 6.2 AFE GUI

1. `DUT RESET → INITIALIZE LMK → AFE RESET → INITIALIZE AFE`。
2. `ADC FORMAT = Analog Input`。
3. 使用與HSDC一致的`120M 8L Subclass 1 / M16 FIXED`配置。
4. `Active Termination = Disable`；增益先低後高，確認不削頂。
5. 固定增益raw RF模式下J25可留空；若使用TGC才接TX_TRG並驗證其電平/極性。

### 6.3 HSDC Pro

1. 選`AFE58JD48_120M_8L_M16_FIXED`，ADC rate填120M。
2. 關閉Time Domain/FFT averaging和continuous streaming。
3. 在`Data Capture Options → Trigger Option`啟用hardware trigger / arm on next。
4. Samples/channel使用Auto Scan頁計算值，必須為4096整數倍。
5. 點Capture/Arm；此時程序應顯示等待J13，而不是已保存。
6. sequencer執行frame reset並發出SCAN_START；HSDC連續記錄整個bank。
7. 捕獲完成後TX_BF_MODE先關閉，再保存BIN和同名scan-plan JSON。

## 7. HKUST Bio-data collector操作

1. 在`陣列與延時`頁設定角度範圍及步進。
2. 打開`逐PRF掃描 Auto Scan`。
3. 第一輪推薦填：PRF `1000`、Sweeps/bank `1`、Guard PRFs `1`。
4. 表格逐行核對Bank、Sweep、SYNC event、TX profile、Beam angle與Sample offset。
5. 點`保存逐PRF掃描方案 JSON`；JSON預設帶`blocked_until_verified_sequencer`標誌。
6. 點`Dry run / 時序檢查`只做數學與存儲檢查，不寫硬件。
7. 未讀回已驗證快速掃描固件時，快速掃描按鈕保持禁用。可切換到`已驗證：每角度獨立BIN`並直接調用現有採集腳本。

## 8. 驗收條件

上高壓與凝膠前，先在低壓/假負載驗證：

- 每輪第一個事件始終為P0，角度表不旋轉。
- 11個PRF間隔為`1.000 ms ±量測誤差`，沒有漏脈衝或雙脈衝。
- 每次發射前profile選擇與LOAD_PROF已完成，沒有在HV pulse期間寫Delay RAM。
- HSDC文件大小等於`Samples × 16 × 2 bytes`。
- 文件內事件sample offset與JSON一致；120 MSPS、1 kHz時相鄰事件約120,000 samples。
- 不接凝膠時，事件串擾峰依角度順序穩定出現；重複捕獲不發生P0偏移。
- TX開/關、角度順序改變時，raw BIN和event QA確實改變，不是重用舊文件。

## 9. 仍需確認的硬件決策

在真正編寫/燒錄快速掃描固件前，需要鎖定：

1. 第一版使用11角/2°單bank，還是21角/1°兩bank。
2. sequencer放在TX7316EVM板載CPLD，還是外部FPGA；推薦板載CPLD以避免SPI雙master。
3. 每個BIN只含一輪掃描，還是同一bank循環多輪；靜態成像建議先1輪，確認後再增加。
4. 固件如何向上位機回報版本、當前bank、profile index與frame reset成功；沒有這些讀回量，UI不應解鎖。

參考：`TX7316 slos950C`的Beamformer Operation與Profile Read/Write章節；`TX7316EVM SBoU224`的CPLD/SYNC原理圖；`AFE58JD48EVM SLOU521`的J25 trigger與JESD初始化章節。
