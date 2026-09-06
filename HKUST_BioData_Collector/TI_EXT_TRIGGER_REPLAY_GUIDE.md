# TI EXT_TRIG 分塊重播採集操作指南

更新日期：2026-09-06
適用：AFE58JD48EVM + TSW14J50 + HSDC Pro + 可重播的低電壓測試信號

## 先說結論

此功能把TI建議落實為「有限DDR窗的受控分塊採集」：每次先讓HSDC等待J13的EXT_TRIG上升沿，再保存一個BIN；下一次把外部觸發相對於同一段重播信號向後移，最後以重疊區驗證後拼接。

它不是連續串流。HSDC保存檔案期間沒有採集，只有當輸入在每次測試中完全可重播，而且輸入、ADC sampling clock與EXT_TRIG相位鎖定時，才可把各窗重建成一條**虛擬時間軸**。禁止用這種方法拼接活體、脈動流或不同心搏的PW Doppler資料。

## 上位機現在做了甚麼

- 以TI最大深度`33,554,432 raw rows/lane`計算每塊時間、分塊數、重疊與磁碟空間。
- 60 MSPS實採路徑固定使用TI交付的40x／M=32 demod配置；20 MSPS／160x只顯示容量方案，缺少匹配CFG與separator時不允許實採。
- 每一塊開始前在獨立命令列要求操作者輸入`READY`，避免未調整trigger delay便誤arm。
- 每塊只接受一個EXT_TRIG rising edge，之後立即disarm，再保存BIN。
- BIN必須精確等於預期bytes；默認對每個BIN計算SHA-256。
- `capture_manifest.json`保存每塊trigger offset、時間、檔名、bytes、hash和HSDC保存結果，並永久標記`gap_free_live_recording=false`。

## 60 MSPS下的基準數字

TI package的raw時間基準是60,000,000 rows/s，而不是`60/32`：

```text
單塊時間 = 33,554,432 / 60,000,000 = 0.559240533 s
單塊大小 = 33,554,432 × 8 lanes × 2 bytes = 512 MiB
TI separator = 64 raw rows / 1 output row
分離後行率 = 60,000,000 / 64 = 937,500 complex rows/s
```

例如目標5 s、相鄰重疊50 ms：

```text
step = 0.559240533 - 0.050000000 = 0.509240533 s
blocks = 10
虛擬覆蓋 = 5.142405333 s
原始資料 = 5.000 GiB
每個重疊區 = 46,875 separated complex rows
```

## 第一次使用：只做低電壓數字／信號源驗證

1. TX7316高壓電源保持OFF，`CW_EN_1=0`、`CW_EN_2=0`、`TX_BF_MODE=0`；不要接人體。
2. 用限流、低電壓函數發生器向一個AFE輸入提供可重複波形，先使用TI配置對應的約486.145 kHz tone或已知digital pattern。
3. 輸入序列必須有可重現的`t=0`，並能在每個block前從相同狀態重新開始。
4. 使用同一參考時鐘或已驗證的同步架構鎖定：信號生成、AFE ADC sampling clock、送往TSW14J50 J13的EXT_TRIG。
5. 核對J13的邏輯電平、極性、阻抗及上升沿；不要把TX高壓OUT接到J13或任何clock輸入。

## AFE與HSDC準備

1. 以管理員身份打開AFE GUI與HSDC Pro；採集腳本也必須用相同權限。
2. 備份當前AFE配置與readback，記錄HSDC device/profile、firmware版本。
3. AFE GUI載入TI的`JESD 60MSPS_Subclass1_8L_40x_demod.CFG`。
4. 完成reset、clock、AFE initialization；每一步等待GUI回到Idle。
5. 在`DEMOD > Manual Setup > Filter Coefficient RAM`從address 0載入TI的`Filter Coefficient M=32.txt`。
6. 先用65,536 rows的小捕獲驗證：HSDC顯示lane 1與5有資料，其餘lane為32768；不要直接從最大深度起步。
7. 驗證TI separator輸出32欄`1I,1Q,...,16I,16Q`，且每個受控輸入只出現在唯一、正確的物理通道。
8. HSDC Pro打開`Trigger Options`：
   - `Trigger mode enable = ON`
   - `Software Trigger = OFF`
   - `Arm on next capture button press = ON`
9. 先手動驗證一次：按Capture/Arm後送一個J13上升沿；確認只產生一個有限DDR block。

