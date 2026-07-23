# 配置文件與寄存器核對

## HSDC Pro profile

倉庫文件：`configs/hsdc/AFE58JD48_120M_8L_MANUAL.ini`

本機安裝位置：

```text
E:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files
```

關鍵內容：16 channels、16 bits、120 MSPS、JESD L=8/M=5/F=4/K=8/N=16/Subclass1，以及目前已驗證的lane mapping。複製後重啟HSDC Pro，在AFE RX下拉選同名profile；若timeout，重新初始化AFE LMK/JESD並確認D3/D4狀態。

## TX7316 1 MHz preset

倉庫文件：`configs/tx7316/1MHz_5pulses.cfg`

目前TI安裝包來源：

```text
E:\Program Files (x86)\Texas Instruments\TX7316 EVM\Config Files\TX7316 5LVL\TX7316 5LVLvE3\Scripts\Quick Start\Internal\1MHz_5pulses.cfg
```

載入後的主要快照：

```text
Reg24: 0x02000002 (TX_BF off) → 0x02000003 (TX_BF on)
Reg25: 0x00000246
Pattern P0 registers 0x60..0x64:
  0x839A836E 0x836D836E 0x836D8399 0x00000007 0x00000000
```

檔名、GUI顯示的period或HSDC target frequency都不是聲學驗證。保存0° pilot，從回波/串擾頻譜確認實際中心頻率。

## Collector配置

`HKUST_BioData_Collector/collector_config.example.json`是可提交基線；UI把本機選項保存為被Git忽略的`collector_config.json`。推薦1 MHz B-mode起點：

```json
{
  "elements": 8,
  "pitch_mm": "1.59",
  "element_width_mm": "1.0",
  "center_frequency_mhz": "1.0",
  "min_angle": "-10.0",
  "max_angle": "10.0",
  "angle_step": "1",
  "samples": "262144",
  "trigger": "normal"
}
```

## 自動腳本的責任邊界

腳本會做：Delay Profile計算/量化、分批寫profile、LOAD_PROF、逐角度TX_BF開關、HSDC capture/save、檔案大小與rail QA、manifest。

腳本不會做：高壓電源、Pattern電平/週期、PRF、AFE增益、人體安全參數。`--center-frequency-mhz`只影響延時計算與報告，必須先在TX GUI載入相同頻率的Pattern。

## 常用命令

```powershell
# 完全不碰硬件
C:\Python27\python.exe automation\tx7316_hsdc_batch_capture.py --dry-run --angles=-10,-9,-8,-7,-6,-5,-4,-3,-2,-1,0,1,2,3,4,5,6,7,8,9,10 --tx-elements 8 --pitch-mm 1.59 --center-frequency-mhz 1

# 0度pilot；只在GUI/電源/仿體均確認後使用
C:\Python27\python.exe automation\tx7316_hsdc_batch_capture.py --capture --enable-internal-bf --angles=0 --center-frequency-mhz 1 --samples 262144 --trigger normal

# 比較兩個run是否真的不同
python HKUST_BioData_Collector\compare_capture_runs.py D:\run_old D:\run_new
```

硬件命令須在倉庫根目錄的管理員CMD/PowerShell執行，TX7316 GUI與HSDC Pro也須以管理員運行。
