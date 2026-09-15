# Windows 发射板控制交接包

适用：Tang Primer 25K + 同一块HV7350前四路独立探头，S2/USB选择一路持续发射，10kHz PRF。上电不发射；取消原来的5秒自动停止。

## 从这里开始

1. **阅读接口合同**：[浏览器离线HTML](docs/USB_WINDOWS_INTERFACE_HANDOFF.html) / [Markdown](docs/USB_WINDOWS_INTERFACE_HANDOFF.md)。详细USB协议、上位机接口、异常处理和AFE/TSW同步都在这里。
2. **烧录固件**：`burn_test/pmod_led_4probe_continuous_2p2mhz_2cycles_10khz_uart.fs`。目标器件为 `GW5A-LV25MG121NC1/I0`，先核对实际核心板。代码和Gowin工程在 `src/`、`pmod_led.gprj`。
3. **选择客户端**：[Python/PyQt](host/python/README.md) / [C#/.NET参考](host/windows_dotnet/README.md)。持久连接，单请求在途，不自动重试START/NEXT。
4. **先STATUS联通**，再在接收端armed、逻辑测试通过后显式START。所有真实串口操作由集成人员主动执行，本包测试不打开硬件。

## 最小Windows联调

```powershell
py -3 -m pip install pyserial
py -3 scripts\control_probes.py --list
py -3 scripts\control_probes.py --port COM5 status
```

COM5需替换为发射板USB-C调试器的实际串口。STATUS是状态查询，不会发射。`start 1`到`start 4`、`next`和`stop`是实际动作命令，确认硬件与接收准备后才发送。

## 核验和测试

- 位流SHA-256：`a9d1b8992abd552fc892cd0dcef2ba1092a25f14236accc9eaa43549509c07e5`。构建及校验详情见[持续发射版发布说明](burn_test/README_four_probe_continuous_20260911.md)。
- `MANIFEST_SHA256.txt` 列出ZIP内全部交付文件的校验和；不包含它自身。
- 离线Python测试：`py -3 -m unittest discover -s tests -p "test_*.py"`，本版53项通过。
- FPGA仿真：`scripts/verify_probe_sequence.py`，需要Icarus；`--full-duration`可用Verilator加速。本版短仿真及完整6秒（300,000,000时钟）验证通过：60,000帧后仍继续输出，随后UART STOP成功停止。
- C#项目目前是源码参考，未在本机编译；在Windows执行该目录README中的build和自测，再做真板联调。

## 必须保留的集成约束

- USB传控制命令，不传ADC数据。AFE/TSW接收需要自身驱动和硬件触发支持。
- START在ACK到达前就可能开始发射，必须先arm接收，用J11同步。
- **关闭COM/拔USB后，只要FPGA及高压链路仍供电，就会一直发射，不会再在5秒后自动停止。** 停止需发送USB STOP或断电；电气故障应使用硬件安全措施。
- 超时代表结果未知。SEQ没有去重功能，不能自动重发START/NEXT。
- S2每次切换HV1→HV2→HV3→HV4→HV1，不作停止键。READY运行时亮，DONE恒灭，FLAGS bit1恒0；旧软件不能继续等completed=1作为采集结束条件。
- 可以连续录制接收数据；切换可能截断旧触发/波形，切换边界数据应丢弃。协议不提供每帧探头ID，STATUS只能查到当前快照，不能精确标注每次物理按键的切换帧。

本包没有自动烧录、自动发送START或自动更新驱动的安装程序。持续发射交付包为 `handoff/FPGA_4PROBE_CONTINUOUS_WINDOWS_HANDOFF_20260911.zip`，不包含Git历史。旧5秒FS、旧交付ZIP及其发布说明保留供回退，不能与本版混用。

仓库位置：[GitHub的FPGA目录](https://github.com/donghuixin/UltrasoundControlPlatform/tree/main/fpga/tang_primer_25k_hv7350)。2026-09-15整理发布标签为 `fpga-hv7350-4probe-continuous-usb-20260915`，详见[发布说明](docs/RELEASE_CONTINUOUS_20260915.md)。固件仍是2026-09-11已构建、验证的持续发射位流，本次未改载波或重新烧录实板。旧标签 `fpga-hv7350-4probe-5s-usb-20260911` 对应5秒版，仅供回退。
