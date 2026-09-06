# HKUST Ultrosound collector platform

## 目前唯一合格的 normal 采集配置（TI 通道映射修復包）

- AFE GUI 必須載入 `JESD 120MSPS_Subclass1_8L.CFG`（SHA-256 `FC5A7093E21D816B7063D826759109C60BC1E31D294C7898B26808109ABAA344`）。
- HSDC Pro 必須使用 `AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1`（SHA-256 `78923A1787DC6794274398B5457DF1EE2F40852B0E9854DDC6AED41E9CDC8E67`）。
- 這一對文件取代本文較早的 normal-mode `M16_FIXED`／`G128OFF` 操作說明。J13 hardware/software trigger 是另一條路徑，只能使用匹配的 `_TRIG` profile。

白色 Liquid Glass 風格的 Python 桌面控制台，用於整合：

- 陣元幾何與多角度 TX7316 Delay Profile 計算；
- TX7316 GUI + HSDC Pro 自動逐角度採集；
- HSDC raw BIN 的離線軟對齊、帶通、DAS、角度複合；
- 2D B-mode、窄扇形掃描、軸向反射深度、頻譜與3D曲面輸出。

## 第一次啟動

1. 先以管理員身份開啟 TX7316 GUI，確認 `CONNECTED`。
2. 以管理員身份開啟 HSDC Pro，確認TSW14J50。`normal` 採集只使用 TI 2026-08-03 提供且 SHA-256 為 `78923A…E67` 的 `AFE58JD48_Custom_PLL_MODE_40x_No Demod_SubClass1`；腳本會驗證完整雜湊後才放行。J13 hardware/software trigger 是尚待16/16 Gate的實驗路徑，只能選 `_M16_FIXED_TRIG`。不要選舊 `MANUAL`、`G128OFF` 或 normal-mode `M16_FIXED` profile。
3. AFE GUI 完成 `DUT RESET → INITIALIZE LMK → AFE RESET → INITIALIZE AFE`。
4. TX GUI 中確認 `CW OFF`；在本上位機第一頁選擇白名單 Pattern、cycles，並填入外部電源的實測 ±HV_A／±HV_B 幅值。
5. 雙擊：

   `Run_HKUST_BioData_Collector_as_admin.cmd`

GUI 使用目前 PATH 中的 Python 3；硬件採集固定調用 `C:\Python27\python.exe`，因為 TX7316 Device GUI DLL 是32-bit。

界面啟動時會啟用 Windows Per-Monitor DPI Awareness v2；所有界面文字使用 Segoe UI / Cascadia Mono 的 TrueType 矢量字體，不再由 Windows 將整個窗口作低解析度位圖拉伸。

## 使用流程

### 1. 陣列與延時

- 輸入陣元數、中心間距、陣元寬度、中心頻率、聲速和Delay Quantum。
- TX7316 G1只支持 `A1–A8`，所以陣元數限制為 `2–8`。
- 少於8個陣元時，只有 `A1…AN`參與延時計算，其餘Delay字段填零；未使用TX輸出仍需物理斷開或在TX GUI關閉。
- 「A1…AN 對應的 HSDC 接收槽」必須按實際接線填寫。本平台目前確認為
  `5,6,7,8,9,10,11,12`；採集腳本會把這個映射寫入manifest，離線重建不再假設使用槽1–8。
- 重複槽處理不再寫死。重建頁可選：自動保留映射中先出現者、保留全部配置槽作診斷，或在示波器／逐SMA排查後手動指定DAS槽。
  所有策略只影響離線重建，不會改寫或刪除原始BIN。在完成真實SMA到HSDC槽映射前，圖像只能視為診斷結果。
- UI 可選 `1°`（精細）或 `2°`（快速）角度步進。`-10°…+10° / 1°` 共21個角度。
- TX7316一次只有16個Delay Profile；超過16角度時採集腳本會在`TX_BF_MODE=OFF`期間自動分批重寫，例如21角度使用`16+5`兩批。軟件設置64角度安全上限。
- 表格會顯示量化後角度、A1–A8 counts、相鄰相位差和最近柵瓣。
- `序號→HW`欄會顯示全局文件序號到當前硬件Profile的映射，例如`16→P00`表示第二批的第一個角度。
- UI會即時計算角度數、TX批次、BIN數量和預估容量；1,048,576 samples、1 repeat時，11角度約0.34 GiB，21角度約0.66 GiB。
- 第一頁的 `TX7316 pattern plan` 參照TI Pattern Profile界面，提供白名單波形、1/2/4/6/8/10/12 cycles、符號電平序列與波形預覽。任何欄位改動都會撤銷先前確認；正式採集前必須重新確認。
- `±HV_A／±HV_B` 是外部電源的實測幅值和manifest記錄，不是可由TX7316 SPI設定的DAC值。`HV_A` 是外層高電平、`HV_B` 是靠近 AVSS 的內層電平，必須滿足 `|HV_A| > |HV_B|`（例如 100 V／50 V）。軟件只會選擇 `P_HV_A/P_HV_B/AVSS/M_HV_A/M_HV_B` 電平路徑；實際電壓仍由外部電源決定。

