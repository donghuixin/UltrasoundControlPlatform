# 1 MHz B-mode 成像操作

## 1. 推薦起步參數

| 參數 | Pilot | 完整掃描 |
|---|---:|---:|
| TX陣元 | A1–A8 | A1–A8 |
| pitch / width | 1.59 / 1.0 mm | 相同 |
| 中心頻率 | 1 MHz | 1 MHz |
| 角度 | 0° | -10°…+10°，先2°、再1° |
| samples/channel | 262,144 | 262,144；需要更多1 kHz脈衝時1,048,576 |
| repeats | 1 | 1 |
| trigger | normal | normal；接SYNCP→J13後可hardware |
| AFE | Min Gain起步 | 不削頂後逐級加增益 |

120 MSPS時，262,144點是2.1845 ms，內含約2個1 kHz事件；一個BIN為8 MiB。21角度約168 MiB。1,048,576點為8.738 ms、32 MiB/BIN，21角度約672 MiB。

## 2. 1 MHz不是在HSDC中設定

1. TX GUI載入1 MHz Pattern preset。
2. UI `center frequency=1.0`只供延時/重建使用。
3. HSDC `ADC Input Target Frequency=1.0M`只供顯示/FFT標記。
4. 首個pilot保存後，在處理頁看 `echo_spectrum`；峰值應在陣元帶寬允許的1 MHz附近。

如果峰值仍是1.5 MHz或2.5 MHz，表示Pattern沒有真正載入、TX_BF沒有生效、捕獲主要是外界噪聲/舊DDR，或0.4 mm陶瓷在1 MHz效率很低。不要只改檔名或UI頻率。

## 3. UI逐步操作

1. `陣列與延時`：8、1.59、1.0、1.0 MHz、1540、5 ns；角度先0到0。
2. 檢查延時表counts不超8191，量化角度合理。
3. `自動化採集`：samples 262144、repeat1、settle0.25、normal。
4. 選本地輸出目錄，確認磁碟餘量。
5. 點Dry run，查看命令列最後是 `DRY RUN COMPLETE`。
6. 勾選全部pre-flight，點開始採集；不要點TI GUI。
7. 等 `capture_manifest.json`為complete。
8. 在處理頁選新run，點運算；核對標題中的run名稱和SHA-256，不使用舊圖。
9. Pilot有可重複回波後改為-10…+10：先2°共11角度，再1°共21角度。

## 4. 1°是否一定更好

不一定。1°只增加發射角度採樣和檔案數，不能修復：

- 只有6個獨立RX數字通道；
- 通道映射/重複錯誤；
- 沒有共同trigger；
- 1.59 mm pitch造成的柵瓣；
- 陣元頻率響應和耦合不佳。

在通道與同步正確後，1°通常令角度複合更平滑；在數據鏈未通過QA時只會重複採集同樣的偽影。

## 5. 深度與影像幾何

共同時間零點下：`z = c·(n-n0)/(2fs)`。120 MSPS、1540 m/s時每sample單程深度增量約0.00642 mm。normal模式的HSDC起點相對TX隨機，因此重建腳本先利用發射串擾/強事件軟對齊；這能做靜態仿體，但深度零點仍需用已知反射面校準。

線性陣列的平面波掃描原生結果更接近矩形/窄梯形。把圖重映射為扇形只改顯示，不會變成凸陣，也不會增加物理視場。

## 6. 通道QA

逐路注入或逐陣元敲擊，建立「物理RX→HSDC channel」表。若 `[3,5] [4,6] [9,15] [10,16]`波形完全相同，先排查JESD profile、FMC lane映射、SMA接線與解包，不把16個槽當作16個獨立通道。重建只使用確認獨立且映射正確的通道。

## 7. 驗收

- TX_BF OFF/ON時，固定深度強事件或頻譜必須有可重複差異；
- 1 kHz事件間隔約120,000 samples；
- 1 MHz附近有能量且各角度文件hash不同；
- 無0/65535 rail code，ADC不削頂；
- 已知反射面深度誤差在校準容許範圍；
- 移動探頭後，新run與舊run的hash、抽樣相關係數和B-mode確實改變。
