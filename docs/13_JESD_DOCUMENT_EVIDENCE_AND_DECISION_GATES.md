# JESD 文件證據、適用邊界與下一步 Gate

更新日期：2026-07-25

狀態：**文件審查完成；根因已縮小，但本地 PDF 不包含可直接修復 TSW14J50RX 去幀表的私有 INI/firmware**

## 1. 這批資料有沒有直接解決問題？

沒有直接提供一個已驗證的修復文件，但解決了三個關鍵判斷問題：

1. AFE58JD48 的 120 MSPS、8-lane、PLL40x/no-demod 使用 Subclass 1 是官方 EVM 流程之一；「只能用 Subclass 2」不是成立的根因假設。
2. AFE 是兩顆 8-channel link/die。實測每顆的 readback 是 L4/M8，HSDC 系統層才是 aggregate L8/M16；不能把 HSDC aggregate 值原樣寫回每顆 AFE。
3. TI JESD reference RTL 在 JESD core 後還有一層 lane/converter decoder。link 能建立、資料能穩定輸出，不代表 converter-to-column 解包正確。

三個 profile 仍產生逐位相同的完整 BIN，說明 Subclass 和自製 `M=16` 欄位都沒有改變實際交付到 HSDC 的 converter lookup。最需要的仍是 TI 修復後且彼此匹配的 AFE58JD48 HSDC INI 與 TSW14J50RX firmware。

## 2. PDF 與本地資料的有效性

| 資料 | 可回答的問題 | 不能直接回答的問題 |
|---|---|---|
| `AFE58JD48EVM_User_Guide__SLOU521_.pdf` | 官方初始化順序、120M/8L/S1 quick-start、trigger 與 JESD link 的分工 | 部分接頭/TSW 截圖針對另一 capture board，不能照抄到 TSW14J50 |
| `sbas881a.pdf` | AFE JESD mode/readback、每顆 8-channel link、數位 test pattern 能力 | 不定義 HSDC 私有 INI 枚舉或 TSW14J50 FPGA 欄位表 |
| `JESD204B_IP_Configuration.pdf` 與 instantiation RTL | JESD core 後的 octet/lane/converter decoder 架構、`lane_mode` 與 active-lane 概念 | 是 Kintex/AFE58J48 參考工程，不是 TSW14J50RX firmware source |
| TX7316 PDF | 高壓、波形、T/R、PRF/SYNCP、觸發安全 | AFE 內部固定數位碼仍複製時，TX 路徑不是原因 |
| `MHR054A_Sch.PDF` | TX7316EVM 板級網名、SYNCP/T/R 與接頭核對 | 不含 AFE–TSW JESD receiver/deformatter |
| Field II guide | 聲場與陣列模擬 | 不處理 JESD converter 解包 |
| `sszz027n.pdf`、`sszz027o.pdf`、`slvt174.pdf` | EVM/HV EVM 條款與高壓安全 | 無去幀診斷參數 |

`sbas881a.pdf` 與 `sbas881a (1).pdf` 的 SHA-256 相同，後者是重複文件，沒有新增證據。

原始資料包含 selective-disclosure/NDA 標記。本倉庫不提交原 PDF、完整抽取文字、圖表、RTL 或私有寄存器序列，只保存使用者實測 readback、公開安全的推導、雜湊與診斷流程。

## 3. 參考 RTL 能告訴我們什麼

本地 reference design 的 example 預設包含：

- `lane_mode=8`；
- 只有兩條 active lane 的 mask；
- 與本機不同的採樣率、PLL/transmit mode、K 與 Subclass 實驗條件。

這些是該 reference bench 的示例，不是本機 profile。對本機 PLL40x、aggregate 8 lanes / 16 converters，任何自製接收 decoder 應按兩 converters/lane 和八條 active lanes 審核。

但這只是架構風險證據，不能據此宣稱 TSW14J50RX 內部一定用了同一段 RTL。HSDC 私有 `JESD IP Core_M`、`Channel Pattern`、`Group128` 和 converter lookup 的實際編碼仍未出現在本地公開/可提交資料中。

## 4. 已完成的封閉實驗

| 實驗 | 只改變的主項 | 結果 |
|---|---|---|
| matched S1/K8 custom | AFE/HSDC 均為 S1/K8 | FAIL，同四組複製 |
| matched S2/K8 custom | 兩端同時改 S2 | FAIL，完整 BIN 與 S1 相同 |
| TI-installed original | 使用 TI 安裝包原 profile，而非自製 literal M16 | FAIL，完整 BIN 再次相同 |

共同 signature：

```text
duplicate groups: [3,5] [4,6] [9,15] [10,16]
missing converters: 3,4,15,16
slot mapping: 1,2,5,6,5,6,7,8,9,10,11,12,13,14,9,10
distinct stable codes: 12/16
BIN SHA-256: 141E592D1631CDC19D42680BE18477E1EB12A6E84627D3F3DC3B2ACF60EBCED3
```

這不是 simple lane permutation；permutation 應保留 16 個唯一碼，只改順序。這裡是四個 converter identity 消失並被其他 converter 確定性取代。

## 5. 下一步最小實驗矩陣

| Gate | 單一變量 | PASS signature | FAIL 後行動 |
|---|---|---|---|
| A | TI 修復後的 HSDC INI + 匹配 TSW firmware 作為一個不可拆組合 | 16/16 唯一碼，無 duplicate | 向 TI 回傳 profile/firmware hash、readback、QA JSON |
| B | vendor 指定的 link/transport test | lanes/transport pattern 無錯 | 若 pattern 已在 HSDC 欄位重複，定位到 receiver/deformatter |
| C | 每次只啟用一個 converter code | 每個 input 只到一個 HSDC slot | 建立具體錯誤 lookup 表交 TI |
| D | known-good TSW/transition/FMC A/B | 換板後 PASS | 若仍同 signature，回到 AFE/profile；若消失，查原板/連接 |
| E | 實體 lane 檢查 | 無隨機 bit/lane loss，ILA/CGS 正常 | 只有 corrected profile 仍 FAIL 才投入高速硬體量測 |

每個 Gate 都必須完整冷啟動，只改一項，保存 profile/firmware/BIN 的 SHA-256。看到完整 BIN hash 沒變，就停止繼續微調該欄位。

## 6. 驗收與成像邊界

Transport PASS 的唯一標準：

- duplicate groups 為空；
- 16 欄全穩定且 16 個 modal code 全不同；
- 每個預期 AFE converter code 恰好出現一次；
- mapping 是 one-to-one。

聲學資料的 effective rank 不是單獨驗收標準，因為平面反射和共模發射串擾本來就可能低 rank。固定數位碼 Gate 通過後，才恢復 analog mode、寫入 manifest mapping、跑 channel QA 與 `--duplicate-policy keep-all` 重建。

## 7. 可重複工具與 skill

- Skill：`skills/afe58jd48-jesd-repair/`
- 單份 BIN QA：`automation/jesd_transport_qa.py`
- 多份報告比較：`skills/afe58jd48-jesd-repair/scripts/compare_transport_qa.py`
- 去識別化證據：`diagnostics/jesd_unique_code_test_summary_20260725.json`
- 完整故障報告：`docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md`
- TI/Opus 求助包：`docs/12_OPUS_HELP_REQUEST_JESD_DEFRAMING.md`
