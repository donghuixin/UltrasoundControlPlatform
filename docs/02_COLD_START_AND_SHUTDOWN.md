# 從完全斷電到自動採集：完整操作流程

本流程只適用凝膠、水槽或流體仿體。TX7316EVM是開放式高壓評估板；本系統沒有醫療隔離、聲輸出限值與人體安全認證，不得貼人體或用於診斷。

## 0. 本機已驗證的基線

| 項目 | 當前值 |
|---|---|
| TX/RX物理陣元 | A1–A8，共8個；pitch `1.59 mm` |
| AFE/HSDC數字槽 | 16槽，軟件目前配置A1–A8對應槽`9…16`；最終映射仍須逐SMA驗證 |
| ADC/JESD | `120 MSPS`、8 lanes、Subclass 1、M=16 |
| HSDC device | `AFE58JD48_120M_8L_M16_FIXED`，不可用舊`MANUAL` |
| TSW | board `TIAOPCAW`、firmware `TSW14J50RX_FIRMWARE` |
| TX頻率白名單 | 1、1.5、2、2.5、4 MHz；寫入後由寄存器回讀驗證 |
| 板載PRF | SYNCP約1 kHz，GUI不能改成20 kHz |

## 1. 完全斷電時接線

先關閉J2、J1、J3、AFE/TSW電源和USB，再接信號線。帶電時不得插拔J5/J7/FMC。

### 1.1 超聲信號鏈

1. TX7316 J7的`OUT_A1…OUT_A8`接8個陣元的高壓端。
2. 陣列公共電極接探頭/系統模擬回路；不要接第二個TX輸出。
3. TX7316 J5的`RX_A1…RX_A8`經短50 Ω同軸接AFE相應SMA。
4. AFE J60與TSW14J50 J4用FMC直接對接；JESD lanes、ADC資料時鐘和SYSREF走FMC。
5. TX、AFE與同軸屏蔽採用短、低電感公共參考。J7 pin2不是地。

### 1.2 觸發線（按模式二選一）

- `normal`：SYNCP、AFE J25和TSW J13可暫時不接；軟件從每個BIN內找發射事件並軟對齊。只適合靜態仿體。
- `hardware`：TX7316已確認的SYNCP測試點經高輸入阻抗、3.3 V兼容緩衝/電平調理後扇出到TSW J13；如需要以發射事件驅動AFE TGC，再分一路到AFE J25 `TX_TRG`。

不要把SYNCP接到AFE LMK時鐘輸入，也不要接TSW J7/J8 Sync A/B。SYNCP是約1 kHz的事件/PRF標誌，不是120 MHz ADC sample clock。它在`TX_BF_MODE=0`時仍可自由運行，因此看到SYNCP不代表高壓TX已啟用。

## 2. 上電前五項檢查

1. 確認板卡是原生5-level或已完成Appendix C 3-level改裝，電源接法與板卡模式一致。
2. `TX_BF_MODE=OFF`，`CW_EN_1=OFF`，`CW_EN_2=OFF`。
3. J7只去陣元、J5只去AFE、FMC沒有偏排或鬆動。
4. 探頭與仿體之間排除大氣泡，排線沒有拉扯陣列。
5. 輸出磁碟使用本地NTFS並預留空間：1,048,576 samples/ch的一個16槽BIN約32 MiB；32 PRF硬件觸發BIN約117.1 MiB/角。

## 3. 電源與USB冷啟動

### 3.1 TX7316邏輯先上

1. 只接TX7316 USB，以管理員身份開TX7316 GUI。
2. 開J3 `+5/GND/-5 V`，按板上S1硬件reset。
3. GUI必須顯示`CONNECTED`；執行`Read All`且沒有`FT_IO_ERROR`。
4. 確認BF與CW全OFF。此時不要先開高壓。

若出現`Error 4 / FT_IO_ERROR / 到達文件結尾`：關閉採集腳本與TX GUI，關J2→J1→J3，拔TX USB至少10秒；只接TX USB後重來。不要按Continue在未知硬件狀態下繼續。

### 3.2 AFE與TSW

1. 確認AFE J60↔TSW J4 FMC已插好，再給AFE/TSW上電。
2. 以管理員身份啟動HSDC Pro並連接TSW14J50。
3. 以管理員身份啟動AFE GUI，依序執行：
   `DUT RESET → INITIALIZE LMK → AFE RESET → INITIALIZE AFE`。
4. AFE起始值：`Analog Input`、`120M 8L Subclass 1`、LNA 15 dB、PGA 18 dB、LPF 20 MHz、VCAT最大衰減/Min Gain、Active Termination Disable。
5. HSDC選`AFE58JD48_120M_8L_M16_FIXED`並Reload INI，ADC rate填`120M`。
6. 初次聯調保持Average、Continuous Capture和Write captured data to file/streaming全OFF。
7. 先手動捕獲1024或4096 samples：不得DDR timeout；基線應在mid-code附近且無削頂。

`M16_FIXED.ini`的本機安裝位置是：

```text
E:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files
```

## 4. TX波形與高壓

1. TX GUI保持`TX_BF_MODE=OFF`和CW OFF。
2. 可由HKUST UI在採集開始時選擇1/1.5/2/2.5/4 MHz；腳本會寫Pattern Profile 0、Reg25，回讀白名單字段，不匹配便Fail Closed。
3. 手動使用時可載入`configs/tx7316/1MHz_5pulses.cfg`；載入後立即再次關閉`TX_BF_MODE`，因為cfg可能把內部BF打開。
4. Delay Profile由採集軟件按角度生成；軟件在BF OFF時寫入、令`LOAD_PROF=1`並等待自清零，之後才開BF。
5. Pattern寄存器回讀只證明數字時序已寫入；接收振鈴峰不是TX電氣頻率。最終聲學頻率和輸出仍應以示波器/水聽器驗證。

