# PW Doppler 嚴格處理流程與 0819 雙接收資料稽核

> 更新日期：2026-09-20。研究與儀器驗證用途，不作臨床診斷。公開倉庫只保存去識別化、聚合層級的流程與技術摘要，不保存人體原始 RF、逐記錄生理參數、影像、本機路徑、原始檔雜湊或個人資料。

## 1. 結論

本流程已把「PRI 分割是否正確」「管壁／管腔是否定位正確」和「是否存在可定量的方向性血流」拆成獨立 Gate。對 2026-08-19 的四個原始示波器記錄重新處理後：

- CH2 可可靠分割每個 PRI，沒有遺失或重複事件；PRF 約 `9,999.965 Hz`。
- CH2 的實測主載波為 `1.9720–1.9729 MHz`，不是採集筆記中的名義 4 MHz。
- 7 個接收資料流全部未通過嚴格血流 Gate，`PSV/EDV/AT/RI/PI/S-D` 必須保持空值。
- 兩個 CH1 資料流出現約 `41.5 cm/s` 的 45°條件式診斷頻譜統計，但 SNR、方向性、距離門和前後半段重現性均不合格；它們不是 PSV。
- CH3 可看到較穩定的週期性壁運動，但它是未標定的雙站只收通道，不能套用單站 Doppler 速度公式。

合成端到端自檢通過：Kasai 速度誤差 `0.916%`、頻譜 centroid 誤差 `4.575%`、方向符號正確。這說明本批不能恢復定量血流的主要原因是資料品質與距離門證據不足，而不是基本速度比例或符號錯誤。

## 2. 通道角色與輸入要求

| 通道 | 角色 | 可用方式 |
|---|---|---|
| CH1 | T/R 後單站回波 | 管壁候選、固定管腔門、標準單站 PW Doppler |
| CH2 | 發射參考 | PRI 事件、亞採樣時間校正、逐脈衝載波相位校正 |
| CH3 | 另一個只收探頭 | 雙站等效延遲／壁運動；幾何標定前不得報單站速度 |

每次分析必須保存或記錄：

- 原始檔 SHA-256、通道數、每通道點數、採樣間隔與量程；
- 實測 PRF、實測載波、聲速、發射／接收幾何和假設角度；
- T/R recovery、電聲 `t0`、wall-filter、距離門與 STFT 參數；
- 遺失 PRI、ADC 削頂、有效量化階、控制門和所有拒絕原因。

修改版、合成版和原始量測必須分開列清單；合成資料不得混入人體量測結論。

## 3. 完整處理 Pipeline

```mermaid
flowchart LR
    A[CH1/CH2 raw RF] --> B[CH2 event detection<br/>PRI indexing]
    B --> C[integer + fractional timing<br/>and TX phase correction]
    C --> D[measured-fc band-pass<br/>matched projection + complex DDC]
    D --> E[aligned RF/IQ matrix]
    E --> F[RF envelope M-mode]
    F --> G[near/far wall candidates<br/>tracking and wall-pair QC]
    G --> H[fixed lumen-centre range gate]
    H --> I[slow-time complex IQ]
    I --> J[50/100/150 Hz<br/>clutter/wall-filter sweep]
    J --> K[signed 3-DPSS STFT<br/>+ lag-one Kasai]
    K --> L[spatial/directional/<br/>repeatability QC]
    L -->|PASS and >=3 cycles| M[PSV EDV AT RI PI S-D]
    L -->|FAIL| N[diagnostic spectrum only<br/>no quantitative velocity]
    G --> O[wall separation D(t)<br/>and centre motion C(t)]
    O --> P[cycle markers only]
    P --> M
```

管壁分支和血流分支不能混用：M-mode 壁定位必須保留低頻壁運動；slow-time wall filter 只作用於已選管腔門的複數 IQ。

## 4. CH2 逐 PRI 分割與對齊

### 4.1 事件檢測

以 CH2 的發射 burst 找出每個事件 `s_m`，建立：

\[
T_{PRI}=\operatorname{median}(s_{m+1}-s_m)/F_s,
\qquad PRF=1/T_{PRI}
\]

不能只按理論 100 us 等間距切割；必須保留實際事件索引並統計遺失、重複和反向事件。

### 4.2 亞採樣校正

以 CH2 中位 burst 作模板，在每個整數事件附近搜索最大相關，再用拋物線或 windowed-sinc 求分數樣點位移 `δ_m`。線性插值會把時間漂移轉成假的慢時間幅相變化，應使用至少 9–17 tap 的 Kaiser/Lanczos/sinc 插值。

### 4.3 載波相位參考

由對齊後 CH2 估計逐脈衝相位 `ψ_m`。後續 CH1 複數解調須乘 `exp(-jψ_m)`，避免發射相位漂移被誤判為 Doppler。

本批事件數為約 `39,099–49,899`，遺失與重複 PRI 均為 0；CH2 鄰接相位一致性約 `0.99998`，因此分段不是主要失敗點。

