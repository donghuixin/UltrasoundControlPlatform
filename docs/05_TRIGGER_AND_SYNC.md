# 同步與觸發模式

## 端口角色

- `TX7316 J7 pin2 SYNCP/TR_BF_SYNC`：板載CPLD輸出的約2.5 V、約1 kHz同步觀測/扇出點。
- `TSW14J50 J13`：外部Capture Start輸入，最大3.3 V；不是ADC sample clock，也不是每個脈衝的存檔命令。
- `AFE J25 TX_TRG`：AFE TGC/demod等發射同步的輸入；Analog Input固定增益模式可以不接。
- `TSW J7/J8 Sync A/B`：多板或特定同步拓撲；目前單AFE-FMC-單TSW不使用。

## Normal模式

接線：J7 pin2、AFE J25、TSW J13全部可留空。

腳本調用HSDC `Pass_Capture_Event`，等同點Capture。優點是最穩定；缺點是block起點相對TX的1 kHz發射隨機，重建必須軟對齊。只適用靜態仿體。

## Hardware模式（原板1 kHz）

接線：J7 pin2中心信號→TSW J13中心；TX AGND→J13外殼。單根短線、確認2.5 V邏輯可直接試；長線或多分支使用3.3 V兼容buffer。

流程：

1. TX_BF先OFF，HSDC選Hardware trigger；
2. 腳本寫/選profile並LOAD_PROF；
3. 腳本TX_BF ON；
4. HSDC等待下一個J13邊沿並讀DDR；
5. 捕獲完成後腳本立刻TX_BF OFF，再保存BIN。

如果一直等，先關高壓/TX_BF，檢查SYNCP是否存在、J13極性/電平、HSDC INI與Trigger Option。不要靠Ctrl+C強行把半完成run當成成功。

## Software模式

HSDC軟件觸發只控制TSW開始，不會同時觸發TX。除診斷HSDC trigger API外，不把它作為相干超聲的共同時間零點。

## 外部5–20 kHz主時基

J7是輸出，不是輸入。外部主時基必須經改裝CPLD/FPGA真正控制TX的同步和TR_EN路徑，另經扇出送AFE/TSW。任何外部注入前先隔離原CPLD驅動，否則兩個輸出互相對打。

## 降低空白資料

Hardware trigger只能固定「開始」。HSDC仍會連續保存所設定的samples。因此成像30–50 mm時可把samples降到16,384或32,768，然後以已知trigger delay裁剪；normal模式為容納隨機1 kHz事件通常需262,144或更多。長時間Doppler要靠FPGA距離門/IQ抽取，而不是反覆Capture小檔。
