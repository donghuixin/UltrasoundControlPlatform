# 四探头手动切换、持续发射固件

版本日期：2026-09-11。目标器件 `GW5A-LV25MG121NC1/I0`，50 MHz系统时钟。

烧录文件：`pmod_led_4probe_continuous_2p2mhz_2cycles_10khz_uart.fs`；同名 `.bin` 是同次构建产物，不是USB串口升级包。

此版本取消旧四探头版本的5秒自动停止：上电不发射，S2依次启动HV1、HV2、HV3、HV4，再回HV1。每路持续发射到下次切换或USB STOP；按键消抖20 ms，长按仅一次事件。运行中按键立即中断旧路、启动新路；不自动跨探头扫描。S1不使用。

READY运行时亮，待机/STOP后灭；DONE恒灭。USB-C仍支持START/NEXT/STOP/STATUS，115200 8N1，6字节请求、9字节回复，命令码与校验不变。FLAGS bit1保留completed字段位置但恒0；上位机不能再等待completed=1或DONE亮才结束录制。

载波2.2 MHz、2 cycles正向主burst、10 kHz PRF、主burst后140 ns延时加100 ns负向尾脉冲均不变。J11每100 μs输出一次200 ns触发，上升沿后2 μs开始主burst。仅选中的一路发射，其他PIN/NIN均为0（RTZ，不是高阻隔离）。

## 持续录制和停止

- 接收端先arm，再按S2或发USB START；不能等START ACK到达后才开始采集。
- 可以一直录制并按键切探头；切换可能截断旧J11/burst/J10，跨切换触发间隔不保证100 μs，丢弃受影响边界数据。
- 协议不传ADC数据，不控制接收通道复用，也没有每帧探头ID或按键时间戳。STATUS快照不能精确给每帧标注物理按键切换边界。
- **关闭串口/拔USB后，如果FPGA与高压仍供电，会一直发射，直到USB STOP或断电；不再有5秒自动停止兜底。** S2是换路键，不是停止键。USB STOP不是硬件急停；电气异常应使用硬件断高压措施。

接口细节见[Windows USB交接文档](../docs/USB_WINDOWS_INTERFACE_HANDOFF.md)，接线见[四探头控制说明](../docs/four_probe_control.md)。

## 构建与验证

- Gowin V1.9.11.03 Education综合/布局布线完成，新FS/BIN已生成。50 MHz约束下Fmax=126.242 MHz，setup/hold违规端点均为0。
- `hv7350_tx_channel` 波形发生模块与旧5秒版逐字一致；PIN/NIN、J11/J10及指示状态统一通过输出寄存器，避免直接输出组合译码毛刺。时序报告不等同于实物接线或模拟波形验收。
- Icarus短仿真及独立UART回归通过：去抖/长按、四路循环、负尾期间同路重启、精确J11/J10/PIN/NIN时序、115200串口和错误输入。
- Verilator完整6秒逐时钟仿真通过：300,000,000时钟、60,000完整帧（120,000个正脉冲、60,000个负尾），随后第60,001帧仍输出；经仿真中的真实波特率UART发送STOP后全部输出停止，保持S2按下不会误重启。DONE/FLAGS完成位始终为0，未force或跳过内部计时状态。
- Python客户端、持续录制示例及协议向量共53项离线测试通过；未打开真实串口或发送实际发射命令。
- C#源码参考需在Windows开发环境编译和串口联调；当前未声称已完成Windows或AFE/TSW实板联调。
- 本轮未自动烧录板卡，未通过真实串口发送发射命令。仿真及构建通过不等于实物声学输出已验收。

首次烧录先关闭高压，仅验证逻辑：上电静默、S2逐路切换、超过5秒不停止、DONE恒灭、USB STOP能停止；确认后再恢复已排障高压链路。

## SHA-256

```text
a9d1b8992abd552fc892cd0dcef2ba1092a25f14236accc9eaa43549509c07e5  pmod_led_4probe_continuous_2p2mhz_2cycles_10khz_uart.fs
f7a19b5ccd53db85ee851950aae8d451a6d069312d415ad488b38e48beb96d37  pmod_led_4probe_continuous_2p2mhz_2cycles_10khz_uart.bin
bd44c77c7ca46154bfba0dfa251d84fc8ab4aaaa52e45d3fdd0f330158367d3c  ../src/pmod_led.v
2e541e219ed58f7dd3b99c3d2f1028cebc4465651a3fa442811ee22dabeac1d0  ../src/probe_uart_control.v
bf30edf7f3532df75986d5d945a4dc7f13c80ba2e030af30d4e4b1aafcd038bc  ../src/pmod_led.cst
59c9daefac16ed8ce2c3b9f0e9fd6ab1bf47ec903af1737f3e60f57f0cd0f38a  ../src/pmod_led.sdc
2953c7d80572e4c30c8463c36c26c7f74905809f5f7353c943ee2d90de934e5d  ../pmod_led.gprj
2ddbb89d2af34e8df318836af80c4347c74f690a027001e6b9682e92bda076d8  source_before_continuous_4probe_20260911.tar.gz
```

## 回退文件

旧5秒四探头固件与交付包不覆盖：

- `pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs` / 同名 `.bin`。
- `README_four_probe_20260911.md`：旧5秒版本历史发布说明，内容仅适用于旧固件。
- `source_before_continuous_4probe_20260911.tar.gz`：本次修改前的源码备份。
- `../handoff/FPGA_4PROBE_WINDOWS_HANDOFF_20260911.zip`：旧5秒交付包。

持续发射新交付包：`../handoff/FPGA_4PROBE_CONTINUOUS_WINDOWS_HANDOFF_20260911.zip`。2026-09-15整理发布标签为 `fpga-hv7350-4probe-continuous-usb-20260915`，见[发布说明](../docs/RELEASE_CONTINUOUS_20260915.md)；本次未更改本页列出的FS、BIN和RTL。旧5秒版本标签不能代表本版。源码归档回退请先解压到独立目录，不直接覆盖当前工程。更早的 `FINAL…autostart.fs` 和消振测试固件仍作为历史备份保留。
