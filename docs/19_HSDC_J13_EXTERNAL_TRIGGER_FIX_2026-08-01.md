# TSW14J50 J13 外部觸發修正與驗證

## 問題結論

`Trigger mode enable` 只控制一個 HSDC DDR block 的起點，不會讓 AFE58JD48 在每個 PRF 重新接收。AFE/JESD 在初始化後持續輸出資料；20 kHz PRF 應控制 TX 時序，TSW14J50 J13 只需要一個有效上升沿開始記錄。

原 `AFE58JD48_120M_8L_M16_FIXED.ini` 中的以下設定是註解：

```ini
\\Is Capture Trigger SMA = 1
```

TI 隨 HSDC Pro 提供的 TSW14J50 外部 SMA trigger 配置則使用有效設定：

```ini
Is Capture Trigger SMA = 1
```

因此新增獨立配置 `AFE58JD48_120M_8L_M16_FIXED_TRIG.ini`。它保留原 M=16、L=8、120 MSPS、Subclass 1 和 channel pattern，只明確啟用 J13 capture-trigger SMA。不要覆寫原配置。

## 安裝

把：

```text
configs\hsdc\AFE58JD48_120M_8L_M16_FIXED_TRIG.ini
```

複製到：

```text
<HSDC Pro>\14J50 Details\ADC files\
```

本機已安裝到：

```text
E:\Program Files\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files\
```

安裝後完全退出並重新啟動 HSDC Pro，再選擇：

```text
AFE58JD48_120M_8L_M16_FIXED_TRIG
```

應顯示：

```text
Board Name       = TIAOPCAW
Firmware Type    = TSW14J50RX_FIRMWARE
ADC Output Rate  = 120M
Channels         = 16
```

## 單次觸發驗證

先關閉 TX 高壓和 CW：

1. 先在 normal mode 捕獲 65,536 samples/channel，確認 JESD 與 DDR 正常。
2. FPGA trigger 輸出接 TSW14J50 `J13 TRIG_IN`，使用同軸並共地。
3. 示波器在 J13 SMA 實際量測，確認低到高的上升沿、無負壓且不超過 3.3 V。
4. HSDC Trigger Option 設定：`Trigger mode enable=ON`、`Software Trigger enable=OFF`、`Delay=0`。
5. 手動測試可勾 `Arm on next capture button press`：按 Capture 後延遲約 100 ms，再輸出一個 5–10 us 的單次高脈衝。
6. 自動化 DLL 模式必須使用 `Trigger_Option(1,0,0,0)`；TI DLL 定義要求 external trigger 時 `ArmOnNextCaptureButtonPress=0`。
7. 觸發後使用 `Read_DDR_Memory(1)` 等待並讀出已捕獲的 block。

20 kHz、50% duty 的週期不是頻率上限問題。若單次脈衝能觸發而連續方波看似不能觸發，通常是第一個邊沿已經啟動 block，後續邊沿在重新 arm 前被忽略。

## HSDC software trigger

同一塊 TSW14J50 使用 software trigger 時，必須把板上的一個 `SYNC/TRIG_OUT` SMA 以短同軸線回接至 `J13 TRIG_IN`。先用示波器確認 J7/J8 哪一個輸出在按下 `Generate Trigger` 時產生約 1.8 V active-high pulse，再將該路接至 J13。

HSDC Trigger Option 設定：

```text
Trigger mode enable              ON
Software Trigger enable          ON
Arm on next capture button press OFF
Trigger CLK Delays               0
```

按 `OK` 後主按鈕變為 `Generate Trigger`；每按一次只產生一次 trigger pulse，並捕獲一個連續 N-sample DDR block。這個選項沒有 PRF/period 設定，也不是 periodic auto-rearm。

`Trigger CLK Delays` 只決定觸發後略過多少個ADC樣本，不是兩次採集之間的時間間隔。

若要以秒級間隔反覆取得獨立快照，上位機可以在「trigger -> read DDR -> save -> re-arm」全部完成後，再等待指定秒數並開始下一個 block。但BIN之間存在USB/保存/重arm缺口，不能把它當作連續PW Doppler慢時間資料。

## 推薦時序

```text
Host:  configure HSDC -> arm external capture
FPGA:  wait for host-ready -> emit one J13 capture_start edge
FPGA:  start/continue 20 kHz PRF for TX7316
TSW:   capture one continuous N-sample DDR block
Host:  Read_DDR_Memory -> save BIN -> disarm
```

20 kHz 主時基可扇出到 TX7316 和需要事件同步的 AFE J25；不要把 J13 當作每個 PRF 的接收門控或 auto-rearm 命令。

## 自動化保護

`automation/tx7316_hsdc_batch_capture.py` 現在：

- normal capture 接受原 `M16_FIXED` 或新的 `M16_FIXED_TRIG`；
- software/hardware capture 強制要求 `M16_FIXED_TRIG`；
- 若 hardware capture 仍選原配置，會在接觸硬件前報出可操作錯誤，而不是等待 J13 超時。

## 驗收與回退

驗收順序：normal capture PASS → 單次 J13 pulse PASS → 1 kHz continuous PASS → 20 kHz continuous PASS。每一步只改一個變量。

回退只需重新選擇原 `AFE58JD48_120M_8L_M16_FIXED`。原 INI 和 TI 安裝文件均未被覆寫。