### 2. 自動採集

- 填寫Samples/channel、Repeat、Settling時間與Trigger模式。
- `normal`適合目前沒有硬件同步線的靜止凝膠採集。
- `hardware`只能在TSW J13已接正確外部觸發時使用。
- 先點 `Dry run`，命令列會彈出但不連接硬件。
- 完成五項Pre-flight確認後，點 `開始自動採集`。
- 若角度超過16，UI會再次顯示批次數和文件數；確認後腳本自動完成批次切換，無需人工操作TX GUI。
- 採集命令列會獨立彈出並保留，GUI則監控新的`capture_manifest.json`。

UI和腳本不會修改實體高壓電源、板載CPLD的PRF或AFE增益。確認TX計畫後，正式採集會先保持 `TX_BF_MODE=0`，再針對1、1.5、2、2.5、4 MHz白名單更新TX7316 Pattern Profile、Repeat Count與Delay Profiles；逐項回讀完全一致後才允許發射，不匹配即拒絕採集。每個完成的run還會保存可由TI GUI重新載入的 `TX7316_*_verified.cfg` 與索引JSON。

### 2.1 逐PRF自動掃描

新`逐PRF掃描 Auto Scan`頁把每一個1 kHz SYNC事件映射為明確的TX Profile、beam angle與HSDC sample offset：

- 11角/2°可規劃為1個profile bank和1個BIN，約11 ms完成一輪；
- 21角/1°會自動拆成16+5兩個bank和兩個BIN；
- UI自動把Samples/channel向上取整為4096的整數倍，並估算每個BIN大小；
- 可保存帶硬件需求和Fail-Closed狀態的JSON方案，並做不接觸硬件的時序Dry Run；
- 原廠CPLD沒有逐SYNC profile sequencer，因此真正快速掃描在讀回已驗證自定義固件前保持禁用；切到`已驗證：每角度獨立BIN`仍可直接運行現有採集。

接線、TX/AFE/HSDC配置、sequencer狀態機與驗收步驟見 [RAPID_PRF_AUTO_SCAN_GUIDE.md](RAPID_PRF_AUTO_SCAN_GUIDE.md)。

### 3. 處理與3D

- 選擇`status=complete`的`capture_*`文件夾。
- 「離線角度取樣」可選擇使用全部已採集角度，或由1°資料選取`-10,-8,…,+10`的2°子集；後者不需要重新採集。
- 「接收旁瓣／振鈴抑制」可選均勻、Hann或Tukey α=0.5接收窗；可另外啟用保守的`√CF` coherence factor。
- 「淺層共模振鈴抑制」只在TX後0–12 mm做帶餘弦退場的共模相減，避免全深度相減誤刪真正的平面反射；三種選項都不改寫原始BIN。
- 建議A/B順序是：`均勻` → `Tukey` → `Tukey + √CF`；只有前12 mm確實受共模振鈴污染時才開啟共模抑制。
- 點`套用選項並重新成像`。
- 分析輸出保存在`capture_*\analysis`：

  - `plane_wave_das_bmode.png`
  - `sector_scan.png`
  - `reflector_depth_profile.png`
  - `echo_spectrum.png`
  - `bmode_3d_surface.png`
  - `analysis_summary.json`

每張圖的標題都包含 `capture_*` 名稱與輸入 BIN 組合的 SHA-256 短指紋；右側摘要和預覽來源條也會顯示同一指紋。切換採集目錄時會強制重新解析目前目錄，不沿用上一個 run 的預覽路徑。

除 PNG 預覽外，2D、扇形、深度、頻譜與3D圖均同步輸出 `.svg`；SVG 的座標、標題和文字可無損縮放。

3D曲面是輔助展示；定量距離仍以2D圖和軸向深度曲線為準。

## 自我檢查

```powershell
python app.py --self-test
python -m unittest discover -s tests -v
```

比較兩次採集是否真的不同：