## 5. 實測載波、帶通與複數解調

發射設定值不能直接當處理載波。應分別保存：數字 pattern 頻率、假負載電氣頻率、避開直達／振鈴窗後的聲學響應頻率。

對每個對齊 PRI：

\[
q_m[n]=LPF\left\{r_m^{BP/MF}[n]e^{-j2\pi f_c n/F_s}\right\}e^{-j\psi_m}
\]

其中 `r_m^{BP/MF}` 是帶通及匹配加權後的 RF。匹配模板不能包含長振鈴尾巴，否則會強化而不是抑制振鈴。

本批逐檔實測 `f_c≈1.972 MHz`；以 `PRF≈10 kHz` 計算：

\[
v_{Nyquist,beam}=\frac{c\,PRF}{4f_c}\approx1.95\;m/s
\]

60 cm/s、45°血流並不接近 Nyquist，因此混疊不是主要瓶頸。

## 6. M-mode、近／遠壁與固定管腔門

由複數 envelope 建立：

\[
M[m,n]=20\log_{10}(|q_m[n]|+\epsilon)
\]

候選壁對必須同時滿足：

1. 合理的壁間距，且管腔內相對低回聲；
2. 主頻帶和敏感頻帶中的位置一致；
3. 近壁和遠壁均可連續追蹤，且 NCC 不在搜索邊界失效；
4. 管腔中央沒有比弱壁更強的第三條持續反射；
5. 管徑變化具有合理週期，且不同帶寬與窗口下不崩潰；
6. 未標定電聲 `t0` 時只稱「等效深度」，不稱絕對解剖深度。

定義：

\[
D(m)=d_f(m)-d_n(m),\qquad
C(m)=\frac{d_f(m)+d_n(m)}{2}
\]

`D(m)` 是壁間距／管徑變化候選，`C(m)` 是血管與探頭的共同運動。`D(m)` 不能直接稱為血液對血管的力，也不能直接代替速度波形。

只有壁對 Gate 通過後，才在：

\[
d_c=\operatorname{median}_m\frac{d_n(m)+d_f(m)}{2}
\]

建立固定距離門。門邊緣須避開兩側壁、匹配濾波主瓣、旁瓣與剩餘振鈴；同時分析中心 `±0.25 mm` 和兩個管腔外控制門。主分析使用固定門，跟隨壁移動的門只作敏感度檢查，避免插值製造假相位。

## 7. Slow-time IQ、wall filter、signed 頻譜與 Kasai

固定深度門的慢時間 IQ：

\[
z_m(d)=e^{-j\psi_m}\sum_n w[n]r_m[d+n]
e^{-j2\pi f_c n/F_s}
\]

若門包含多個深度，優先在各深度分別算頻譜後加功率，避免不同深度的複數相位抵消。

### 7.1 Wall filter

本批比較 50、100、150 Hz 複數 slow-time 高通。只接受 cutoff 改變後主方向、局部化和速度包絡仍穩定的結果。過高 cutoff 會削弱舒張期低速流，使 EDV 偏低、RI/PI/S-D 偏高。

### 7.2 Signed DPSS-STFT

對複數 IQ 做有符號頻譜：

\[
S(t_k,f)=\frac1K\sum_{l=1}^{K}
\left|\sum_m v_l[m-t_k]\tilde z_m e^{-j2\pi fm/PRF}\right|^2
\]

本批使用 `NW=2.5`、`K=3`、512 PRI window、128 PRI hop、2048-point FFT。頻譜必須出現單側、隨心動週期開合的 systolic envelope；跨時間固定的水平窄線和正負對稱能量不能稱為血流。

方向性：

\[
\eta_{dir}=\frac{|P_+-P_-|}{P_++P_-}
\]

### 7.3 Lag-one Kasai

\[
f_D=\frac{PRF}{2\pi}\arg\left(\sum_m z_mz_{m-1}^{*}\right)
\]

\[
v_{beam}=\frac{c f_D}{2f_c},\qquad
v=\frac{v_{beam}}{\cos\theta}
\]

Kasai 用於平均速度、方向和相干性 QC；PSV/EDV 必須取自通過噪聲與方向門檻的頻譜包絡。

雙站 CH3 應使用：

\[
f_D=\frac{f_c}{c}(\hat k_{TX}+\hat k_{RX})\cdot\mathbf v
\]

在 TX/RX 有向幾何未標定前，不得把 CH3 的 `c·t/2` 當絕對深度，也不得用 `cf_D/(2f_c cos45°)` 報速度。

## 8. 四類窗口不能混淆

| 窗口 | 軸 | 作用 |
|---|---|---|
| PRI frame | fast time | 保存一次發射後完整接收區間 |
| 壁搜尋 ROI | fast-time depth | 尋找近／遠壁候選 |
| Flow range gate | fast-time depth | 每個 PRI 提取一個或一組複數 IQ |
| STFT ensemble | slow time | 形成隨時間變化的 Doppler 頻譜 |

