# 2026-08-19 示波器頸動脈樣Doppler與TI Dec=32總交接

適用平台：外部脈衝發射器/T/R + MSO8304A示波器，以及AFE58JD48EVM + TSW14J50/HSDC Pro。
資料範圍：2026-08-15至2026-08-19的本機示波器分析、AFE Demod排查與TI技術支援進展。
安全範圍：研究與儀器診斷；本倉庫不保存人體原始資料，也不對任何結果作臨床聲明。

## 1. 當前結論

這幾天的工作已把「沒有血流圖」拆成兩個不同問題：

1. **脈搏/血管壁運動已能在部分記錄中重複提取。** 最新30 V/0 V、2 MHz、10 MSPS資料中，`RigolDS1.bin`可得到約71.6–71.9 bpm的局部脈搏候選，前壁約13.01 mm、後壁約18.02 mm。
2. **方向性血流速度仍未通過有效性Gate。** 三組真管腔中心的flow-band SNR都低於3 dB或方向性不足；零速附近的固定對稱譜線主要由發射振鈴、共同組織/探頭運動、量化與削頂造成。因此正式PSV/EDV保持空值。

若強制以三組中心門的90% excess-power頻譜上緣作低可信度估計：

- 未校正軸向表觀峰值約37–45 cm/s，中位約40.6 cm/s；
- 若條件式假設聲束與血流夾角59°，約72–87 cm/s，中位約78.8 cm/s；
- 只能寫成`conditional diagnostic estimate`，不能寫成已驗證PSV；EDV仍不可報告。

硬體長記錄方面，TI最新回覆確認：

- 不能只把8個AFE通道送入DDR，DDR會接收完整16通道資料；
- FPGA可捕獲最多`33,554,432`個HSDC樣點；
- 完整資料可能不全部顯示在HSDC圖窗，但可以由GUI導出；
- TI正在驗證匹配高Decimation CFG與INI，預計另行提供。

因此近期最重要的下一步不是再調離線算法，而是取得並驗證TI的Dec=16/32成套配置。

## 2. 進展時間線

### 2.1 0815：初始RF與血流定位重分析

- 將原始RF先按PRF事件切段，而不是對整段示波器資料直接做CW解調。
- 加入CH2發射參考對齊、數字I/Q下變頻、fast-time深度門與slow-time wall filter。
- 比較PRF差分、包絡M-mode、Kasai與STFT等路徑。
- 結論：PRF差分能突出變動，但同時放大觸發抖動、探頭運動與T/R振鈴，不能單獨證明血流。

### 2.2 0818：MSO8304A兩通道、4 MHz與2 MHz比較

- CH1固定為T/R後回波，CH2固定為實測發射參考。
- 將PRF降至10 kHz並增加連續記錄時間，以覆蓋多個周期。
- 4 MHz資料在淺層可提供較短波長，但接收SNR和振鈴問題未因此消失。
- 2 MHz資料的穿透和壁回波更穩定，因此近期以2 MHz作主線；是否改4 MHz必須由流體仿體的方向性SNR決定，不能只看理論散射強度。

### 2.3 10 MSPS長記錄與ICA/ECA資料

- 10 MSPS對2 MHz載波仍有5 samples/cycle，可保留相位解調所需資訊。
- 建立CH2事件細對齊、深度M-mode、前後壁定位、壁位移/管徑候選、距離門、wall-filter sweep與Doppler有效性判定。
- 多組ICA記錄能看到約70–80 bpm的周期候選，但部分周期同時出現在全深度共同增益或探頭運動控制中。
- 增加獨立控制：TX振幅、事件對齊漂移、共同gain、壁profile correlation、線性化位移與深度局部化。

### 2.4 最新30 V/0 V單極性資料

三個BIN均為：

- 2通道RG01；
- 10 MSPS；
- 每通道112,400,000點；
- 約11.24秒；
- 約112,399個PRF事件；
- PRF約10 kHz；
- 實測載波約2.024–2.025 MHz；
- 約27%的事件需要±1個sample細對齊。

這批資料證明提高CH1顯示/接收係數確實能增加可見細節，但同時更清楚地暴露了長振鈴、削頂和量化限制。

