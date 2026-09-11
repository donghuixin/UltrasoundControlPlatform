# 四探头 5 秒顺序发射固件

构建日期：2026-09-11。Gowin V1.9.11.03 Education，目标器件 `GW5A-LV25MG121NC1/I0`。

烧录文件：`pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs`。

本版本上电不发射；S2 依次启动 HV1、HV2、HV3、HV4，每次 5 秒，运行中再次按下立即切下一路。其余通道不发射。2.2 MHz、2 cycles、10 kHz PRF、140 ns 后 100 ns 负向尾脉冲保持不变。USB-C 串口支持 START/NEXT/STOP/STATUS。

详细接线、灯逻辑、采集配合与电脑指令见 [四探头控制说明](../docs/four_probe_control.md)。FPGA 固件仅控制发射及同步，不替代 AFE/TSW 接收采样固件。

## 构建核对

- 实际综合与布局布线完成，FS/BIN 已生成。
- 50 MHz 约束；实现报告 Fmax=125.984 MHz，setup/hold 违规端点均为 0。
- PIN/NIN、J11、J10 均经输出寄存器，避免将组合译码毛刺直接输出。
- 时序报告约束覆盖板内逻辑，不等同于实物接线、模拟波形或换能器安全验证。
- 未自动烧录板卡，未通过串口发送任何发射命令。

## 验证结果

- Icarus 实际 RTL 集成：启动静默、消抖/长按、HV1～HV4 循环、运行中切换、同路负尾期间重启、STOP、每拍波形和 250,000,000 计数边界均通过。
- 独立 UART RTL：实际 50 MHz / 115200 8N1，错误校验、半包超时、帧错误、break、ACK、排队及全双工测试通过。
- Python 串口协议脚本 11 项单元测试通过，未访问真实串口。
- 最终注册输出版 Verilator 完整 5 秒 RTL 仿真通过：50,000 次 J11、100,000 个 PIN 正脉冲、50,000 个 NIN 消振脉冲；严格 5 秒停止，未选通道始终为 0。
- 原 `hv7350_tx_channel` 波形发生模块逐字保留；所有对外时序统一注册延迟一拍，相对 J11 的时序不变。

这些是仿真与编译结果，不代表实物已经烧录或实际超声信号已验收。

## SHA-256

```text
a4dfe8bd5030e336c011ed138eb02b064a19936257fac45c7c2f24a8aea0be63  pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs
d2da650eb6ee7402c2b291aa8091d9dffe574cd68f8593616d4190e4d32f5e63  pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.bin
2c51b5dc3dbdf6c35febb9afa8eff8feece01580b7d7226a4fa49e221af85e3c  ../src/pmod_led.v
2e541e219ed58f7dd3b99c3d2f1028cebc4465651a3fa442811ee22dabeac1d0  ../src/probe_uart_control.v
b9c9432076bd41fc433021dd68ed29fc27379191da14cbcd8f53dee114ca06b8  ../src/pmod_led.cst
59c9daefac16ed8ce2c3b9f0e9fd6ab1bf47ec903af1737f3e60f57f0cd0f38a  ../src/pmod_led.sdc
2953c7d80572e4c30c8463c36c26c7f74905809f5f7353c943ee2d90de934e5d  ../pmod_led.gprj
```

## 旧版回退

旧版八路自动发射 FS 未覆盖：`pmod_led_FINAL_2p2mhz_2cycles_pos_fixed140ns_neg30v_100ns_autostart.fs`。

```text
f2021537d6facac767b4c1101f1ee417342aa0bed40c74f4fc81953e3e0397bc  pmod_led_FINAL_2p2mhz_2cycles_pos_fixed140ns_neg30v_100ns_autostart.fs
043ef8326c2de4fdb226321bb56e1905436890fb5f5fe6b289bc4c86e83d14a4  source_before_four_probe_20260911.tar.gz
```

如需旧代码，先把旧源码归档解压到独立目录，不要直接覆盖当前工程。固件构建时使用本地归档保存回退点；后续GitHub更新记录见仓库提交与版本标签。
