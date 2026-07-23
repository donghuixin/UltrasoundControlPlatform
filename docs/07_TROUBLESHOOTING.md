# 故障排查與驗收

## TX7316 `Error 4 / FT_IO_ERROR`

原因通常是USB/FTDI handle失效、被另一TI GUI占用或斷電後GUI仍顯示假CONNECTED。停止高壓，關閉腳本和GUI，拔TX USB與J3等10秒，只接TX重啟；不要點Continue繼續未知狀態。

## HSDC `Read DDR timed out`

依序檢查：

1. TSW FPGA不是reset；
2. AFE→TSW sample clock存在；
3. JESD sync建立，D3/D4符合EVM指南；
4. HSDC profile與AFE L/M/F/K/Subclass一致；
5. Hardware模式下J13確實有合格邊沿；
6. 重新按AFE `DUT RESET → INITIALIZE LMK → AFE RESET → INITIALIZE AFE`，再重選profile。

## TX_BF開關看不出差異

不要只看整段4096點的縮放圖。比較同一通道、同一增益、相同trigger下：

- 1 kHz週期性事件（約120,000 samples間隔）；
- 1 MHz帶通後RMS與頻譜；
- BF ON/OFF的差值與固定深度事件；
- TX電源電流。

若完全相同，確認LOAD_PROF已自清零、Reg24 bit0真正變化、Pattern已寫入、CPLD硬件reset已啟動、捕獲不是舊DDR。

## 頻率顯示1.5 MHz而不是1 MHz

可能是換能器/匹配的聲學峰值、Pattern仍為舊值、採集主要是振鈴/噪聲，或分析窗選到別的事件。用同一pilot比較TX OFF/ON，核對TX preset寄存器，再從已對齊的主回波窗計算頻譜。UI/HSDC文字欄本身不能改TX頻率。

## 多個RX channel完全重複

HSDC顯示16槽不代表16個物理RX。逐路只注入一個已知信號，建立映射；檢查FMC、JESD lane mapping、ADC profile與J5→SMA線束。完全相同的通道在重建前去重並標記，不能當作額外孔徑。

## 圖像看不到管道/腫瘤

先不用全角度。做0°A-scan：

1. 找到耦合面與已知底面；
2. 用已知厚度校準time-zero和聲速；
3. 把探頭移動5–10 mm，新run必須有變化；
4. 確認目標在陣列成像平面內，線性陣列只能解析一個切面；
5. 降低dynamic range、使用TGC、排除氣泡和探頭上方厚耦合層；
6. 先把金屬絲/硬反射物成像成功，再追求低對比管腔。

## 程式停在保存

`ADC_Save_Raw_Data_As_Binary_File`保存32–128 MiB可能需30–60秒，窗口無新輸出不等於死機。檢查目標檔案大小是否持續增加、HSDC是否仍響應；timeout之前不按Ctrl+C。Ctrl+C會令manifest變error，該run不可視為complete。

## 上傳前資料洩漏檢查

```powershell
git status --short
git ls-files | Select-String -Pattern '\.bin$|auto_runs|capture_|analysis/'
git grep -n -E 'ghp_|github_pat_|password|secret|token'
```

第一個資料搜尋應無結果；本倉庫的`.gitignore`也會排除原始資料、圖像與日誌。
