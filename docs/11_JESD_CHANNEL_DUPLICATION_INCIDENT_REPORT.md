# AFE58JD48 / TSW14J50 JESD 通道複製故障報告

更新日期：2026-07-25
狀態：**未修復；已完成三組數位 transport 隔離測試，等待 TI 更新的 HSDC/TSW14J50 profile 或固件**

## 1. 結論摘要

目前 16 個 HSDC 欄位不是 16 條獨立的 AFE converter 資料。三種互相獨立的 JESD 配置均得到完全相同的結果：

- bit-exact 重複組：`[3,5]`、`[4,6]`、`[9,15]`、`[10,16]`；
- 16 個欄位只包含 12 個不同的固定測試碼；
- AFE CH3、CH4、CH15、CH16 消失，分別被 CH5、CH6、CH9、CH10 取代；
- 每欄在 65,536 samples 內 100% 穩定；
- 三份 raw BIN 的 SHA-256 完全相同。

因此，這不是聲學串擾、探頭、FPC、TX7316、T/R switch、AFE 增益或凝膠模型造成的。現有證據也排除了「只要改 Subclass」和「只要把 HSDC `JESD IP Core_M` 從 5 改成 16」這兩個單一原因。

最可能的根因是目前 HSDC Pro 5.31 / TSW14J50RX 所使用的 AFE58JD48 JESD 去幀 profile 或 FPGA 固件表存在 converter-to-output-column 配置錯誤。TI E2E 已有一個與本機**完全相同通道映射**的公開案例，TI 工程師回覆其中一個 TSW14J50 firmware INI 有 bug，需向 TI ultrasound RX support 索取更新文件。

在拿到並驗證 TI 更新文件前，`drop-later` 只能避免重複計權，不能恢復遺失的四條物理通道，也不能支撐可靠的 8/16 通道 DAS 成像。

## 2. 系統與隔離測試方法

測試鏈：

```text
AFE58JD48EVM internal per-channel constant codes
    -> JESD204B, aggregate 8 lanes
    -> TSW14J50RX firmware/deformatter
    -> HSDC Pro raw 16-column BIN
    -> automation/jesd_transport_qa.py
```

測試時關閉 TX7316 高壓、CW 與 `TX_BF_MODE`，不使用探頭或聲學回波。AFE 16 個 converter 寫入互不相同的固定數位碼，再抓取 `65,536 samples/channel`、16-bit、16-column raw BIN。

這個方法刻意繞過：

- 壓電陣元、FPC、J5/J7 線束與焊點；
- TX7316 發射與 T/R switch；
- AFE 類比輸入、LNA、VCAT、PGA、LPF；
- 凝膠、PDMS、反射面與電磁/聲學串擾。

所以只要數位固定碼仍被複製，根因必須位於 AFE 數位通道配置、JESD transport、TSW14J50 去幀或 HSDC 欄位輸出之中。

## 3. 三組實驗矩陣

| Gate | AFE | HSDC / TSW profile | 主要差異 | 結果 |
|---|---|---|---|---|
| S1/K8 custom | Subclass 1，K=8；兩 die 讀回 `Reg31=02C0, Reg34=0907, Reg35=03C0, Reg36=0007` | repository `M16_FIXED`，L/M/F/S/N/K=`8/16/4/1/16/8` | 自製 M=16 | FAIL，同四組複製 |
| S2/K8 custom | Subclass 2，K=8；兩 die 讀回 `02C0,1107,03C0,0007` | repository `M16_S2_K8_EXPERIMENTAL` | 兩端同改 Subclass 2 | FAIL，同四組複製 |
| TI installed original | Subclass 1，K=8 | TI 安裝包原始 40x/no-demod/S1 profile，`JESD IP Core_M=5` | 未使用 repository M16 設定 | FAIL，同四組複製 |

三份 BIN 的 SHA-256：

```text
141E592D1631CDC19D42680BE18477E1EB12A6E84627D3F3DC3B2ACF60EBCED3
```

三次輸出的**整份檔案完全相同**，不只是統計相似。

去識別化彙總位於 [`diagnostics/jesd_unique_code_test_summary_20260725.json`](../diagnostics/jesd_unique_code_test_summary_20260725.json)。raw BIN、完整本機路徑和採集資料不提交 Git。

## 4. 實測 converter 映射

| HSDC slot | 實際 AFE code/channel | 判定 |
|---:|---:|---|
| 1 | CH1 | 正常 |
| 2 | CH2 | 正常 |
| 3 | CH5 | **應為 CH3，錯誤複製 CH5** |
| 4 | CH6 | **應為 CH4，錯誤複製 CH6** |
| 5 | CH5 | 正常來源，但與 slot 3 重複 |
| 6 | CH6 | 正常來源，但與 slot 4 重複 |
| 7 | CH7 | 正常 |
| 8 | CH8 | 正常 |
| 9 | CH9 | 正常來源，但與 slot 15 重複 |
| 10 | CH10 | 正常來源，但與 slot 16 重複 |
| 11 | CH11 | 正常 |
| 12 | CH12 | 正常 |
| 13 | CH13 | 正常 |
| 14 | CH14 | 正常 |
| 15 | CH9 | **應為 CH15，錯誤複製 CH9** |
| 16 | CH10 | **應為 CH16，錯誤複製 CH10** |

這是一個「四條 converter 被確定性替換」的模式，不是簡單 lane permutation。若只是 lane mapping 次序錯誤，16 個唯一碼仍應各出現一次，只是欄位順序不同。

## 5. 已排除與尚未排除的原因

### 已由實驗排除

