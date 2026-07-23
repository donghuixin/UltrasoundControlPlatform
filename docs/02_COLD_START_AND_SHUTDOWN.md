# 從完全斷電開始的冷啟動與關機

以下流程適用凝膠/水槽仿體。第一次或接線變更後，不跳過低壓驗證；沒有示波器時應把高壓保持關閉，先用假負載/已知信號驗證接收鏈路。

## A. 上電前

1. 檢查板號、跳線、5-level/3-level模式與供電端子完全一致。
2. 確認J7高壓只去陣元、J5低壓只去AFE、公共電極和AGND正確。
3. 確認AFE J60與TSW J4 FMC完全插合，沒有偏一排。
4. 確認CW OFF、所有高壓電源輸出關閉、旋鈕/固定源極性正確。
5. 凝膠無大氣泡，探頭聲學面完全耦合；排線沒有拉扯陣列。
6. 將資料輸出目錄放在有足夠空間的本地NTFS磁碟。

## B. 清除 FTDI 殘留狀態

如果上一輪出現 `Error 4 / FT_IO_ERROR / 到達文件結尾`：

1. 關閉採集命令列與HKUST UI。
2. 關閉TX7316 GUI，不按Continue。
3. J2、J1、J3全部關閉。
4. 拔TX7316 USB，等10秒；必要時暫時拔AFE USB，避免抓錯FTDI。
5. 重新只接TX USB，再開始下面流程。

## C. GUI與低壓初始化

1. 右鍵以管理員啟動TX7316 GUI。
2. 開J3 `±5 V`，按板上S1硬件reset，確認GUI `CONNECTED`。
3. 點 `Read All`；若報FTDI錯誤，回到B，不上高壓。
4. 保持 `TX_BF_MODE=OFF`、`CW_EN_1=OFF`、`CW_EN_2=OFF`。
5. 右鍵以管理員啟動HSDC Pro，連接TSW14J50 `TIAOPCAW`。
6. 啟動AFE GUI並依序：`DUT RESET → INITIALIZE LMK → AFE RESET → INITIALIZE AFE`。
7. AFE初值：Analog Input、120M 8L Subclass1、LNA 15 dB、PGA 18 dB、LPF 20 MHz、VCAT Min Gain/最大衰減、Active Termination Disable。
8. HSDC選 `AFE58JD48_120M_8L_MANUAL`，確認120M、Normal trigger、average/continuous/stream-to-file全OFF。
9. 先做一次1024或4096 samples的手動Capture；必須沒有timeout，基線約在mid-code且不削頂。

## D. 載入1 MHz TX preset

1. TX GUI `TX_BF_MODE=OFF`。
2. 載入 `configs/tx7316/1MHz_5pulses.cfg`，或在Quick Setup選對應 Internal 1MHz preset。
3. 等左下角 `Idle`。
4. `Read All`核對：Reg24先為`0x02000002`（BF off），Reg25約`0x00000246`，Pattern Profile 0為配置快照中的0x60–0x64。
5. 不把HSDC `Target Frequency=1M`當作頻率已改；真正驗證靠採集後回波/串擾的頻譜峰值。

## E. 高壓最後上

### 5-level

1. 開J3 ±5 V並確認穩定；
2. 開J1 ±30 V；
3. 最後開J2 ±100 V；
4. 觀察電源是否撞限流、板卡是否發熱/異味/異響。

### 3-level Appendix C

1. 確認改裝電阻檢查已做；
2. J2保持斷開；
3. 開J3 ±5 V，再開J1 ±30 V。

## F. 啟動HKUST UI

1. 雙擊 `HKUST_BioData_Collector\Run_HKUST_BioData_Collector_as_admin.cmd`。
2. `陣列與延時`填8、1.59 mm、1.0 mm、1 MHz、1540 m/s、5 ns。
3. `自動化採集`先Dry run；命令列應列出角度和counts並以0退出。
4. 做0°單角度pilot，再做全角度；詳見B-mode文檔。

## G. 正常關機

1. 等任何Save完成，確認manifest `complete`。
2. 在TX GUI取消`TX_BF_MODE`，確認CW OFF。
3. 依序關J2 → J1 → J3。
4. 關AFE/TSW電源，再退出UI和三個TI GUI。
5. 最後拔USB和信號線。材料或探頭仍帶電時不重新插拔J5/J7。
