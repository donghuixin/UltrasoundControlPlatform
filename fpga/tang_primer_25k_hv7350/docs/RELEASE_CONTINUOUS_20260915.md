# 2026-09-15：四探头持续发射固件交付

发布标签：`fpga-hv7350-4probe-continuous-usb-20260915`。

## 最终发射参数

| 参数 | 当前值 |
| --- | --- |
| 主载波 | 2.2 MHz，50 MHz时钟下NCO字为`0x0B439581` |
| 主burst | 2 cycles，正极性RTZ；不是无限长连续载波 |
| PRF | 10 kHz，每100 μs重复一次burst |
| 消振 | 完整主burst后等待140 ns，再发100 ns负向尾脉冲；VNN按原−30 V设置 |
| J11 | 200 ns宽；其上升沿后2 μs启动主burst |
| 输出选择 | S2/USB一次只选择同一块HV7350的TX1～TX4之一 |
| 持续时间 | 无5秒上限，保持到下一次选择或USB STOP |

NCO按`0x0B439581 × 50,000,000 / 2^32`计算为约2,199,999.9997 Hz，即标称2.2 MHz；实际值受板载时钟精度影响，边沿有20 ns时钟量化。USB命令不能更改此频率。

## 从5秒版更新的内容

- 去掉5秒定时退出。上电静默；第一次S2启动HV1，后续依次HV2→HV3→HV4→HV1，长按只触发一次。
- START/NEXT持续发射，STOP停发。READY运行时亮；DONE恒灭，原completed标志位恒0。
- 保留原6字节请求、9字节回复和115200 8N1协议，更新Python/C#使用说明、黄金向量、持续录制例程及测试。
- 接收端可一次arm后持续保存数据，换路不由该例程重启接收；切换边界应丢弃，STATUS不提供逐帧探头标签。
- 关闭COM或拔USB不等于停止；只要FPGA和高压链路仍供电，就持续输出。没有自动超时兜底，结束需显式STOP并确认。S2只换路，不是停止键。

## 下载和烧录

- FS：`burn_test/pmod_led_4probe_continuous_2p2mhz_2cycles_10khz_uart.fs`。
- 交付ZIP：`handoff/FPGA_4PROBE_CONTINUOUS_WINDOWS_HANDOFF_20260911.zip`。
- 目标：`GW5A-LV25MG121NC1/I0`，先核对核心板；高压关闭时先验证3.3 V逻辑。
- [Windows入口](../README_WINDOWS_HANDOFF.md) / [USB接口合同](USB_WINDOWS_INTERFACE_HANDOFF.md)。

FS SHA-256：`a9d1b8992abd552fc892cd0dcef2ba1092a25f14236accc9eaa43549509c07e5`。

固件于2026-09-11构建，本次整理不更改RTL、FS/BIN或发射波形，仅更新GitHub交付和发布入口。ZIP重打后以内部`MANIFEST_SHA256.txt`核对交付文件。

## 验证范围与回退

- 本次重新核对源码/位流SHA-256、静态时序模型及53项Python离线测试。
- 该相同RTL版本此前通过Gowin综合/布局布线，50 MHz约束下Fmax=126.242 MHz，setup/hold违规0。
- 此前完整6秒RTL仿真经过300,000,000时钟，60,000帧后仍继续，随后UART STOP成功；按键、串口、错误请求和波形回归通过。本次没有再次运行6秒长仿真。
- C#参考源码未在本机编译；未由助手烧录实板或验收USB/AFE/TSW联合采集与高压声学输出。
- 旧标签`fpga-hv7350-4probe-5s-usb-20260911`、旧5秒FS/BIN与ZIP保留；更早autostart和2 MHz版本也保留。旧ZIP位于仓库/本地`handoff/`，不重复嵌套在新ZIP内。

这是实验室高压超声发射固件，不是医疗认证设备；软件STOP不能代替硬件急停。
