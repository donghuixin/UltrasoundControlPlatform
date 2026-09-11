# Tang Primer 25K + HV7350 四探头发射控制

当前交付版：`fpga-hv7350-4probe-5s-usb-20260911`。同一块HV7350的TX1～TX4各接一个独立探头，一次只发射一路；不是四块HV板，也不再八路自动发射。

## 下载与Windows交接

- [完整交付ZIP](handoff/FPGA_4PROBE_WINDOWS_HANDOFF_20260911.zip)：烧录文件、源码、协议、Python/C#客户端、测试和回退包。
- [从这里开始](README_WINDOWS_HANDOFF.md)。
- [USB/Windows接口合同](docs/USB_WINDOWS_INTERFACE_HANDOFF.md) / [离线HTML](docs/USB_WINDOWS_INTERFACE_HANDOFF.html)。HTML下载后用浏览器打开。
- [Python/PyQt客户端](host/python/README.md) / [C#/.NET参考客户端](host/windows_dotnet/README.md)。
- [固件构建与位流校验](burn_test/README_four_probe_20260911.md)。

USB只传控制命令，不传ADC数据。本次提供集成SDK和接口合同，尚未把功能接入仓库既有Windows采集UI；AFE/TSW接收仍使用其自身驱动。

## 当前固件行为

- 上电静默。S2每次有效按下启动HV1→HV2→HV3→HV4→HV1；长按只触发一次。
- 每次发射5秒、PRF 10 kHz；期间再次按下立即中断前一路，切换下一路并重新计时。
- 2.2 MHz、2 cycles、正极性RTZ；完整主burst结束后等待140 ns，再输出100 ns负向消振脉冲。VNN设定为−30 V。
- 只有选定一路发射，其余通道PIN/NIN为0。这不是接收端模拟多路复用器。
- READY表示正在发射；DONE表示自然完成5秒。STOP清除DONE；S1不用。
- 每帧J11输出200 ns触发脉冲；J11上升沿后2 µs开始主burst。J10从主burst开始拉高50 µs。
- USB-C调试口虚拟串口：115200、8N1、无流控，FPGA RX=B3、TX=C3。
- USB支持START(指定HV1～HV4)、NEXT、STOP和STATUS。字节协议及错误处理以接口合同为准。

## 烧录、验证与重建

使用Gowin Programmer加载 `burn_test/pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs`。目标器件：`GW5A-LV25MG121NC1/I0`。先核对核心板，在VPP/VNN关闭时检查3.3 V时序。

FS SHA-256：`a4dfe8bd5030e336c011ed138eb02b064a19936257fac45c7c2f24a8aea0be63`。

`MANIFEST_SHA256.txt`校验ZIP交付文件；仓库额外的首页、Git忽略规则和ZIP自身不在此清单中。从本目录运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/verify_scan_timing.py
python3 scripts/verify_probe_sequence.py --full-duration
gw_sh scripts/build_fpga.tcl
```

RTL仿真需要Icarus/Verilator，重建需要Gowin。本版综合/布局布线通过，50 MHz约束下setup/hold违规端点为0；完整5秒RTL仿真及47项Python测试通过。C#源码尚未在开发机编译；Windows编译、真板USB联调和实际超声输出仍需验收。没有自动烧录或发送START。

## 回退与集成边界

- 上一版2.2 MHz、2 cycles、140 ns消振、八路上电自动发射FS保留在`artifacts/`及`burn_test/`；旧源码在`burn_test/source_before_four_probe_20260911.tar.gz`。
- 更早2 MHz纯正极性版本仍在`artifacts/`，原标签`fpga-hv7350-2mhz-2cycles-positive-20260829`保留。历史文档保留实验依据，当前控制以四探头接口合同为准。
- 先arm接收端，再发START；ACK到达前可能已开始发射，不能用ACK作采样触发。
- 超时表示结果未知，SEQ不去重，不能自动重发START/NEXT。
- 关闭串口或拔USB不立即停止；固件在该次5秒到期停止，需提前停止时显式STOP。
- S2仍可切通道，协议不能锁定按键；采集期间不操作S2，切换边界数据应丢弃。
- 这是实验室高压超声平台，不是医疗认证设备。软件STOP不等于硬件急停，VNN也不钳制压电端瞬时电压。回退前关闭高压，旧autostart位流配置完成即发射。

## 历史版本说明（仅供回退）

<details>
<summary>展开查看原八路自动发射版本与2 MHz回退基线</summary>

This directory contains the final fixed transmit/damping build and the original
2 MHz rollback baseline for the eight-channel HV7350 transmitter.

## Final selected behavior

- Automatic startup after FPGA configuration; no button press is required.
- Carrier: **2.2 MHz** (`DEFAULT_FREQ_WORD = 0x0B439581` at 50 MHz).
- Main burst: **2 cycles**, positive-unipolar RTZ.
- Beam profile: fixed **0 degrees** in this build.
- PRF: **10 kHz** (100 us between bursts).
- J11: 200 ns trigger pulse, exactly 2 us before each burst.
- J10: rises with the burst and remains high for 50 us.
- After the main burst: 140 ns at RGND, then one 100 ns negative damping
  pulse on NIN. The design assumes VNN is fixed at -30 V.
- S1 is disconnected. S2 is retained only as an optional emergency
  stop/restart input.
- READY and DONE are steady high while transmission is running.
- UART cannot override the fixed carrier or cycle count.

The 2.2 MHz/140 ns setting produced the lowest measured CH1 post-T/R-switch
ringing among the 2.0, 2.2, and 2.4 MHz experiments. A second negative pulse is
not included because its cancellation phase was not measured, and the existing
high-resolution CH2 captures already showed approximately -46 to -51 V
instantaneous ceramic-terminal excursions with VNN fixed at -30 V.

## Final programming artifacts

- `artifacts/pmod_led_FINAL_2p2mhz_2cycles_pos_fixed140ns_neg30v_100ns_autostart.fs`
  - SHA-256: `f2021537d6facac767b4c1101f1ee417342aa0bed40c74f4fc81953e3e0397bc`
- `artifacts/pmod_led_FINAL_2p2mhz_2cycles_pos_fixed140ns_neg30v_100ns_autostart.bin`
  - SHA-256: `c7d5b6ca0e9d24e5ba1b1ad210566be2e377a625278d652b2fc32f18fc824086`

Use the `.fs` file with Gowin Programmer. The transmitter starts automatically
as soon as FPGA configuration completes, so keep the high-voltage rails off
during programming and logic-level verification.

## Timing and measurement documentation

- `docs/final_tx_rx_timing.md`: exact J11/PIN/NIN timing, 13-20 mm range-gate
  calculation, analog blanking, template subtraction, and Doppler processing
  order.
- `docs/final_control_2p2mhz.md`: final parameter decision and comparison of
  the three carrier-frequency experiments.
- `docs/ringing_damping_results_2mhz.md`: 2.0 MHz delay sweep.
- `docs/ringing_damping_results_2p2mhz.md`: 2.2 MHz delay sweep and peak-voltage
  caution.
- `docs/beamformer_control.md`: complete FPGA behavior and wiring summary.
- `docs/hv7350_wiring.md`: FPGA-to-HV7350 wiring details.

## Original rollback baseline

The earlier 2.0 MHz, 2-cycle, positive-only build remains available and is
preserved by tag `fpga-hv7350-2mhz-2cycles-positive-20260829`:

- `artifacts/pmod_led_2mhz_2cycles_positive_10khz.fs`
  - SHA-256: `2387ddf2f2f56a7190c81315636add51abffe9f930ac46348b9a820e5a73b36d`
- `artifacts/pmod_led_2mhz_2cycles_positive_10khz.bin`
  - SHA-256: `ea99941ec9fade86d59ef353f1b2fe90e84e793dab2931ea57777460628a8714`

That tagged baseline has no negative damping pulse and requires manual button
control. It is retained only for rollback and comparison.

## Rebuild and verify

From this directory:

```bash
python3 scripts/verify_scan_timing.py
python3 scripts/configure_beamformer.py \
  --dry-run \
  --frequency-mhz 2.2 \
  --cycles 2 \
  --angle-deg 0 \
  --pitch-mm 1.0
gw_sh scripts/build_fpga.tcl
```

The Gowin project targets `GW5A-LV25MG121NC1/I0`. Generated `impl/` output is
not versioned; only named programming artifacts are committed.

## Safety boundary

This is an experimental high-voltage ultrasound pulser and is not a medically
certified system. Validate all 3.3 V logic signals with VPP/VNN disabled. The
final bitstream transmits automatically, and VNN=-30 V must not be treated as a
clamp on instantaneous ceramic voltage.

</details>
