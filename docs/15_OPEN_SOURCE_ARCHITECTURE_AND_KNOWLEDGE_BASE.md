# 開源工程、架構與可遷移知識庫

更新日期：2026-07-31

## 1. 使用邊界

本文件把開源工程分成「可直接借鑑的演算法」、「可借鑑的 JESD 架構」與「僅供歷史參考的硬體」。
它們都不能直接取代 TX7316、AFE58JD48、TSW14J50 的 TI GUI、寄存器與 FPGA firmware。

| 工程 | 已核對來源 | 可借鑑內容 | 不應直接推論 |
|---|---|---|---|
| USTB | Bitbucket `ustb/ustb` | MATLAB beamforming、延遲模型、資料結構、指標與範例 | 不能直接控制本機 TI EVM |
| UltraSpy | GitLab `pecarlat/ultraspy` | RF/IQ DAS、FDMAS、TFM、Color/Power Doppler、CPU/GPU 管線 | 不能替代 HSDC deformatter 或 AFE 初始化 |
| ListenToJESD | GitHub `pulp-bio/ListenToJESD` | 公開 JESD204 接收端、CGS/ILA/transport 分層的 RTL 思路 | 不是 TSW14J50 bitstream，也不證明本機 M/F/K 映射 |
| echomods | GitHub `kelu124/echomods` | 開放式超聲採集、脈衝回波實驗、資料記錄方法 | 舊硬體與寄存器不可直接套用到 AFE58JD48 |
| murgen-dev-kit | GitHub `kelu124/murgen-dev-kit` | 開源探頭與實驗硬體參考 | 本地 partial clone 未完整 checkout，暫不作代碼依據 |
| ADCoctoSPI01 | GitHub `mlab-modules/ADCoctoSPI01` | ADC/SPI 控制板與量測流程參考 | 與本機 JESD204B/HSDC 資料格式不同 |

## 2. 已從來源代碼確認的設計模式

### USTB

USTB 適合建立「可重現的離線重建基準」：固定資料格式、聲速、陣元幾何、發射事件與接收序列，
再比較 DAS、相干複合與品質指標。它應用在 transport gate 通過之後；若 HSDC 欄位仍複製，
任何高階 beamformer 都只會把錯誤資料處理得更漂亮。

### UltraSpy

本地源碼 `scripts/doppler_flow.py` 清楚分離 Reader、GridScan、DelayAndSum、RF-to-IQ、
packet beamforming 與 Color/Power Doppler。這支持本平台採用相同的模組邊界：

```text
raw block -> manifest/map validation -> event segmentation -> RF/IQ -> beamforming
          -> clutter filter -> Doppler estimator -> velocity/power display
```

其速度 Nyquist 關係採用 `v_N = c*PRF/(4*fc)`。本平台必須使用實際 ensemble PRF、
聲束與流向夾角以及已校準的 `fc`；延長單個 burst 只改善窄帶與 SNR，不會提高速度 Nyquist 上限。

### ListenToJESD

它的價值是協助區分 link layer 與 transport layer：鏈路能建立不代表 converter-to-column
解包正確。本機穩定的 bit-exact 複製更像 deformatter／converter lookup／HSDC column assembly，
不能只以 CGS/ILA 成功宣告 16 通道正常。

## 3. 本平台正確架構

```text
TX7316 pattern/delay -> 高壓 T/R 節點 -> 探頭/仿體
探頭回波 -> TX7316 內建 T/R switch -> AFE58JD48 analog front end/ADC
AFE JESD204B -> TSW14J50 FPGA/DDR -> HSDC Pro DLL/save -> raw BIN
raw BIN + immutable manifest -> transport QA -> calibration -> B-mode/Doppler
```

三種時間尺度不可混用：

- JESD reference/device clock：維持 ADC 與 FPGA 高速鏈路，不等於 PRF 觸發。
- PRF／發射事件：定義每條 A-line 或 Doppler slow-time sample。
- HSDC capture arm/start：觸發一次 DDR 記錄，不會自動把每個 PRF 分割成獨立檔案。

## 4. B-mode 與 Doppler 的不同需求

### B-mode

先完成：16 欄唯一碼 transport gate、接收映射、單通道平面反射、通道增益／極性／延遲校準。
現有 1.59 mm pitch 在 1.6–1.7 MHz 約為 1.65–1.75 波長，存在不可由軟體完全消除的柵瓣。
先使用 `-4°/0°/+4°`，固定仿體，逐角度保存相同 manifest 與校準版本。

### PW Doppler

PW Doppler 要在同一角度與同一 range gate 重複發射，形成連續 slow-time ensemble。
推薦資料路徑為：窄帶複數解調、壁濾波、Kasai 或短時 FFT、混疊檢測、角度校正。
HSDC Pro 的一般 DDR capture 是「先捕獲、後保存」，不是無限時邊錄邊傳；多個心動週期需分塊採集、
每塊保留 overlap 與時間戳，或開發 TSW14J50 自訂 FPGA streaming。外部 trigger 只用來確定 block 起點，
不能替代每個 pulse 的可靠 PRF 標記。

## 5. 1.6–1.7 MHz 實測結論

操作者回報目前探頭最佳響應約為 `1.6–1.7 MHz`，暫定 `1.65 MHz` 作為下一輪標定中心。
必須同時保存 TX 設定頻率、示波器電氣頻率與回波／水聽器聲學峰值。只有三者一致，
才可把該頻率寫入正式成像或 Doppler profile。

## 6. 本地知識庫與版本固定

第三方源碼不提交到本倉庫。已在工作站建立：

```text
E:\Users\dxhui\Desktop\TI_AFE58jd48\Ultrasound_OpenSource_KnowledgeBase
```

本倉庫只保存來源 URL、commit、適用邊界和派生流程；完整清單見該資料夾的
`SOURCE_MANIFEST.md`。這避免把第三方歷史、授權檔與不完整 partial clone 混入產品倉庫。