## 3. 最新血管壁與脈搏結果

| 記錄 | 穩定段 | 前壁 | 後壁 | 靜態管徑 | 脈搏判讀 |
|---|---:|---:|---:|---:|---|
| RigolDS0 | 2.25–7.25 s | 13.398 mm | 18.018 mm | 4.620 mm | 13-mm附近有約69–75 bpm成分，但局部化/一致性不足，拒絕 |
| RigolDS1 | 1.05–6.05 s | 13.013 mm | 18.018 mm | 5.005 mm | 最佳候選，71.6–71.9 bpm |
| RigolDS2 | 4.65–9.65 s | 13.629 mm | 18.172 mm | 4.543 mm | 約77–80 bpm，但與共同gain/運動高度相關 |

`RigolDS1`的原壁間距p05–p95變化約71 um，可作儀器診斷量級；不能直接解釋成臨床血管擴張。`RigolDS2`曾得到約0.588 mm的表觀變化，幅度明顯過大且控制相關性高，已判定不可靠。

## 4. 真管腔距離門與血流結果

距離門重新限定在前後壁中點±0.5 mm，避免選到前壁強反射。掃描2、2.5、3、4-cycle接收門和50/100-Hz wall filter後：

| 記錄 | 管腔中心 | 最佳中心門 | Wall filter | SNR | 方向性 | 判定 |
|---|---:|---:|---:|---:|---:|---|
| RigolDS0 | 15.708 mm | 15.25 mm、1.54 mm | 50 Hz | 1.24 dB | -0.075 | Reject |
| RigolDS1 | 15.516 mm | 15.25 mm、0.77 mm | 50 Hz | -0.86 dB | -0.194 | Reject |
| RigolDS2 | 15.901 mm | 15.50 mm、1.54 mm | 50 Hz | 2.45 dB | -0.156 | Reject |

三組在真管腔中心均沒有同時達到：

```text
SNR >= 3 dB
abs(directionality) >= 0.15
```

RigolDS2在14.0 mm可得到約3.30 dB，但該位置靠近前壁，不在管腔中心。原來14.75-mm門的3.04 dB也未通過frame directionality；不能以此計算PSV/EDV。

相位穩定、參考回歸、SVD/低秩抑制、不同wall filter與split-half驗證沒有把三組資料提升成有效方向性血流。

## 5. 為什麼能看見跳動卻看不到血流速度

### 5.1 兩類訊號不同

- 血管壁和探頭運動是強散射、低頻、可在RF包絡/M-mode中看到。
- 紅細胞散射比壁回波弱很多，必須在正確管腔門內形成穩定、單向、隨周期變化的Doppler包絡。
- 因此「示波器上看到跳動」不等於已取得方向性血流。

### 5.2 有效位深有限

最新BIN的CH1抽樣只出現256個電平，等效8 bit。16–24 us血管窗口內只有：

- RigolDS0：57個有效電平；
- RigolDS1：56個有效電平；
- RigolDS2：70個有效電平。

提高垂直增益不能增加BIN的碼寬，只會在不削頂時改善有效碼利用率。

### 5.3 早期削頂

CH1接收軌約為-0.821 V和+1.229 V。發射後早期窗口中：

- 負軌碼約佔5.6–5.8%；
- 正軌碼約佔0.87–0.88%。

因此目前不能再提高CH1全時段增益。需要降低發射後過載、使用TGC或改善T/R恢復。

### 5.4 振鈴正好落入血管窗

16–24 us的相干中位振鈴RMS與PRF間變動RMS為：

| 記錄 | 相干RMS | PRF變動RMS | 比值 |
|---|---:|---:|---:|
| RigolDS0 | 47.1 mV | 30.1 mV | 1.56 |
| RigolDS1 | 46.2 mV | 31.3 mV | 1.48 |
| RigolDS2 | 74.3 mV | 34.6 mV | 2.15 |

RigolDS2到30–40 us仍有約30.4 mV相干振鈴。這些固定相位成分經I/Q和STFT後形成零速附近的水平對稱條紋。

### 5.5 單極性發射過衝