1. **探頭/FPC/焊點/TX/RX 類比鏈**：固定碼在 ADC 數位端產生，故障仍存在。
2. **聲學或電磁串擾**：無聲學輸入；多 MB 欄位 bit-for-bit 相同不符合普通串擾。
3. **單純 Subclass 1/2 不匹配**：S1/K8 與匹配的 S2/K8 結果完全相同。
4. **repository M16 profile 是唯一根因**：TI 安裝包原始 `M=5` profile 也得到相同 BIN。
5. **隨機 JESD lane signal-integrity bit error**：16 欄在 65,536 rows 內各自 100% 穩定，capture/JESD link 可正常完成；沒有隨機錯碼特徵。
6. **軟件重建讀錯前 8 欄**：重建器已改為從 manifest 讀 `rx_hsdc_slots_1_based`；這不影響固定碼 transport FAIL 的結論。

### 仍需驗證，按可能性排序

1. **TSW14J50RX firmware INI / HSDC JESD 去幀表 bug**：最高可能，且有 TI 公開同症狀案例。
2. **HSDC 私有欄位的枚舉語義**：`JESD IP Core_M=5` 可能不是 literal M；`Channel Pattern`、`Group128` 或 converter lookup 可能共同決定 16 欄解包。
3. **AFE 兩 die 的 converter/lane mapping 與 TSW profile 不完全一致**：需拿 TI 更新文件逐項比較，而不是繼續猜 INI。
4. **TSW14J50 固件版本過舊或 profile 與固件 build 不匹配**。
5. **AFE–TSW transition/FMC 或實體 JESD lane 問題**：目前機率較低；只有使用 TI 修復 profile 後仍失敗，才進入交換板卡、量測 lane 或檢查 FMC 的硬體 Gate。

## 6. 與 TI 公開案例的吻合

TI E2E 案例：

- [AFE58JD48EVM: AFE58JD48 channel mapping issue with JESD204B interface](https://e2e.ti.com/support/data-converters-group/data-converters/f/data-converters-forum/1567281/afe58jd48evm-afe58jd48-channel-mapping-issue-with-jesd204b-interface)

公開案例列出的現象正是：

```text
CH3=CH5 -> INP5
CH4=CH6 -> INP6
CH9=CH15 -> INP9
CH10=CH16 -> INP10
```

TI 工程師在該 thread 表示 TSW14J50 firmware INI 中存在 bug，並要求聯絡 `ultrasound_rx-support@list.ti.com` 取得更新文件。這使「特定已知 profile/firmware bug」成為目前最有證據的根因，而不是一般性的 JESD lane 對齊猜測。

相關官方資料：

- [AFE58JD48 product page](https://www.ti.com/product/AFE58JD48)：16-channel AFE、兩組 8-channel ADC，支援 JESD204B subclasses 0/1/2。
- [TSW14J50EVM User's Guide](https://www.ti.com/lit/ug/slau576a/slau576a.pdf)：HSDC 所選 ADC INI 會配置 FPGA JESD lane/converter/F/K 等參數；因此錯誤的 INI/去幀表能在 link 仍可工作的情況下造成穩定欄位錯配。

## 7. 下一步閉環，不再盲試

### Gate A：取得 TI 更新文件

向 TI 提交本報告、三組 profile 名稱、TSW14J50 firmware 名稱/版本、HSDC Pro 5.31，以及固定碼映射。索取：

- 修復後的 AFE58JD48 120/125 MSPS、8-lane、no-demod HSDC ADC INI；
- 與該 INI 匹配的 TSW14J50RX firmware build；
- `JESD IP Core_M`、`Channel Pattern` 與 `Group128` 的實際編碼說明；
- 正確的兩 die converter/lane mapping。

不要覆蓋原文件；用新名稱安裝並保存 SHA-256。

### Gate B：修復 profile 的唯一碼驗收

1. 完整冷啟動 AFE、TSW、HSDC；不使用 TX。
2. 讀回兩 die 的 PLL/Subclass/K/L/M。
3. 再抓 65,536×16 固定碼 BIN。
4. 執行：

   ```powershell
   python automation/jesd_transport_qa.py "C:\path\fixed_profile_unique_codes.bin"
   ```

5. 必須同時滿足：

   - duplicate groups 為空；
   - `distinct_modal_code_count = 16`；
   - 16 欄全部 stable；
   - 16 個預期 AFE code 各出現一次；
   - mapping 可唯一恢復。

### Gate C：只有 TI 修復 profile 仍失敗才查硬體

按一次只改一項的順序：converter/channel pattern → lane mapping → Group128/deformatter → 另一 TSW14J50/FMC transition → 實體 JESD lane。每一步都重跑唯一碼 Gate；不要用聲學圖像作 transport 驗收。

## 8. 對成像的直接影響

現有資料最多只有 12/16 數位自由度；目前實際使用 HSDC 9–16 時，`9=15`、`10=16`，所以最多 6/8 條不同資料。DAS 把複製欄當作新陣元會錯誤加權；把後出現的複製欄丟掉只剩六陣元，橫向孔徑和解析度都下降。

因此在 transport Gate 通過前：

- 不把 2D 圖的模糊歸因於成像算法；
- 不以 MVDR、DMAS 或「超分辨率」補救缺失 converter；
- 不宣稱已完成 8/16 通道成像；
- 可以保留六通道資料作界面深度與流程驗證，但必須標註為降級模式。

## 9. 回滾與資料政策

- 所有實驗 profile 均用新名稱，不覆蓋 TI 原始文件。
- 恢復類比前載入 `configs/afe58jd48/ADC_ANALOG_RESTORE.cfg`，確認每通道 Reg29 回到 0。
- raw BIN、capture folder、截圖及含本機使用者路徑的完整 JSON 不提交 Git。
- Git 只保存程式、配置、去識別化統計、雜湊與操作記錄。
