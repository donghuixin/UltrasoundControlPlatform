# 配置文件與寄存器核對

## HSDC Pro profile

倉庫文件：`configs/hsdc/AFE58JD48_120M_8L_M16_FIXED.ini`

本機安裝位置：

```text
E:\Program Files (x86)\Texas Instruments\High Speed Data Converter Pro\14J50 Details\ADC files
```

關鍵內容：16 output columns、16 bits、120 MSPS、候選 JESD L=8/M=16/F=4/K=8/N=16/Subclass1，以及目前的lane mapping。它是實驗配置，不是已驗證基線。複製後重啟HSDC Pro，在AFE RX下拉選同名profile；若timeout，重新初始化AFE LMK/JESD並確認D3/D4狀態。

不要把`JESD IP Core_M`的數字直接當成公開 JESD literal M。2026-07-25 已分別測試 repository `M16_FIXED`、matched S2/M16 和 TI 安裝包原始 `M=5` profile；三者輸出 BIN 完全相同，均有 `[3,5] [4,6] [9,15] [10,16]` 逐位重複。故障很可能位於 TSW14J50/HSDC 的 firmware INI/去幀表，且 TI E2E 有完全相同的已知案例。現階段沒有任何 profile 可稱為 validated；必須取得 TI 修復文件並通過16個唯一數位碼驗收。完整證據見 `docs/11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md`。

## TX7316 1 MHz preset

倉庫文件：`configs/tx7316/1MHz_5pulses.cfg`

注意：這是TI安裝包的原始文件名；其`REPEAT_COUNT=3`代表pattern總共執行4次，因此是4個聲學週期。SBOU224A的Quick Setup也稱它為`Internal: 1 MHz, 4 pulses`。

這個cfg不是0度成像的完整preset：Profile 0的A1-A8延時為`[0,10,20,30,40,50,60,70]`，且最後寫`Reg24=0x02000003`啟用`TX_BF_MODE`。載入後先關閉BF；自動採集腳本會按角度覆寫delay profile，手動0度測試則須把八路延時全部設0。Pattern/Delay寫入後仍要脈衝Register 0 bit3 `LOAD_PROF`並確認自清零。

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

`HKUST_BioData_Collector/collector_config.example.json`是可提交基線；UI把本機選項保存為被Git忽略的`collector_config.json`。目前Collector基線使用1.5 MHz已知pattern、8個物理通道和HSDC槽5–12：

```json
{
  "elements": 8,
  "pitch_mm": "1.59",
  "element_width_mm": "1.0",
  "rx_hsdc_slots": "5,6,7,8,9,10,11,12",
  "center_frequency_mhz": "1.5",
  "min_angle": "-10.0",
  "max_angle": "10.0",
  "angle_step": "1",
  "samples": "262144",
  "trigger": "normal",
  "doppler_preset_key": "carotid_phantom_raw_low_flow"
}
```

可在倉庫根目錄執行`python HKUST_BioData_Collector/config_audit.py`，檢查repository HSDC snapshot、Collector JSON和所有頸動脈流量仿體預設的語法與數學一致性。這是只讀審計，不代替GUI/AFE寄存器readback或16/16唯一碼transport Gate。

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