確認低壓與GUI正常後才開高壓：

- 原生5-level：J3 ±5 V → J1 ±30 V → J2 ±100 V。
- 已完整改裝3-level：J3 ±5 V → J1 ±30 V；J2斷開並絕緣。

任何電源撞限流、異味、異響或異常發熱都應立即關J2→J1→J3。

## 5. 啟動HKUST Bio-data collector

1. 關閉所有舊採集命令窗，確認沒有另一個腳本正在控制HSDC。
2. 雙擊`HKUST_BioData_Collector\Run_HKUST_BioData_Collector_as_admin.cmd`。
3. 頂部應顯示`Admin: yes / TX GUI: open / HSDC: open`。這些只表示進程存在；HSDC Automation連線是否健康仍以正式採集日誌為準。
4. `陣列與延時`頁填：8陣元、pitch 1.59 mm、寬1.0 mm、聲速1540 m/s、Delay quantum 5 ns、HSDC槽`9,10,11,12,13,14,15,16`。
5. 選中心頻率和角度，例如`-10…+10° / 2°`共11角。
6. `自動採集`先點Dry run；必須列出角度、延時counts、profile批次、預估檔案數/容量並以exit code 0結束。

## 6. 正式成像採集

### 6.1 靜態仿體、normal模式

1. Samples/channel先用`1,048,576`，Repeats=`1`，Settle=`0.25 s`，Trigger=`normal`。
2. 選本地輸出根目錄並勾完五項Pre-flight。
3. 點`開始自動採集`一次。此時按鈕會鎖定；不要再啟動第二個採集。
4. 命令窗逐角度執行：寫/選profile→LOAD_PROF自清零→BF ON→HSDC Capture→BF OFF→保存BIN→QA。
5. `ADC_Save_Raw_Data_As_Binary_File`保存32–128 MiB可需30–60秒；心跳和檔案大小仍更新即代表程序存活。不要按Ctrl+C。

### 6.2 共同起點、hardware模式

1. 先完成第1.2節的SYNCP→buffer→TSW J13；AFE J25只在需要同步TGC時接。
2. HSDC Trigger Option啟用hardware trigger / arm on next capture，delay=0；Continuous Capture與Number of Captures不要用來代替一個長DDR block。
3. UI Trigger選`hardware`。腳本會在profile切換/保存時改回normal以避免自由運行SYNCP誤觸發，BF穩定後才重新arm。
4. 下一個SYNCP上升沿只決定整塊DDR資料的起點；後續1 kHz發射事件仍連續落在同一BIN內。
5. 推薦的32 PRF/角配置為`3,837,952 samples/channel`，約31.983 ms、117.125 MiB/角。

### 6.3 逐PRF換角度

原廠CPLD不能保證每1 ms自動增加Delay Profile。UI的`逐PRF掃描 Auto Scan`目前可生成時序JSON、樣本數和Fail-Closed檢查，但真正的11角/2°單BIN快速掃描需要已驗證的自定義CPLD/FPGA sequencer。未驗證固件前使用「每角度獨立BIN」，不要把規劃JSON誤當作硬件已執行。

## 7. 成功判定

一次run只有同時滿足以下條件才算成功：

- 命令窗以exit code 0結束；
- `capture_manifest.json`的`status`為`complete`；
- BIN數量等於角度數×Repeats，且每個大小=`samples × 16 × 2 bytes`；
- 日誌顯示`M16_FIXED`、正確board/firmware、TX pattern readback matched；
- QA沒有ADC rail samples；若削頂，降低AFE增益/TGC或TX電壓後重錄；
- hardware模式量得相鄰事件約120,000 samples（120 MSPS、1 kHz）；
- 移動探頭或改角度後原始BIN的SHA-256/波形確實改變。

## 8. 離線重建

1. 打開`處理與成像 Process`，選擇`status=complete`的capture資料夾。
2. RX重複槽策略先用自動保留先出現者；物理映射未逐SMA驗證時，摘要會保留警告，不能把6個獨立槽說成8個已驗證通道。
3. 可選全部1°角度或每隔一角取2°子集；這只改離線重建，不改原始BIN。
4. 點`強制重新運算`。輸出包含頻譜、回波時域、通道QA、PRF週期、逐週期圖和2D DAS。
5. 白色代表較強包絡。TX設定頻率、Pattern基頻、接收振鈴峰和延遲回波窗峰分開顯示，不能互相替代。

## 9. 正常關機

1. 等BIN保存與重建完成，確認manifest為complete。
2. TX GUI取消`TX_BF_MODE`並確認CW OFF。
3. 依序關J2 → J1 → J3。
4. 關AFE/TSW電源，再退出HKUST UI、AFE GUI、HSDC Pro、TX GUI。
5. 最後拔USB和信號線。

## 10. 最常見故障

- `HSDC Connect_Board code=66`：Automation連線已關閉或另一個採集客戶端仍占用。停止所有採集，只保留一個HSDC Pro，重啟HSDC Pro、重選`M16_FIXED`，再啟動一次UI任務。
- `Read DDR TIMED_OUT_ERROR`：檢查AFE初始化、JESD/clock、M16_FIXED與hardware模式的J13邊沿。
- `FT_IO_ERROR`：按第3.1節完整USB/低壓冷啟動，不在錯誤對話框按Continue。
- 命令窗似乎卡住：先看心跳、elapsed time和目標BIN大小；保存大檔期間不按Ctrl+C。
- `expected_prf_hz=None`重建錯誤：當前版本已修正，缺值會回退至1 kHz並在摘要標記；舊run可直接強制重建。
