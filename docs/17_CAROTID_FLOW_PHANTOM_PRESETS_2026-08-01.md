# 頸動脈流量仿體PW Doppler預設與配置審計（2026-08-01）

適用平台：TX7316EVM + AFE58JD48EVM + TSW14J50/HSDC Pro + `HKUST_BioData_Collector`。

## 安全與用途邊界

這些是**頸動脈樣流量仿體/已知泵速台架**預設，不是人體掃描或狹窄診斷協議。本平台尚未完成聲學輸出、MI/TI、電氣隔離、探頭接觸材料和醫療設備驗證。FDA要求診斷超聲遵循ALARA並記錄實際工作模式、輸出指標和暴露時間：<https://www.fda.gov/radiation-emitting-products/medical-imaging/ultrasound-imaging>。

正式頸動脈檢查還要求B-mode、彩色流、頻譜波形和多位置速度測量，不能只用單個PW數值下診斷結論。IAC/ACR/AIUM資料要求可調距離門和角度校正，並建議聲束—血流角維持45–60°、避免超過60°：

- <https://aium.s3.amazonaws.com/guidelines/extracranial/imageResources.pdf>
- <https://gravitas.acr.org/PPTS/DownloadPreviewDocument?DocId=190&ReleaseId=2>
- <https://intersocietal.org/wp-content/uploads/2023/11/IAC-Updated-Recommendations-for-Carotid-Stenosis-Interpretation-Criteria_11.1.23.pdf>

## Repository配置審計結果

執行：

```powershell
python HKUST_BioData_Collector\config_audit.py
python HKUST_BioData_Collector\config_audit.py --collector-config HKUST_BioData_Collector\collector_config.json
```

當前結果：`PASS`，0 error、7 warning。warning包括三個HSDC profile尚未通過16/16唯一碼transport Gate、三個AFE overlay只能與指定實驗成對使用，以及TI TX quick-start檔名/實際內容不一致；它們都不是語法錯誤，也不代表相應硬件Gate已通過。

已修正：

1. 兩個HSDC實驗INI內損壞的`Menu Enable`文字已恢復為`Trigger Option`。
2. Collector首次啟動與example/local JSON統一為1.5 MHz、8元素、HSDC槽5–12、tapered-5level。
3. 一鍵PW原始RF方案使用8,388,608 samples/channel：120 MSPS下約69.9 ms、約69個1 kHz脈衝，足夠64-pulse STFT，但不足心動周期。
4. TX自動化的help文字已與實際白名單1/1.5/2/2.5/4 MHz一致。

仍未通過：

- 所有repository HSDC INI都未通過16/16唯一碼transport Gate；槽5–12只是避開目前已知固定重複對的8路降級映射。
- `configs/tx7316/1MHz_5pulses.cfg`實際是4個聲學周期且不是0°完整preset；一鍵PW不直接使用該文件，而由自動腳本寫入並讀回1.5 MHz白名單pattern和固定角度delay。
- AFE Subclass 1/2 cfg必須和同名HSDC實驗成對使用，不可混搭；完成transport試驗後還要恢復analog配置。

## 頸動脈流量仿體預設

所有方案默認8路物理孔徑、HSDC槽5–12、1.5 MHz、0° TX steering、60° flow angle、25 mm門中心。深度和flow angle應按仿體幾何修改；預設名稱不代表量值已校準。

| 預設 | PRF / 時長 | 期望速度 | 速度Nyquist | 無模糊深度 | 75 BPM周期 | 狀態 |
|---|---:|---:|---:|---:|---:|---|
| 低速短塊 | 1 kHz / 0.07 s | 0.25 m/s | 0.513 m/s | 770 mm | 0.09 | 現有raw後端可執行 |
| 常規波形 | 5 kHz / 10 s | 1.5 m/s | 2.567 m/s | 154 mm | 12.5 | 需連續I/Q固件 |
| 低速/舒張流 | 2.5 kHz / 15 s | 0.6 m/s | 1.283 m/s | 308 mm | 18.75 | 需連續I/Q固件 |
| 高速射流 | 7.5 kHz / 10 s | 3.0 m/s | 3.850 m/s | 102.7 mm | 12.5 | 需連續I/Q固件 |
| 長記錄 | 5 kHz / 30 s | 1.5 m/s | 2.567 m/s | 154 mm | 37.5 | 10秒Gate通過後使用 |

高速方案只用於已知狹窄管/泵速仿體，不把速度值直接映射成人體狹窄程度。IAC 2023標準也要求綜合灰階斑塊、ICA/CCA比值、PSV和EDV，而不是單一速度閾值。

## 一鍵執行

1. 啟動Collector，按`Alt+4`進入`PW多普勒 Doppler`。
2. 在`Carotid flow-phantom preset`選擇方案。
3. 完成三項Pre-flight；系統不會自動勾選安全確認。
4. 對「可執行」短塊點`一鍵採集並分析`：程式套用全部參數、寫入並讀回固定TX角度、採集單一BIN，然後自動生成速度譜。
5. 對I/Q方案點`一鍵載入並檢查Gate`：程式完成計算與Session Plan，但在5 kHz共同PRF和連續I/Q後端通過前拒絕啟動硬件。

第一次台架運行先用低速短塊確認：TX marker週期、距離門、無削頂、流向反轉時頻移符號反轉。之後再驗收10秒常規I/Q方案，最後才使用30秒長記錄。
