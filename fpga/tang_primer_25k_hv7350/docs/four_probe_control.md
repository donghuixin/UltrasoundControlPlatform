# 四探头手动切换、持续发射与 USB 控制（2026-09-11）

Windows上位机开发交接请优先阅读 [USB接口交接文档](USB_WINDOWS_INTERFACE_HANDOFF.md)；同目录HTML版可离线用浏览器打开。可集成客户端在 `host/python` 和 `host/windows_dotnet`。

当前 `pmod_led.gprj` 使用这个版本。同一块 HV7350 的 TX1～TX4 分别连接四个独立探头；不是四块驱动板，也不是四通道同时波束赋形。

## 按键和指示灯

- 上电待机，所有 PIN/NIN、J11、J10 都为低，不自动发射。
- S2 首次按下：HV1 发射；第二次：HV2；随后 HV3、HV4，再回到 HV1。
- 启动后选中探头以 10 kHz PRF 持续发射，没有时长或帧数上限；取消原来的 5 秒自动停止，也不会自动启动下一探头。
- 发射期间再次按 S2，立即中断旧通道并启动下一通道，直到下次切换或 USB STOP。按键仍有 20 ms 消抖；“立即”是有效按键被识别后，不等待旧帧结束。长按只产生一次事件。
- S1 无效。S2 不再是停止按钮。需要中途停止且不切换时，发送 USB `stop`；出现电气故障应断开高压供电，不依赖串口作为硬件急停。
- READY：发射期间亮，待机/STOP 后灭。DONE 恒灭，因为本版不再有计时自然结束事件。上电两灯灭。

可以一直保持接收端录制，按 S2 改变当前发射探头；每路录制时间由使用者决定，不能再假定固定 50,000 帧。**关闭串口或拔掉 USB 不会停止发射；只要 FPGA 及高压链路仍供电就会继续，直到收到 USB STOP 或断电。** 没有断线看门狗，也没有 5 秒自动停止兜底。

## 波形不变，只有一个输出通道工作

载波标称 2.2 MHz，NCO 字 `0x0B439581`，主 burst 为 2 cycles 正极性 RTZ。主 burst 完成后等待 140 ns，再发一个 100 ns 的 NIN 负向消振脉冲。电源保持 VPP=+30 V、VNN=-30 V 时，对应正向主脉冲和负向尾脉冲；电源值由硬件决定，不由 FPGA 设置。

以每枚 J11 上升沿为 t=0：

| 信号 | 时间 |
| --- | --- |
| J11 高 | 0～0.200 μs |
| 选中通道 PIN 高 | 2.000～2.240 μs、2.460～2.700 μs |
| 选中通道 NIN 高 | 3.060～3.160 μs |
| J10 高 | 2.000～52.000 μs |
| 下一枚 J11 | 100.000 μs |

所有时刻是 FPGA 数字端时序，高压端还会包含传播延迟、负载响应和振铃。50 MHz 量化使两个 PIN 上升沿相差 460 ns，这是保留原波形的正常结果。

未选中的三路及 HV5～HV8 始终 PIN=NIN=0。在 OEN=1 的现有接法下，这代表 HV7350 的 RTZ 接地状态，**不是高阻隔离，也不是接收多路复用**。FPGA 不改变原有 TR 开关电路。

切换时先清空共享波形发生器，再为新通道产生一枚 J11，经过完整 2 μs 才输出 PIN。因此不会把旧通道的半个 burst/负尾转接到新通道。中断可能截短旧 burst、旧 J11 或 J10，采集软件应丢弃该次不完整发射。两次会话之间的 J11 间隔不保证 100 μs；10 kHz 只保证在同一连续会话内。

所有 PIN/NIN、J11/J10 以及指示状态统一经过输出寄存器，避免直接将计数器/通道组合译码毛刺送到外部。相对内部状态延迟一拍（20 ns），上表的外部相对时序不变；运行中切换具有至少一拍全低间隔，再产生新通道 J11。

