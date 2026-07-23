# 系統與模式總覽

## 信號鏈

```text
TX7316 J7 OUT_A1…A8 → 壓電陣列 → 回波
                         ↓ 同一陣元節點
TX7316 內部 T/R switch → J5 RX_A1…A8 → AFE58JD48 SMA → JESD/FMC → TSW14J50 → HSDC Pro → BIN
```

TX7316 本身帶 T/R switch。J5 是 T/R switch 保護後的低壓 RX 排針，應連 AFE；正常單端陣元不需要再把高壓 TX 端直接接 AFE，也不需要另加一顆功能重複的主 T/R switch。接口板上的二次限幅、ESD、終端與連接器仍然有價值。

## 四種工作模式

| 模式 | TX 電源/板卡 | 同步線 | 能完成的工作 | 主要限制 |
|---|---|---|---|---|
| 5-level 靜態 B-mode | J3 ±5、J1 ±30、J2 ±100 V | 可全部留空 | 原板 CPLD 1 kHz，多角度逐檔採集、離線軟對齊 | 非嚴格相干；只測仿體 |
| 5-level 硬件起始觸發 | 同上 | J7 pin2 → TSW J13 | 每個 HSDC block 起點鎖到下一個 SYNCP 邊沿 | J7仍是1 kHz輸出；AFE raw RF不需J25 |
| Appendix C 3-level | 已完整改板；J3 ±5、J1 ±30、J2不接 | 同上 | 約 `+30/0/-30 V` | 不是剛買來即可用，須斷電核對改裝 |
| 長時間 PW Doppler | 自製/改裝主PRF控制路徑 | 同一主時基送TX、AFE/FPGA、TSW | 固定角度、距離門、連續I/Q慢時間 | 原板J7不可輸入20 kHz；HSDC逐檔保存不能代表心動週期 |

## 軟件分工

- TX7316 GUI：Pattern、Delay/Profile、T/R時序、TX_BF_MODE；不設 HSDC 採樣率。
- AFE58JD48 GUI：AFE、LMK、JESD、LNA/PGA/TGC、濾波與可選 demod/decimation。
- HSDC Pro：TSW14J50 firmware、JESD解包、採樣點數、capture/trigger/save。
- HKUST UI：計算延時、啟動自動採集、監看 manifest、調用離線重建；不改高壓或AFE增益。
- `tx7316_hsdc_batch_capture.py`：控制已開啟的兩個 GUI，分批寫 Delay Profiles，逐角度 Capture/Save。
- `reconstruct_ultrasound.py`：解析 BIN、通道QA、軟對齊、濾波、DAS與圖表。

## 判斷一次採集是否成功

只有同時滿足以下條件才算成功：

1. 命令列退出碼為0；
2. 新建的 `capture_*/capture_manifest.json` 中 `status` 是 `complete`；
3. BIN數量等於角度數×repeats；
4. 每個 BIN 大小等於 `samples × 16 × 2 bytes`；
5. manifest 的每個 capture 有角度、硬件profile、時間戳和QA；
6. 不是只看 HSDC 畫面或命令列停在 `Saving...`。
