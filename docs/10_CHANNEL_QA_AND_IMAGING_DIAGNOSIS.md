# 通道QA、成像失敗原因與三級排查

本文件針對AFE58JD48EVM、TSW14J50、TX7316EVM與HSDC Pro的現有8陣元實驗鏈。所有高壓測試只限凝膠、水槽或仿體；數位與類比隔離測試先關閉TX高壓與`TX_BF_MODE`。

## 1. 目前已確認的事實

2026-07-25 已把通道複製從聲學資料進一步重現到 AFE 內部 16 通道唯一數位碼：matched S1/K8、matched S2/K8 以及 TI 安裝包原始 S1 profile 都得到同一份 raw BIN SHA-256，並固定缺少 AFE CH3、CH4、CH15、CH16。這證明複製位於數位 transport/去幀鏈，而不是探頭或成像算法。完整實驗矩陣與下一步見 [JESD 通道複製故障報告](11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md)。

以`capture_20260724_202654`為例，manifest配置的接收槽是HSDC 9–16，不是1–8。對完整BIN逐位計算SHA-256後得到：

- 全16槽的逐位重複組：`3=5`、`4=6`、`9=15`、`10=16`。
- 目前真正配置的9–16槽內，逐位重複只有`9=15`、`10=16`；因此最多只有6條不同的數位流。
- 上述四對在11個角度BIN中全部持續存在，較像確定性的converter/profile/FPGA解包映射，不像偶發雜訊或單次接觸不良。
- 對9–16槽、1.5 MHz帶通、4–42 mm事件窗做SVD，第一奇異值約佔69.2%，95%有效秩為5、99%有效秩為6。把未配置的1–8槽、發射串擾及平面反射一起算進去，會把秩誤判成1–2。

這表示聲學資料不是「八路完全塌成一路」，但接收自由度確實從8降到最多6，而且強共模、平面多次反射和柵瓣仍然足以淹沒橫向結構。數位唯一碼測試已確認槽15、16複製的是槽9、10對應 converter；暫時屏蔽只能避免重複計權，不代表物理A7/A8壞掉，也不修復JESD映射。

## 2. 自動QA工具

```powershell
python automation\channel_health_qa.py --capture-dir "E:\path\to\capture_YYYYMMDD_HHMMSS"
```

工具嚴格從`capture_manifest.json`讀取`rx_hsdc_slots_1_based`，預設使用0度BIN並驗證PRF事件。輸出到`analysis/channel_qa/`：

- `channel_health.json`：逐位重複、跨檔持續性、相關性、SVD、每槽帶通能量、事件一致性與rail比例。
- `channel_health.csv`與`channel_health.png`：人工檢查表與圖。
- `channel_mask.json`：暫時選擇的一組互不逐位重複槽。
- `six_channel_event_cutouts.npz`：只含有效事件窗與六槽的輕量診斷資料。
- `channel_baseline_6ch.zip`：可傳送給另一台電腦的診斷包，不包含完整原始BIN。
- `reconstruct_selected_channels.txt`：以選中槽重建的命令。

SNR欄位是「指定深度窗的帶通能量相對晚時電子噪聲」，會包含平面界面、振鈴和混響，不能直接稱為血管或腫瘤SNR。判斷橫向信息時必須同時看逐位重複、去共模相關性、SVD以及探頭移動實驗。

## 3. 先修正的兩個軟件認知

目前`reconstruct_ultrasound.py`已從manifest讀取9–16槽，並按1-based槽號轉成BIN列索引；不再固定取前8列。若舊分析目錄由舊版腳本生成，先刪除該run的`analysis/`或在UI點「清除分析緩存」後強制重算。

`sector_scan.png`是「發射角度×同一條A-line包絡」的扇形顯示，不是完整接收DAS，所以水平條紋不能用來判斷橫向分辨率。接收波束合成結果以`plane_wave_das_bmode.png`及逐PRF的RX-DAS圖為準。

## 4. 為甚麼目前圖像不好

按優先級排列：

1. **數位槽重複與映射未驗收。** 9=15、10=16使8槽只剩6條不同資料，且槽號尚不能安全等同物理陣元號。
2. **發射直通、探頭/PDMS橫向耦合與平行界面混響。** 所有通道同時看見的大脈衝會造成高相關、水平亮帶與幀間相位漂移。
3. **1.59 mm間距嚴重空間欠採樣。** 軟件加窗、DMAS、MVDR或coherence factor只能抑制旁瓣，不能從已混疊資料恢復缺失的空間頻率。
4. **未做逐陣元time-zero、增益、極性與相位校準。** 幾個ADC sample的時間偏差就會使相干疊加互相抵消。
5. **每個角度分開保存。** 沒有共同硬體觸發/相位參考時，只能做包絡或功率的非相干角度複合，不能把不同檔RF直接相干相加。
6. **換能器接收共振約在1.5 MHz。** 改TX pattern到2、2.5或4 MHz後，接收仍可能被探頭的1.45–1.6 MHz機械模態主導。