## 四路接线

以下 H2、H1 是 HV7350 板排针；B2/F2 等是 FPGA 球位/信号名，并非排针序号。先确认实际 PCB 的第 1 脚方向。

| 探头 | FPGA PIN → HV 板 | FPGA NIN → HV 板 | 高压输出 |
| --- | --- | --- | --- |
| HV1 | B2 → H2.2 / PIN1 | F2 → H2.4 / NIN1 | H1.1 / TX1 |
| HV2 | E1 → H2.6 / PIN2 | E3 → H2.8 / NIN2 | H1.5 / TX2 |
| HV3 | J1 → H2.10 / PIN3 | G4 → H2.12 / NIN3 | H1.9 / TX3 |
| HV4 | H1 → H2.14 / PIN4 | K7 → H2.16 / NIN4 | H1.13 / TX4 |

第四路 FPGA 球位 H1 与 HV 板连接器 H1 重名，注意区分。CLK=H2.1、REN=H2.29、OEN=H2.31 保持原来的 3.3 V 使能接法；各板共地。高压输出不可接到 FPGA。

## USB 接口

正常 Tang Primer 25K Dock 板的 **USB-C 调试口** 同时提供 JTAG 和 UART。用数据线连接电脑，打开其串口即可；不是 USB-A Host 口，不需要 FPGA 原生 USB IP。

