# HKUST Bio-data collector

白色 Liquid Glass 風格的 Python 桌面控制台，用於整合：

- 陣元幾何與多角度 TX7316 Delay Profile 計算；
- TX7316 GUI + HSDC Pro 自動逐角度採集；
- HSDC raw BIN 的離線軟對齊、帶通、DAS、角度複合；
- 2D B-mode、窄扇形掃描、軸向反射深度、頻譜與3D曲面輸出。

## 第一次啟動

1. 先以管理員身份開啟 TX7316 GUI，確認 `CONNECTED`。
2. 以管理員身份開啟 HSDC Pro，確認TSW14J50並選`AFE58JD48_120M_8L_M16_FIXED`；不要選JESD M=5的舊`MANUAL`profile。
3. AFE GUI 完成 `DUT RESET → INITIALIZE LMK → AFE RESET → INITIALIZE AFE`。
4. TX GUI 中人工確認 Pattern Profile、PRF、脈衝週期、CW OFF 和電源電壓。
5. 雙擊：

   `Run_HKUST_BioData_Collector_as_admin.cmd`

GUI 使用目前 PATH 中的 Python 3；硬件採集固定調用 `C:\Python27\python.exe`，因為 TX7316 Device GUI DLL 是32-bit。

界面啟動時會啟用 Windows Per-Monitor DPI Awareness v2；所有界面文字使用 Segoe UI / Cascadia Mono 的 TrueType 矢量字體，不再由 Windows 將整個窗口作低解析度位圖拉伸。

## 使用流程

### 1. 陣列與延時

- 輸入陣元數、中心間距、陣元寬度、中心頻率、聲速和Delay Quantum。
- TX7316 G1只支持 `A1–A8`，所以陣元數限制為 `2–8`。
- 少於8個陣元時，只有 `A1…AN`參與延時計算，其餘Delay字段填零；未使用TX輸出仍需物理斷開或在TX GUI關閉。
- UI 可選 `1°`（精細）或 `2°`（快速）角度步進。`-10°…+10° / 1°` 共21個角度。
- TX7316一次只有16個Delay Profile；超過16角度時採集腳本會在`TX_BF_MODE=OFF`期間自動分批重寫，例如21角度使用`16+5`兩批。軟件設置64角度安全上限。
- 表格會顯示量化後角度、A1–A8 counts、相鄰相位差和最近柵瓣。
- `序號→HW`欄會顯示全局文件序號到當前硬件Profile的映射，例如`16→P00`表示第二批的第一個角度。
- UI會即時計算角度數、TX批次、BIN數量和預估容量；1,048,576 samples、1 repeat時，11角度約0.34 GiB，21角度約0.66 GiB。

### 2. 自動採集

- 填寫Samples/channel、Repeat、Settling時間與Trigger模式。
- `normal`適合目前沒有硬件同步線的靜止凝膠採集。
- `hardware`只能在TSW J13已接正確外部觸發時使用。
- 先點 `Dry run`，命令列會彈出但不連接硬件。
- 完成五項Pre-flight確認後，點 `開始自動採集`。
- 若角度超過16，UI會再次顯示批次數和文件數；確認後腳本自動完成批次切換，無需人工操作TX GUI。
- 採集命令列會獨立彈出並保留，GUI則監控新的`capture_manifest.json`。

UI和腳本不會修改：高壓電源、5-level電壓、Pattern Profile波形、PRF、發射週期數、AFE增益。

### 3. 處理與3D

- 選擇`status=complete`的`capture_*`文件夾。
- 點`運算並繪製2D / 3D`。
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
C:\Python27\python.exe ..\automation\tx7316_hsdc_batch_capture.py --dry-run --angles=-10,-8,-6,-4,-2,0,2,4,6,8,10 --tx-elements 8 --pitch-mm 1.59 --element-width-mm 1.0 --center-frequency-mhz 1.0 --sound-speed-m-s 1540 --delay-quantum-ns 5
```

## 安全邊界

此程序只用於凝膠、水槽或組織仿體，不是醫療設備，不得直接用於人體。沒有共源硬件觸發時，重建使用發射串擾進行軟對齊，只能做靜態非相干複合。

## PW Doppler

UI現在包含`PW多普勒 Doppler`頁面，可計算PRF的無模糊深度、速度Nyquist、單塊脈衝數、原始RF數據量和距離門I/Q數據量，並可啟動固定角度HSDC短塊採集。

重要限制：TX7316EVM板載CPLD的1 kHz PRF不能由GUI或本程式直接改變；多個HSDC BIN之間存在保存缺口，不能拼成連續心動週期。完整接線、AFE/TSW配置和連續I/Q方案見 [PW_DOPPLER_OPERATION_GUIDE.md](PW_DOPPLER_OPERATION_GUIDE.md)。