## 5. 柵瓣的量化邊界

對最大偏轉角`theta_max`，避免可見柵瓣的常用上限為：

```text
p <= lambda / (1 + |sin(theta_max)|)
```

取聲速1540 m/s、偏轉±10度：1.0、1.5、2.0、2.5、4.0 MHz的上限約為1.31、0.875、0.656、0.525、0.328 mm。現有1.59 mm間距連1 MHz的±10度掃描也不滿足；若採保守`lambda/2`設計，1.5 MHz應約0.51 mm。

現有硬體的實際策略是：先用1.5 MHz取得較好的靈敏度，只做0度或極小角度pilot；成像時加Hann/Tukey接收孔徑、角度非相干複合與coherence factor，並把結果標註為有空間混疊。下一版1.5 MHz陣列優先把pitch設為約0.50 mm；若一定要保留1.59 mm，工作頻率需降到約0.8 MHz以下才適合±10度。

## 6. 三級隔離排查

### A. 數位JESD/解包：先證明16條converter資料不同

1. 關閉TX高壓、`TX_BF_MODE`與AFE類比輸入刺激。
2. 重做AFE GUI的`DUT RESET -> INITIALIZE LMK -> AFE RESET -> INITIALIZE AFE`。
3. 在AFE GUI對兩顆ADC die啟用可區分converter的數位test pattern或channel/ramp pattern。使用GUI可讀回欄位，不盲寫未知寄存器。
4. HSDC選`AFE58JD48_120M_8L_M16_FIXED`，只抓4096–65536 sample。
5. 檢查D3/D4、JESD sync與HSDC無timeout，再比對16列。若`3=5`等仍逐位相等，故障在AFE輸出模式、兩die的LMFS、lane順序、HSDC INI或TSW FPGA解包，與探頭焊點無關。
6. 注意AFE58JD48資料手冊把16通道分成兩顆8通道die；40X/8-lane模式是每顆die `L=4,M=8,F=4`。HSDC顯示的聚合`L=8,M=16,F=4`必須與GUI實際模式及FPGA固件一致，不能只憑profile名稱判定正確。

### B. 類比SMA映射：證明每個AFE輸入口落到唯一數位槽

1. 退出test pattern，TX高壓仍保持關閉。
2. 用信號源從約`-30 dBm`、1.5 MHz開始，每次只注入一個AFE SMA；確認50 ohm、共地及輸入幅度安全。
3. 每個SMA抓一個短BIN，記錄唯一顯著上升的HSDC槽，形成`INP1..16 -> slot1..16`實測表。
4. 若注入INP15卻只讓slot9響應或完全複製slot9，先修數位mapping；若16個SMA都能唯一映射，再查J5轉接板、同軸、連接器與焊點。

### C. 聲學陣元：最後才判斷探頭與T/R路徑

1. 用固定金屬絲/平面反射體，保持探頭位置、增益和電壓完全不變。
2. 逐次只啟用一個TX陣元、全部已驗證RX接收，記錄發射效率。
3. 再固定一個TX，逐RX比較同一深度窗的帶通SNR、到達時間、極性及頻譜中心。
4. 只有數位與SMA映射均通過後，某一物理陣元仍無合理回波，才判定J5線束、T/R、FPC、陶瓷或焊點故障。

## 7. 六通道基線的正確用途

暫時用`9,10,11,12,13,14`，屏蔽`15,16`，可以避免把兩條完全重複資料當成額外孔徑而產生錯誤增益。這組資料只適合驗證：探頭移動後圖像是否改變、已知平面深度是否正確、通道校準是否提高相干性。它不能證明槽9–14就是連續的物理A1–A6，也不能憑演算法恢復缺失的A7/A8空間資訊。

驗收門檻：

- 16個AFE SMA逐一注入時，各自只有唯一槽主響應；無逐位重複。
- 8個實際RX陣元在固定反射體上均有可重複回波，無削頂。
- 校準後同一反射面的跨通道到達時間符合幾何預期。
- 0度pilot移動探頭2–5 mm後，內部特徵跟著合理移動，而固定電子串擾不移動。
- 通過以上條件後才比較DAS、DMAS、MVDR、CF或超分辨率方法。