- 115200 baud、8 data bits、no parity、1 stop bit，无流控。
- FPGA 接收 B3，发送 C3。这个方向已由同一示例仓库的 `UART/simple_uart/src/top.cst` 核对。
- 使用板载调试器时不要再向 B3 接另一个 USB-UART 的 TX，避免两个输出互相驱动。
- 串口 ACK 表示控制状态，不是超声 ADC 数据。此固件没有实现 AFE/TSW 的采样、存储或 USB 波形上传。
- 官方硬件说明：[Sipeed Tang Primer 25K](https://wiki.sipeed.com/hardware/en/tang/tang-primer-25k/primer-25k.html)。不同底板版本应核对其原理图。

### 电脑操作

在本项目目录运行。真实通信需要 Python 3 和 pyserial；纯打包自检不需要串口依赖。

```sh
python3 -m pip install pyserial
python3 scripts/control_probes.py --list
python3 scripts/control_probes.py --port /dev/cu.usbmodemXXXX start 1
python3 scripts/control_probes.py --port /dev/cu.usbmodemXXXX start 2
python3 scripts/control_probes.py --port /dev/cu.usbmodemXXXX next
python3 scripts/control_probes.py --port /dev/cu.usbmodemXXXX stop
python3 scripts/control_probes.py --port /dev/cu.usbmodemXXXX status
python3 scripts/control_probes.py --dry-run --seq 0 start 1
```

将示例串口替换为 `--list` 列出的实际设备；Windows 使用 `python` 和例如 `COM5`。先用 `status` 确认通信，不要用反复 START 判断连接是否正常。

`start N` 直接启动指定探头持续发射；即使该探头正在运行，也从头重新产生 J11 和发射波形，重置 PRF 相位。`next` 与 S2 相同。`stop` 中断当前输出但保留下一探头游标。`status` 不改变发射。按键和 USB 共用游标，例如 `start 3` 之后下一次 S2/`next` 会启动 HV4。

START/NEXT/STOP 返回的是命令执行后的状态。每发一条普通命令，等待对应回复再发下一条；超时不能判断命令未执行，脚本不会自动重发 START。此时先查询状态或发送 STOP。没有自动“结束推送”，需要时轮询 STATUS；不能再等待 DONE 或 completed=1 才结束采集。

### 固定二进制协议（旧角度配置协议不再使用）

请求共 6 字节：`A5 5A CMD ARG SEQ XOR`；XOR 为 CMD、ARG、SEQ 按位异或。

| CMD（十六进制） | ARG | 动作 |
| --- | --- | --- |
| 10 | 1～4 | START 指定探头 |
| 11 | 0 | NEXT |
| 12 | 0 | STOP |
| 13 | 0 | STATUS |

回复共 9 字节：`5A A5 CMD SEQ RESULT ACTIVE NEXT FLAGS XOR`。最后一字节为 CMD 至 FLAGS 异或。RESULT：0 成功、1 未知命令、2 参数错误；ACTIVE：1～4，待机为 0；NEXT：1～4；FLAGS bit0=运行，bit1 保留原 completed 位置但本版恒为 0，其余为 0。帧格式、命令码和校验不变，行为从限时发射改为持续发射。

例：`A5 5A 10 01 00 11` 启动 HV1；`A5 5A 12 00 01 13` 停止。校验错误、UART 停止位错误或半包超过 10 ms 不触发操作。非法命令/参数回复错误但不改变发射。

不要继续用历史 `configure_beamformer.py` 控制此版本；频率、周期数、消振延时均固定，串口只控制四路选择和开停。校验与序号用于基本完整性检查，不是安全认证机制。

## 接收采集如何配合

1. 四个探头各自使用其对应的 TR/RX 接收路径。TX 轮换不等于把四路 RX 自动接到同一 ADC，接收映射/复用仍由采集硬件负责。
2. 先准备并启动 AFE/TSW 采集等待，再按 S2 或发送 START。不能等收到 USB ACK 后才启动采集，否则会漏掉前几次发射。
3. 每次发射仍由 J11 上升沿做硬件同步。USB 包的到达时间有抖动，不作为采样时基。
4. 以“探头编号、会话编号、会话内发射序号”保存数据。USB START 指定的编号可用于标记；按钮控制时可查询状态，但其回复不是每一帧的实时通道标记。
5. 接收可一直录制，不必每换探头重新启动软件录制。切换可能截断旧触发/波形，跨切换的触发间隔也可能不是 100 μs；丢弃切换边界受影响的数据，并由接收程序实际统计有效帧数。STATUS 没有逐帧探头 ID 或按键时间戳，物理 S2 切换时不能仅靠低频轮询精准标注通道边界；不确定的边界区间应排除在分析外。
6. 仍须做接收保护和振铃门控。原 2.2 MHz/140 ns 消振参数来自原探头测试，不保证四个不同探头具有相同最佳消振效果；本次按要求保持它不变。

## 构建、验证与回退

Gowin 工程：`pmod_led.gprj`，目标 `GW5A-LV25MG121NC1/I0`。需要匹配实际新核心板型号。

持续发射版烧录文件：`burn_test/pmod_led_4probe_continuous_2p2mhz_2cycles_10khz_uart.fs`。构建校验和及验证状态见 [发布说明](../burn_test/README_four_probe_continuous_20260911.md)。

- `python3 scripts/verify_scan_timing.py`：参数/波形计算检查，不冒充 RTL 仿真。
- `python3 scripts/verify_probe_sequence.py`：RTL 仿真（需要 Icarus Verilog）。
- `python3 -m unittest discover -s tests -p 'test_*.py'`：电脑协议脚本测试，不访问真实串口。
- Gowin `Run All` 或执行 `scripts/build_fpga.tcl` 后，构建产物在 `impl/pnr`。

本次修改前的5秒源码保存在 `burn_test/source_before_continuous_4probe_20260911.tar.gz`。旧5秒四探头FS为 `burn_test/pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs`，旧交付ZIP `handoff/FPGA_4PROBE_WINDOWS_HANDOFF_20260911.zip` 保留。更早的八路自动发射源码归档和 `FINAL…autostart.fs` 也未覆盖。

烧录新版本后先断开高压供电，确认上电无输出、S2 只选一路、超过 5 秒仍持续输出、再次按键能切换、USB STOP 能停机，再恢复已排障的高压链路。烧录新 FS 与“更新代码”是两件事，本次工具不自动给实际硬件下载或发送 START。