名義30 V/0 V的CH2量測節點實際約有：

- 正峰值約+42.5 V；
- 負過衝約-21 V。

因此下一輪優先比較對稱雙極性、較低電壓和主動阻尼/放電；不以更高接收增益掩蓋振鈴。

## 6. 已排除的主要誤區

| 假設 | 現在的判斷 |
|---|---|
| 10-kHz PRF不夠 | 不是主要限制；2 MHz時軸向Nyquist約1.925 m/s |
| 2 MHz紅細胞散射必然不夠，必須4 MHz | 尚無證據；4 MHz提高散射同時增加衰減，應由仿體SNR決定 |
| Wall filter越高越容易看到血流 | 錯；過高會切掉舒張期和慢流，只能在距離門後比較50/100 Hz |
| 將不同PRF的RF直接相減就等於血流 | 錯；差分也包含trigger jitter、探頭/組織運動與ring-down變化 |
| 選擇SNR最高深度就能算速度 | 錯；最高點可能在前壁，必須限制在解剖管腔中心 |
| 關掉8個AFE通道能讓TSW錄兩倍時間 | TI已否定；所有16通道仍進DDR |
| HSDC GUI只顯示一小段表示沒有錄滿 | 錯；Analysis Window與完整capture/export是兩個長度 |

## 7. AFE58JD48/TSW14J50進展

### 7.1 通道複製故障

2026-07-25的16個唯一碼測試曾出現固定duplicate pairs和4個缺失converter。TI在2026-08-03提供修正的No-Demod CFG與INI。後續`Test00804.bin`不再出現歷史bit-exact duplicate signature，但正式16/16 acceptance仍要求在修正profile下重做16個不同constant code測試。

### 7.2 Demod Import

60-MSPS、Dec=4、DownConv配置已證明：

- HSDC transport BIN能捕獲；
- BIN大小與transport columns一致；
- AFE Demod同步字到達TSW/HSDC；
- 失敗位於AFE GUI separator/版本相容或packing識別，不是「完全沒有資料」。

目前HSDC 5.31 + AFE GUI 2.0.0.1不能產生有效`Demod Separated Data.csv`，所以高Decimation必須用TI成套驗證檔案和明確I/Q格式。

### 7.3 TI 2026-08-19前的最新回覆

TI正在驗證滿足本項目的AFE CFG和HSDC INI。支援工程師同時確認：

- `33,554,432`樣點的capture可由FPGA保存；
- 不一定全部顯示於GUI；
- 可由GUI導出完整資料；
- 不能只選8通道寫DDR，16通道都會被DDR接收。

公開倉庫只記錄以上去識別化技術結論，不保存私人郵件地址、原始附件或私有寄存器內容。

## 8. 8.5秒容量重新核算

TSW14J50公開規格為4-Gbit DDR3，即512 MiB，最多256M個16-bit words。HSDC Pro的Capture Option使用`samples per channel`，而Analysis Window可以比完整捕獲短。

基於目前Dec=4捕獲的4個60-MSPS transport columns：

```text
Dec=4 word rate = 4 * 60M = 240M word/s
Dec=32相對Dec=4再降低8倍
Dec=32 word rate ~= 30M word/s = 60 MB/s
duration = 256M word / 30M word/s = 8.95 s
```

所以`8.5 s`仍是合理保守目標；只是原因不再是「只保存8個AFE通道」，而是TI驗證的DDC/Decimation/compression transport降低了總word rate。`33,554,432`的每logical-channel定義和最終column數仍需TI在交付INI時確認。

## 9. 下一步嚴格順序

1. **等待TI成套檔案**：不手改現有20x/40x Demod INI。
2. **附件歸檔和雜湊**：保存CFG、INI、firmware名稱、版本與SHA-256，不提交私有內容。
3. **16個唯一碼Gate**：先65,536 samples，不接高壓。
4. **2-MHz NCO已知tone Gate**：1.95/2.00/2.05 MHz確認I/Q與正負頻率。
5. **Dec=16 Gate**：驗證channel map、I/Q、sample rate、FIR delay和完整導出。
6. **Dec=32 Gate**：重複全部數字驗收，不因Dec=16通過而省略。
7. **捕獲深度Gate**：依次1M、8M、33.55M samples/channel，核對bytes、rows和秒數。
8. **已知深度反射體**：校正Dec=32 group delay與depth zero。
9. **零流/正流/反流仿體**：驗證方向性、速度比例和零流noise floor。
10. **8.5秒多周期仿體記錄**：中心range gate、50/100-Hz wall-filter對照，通過有效性Gate後才計算PSV/EDV。
11. **30秒以上需求**：轉入FPGA range-gated slow-time I/Q，不再增加HSDC完整transport capture。

