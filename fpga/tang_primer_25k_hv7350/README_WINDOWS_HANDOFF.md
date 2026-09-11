# Windows 发射板控制交接包

适用：Tang Primer 25K + 同一块HV7350前四路独立探头，S2/USB选择一路，每次5秒，10kHz PRF。上电不发射。

## 从这里开始

1. **阅读接口合同**：[浏览器离线HTML](docs/USB_WINDOWS_INTERFACE_HANDOFF.html) / [Markdown](docs/USB_WINDOWS_INTERFACE_HANDOFF.md)。详细USB协议、上位机接口、异常处理和AFE/TSW同步都在这里。
2. **烧录固件**：`burn_test/pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs`。目标器件为 `GW5A-LV25MG121NC1/I0`，先核对实际核心板。代码和Gowin工程在 `src/`、`pmod_led.gprj`。
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

- 位流SHA-256：`a4dfe8bd5030e336c011ed138eb02b064a19936257fac45c7c2f24a8aea0be63`。
- `MANIFEST_SHA256.txt` 列出ZIP内全部交付文件的校验和；不包含它自身。
- 离线Python测试：`py -3 -m unittest discover -s tests -p "test_*.py"`。
- FPGA仿真：`scripts/verify_probe_sequence.py`，需要Icarus；完整5秒可选Verilator。完整5秒已在开发环境重跑通过。
- C#项目目前是源码参考，未在本机编译；在Windows执行该目录README中的build和自测，再做真板联调。

## 必须保留的集成约束

- USB传控制命令，不传ADC数据。AFE/TSW接收需要自身驱动和硬件触发支持。
- START在ACK到达前就可能开始发射，必须先arm接收，用J11同步。
- 关闭COM/拔USB不立即停止发射；STOP才是命令停止，电气故障应使用硬件安全措施。
- 超时代表结果未知。SEQ没有去重功能，不能自动重发START/NEXT。
- S2仍能随时改变探头；自动采集中约定不操作S2，此协议不能锁定按键。

本包没有自动烧录、自动发送START或自动更新驱动的安装程序。ZIP交付包不包含Git历史，提供源文件、固定FS和校验清单；版本历史请查看[GitHub仓库的FPGA目录](https://github.com/donghuixin/UltrasoundControlPlatform/tree/main/fpga/tang_primer_25k_hv7350)。本版标签为 `fpga-hv7350-4probe-5s-usb-20260911`。