正式腳本會讀取HSDC `Default_controls.ini`中最後保存的Board Name與ADC/DAC selection，再執行`Connect_Board → Select_AFE_Device → Reload_Device_INI`，以建立Automation DLL所需的ports；它不會替你判斷一個錯選的profile是否正確。因此開始前必須在HSDC GUI選好並保存本次已驗證的device。

任何lane、sync、通道身份或trigger結果不符合預期時停止；不要進入最大深度分塊。

## 在上位機中建立方案

1. 打開`PW多普勒 Doppler`頁面，找到`TI EXT_TRIG 分塊重播 · 非連續`。
2. `Raw lane rate`保持`60 MSPS · TI 40x/M32包（可實採）`。
3. `虛擬目標時長`先填`5`；`相鄰重疊`先填`50 ms`。
4. `Raw rows/lane`填`33554432`。若先做小規模端到端驗證，可填`65536`，但重疊必須小於該block時間。
5. 離開輸入框後檢查：block duration、block count、virtual span、總GiB、separator rate及offset範圍。
6. 先點`導出分塊JSON`保存實驗方案，再點`分塊Dry run`。Dry run不連HSDC、不arm、不建資料目錄。
7. 確認輸出磁碟至少有「預計總資料 + 1 GiB」空間。

## 正式逐段採集

1. 勾選兩項確認：確定性重播/相位鎖定，以及理解它不是活體連續記錄。
2. 點`逐段觸發並保存`，閱讀最後警告後確認。
3. 獨立命令列顯示Block 1：
   - 重置輸入到相同`t=0`；
   - 在外部delay generator設定畫面要求的offset；
   - 再次確認三路相位關係；
   - 輸入`READY`。
4. 腳本arm HSDC；此時才送一個合格EXT_TRIG rising edge。
5. 等待HSDC完成DDR讀取、BIN保存、精確bytes驗證及SHA-256。保存期間不要點HSDC GUI。
6. 命令列進入下一塊後才改delay；重複至全部block完成。
7. 上位機狀態會顯示`files n/N`；完成後打開`capture_ti_replay_YYYYMMDD_HHMMSS`。

若輸錯offset，不要繼續湊數；中止該run並重新開始。每個run的offset序列必須完整、單調且與manifest一致。

## 如何判斷保存長度合理

每塊必須同時通過：

1. 檔案大小為`raw_rows_per_lane × 8 × 2 bytes`。最大深度應為`536,870,912 bytes`。
2. manifest中的`captures`數量等於`planned_captures`，全部entry為`status=complete`。
3. 每個檔案SHA-256非空且重新計算一致。
4. raw時間長度用`raw_rows_per_lane / raw_lane_rate_hz`計算；不能用檔案保存耗時。
5. 60 MSPS TI separator輸出完整frame上限為`floor(raw_rows/64)`；最大深度理論為524,288 rows。實際可因搜尋sync與尾端不足64 rows而略少，但每塊差異必須可由相同sync起點解釋。
6. 相鄰兩塊分離後的重疊區預期點數為`overlap_s × 937,500`；50 ms即46,875 rows。

## 拼接接受門

先對每塊獨立執行TI separator，再按manifest的trigger offset放到虛擬時間軸。相鄰窗只在以下全部通過後裁剪重疊並拼接：

- sync位置穩定，通道欄位與I/Q順序一致；
- 重疊區sample index與pulse count一致，沒有漏pulse或重複pulse；
- 每個有效通道的重疊區幅值、相位及相關性在預先設定容差內；
- 觸發offset殘差沒有隨block累積；
- 任一block沒有削頂、全零、lane丟失或保存錯誤。

任一門失敗，該run不得生成stitched結果。原始BIN和manifest保留，不覆寫。

## 20 MSPS／160x的位置

TI說可評估20 MHz sampling rate、160x、最大capture depth，理論單塊為：

```text
33,554,432 / 20,000,000 = 1.6777216 s
```

但目前TI附件只有60 MSPS／40x配置及其separator。上位機可以顯示20 MSPS的block數與磁碟方案，但會禁止實採，也不會猜測separator row rate。取得並驗證20 MHz／160x AFE CFG、HSDC profile、frame mapping、separator及最大samples後才可解鎖。

## 活體或脈動流真正的長時間路徑

需要5–10 s連續PW Doppler時，不使用本頁拼接。應改用真正的無間隙資料路徑：

- TSW/其他FPGA在固定range gate內每PRF保留一個complex slow-time sample，帶單調pulse index/timestamp，再持續串流；或
- 經驗證的類比/數位baseband I/Q輸出接可持續寫盤的同步DAQ。

這兩種方法才能保留血流逐脈衝相位歷史，並支持心動周期、PSV/EDV等時間序列分析。