完整逐步操作見[Dec=32長時PW Doppler SOP](24_AFE58JD48_TSW14J50_DEC32_LONG_PW_DOPPLER_SOP_2026-08-19.md)。

## 10. 交接給下一位操作者的停止條件

任何一項出現時立即停止並返回上一Gate：

- TX pattern、CW或高壓狀態讀回不符合預期；
- FPGA firmware version為`0.0`；
- JESD link/DDR狀態異常；
- 16個唯一碼有duplicate、missing或不穩定；
- I/Q正負tone方向不一致；
- 完整capture的中間或尾部有重複/缺失；
- AFE、示波器或ADC發生削頂；
- 距離門不在前後壁之間；
- 流向反轉但頻譜符號不反轉；
- SNR/方向性未過門檻卻準備輸出PSV/EDV。

## 11. 本機分析產物與資料政策

本機workspace已生成但不提交Git的主要產物包括：

```text
analysis_0818_30V0V_RigolDS0/
analysis_0818_30V0V_RigolDS1/
analysis_0818_30V0V_RigolDS2/
analysis_0818_30V0V_*_pulse_audit/
analysis_0818_30V0V_*_gate_sweep/
analysis_0818_30V0V_combined/
analysis_0818_30V0V_audit/
analysis_0818_30V0V_report/
```

相關本機分析腳本包括：

```text
analyze_carotid_wall_flow.py
audit_0818_pulse_wave.py
sweep_ds2_range_gate.py
enhance_ica_doppler.py
audit_30v_unipolar_scope.py
estimate_30v_conditional_psv.py
```

原始BIN、分析圖片、NPZ、私人郵件、TI附件和本機絕對路徑均不提交公開GitHub。若後續要遷移分析程式，應先加入合成fixture、移除本機預設路徑並補單元測試。

## 12. 決策記錄

| 問題 | 決策 |
|---|---|
| 是否已提取脈搏 | RigolDS1有最可信約72-bpm候選；其餘需保留低可信標記 |
| 是否已恢復方向性血流 | 沒有；中心門有效性Gate未通過 |
| 是否報告PSV/EDV | 正式值不報；條件式峰值約79 cm/s只作低可信診斷 |
| 是否提高CH1增益 | 暫不；先消除早期削頂和16–24-us振鈴 |
| 是否改4 MHz | 不作首要動作；先以2 MHz完成仿體方向性Gate |
| 是否提高PRF | 暫不；10 kHz已足夠，目前不是alias限制 |
| 是否用PRF差分直接算血流 | 否，只作運動/變化輔助圖 |
| 是否可以只存8個AFE通道 | 否，TI確認DDR接收16通道 |
| Dec=32是否仍可能錄8.5秒 | 是，理論約8.95秒，但須TI profile與實測確認 |
| 何時轉自訂FPGA | 有效有限block通過後，若需要30秒以上再做range-gated slow-time I/Q |

## 13. 公開參考

- [AFE58JD48產品頁與datasheet](https://www.ti.com/product/AFE58JD48)
- [TSW14J50 User's Guide](https://www.ti.com/lit/ug/slau576a/slau576a.pdf)
- [HSDC Pro User's Guide](https://www.ti.com/lit/ug/slwu087e/slwu087e.pdf)
- [TI通道複製修復包交接](20_TI_AFE58JD48_CHANNEL_COPY_FIX_2026-08-03.md)
- [AFE Demod Import與長時Doppler交接](22_HANDOFF_2026-08-07_AFE_DEMOD_IMPORT_AND_LONG_DOPPLER.md)