## 9. 嚴格 QC／拒絕條件

只有全部通過才能輸出定量速度：

- CH1/CH2 無削頂，管腔門至少約 32 個有效 ADC levels；
- CH2 事件模板與相位參考可靠，沒有遺失／重複 PRI；
- 候選距離門不被 T/R recovery 或固定振鈴覆蓋；
- 近／遠壁跨頻帶穩定，追蹤相關合格，中央無競爭反射；
- flow SNR `>=3 dB`；
- `abs(directionality)>=0.15`，且有效 STFT frames 不為 0；
- 管腔中心功率至少比管腔外控制門高約 3 dB；
- Kasai 相干性至少約 0.10，並和 STFT 方向一致；
- 不是跨深度／跨時間固定的窄線，Nyquist 邊緣沒有混疊證據；
- 50/100/150 Hz wall-filter sweep、中心 `±0.25 mm` 和前／後半段的方向及主要包絡可重現；
- 至少 3 個由可靠壁搏動、PPG 或 ECG 切分的合格心動週期；
- 入射角及單站／雙站幾何足以支持所報速度。

任一項失敗時，只保存診斷頻譜與拒絕原因；PSV/EDV 等欄位保持空值。

## 10. 心動週期血流指標

只有嚴格血流 Gate 通過後才計算：

\[
PSV=\max v_{env}(t),\qquad
EDV=\operatorname{median}(\text{下一收縮足點前的末期舒張包絡})
\]

\[
AT=t_{first\ systolic\ peak}-t_{systolic\ foot}
\]

\[
RI=\frac{PSV-EDV}{PSV},\quad
PI=\frac{PSV-EDV}{TAMV},\quad
S/D=\frac{PSV}{EDV}
\]

每個週期獨立計算，最終報 3–5 個合格週期的 median、MAD 或 IQR。壁搏動只用作週期邊界，壁位移峰不能代替 PSV。

## 11. 0819 去識別化聚合稽核結果

公開摘要不保留逐檔壁深、心率或候選速度，只保存判斷演算法是否成功所需的聚合工程指標：

| 指標 | 聚合結果 |
|---|---|
| 原始量測記錄 | 4 |
| 接收資料流 | 7（4個單站CH1；3個雙站CH3） |
| 採樣率 | 約25 MSPS |
| PRF | 約9,999.965 Hz |
| 實測主載波 | 1.9720–1.9729 MHz |
| 遺失／重複PRI | 0 / 0 |
| 可用固定壁對／管腔門 | 0 / 7 |
| 具形態支持的等效壁搏動候選 | 1 / 7；不等於血流通過 |
| Flow SNR | 全部低於0 dB；約 -21.7 至 -3.6 dB |
| signed方向性 | 約 -0.034 至 0；未達0.15門檻 |
| 有效STFT frames | 全部0% |
| 嚴格定量血流通過 | 0 / 7 |

兩個 CH1 流的被拒絕頻譜在相同速度區附近產生約 `41.5 cm/s` 的條件式 q95 統計；因兩者數值幾乎相同、缺少方向性與心動調制，且所有有效 frame 均為 0，它更符合固定線／噪底統計而不是生理 PSV。該值只用來記錄拒絕模式，不是個體血流結果。

共同失敗原因：

1. 約 6.5–6.6 us 的固定強峰在多個 CH1 記錄重現，應視為直達／振鈴而不是血管壁；
2. 沒有任何候選壁對完整通過跨頻帶、追蹤和中央第三反射 Gate；
3. 多個 CH1 管腔窗只有約 10–17 個活躍量化階；
4. 全部中心門 SNR 低於 0 dB，signed spectra 主要是零速強線、對稱寬帶噪聲或固定水平線；
5. 50/100/150 Hz、距離門擾動和 split-half 結果不穩定；
6. CH3 未完成雙站幾何標定。

因此本批可以保存 PRF、實測載波、事件完整性、拒絕模式及聚合 QC，但不能報血流 PSV/EDV/AT/RI/PI/S-D。

## 12. 下一次採集的最小閉環

1. 用無目標水槽與已知深度平面反射體標定電聲 `t0`、固定系統峰和 T/R recovery 結束時間。
2. 調整類比增益／量程，使管腔窗至少使用約 32 個 ADC levels，同時無削頂。
3. 用 B-mode 或已知解剖位置確認近壁／遠壁，固定 1.5–2 mm 中央 sample volume。
4. 固定探頭壓力和角度；CH3 使用前先量測 TX/RX 探頭位置、交會深度與有向角度。
5. 在零流、正流和反流仿體依次驗證噪聲底、符號、速度比例和角度校正。
6. 只有當單向頻譜包絡隨心動週期重現，且通過控制門、filter sweep、gate sweep 和 split-half Gate，才輸出 PSV/EDV。
