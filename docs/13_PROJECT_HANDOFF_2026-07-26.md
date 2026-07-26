# UltrasoundControlPlatform 项目交接（2026-07-26）

> 归档日期：2026-07-26（Asia/Shanghai）  
> 建议恢复开发日期：2026-07-29  
> 目标仓库：[donghuixin/UltrasoundControlPlatform](https://github.com/donghuixin/UltrasoundControlPlatform)  
> 对照基线：`main@7042dc19`（2026-07-24 21:19:49 UTC）  
> 当前阶段：采集与重建软件已形成可运行平台；AFE58JD48/TSW14J50 的 JESD 去帧映射仍是首要阻塞。  
> 安全边界：仅限凝胶、水槽和流体仿体；开放式高压 EVM 未经医疗安全认证，不接人体、不用于诊断。

## 1. 两天后先看这里

当前不是“没有采到数据”，而是“已经能稳定完成采集、保存、重建和 QA，但 16 个 HSDC 输出槽中存在确定性的 converter 复制”。在修复 JESD 去帧前，继续调探头、DAS、增益或凝胶不能恢复丢失的空间通道。

已重复确认的复制关系：

```text
HSDC slot 3  = slot 5
HSDC slot 4  = slot 6
HSDC slot 9  = slot 15
HSDC slot 10 = slot 16
```

matched S1/K8、matched S2/K8 和 TI 安装包原始 S1 profile 三组测试得到位元级一致的 BIN。根因优先级最高的是 TSW14J50RX firmware INI / HSDC JESD 去帧表错误。恢复开发后的第一件事应是取得 TI 修复文件并跑 16/16 唯一码 Gate，而不是继续猜 `M`、Subclass 或声学接线。

## 2. 当前系统基线

| 项目 | 当前基线 | 状态 |
|---|---|---|
| TX | TX7316EVM，5-level，A1-A8 共 8 个物理阵元 | 可自动写入 profile；声学输出仍需示波器/水听器验证 |
| RX/ADC | AFE58JD48EVM，16 analog channels / two 8-channel dies | 模拟输入链可工作；数字槽映射未通过唯一性验收 |
| 采集板 | TSW14J50 + HSDC Pro | DDR block capture 可用，不是无缝 USB streaming |
| JESD profile | 120 MSPS、8 lanes、16 数字槽、Subclass 1 | link 可建立；4 组槽复制，尚未修复 |
| 阵列 | 8 阵元，单元约 `1.0 x 1.0 x 0.4 mm`，pitch `1.59 mm` | 大 pitch 在高频下有明显栅瓣风险 |
| TX 频率白名单 | 1、1.5、2、2.5、4 MHz | 数字 pattern 写入和寄存器回读已支持；不等于声学频率已验证 |
| 当前可复现 preset | 1 MHz / 5 pulses | 已纳入仓库配置 |
| 计划重点频率 | 2.5 MHz | 用户当前认为换能器在该频率表现较好；待脉冲回波实测 |
| 原板 PRF | 约 1 kHz，自由运行 | GUI 不能直接改成 5/20 kHz；SYNCP 是输出 |
| 多角度扫描 | `-10 deg ... +10 deg`，1 deg 或 2 deg 步进 | 超过 16 个角度自动分 bank |
| 数据策略 | raw BIN、运行目录、图像和本机状态不进 Git | 保持现行政策 |

## 3. 这段时间已完成的任务

### 3.1 平台与自动采集

- 建立 `UltrasoundControlPlatform` 仓库和分层文档，覆盖硬件接线、冷启动、B-mode、PW Doppler、触发同步、配置、排障和本机软件来源。
- 建立 HKUST Bio-data collector 桌面 UI，接入 TX7316 与 HSDC 自动化入口。
- 支持 2-8 个 TX/RX 阵元、Delay Profile 计算、多角度采集和超过 16 角度时自动分 bank。
- TX 频率白名单扩展到 1、1.5、2、2.5、4 MHz；Pattern Profile/Reg25 写入后回读，不匹配即 Fail Closed，禁止继续高压采集。
- 每个完成 run 可保存已验证的 TX7316 cfg 快照、索引、manifest、来源 SHA-256 和 QA 结果。
- HSDC 阻塞调用加入心跳、等待时间和文件保存进度；关闭 Windows Console QuickEdit，避免误点命令窗导致程序假死。
- UI 限制同一时间只有一个采集任务，减少 HSDC Automation `code 66`。

### 3.2 重建与诊断

- 建立 HSDC raw BIN 检查、软对齐、带通、DAS、角度复合和 2D/3D 图流程。
- 新增 PRF 事件模板验证、通道 QA、逐 PRF 图像、周期合成 QA、回波时域、pattern 读回和元数据输出。
- 新增 `diagnose_prf_alignment.py`，独立检查事件间隔、模板相关性和时零抖动。
- 明确区分 TX 设置频率、pattern 基频、探头振铃峰和延迟回波窗峰，避免把约 1.45-1.6 MHz 振铃误判为所有 TX 设置都发在同一频率。
- 明确 `sector_scan.png` 只是“发射角度 x 单条 A-line 包络”显示，不是完整 RX-DAS；成像判断应看 `plane_wave_das_bmode.png` 和逐 PRF RX-DAS。

### 3.3 同步、Doppler 与容量设计

- 完成 Normal、Hardware、Software 和未来外部主 PRF 四类触发模式的职责划分。
- 确认 TSW14J50 `J13` 是 Capture Start 输入，不是 ADC sample clock，也不是每个 PRF 周期的单独保存命令。
- 确认 HSDC/TSW 是 DDR block capture；多次 Capture 之间有保存空档，不能拼成连续心动周期。
- 完成 1 kHz PW Doppler 可行性、Nyquist 速度、无模糊深度、距离门、I/Q、wall filter 和慢时间 STFT 流程设计。
- UI 已提供 PW Doppler 计算与固定角度短块采集入口，也提供逐 PRF Auto Scan 的 bank、event offset、4096 点量化和容量估算；它不会虚假宣称能修改原板 PRF 或实现无缝 streaming。

### 3.4 JESD 故障隔离

- 用 AFE 内部 16 通道唯一数字码，把问题从探头、声学串扰和离线算法隔离到数字 transport/去帧链。
- 三种独立 profile 得到相同的四组 converter 复制，并保存可复查的 SHA-256 和映射证据。
- 已排除“只改 Subclass”“只把 `JESD IP Core_M` 改成 16”“随机 lane bit error”等单一解释。
- 找到 TI E2E 的同症状案例；TI 工程师确认一份 TSW14J50 firmware INI 存在 bug，并建议联系 `ultrasound_rx-support@list.ti.com` 获取更新文件。
- 已形成 [JESD 故障报告](11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md)和[可直接用于外部求助的证据包](12_OPUS_HELP_REQUEST_JESD_DEFRAMING.md)。

## 4. 尚未完成的任务

| 优先级 | 任务 | 完成标准 |
|---|---|---|
| P0 | 向 TI 获取修复后的 TSW14J50/AFE58JD48 firmware INI 或 FPGA firmware | 得到文件、版本、适用 HSDC 版本和 lane/converter 说明，并归档原始邮件/附件信息 |
| P0 | 重跑 16 通道唯一数字码 Gate | 16 列两两不再逐位相同；固定码与 converter 编号完全匹配；连续多次 capture 结果一致 |
| P0 | 修复前冻结 8/16 通道成像结论 | 只允许把槽 9-14 六通道降级数据用于流程/深度验证，不宣称完整阵列成像 |
| P1 | 数字 Gate 通过后做逐 SMA 模拟注入 | 每个 AFE 输入只落到预期唯一数字槽；完成 A1-A8 到 HSDC 的测量证书 |
| P1 | 核实 TX7316EVM 同步引脚 | 对具体板版号做断电导通和示波器确认，关闭 J7 pin 2 与手册原理图网络名冲突 |
| P1 | 2.5 MHz 脉冲回波标定 | 保存 SYNC/TX/RX 波形，测中心频率、-6 dB 带宽、cycles、振铃、恢复时间、50 mm SNR |
| P1 | 1 kHz 流动仿体 PW Doppler | 已知流速下得到稳定频谱、方向和速度估计，并与理论误差比较 |
| P1 | 5 kHz 主 PRF 方案 | 选择修改 CPLD、外部 FPGA 控制或自制时序板；低压假负载先通过电平/极性/总线冲突验收 |
| P2 | 连续 6-10 s Doppler 数据路径 | FPGA 做距离门 + I/Q/降采样，每个 PRF 仅保留目标门复数样本；禁止用多次 HSDC Save 假装连续 |
| P2 | Appendix C 3-level / 16TR 改板 | 完成逐器件 BOM、板卡正反面定位、改装照片、通断测试和回退方案后再上高压 |
| P2 | 血流论文/产品矩阵 | 只保留真实 blood-flow 测量论文，补齐 Lumia 等产品与论文、DOI、临床/仿体验证级别 |
| P3 | 可重构贴片与三维血管方向 | 完成 RCA/MUX 通道预算、仿体设计、3D centerline 和局部流速方向验证 |

## 5. 2.5 MHz、50 mm、1 kHz 的当前建议

软组织声速取 `c = 1540 m/s`：

```text
波长 lambda = c/f0 = 1540 / 2.5e6 = 0.616 mm
50 mm 双程时间 t = 2z/c = 64.9 us
120 MSPS 下 50 mm 样点数 = 120e6 * 64.9e-6 = 7792
建议硬件起始触发短窗 = 16384 samples/channel
16384 / 120 MSPS = 136.5 us，对应约 105 mm 深度
```

仓库当前真实采样基线是 120 MSPS。此前讨论过的 `40 MSPS + 4096 points` 是探索性方案，不应覆盖现有已验证的 JESD 配置。首次 2.5 MHz 实验应保持 120 MSPS，减少同时变化的变量。

2.5 MHz 的轴向 Nyquist 速度（`cos(theta)=1`）为：

| PRF | Nyquist 速度 |
|---:|---:|
| 1 kHz | 0.154 m/s |
| 5 kHz | 0.770 m/s |
| 10 kHz | 1.540 m/s |

因此 1 kHz 适合链路联调、功率多普勒和慢流，但普通动脉速度容易混叠。50 mm 只需约 65 us 回波时间，传播深度不是 5 kHz 的障碍；真正约束是 TX 时序、振铃恢复、共同 PRF 时基和连续慢时间数据路径。

当前短块 Doppler 基线仍可用 `4,194,304 samples/channel @ 120 MSPS`，约覆盖 34.95 ms，即约 35 个 1 kHz 脉冲。要做 128/256 pulse 频谱，需要更长的单次 DDR block、减少通道、FPGA 距离门或 I/Q 降采样，并先核对 TSW 总容量。

## 6. 接线与触发的关键结论

```text
TX7316 J7 OUT_A1-A8 -> 换能器阵列
同一阵元回波 -> TX7316 内部 T/R switch -> J5 RX_A1-A8
J5 RX -> AFE58JD48 SMA -> JESD/FMC -> TSW14J50 -> HSDC Pro

经实测确认的 TX7316 SYNCP
  -> 高输入阻抗、3.3 V 兼容 buffer/level conditioner
  -> TSW14J50 J13 Capture Start
  -> 需要 TGC/demod 时再有源扇出到 AFE J25
```

- TX7316 已带主 T/R switch，正常单端阵元不要把高压 TX 端直接接 AFE。二次限幅、ESD、终端和连接器保护仍有价值。
- 不要被动 Y 分支 SYNCP；需要多路时使用有源扇出。
- 不要把 SYNCP 接到 AFE LMK、TSW J7/J8 Sync A/B 或 ADC sample-clock 输入。
- `TX_BF_MODE=0` 时 SYNCP 仍自由运行可以是正常现象。
- 外部 5-20 kHz 不能回灌 J7。必须隔离原 CPLD 输出，并从真正的 TX 同步/TR_EN 控制路径注入。

### J7 pin 2 的文档冲突

仓库当前操作文档把 `J7 pin 2` 作为约 2.5 V、1 kHz SYNCP 输出；此前放大 TX7316EVM 手册原理图时，却出现 `J7 pin 20 = SYNCP_P`、`J7 pin 2 = OUT_A5` 的网络名。可能原因包括连接器视图方向、页码/版本或引脚编号理解差异。

在具体 EVM 上闭环前，不应继续用文字争论：

1. 完全断电；
2. 按板卡丝印和原理图确认 J7 pin 1 方向；
3. 做 SYNCP 测试点到 J7 候选脚的通断测试；
4. 上低压后用高阻探头找出约 1 kHz、约 2.5 V 波形；
5. 保存板卡正反面照片、探针位置和示波器截图；
6. 再统一更新 `01_HARDWARE_CONNECTIONS.md` 与 `05_TRIGGER_AND_SYNC.md`。

## 7. 已踩过的坑

1. **把 ADC fast-time sample rate、PRF 和 TX 中心频率混为一谈。** 120 MSPS、1 kHz PRF 和 2.5 MHz 是三个独立参数。
2. **认为 HSDC 的 `ADC Input Target Frequency` 会设置 TX。** 它只影响 FFT 显示/标记。
3. **认为寄存器回读等于声学验证。** pattern 写对不代表探头实际中心频率、带宽和声压符合设置。
4. **认为 J13 每个触发只存一个 50 mm 窗。** J13 只锁定 block 开始；HSDC 仍连续保存配置的 samples。
5. **认为 Continuous Capture 是无缝流。** 多个 DDR capture 之间有保存空档，不能用于连续心动时间轴。
6. **认为 Auto Re-Arm 菜单存在就代表当前固件支持。** 必须通过触发计数和 DDR 占用实测；部分 TI 配套固件并未实现该功能。
7. **认为 J7 可作为外部 PRF 输入。** 当前 J7 同步是 CPLD 输出；回灌会造成两个输出对打。
8. **认为默认 5-level 可无改动释放 16TR。** Appendix C 3-level 需要电阻/器件改装和不同供电，不能只悬空 `3LVL`。
9. **看到 16 列数据就认为有 16 条独立 converter。** 必须先跑内部唯一数字码和逐列相等检查。
10. **把重复槽屏蔽当成修复。** `drop-later` 只避免重复计权，不能恢复丢失通道。
11. **把 profile 名称里的 M16 当成硬证据。** HSDC 私有字段可能是枚举或与 `Channel Pattern/Group128` 联合解释。
12. **用声学图判断数字 transport。** transport 验收必须用固定唯一数字码，不看探头图像。
13. **把单 A-line 扇形图当成完整 DAS。** 这会夸大“成像成功”或误判水平条纹。
14. **忽略 1.59 mm pitch 的栅瓣。** 频率升到 2.5 MHz 后 `pitch/lambda` 更大，不能把栅瓣伪影全归因于算法。
15. **用 NI-9203 采超声 RF。** 它的输入形式和采样率不适合 MHz 级 RF；现有 AFE58JD48 路线才是正确方向。
16. **重复点击采集或按 `Ctrl+C` 催促。** 可能触发 HSDC code 66，或把半完成 run 误认为成功；应看心跳、退出码、manifest 和文件尺寸。

## 8. 恢复开发的严格顺序

1. 拉取 `main`，确认至少包含 `7042dc19` 和本交接文档。
2. 阅读 [JESD 故障报告](11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md)及 [Opus/TI 求助包](12_OPUS_HELP_REQUEST_JESD_DEFRAMING.md)，不要重复已排除实验。
3. 联系 TI ultrasound RX support，索取修复后的 TSW14J50 firmware INI/firmware 和字段说明。
4. 保持 AFE internal unique pattern，不接声学链，执行 16/16 唯一码 Gate。
5. Gate 失败时一次只改一个 converter/channel pattern、lane mapping、Group128/deformatter 项；每次保存 profile、BIN SHA-256 和映射矩阵。
6. Gate 通过后才做逐 SMA 低压注入，建立 AFE 输入到 HSDC 槽的唯一映射。
7. 再回到 TX7316 + 探头，先做已知深度平面反射体和通道到达时间校准。
8. 实测关闭 J7/SYNCP 引脚冲突，并验证 J13 hardware-trigger block 起点稳定。
9. 在 120 MSPS 下做 1 MHz 已知 preset 基线，再测试 1.5、2、2.5、4 MHz；每个频率都保存 TX/RX 波形与声学频谱。
10. 用 2.5 MHz、1 kHz、已知恒速流体仿体做短块 Doppler；先证明频移和流向，再设计 5 kHz/长时间 I/Q 架构。

## 9. 可重构贴片与三维血管走向的后续路线

这是 P3 研究路线，不能抢占当前 JESD 修复：

- 硬件优先考虑 `row-column addressed array (RCA) + reconfigurable sub-aperture`，用 `N+N` 行列电极形成近似 `N x N` 虚拟交点。
- 现有 16TR 可做 `8 rows + 8 columns` 浅层概念验证；50 mm、2.5 MHz 下若目标横向分辨率约 1.5 mm，近似需要约 20.5 mm 孔径，因此正式方案应评估 `32+32` 或 `64+64` RCA。
- MUX 分时适合静态/慢变化三维血管几何，不适合直接承担高 PRF 全体积实时矢量多普勒，因为每个状态的有效 PRF 会下降。
- 算法基线：3D beamforming/f-k migration -> slow-time SVD -> 3D power Doppler -> 多视角一致性 -> vesselness -> skeleton/centerline -> 局部 PCA/Hessian 切向 -> 沿中心线 PW Doppler。
- Kakeya 思想只作为角度覆盖与方向聚集惩罚的启发；Boltzmann/输运思想只作为 `f(x,v,t)` 时空流动先验。两者必须与标准均匀角度 + SVD + PCA 基线做消融，不能先写成性能结论。

## 10. 实验留档要求

每次实验至少保存：

```text
YYYY-MM-DD_runNN/
  README.md
  wiring.jpg
  scope_sync_tx_rx.png
  tx7316_config.png
  afe58jd48_config.png
  hsdc_config.png
  capture_manifest.json
  metadata.json
  raw.bin                 # 仅本地，不提交 Git
  quicklook.png           # 仅本地，不提交 Git
  qa_summary.json         # 去识别后可提交 diagnostics/
```

一次采集只有同时满足以下条件才算成功：进程退出码为 0；manifest `status=complete`；BIN 数量和角度/repeats 一致；文件尺寸等于 `samples x 16 x 2 bytes`；每个 capture 有角度、profile、时间戳和 QA；不是只看 HSDC 屏幕或 `Saving...`。

## 11. 关键文档

- [系统与模式总览](00_SYSTEM_OVERVIEW.md)
- [完整电气连接与通道映射](01_HARDWARE_CONNECTIONS.md)
- [PW Doppler 与多个心动周期](04_PW_DOPPLER.md)
- [同步与触发模式](05_TRIGGER_AND_SYNC.md)
- [2026-07-24 软件更新](09_RECENT_SOFTWARE_UPDATES.md)
- [通道 QA 与成像诊断](10_CHANNEL_QA_AND_IMAGING_DIAGNOSIS.md)
- [JESD 通道复制故障报告](11_JESD_CHANNEL_DUPLICATION_INCIDENT_REPORT.md)
- [JESD 去帧求助包](12_OPUS_HELP_REQUEST_JESD_DEFRAMING.md)
- [TI 同症状 E2E 讨论](https://e2e.ti.com/support/data-converters-group/data-converters/f/data-converters-forum/1567281/afe58jd48evm-afe58jd48-channel-mapping-issue-with-jesd204b-interface)

## 12. 本次交接的边界

- 本文依据目标仓库现有文档、最近提交和此前完成的手册调研整理；本次归档没有连接三块 EVM，也没有产生新波形或 raw BIN。
- 仓库已有软件功能按现有提交和文档记录为“已完成”，本次没有在 Windows/TI GUI 环境重新执行硬件集成测试。
- `2.5 MHz` 是下一阶段重点实验频率，不是已通过声学验收的最终频率。
- 公开仓库不保存本机绝对路径、凭据、原始 BIN、未去识别日志或人体数据。
- 支付记录和 OpenEarable 蓝牙问题属于其他主题，不纳入本项目交接。

## 13. 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-26 | 首次交接；汇总平台功能、JESD P0 阻塞、2.5 MHz/50 mm Doppler 方案、同步引脚冲突、踩坑和恢复顺序。 |
