# 完整電氣連線與通道映射

## 1. 斷電接線原則

所有信號線在 J1/J2/J3、AFE電源和USB都斷開時完成。高壓TX、低壓RX、數字同步和地線不要混用；J7 pin2不是地。

### 主信號鏈

| 來源 | 去向 | 說明 |
|---|---|---|
| TX7316 J7 pins 3–18 | 16個單端陣元的高壓端 | 目前只用A1–A8時，其餘保持斷開 |
| 陣列公共電極 | 探頭/系統模擬回路 | 不接第二個TX輸出 |
| TX7316 J5 pins 3–18 | AFE對應SMA INP1–INP16 | J5為內部T/R switch後的RX輸出 |
| AFE J60 | TSW14J50 J4 | FMC直接對接，JESD與SYSREF走FMC |
| TX7316 AGND測試點 | AFE AGND/同軸屏蔽 | 短、低電感、單點參考 |

### 16路映射

| 系統通道 | J7 TX | J5 RX | AFE SMA |
|---:|---|---|---|
| 1 | pin3 OUT_A1 | pin3 RX_A1 | J6 INP1 |
| 2 | pin5 OUT_A2 | pin5 RX_A2 | J8 INP2 |
| 3 | pin7 OUT_A3 | pin7 RX_A3 | J10 INP3 |
| 4 | pin9 OUT_A4 | pin9 RX_A4 | J12 INP4 |
| 5 | pin4 OUT_A5 | pin4 RX_A5 | J14 INP5 |
| 6 | pin6 OUT_A6 | pin6 RX_A6 | J16 INP6 |
| 7 | pin8 OUT_A7 | pin8 RX_A7 | J19 INP7 |
| 8 | pin10 OUT_A8 | pin10 RX_A8 | J21 INP8 |
| 9 | pin11 OUT_B1 | pin11 RX_B1 | J7 INP9 |
| 10 | pin13 OUT_B2 | pin13 RX_B2 | J9 INP10 |
| 11 | pin15 OUT_B3 | pin15 RX_B3 | J11 INP11 |
| 12 | pin17 OUT_B4 | pin17 RX_B4 | J13 INP12 |
| 13 | pin12 OUT_B5 | pin12 RX_B5 | J15 INP13 |
| 14 | pin14 OUT_B6 | pin14 RX_B6 | J17 INP14 |
| 15 | pin16 OUT_B7 | pin16 RX_B7 | J18 INP15 |
| 16 | pin18 OUT_B8 | pin18 RX_B8 | J20 INP16 |

J5到AFE建議用2×10轉16路SMA接口板和短50 Ω微同軸，不用杜邦線/麵包板。上表是完整16路參考拓撲，不代表目前線束已逐路驗證。當前軟件把8個物理A1–A8映射到HSDC數字槽`9…16`，但此映射保持可配置；在完成「一次只向一個AFE SMA注入已知信號」或示波器逐路排查前，不把重複槽或HSDC槽號視為最終硬件證書。HSDC顯示16個數字槽是正常的，未接槽不等於有效陣元。

## 2. RX終端

某些 Appendix C 改裝會令 J5 每路具有約 `49.9 Ω || 20 pF`；AFE SMA又可能有49.9 Ω與0.1 µF AC耦合。兩端都保留時等效約25 Ω，接收幅度可能下降約6 dB。

- 第一次聯調可保留雙終端，AFE `Active Termination = Disable`。
- 最終接口只保留一組可選50 Ω終端；任何電阻改動均在斷電、確認原理圖與板卡版本後做。
- 不用提高高壓去補償雙終端的幅度損失。

## 3. 5-level 原板模式

如果板卡未做 Appendix C 3-level改裝，按5-level使用：

| 接口 | 電壓 | 初始限流建議 |
|---|---:|---:|
| J3 | `+5 / GND / -5 V` | 每路約200 mA |
| J1 | `+30 / GND / -30 V` | 每路約30 mA |
| J2 | `+100 / GND / -100 V` | 每路約30 mA |

`|J2|`必須高於`|J1|`。固定電源不能在GUI裏“配置電壓”；GUI只配置芯片狀態，實際電壓由外部電源決定。若無法設定低壓低限流，先不接陣元，使用假負載並用保險絲/限流模組完成電氣驗證。

## 4. Appendix C 3-level模式

只有以下斷電檢查全部通過才可不用J2：

- R1、R4安裝0 Ω；
- R22移除、R23安裝0 Ω；
- Appendix C指定的TX/RX短接電阻已移除；
- J7 A/B輸出不再意外短接；
- J5 pins3–18各自約49.9 Ω對地；
- J1與J2之間無短路。

此時用J3 ±5 V、J1 ±30 V、J2斷開並絕緣，GUI選3-level。剛買來的5-level板不能只靠GUI變成這個接法。

## 5. 同步端口

| 端口 | 方向/用途 | 當前成像 |
|---|---|---|
| TX已確認的SYNCP測試點 | 板載CPLD約2.5 V、約1 kHz輸出 | normal可留空；hardware經緩衝送TSW J13 |
| AFE J25 TX_TRG | AFE外部TX同步輸入 | raw Analog Input可留空；TGC/demod需共源同步 |
| TSW J13 Trigger | Capture Start外部輸入，最大3.3 V | hardware模式接SYNCP或主同步源 |
| TSW J7/J8 Sync A/B | 板間同步用途 | 單AFE+單TSW維持現有FMC方案，留空 |

SYNCP不是外部輸入口，不可把20 kHz函數發生器接回去。正式連線使用高輸入阻抗、3.3 V兼容的有源緩衝/扇出並共地；先以斷電導通與板卡原理圖確認所用J7/TP焊盤確實是SYNCP，再用示波器確認幅度、極性與邊沿。不要用被動T形把多塊板直接並聯。
