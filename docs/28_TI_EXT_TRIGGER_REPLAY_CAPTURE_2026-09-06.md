# TI EXT_TRIG確定性重播長窗採集：上位機實現

日期：2026-09-06

TI的建議已落實到上位機，但功能名稱固定為「分塊重播 · 非連續」，避免把多次DDR capture誤稱為連續錄製。完整操作、容量公式、保存長度驗收與拼接Gate見：

- [上位機TI EXT_TRIG分塊重播操作指南](../HKUST_BioData_Collector/TI_EXT_TRIGGER_REPLAY_GUIDE.md)
- [分塊計算模型](../HKUST_BioData_Collector/long_capture_model.py)
- [Python 2.7 HSDC採集器](../automation/hsdc_demod_replay_capture.py)

## 實現邊界

- 60 MSPS／40x／M=32：可在TI包已完成小深度通道與trigger Gate後逐段保存。
- 20 MSPS／160x：只計算理論容量；TI附件沒有匹配CFG、frame mapping與separator，因此上位機拒絕實採。
- 每塊保存exact-size BIN、SHA-256與offset manifest；下一塊前要求操作者設定外部trigger delay並輸入`READY`。
- HSDC `Set_Write_Capture_to_File`沒有被當成串流方案；現有板卡/INI的ports未配置，而且該選項不能消除DDR塊之間的主機保存空檔。
- TI separator每64 raw rows輸出1條16通道complex row；60 MSPS下輸出cadence為937.5 k rows/s，而不是先前誤寫的1.875 MSPS。

## 五秒預設方案

最大深度、50 ms overlap時為10塊，每塊0.559240533 s／512 MiB，虛擬覆蓋5.142405333 s，總原始資料5 GiB。只允許相位鎖定、每次完全相同的輸入重播；活體或脈動流仍須真正無間隙的range-gated I/Q串流硬件。