```powershell
python compare_capture_runs.py <old_capture_folder> <new_capture_folder>
```

命令會生成三聯對照 PNG/SVG、標準化 B-mode 相關係數、逐 BIN 抽樣相關係數與 SHA-256 指紋。

採集腳本的可變參數Dry Run：

```powershell
C:\Python27\python.exe ..\automation\tx7316_hsdc_batch_capture.py --dry-run --angles=-10,-8,-6,-4,-2,0,2,4,6,8,10 --tx-elements 8 --pitch-mm 1.59 --element-width-mm 1.0 --center-frequency-mhz 2.5 --sound-speed-m-s 1540 --delay-quantum-ns 5
```

## 安全邊界

此程序只用於凝膠、水槽或組織仿體，不是醫療設備，不得直接用於人體。沒有共源硬件觸發時，重建使用發射串擾進行軟對齊，只能做靜態非相干複合。

## PW Doppler

PW頁面新增`TI EXT_TRIG 分塊重播 · 非連續`卡片，可計算60 MSPS demod最大DDR窗、重疊、trigger offset與磁碟空間，並逐塊保存exact-size BIN、SHA-256及manifest。此功能只適用確定性相位鎖定重播，不會把多個BIN標成活體連續資料；詳見[操作指南](TI_EXT_TRIGGER_REPLAY_GUIDE.md)。

UI現在包含`PW多普勒 Doppler`頁面，可計算PRF的無模糊深度、速度Nyquist、TSW總DDR分攤、單塊脈衝數、原始RF數據量、距離門I/Q數據量和預估心動周期數。現有模式會配置固定TX波束角度、採集單一連續HSDC raw-RF塊，完成後自動輸出距離門I/Q、wall filter、速度譜、速度CSV和周期可信度摘要。

頁面提供五個頸動脈樣流量**仿體**預設。現有1 kHz/70 ms低速短塊可在完成Pre-flight後一鍵採集並分析；2.5/5/7.5 kHz多周期方案會一鍵載入並檢查硬件Gate，不能繞過尚未驗證的共同PRF與連續I/Q後端。配置審計可執行`python config_audit.py`。

重要限制：TX7316EVM板載CPLD的1 kHz PRF不能由GUI或本程式直接改變；現有M=16、120 MSPS原始RF的理論最長單塊只有約0.140秒，多個HSDC BIN之間又存在保存缺口，不能拼成連續心動週期。最佳10秒心動方案需要5 kHz共同PRF和FPGA距離門I/Q後端；在固件通過前UI會保持硬件Gate。完整推導見 [PW_DOPPLER_OPERATION_GUIDE.md](PW_DOPPLER_OPERATION_GUIDE.md)、[多心動周期設計](../docs/16_PW_DOPPLER_MULTI_CYCLE_DESIGN_2026-08-01.md)、[流量仿體預設](../docs/17_CAROTID_FLOW_PHANTOM_PRESETS_2026-08-01.md)和[最新兩日總交接](../docs/21_HANDOFF_2026-08-05_TWO_DAY_UPDATE_CW_IQ_CAPTURE_AND_IMAGING.md)。

## CW Doppler / 三傾角DBUD

`CW多普勒 DBUD`頁面實作Science Advances 2021三傾角算法的配置、有限DDR採集與I/Q預覽。現有拓撲使用8個貼片、17°/20°/23°三行；TX預設為現有200 MHz BF_CLK可直接產生的3.125 MHz。AFE數位研究路徑由`15/10/7.5/6/5 MSPS`選擇器控制，分別對應硬體抽取`D=4/6/8/10/12`，因為complex I/Q率為`120 MSPS/(2D)`。完成採集後會保存`cw_iq.bin`、manifest、通道摘要和I/Q／基帶頻譜預覽；5 MSPS、8通道complex I/Q的512 MiB理論時長約3.36秒。

8個貼片也不等於HSDC會自動縮成8-slot JESD；要做三行DBUD，三行頻移必須獨立且同時。長時記錄優先使用AFE類比CW輸出加外部同步I/Q ADC。平台可校驗並載入TI GUI安裝包的3.125 MHz CW quick-start，在J1正負高壓軌均實測為±5 V、500 mA限流和仿體確認後，只允許0.05至5秒限時CW，並提供獨立停止按鈕。精確1/2/4 MHz仍鎖定，直到128 MHz BF_CLK硬件通過實測。完整步驟見 [CW_DOPPLER_OPERATION_GUIDE.md](CW_DOPPLER_OPERATION_GUIDE.md)。
