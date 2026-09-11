# Windows / Python 上位机接入

`fpga_probe_client.py` 是自包含的持久串口客户端，可以直接复制进 PyQt / PySide 等上位机工程。不依赖本仓库 `scripts` 目录，也不需要修改 FPGA 的 USB 协议。

## 连接与最小用法

1. 将固件对应的 Tang Primer 25K Dock **USB-C 数据口**接到 Windows。这里使用板载 USB-UART，不是 USB-A Host 接口。
2. 在设备管理器确认串口号（例如 `COM5`），并关闭占用这个串口的串口助手。一个串口只能由一个上位机拥有，不要为多个按钮各开一个客户端。
3. 在上位机使用的 Python 环境安装 `pyserial`：`python -m pip install pyserial`。
4. 将 `fpga_probe_client.py` 放入可导入路径，在工作线程里运行以下代码。**此示例会在明确调用 START 的那一行开始真实发射，不要未准备好采集就直接执行。**

```python
from fpga_probe_client import FpgaProbeClient

client = FpgaProbeClient("COM5", timeout=1.0, write_timeout=1.0)
status = client.connect(check_status=True)  # 显式选择 STATUS，不发送 START/STOP
print(status.active_probe, status.next_probe, status.running, status.completed)

# 先用 AFE / TSW 自己的 SDK 配置、启动采集并确认 external trigger 已 armed。
# 然后由用户操作调用：
# ack = client.start_probe(1)  # HV1 发射 5 s，中途调用会替换原会话
# ack = client.next_probe()   # 共享 S2 的下一通道顺序
# ack = client.stop()         # 明确停止，不会自动重发

status = client.get_status()  # 查询不会重新开始 5 s，也不会改变探头
client.close()                # 只关闭串口，不会停止 FPGA
```

`with FpgaProbeClient("COM5") as client:` 会连接并在退出时关闭串口，但不会自动发任何命令。构造对象也不会打开串口。`connect()` 不带参数只连接；`connect(check_status=True)` 才查询一次状态。**新连接默认 UNKNOWN，START / NEXT 会被客户端拦截，必须先显式 STATUS 或 STOP 成功确认状态。**

`example_integration.py` 提供可替换的 AFE SDK 接口及 `acquire_one_probe()`。直接运行该文件只打印说明，**不会打开串口或发送 START**；上位机明确调用函数才会发射。

## 接收与触发必须这样安排

- 串口只控制 FPGA 发射，不传回 ADC / 超声采样数据，也不会替你配置 AFE、TSW、采样率、增益或采集长度。
- **AFE/采集卡先 armed，之后才发送 START。** ACK 返回前，第一条 J11 已经可能产生；不能等 ACK 后才启动采集，也不能把 ACK 当采样时标。
- J11 每 100 µs 一个 200 ns 正脉冲，发射相对 J11 上升沿延后 2 µs。完整 5 s 会话包含 50,000 次触发；接收硬件是否支持持续触发、无间隙采集及足够缓冲，需要通过其 SDK 和硬件验证。
- 中途 START、NEXT、S2 切换或 STOP 会截断旧会话；不能继续假定该会话仍有 50,000 条有效记录。切换边界记录应作废，新的通道需要重新正确标记和接收准备。
- 程序关闭、`close()`、USB 断线、通信超时**不会立即停止 FPGA**；当前固件会自行完成剩余的 5 s，除非板上按键切换或新的 STOP 被成功接收。串口不是硬件急停。

## 在 Qt 中使用

客户端是同步 I/O。放在一个专用 worker / `QThread` 中，再通过信号把 `ProbeStatus` 或异常送回 UI；不要在 GUI 主线程调用。单次事务可能耗时约 `write_timeout + timeout`，UNKNOWN 状态的显式恢复另加 30 ms（等待其他调用的锁还会增加排队时间）。不要每次点击都重新连接。

同一实例内部用锁包住整个“写请求→读回复”，保证最多一个未完成请求。多个线程调用同一实例也不会交叉包，但 STOP 会等当前请求释放锁；默认最坏等待可能接近上述超时之和。线程锁不跨进程、不跨多个客户端实例。建议 UI 将按钮变成明确的排队操作，不并发堆积 START / NEXT。

`ProbeStatus` 字段：

| 字段 | 含义 |
|---|---|
| `command`, `sequence`, `result` | 回复关联命令、序号、结果（0 成功） |
| `active_probe` | 0 为空闲，1～4 为当前探头 |
| `next_probe` | 1～4，下一次 NEXT / S2 要启用的探头 |
| `running` | 发射会话运行中 |
| `completed` | 正常 5 s 完成，START / NEXT / STOP 清除 |

状态是命令被处理时的快照，不是实时量；S2、自动完成可能在 ACK 后改变它。要刷新显示，由上位机主动调用 `get_status()`；客户端不会创建后台轮询。RUNNING 和 COMPLETED 不能同时为 1；RUNNING 必须与 `active_probe != 0` 一致，客户端会验证这些条件。

## 错误与恢复策略

所有命令，包括 STATUS，均**只发送一次、不自动重发**。每次实际发送前序号加一（8 bit 回绕），超时后不回退；序号仅关联回复，**不是固件去重/幂等机制**。重复 START / NEXT 会真实重启/切换会话。

| 异常 / 状态 | 上位机处理 |
|---|---|
| `CommandRejected` | 已收到合法匹配回复，但 result=1（未知命令）或 2（参数错误）；异常的 `.response` 有状态快照 |
| `ResponseTimeout` | 没收到有效匹配回复；命令可能已经执行，`state_unknown=True` |
| `TransportError` | 串口打开/写/读/关闭错误或部分写入；可能未完整送达，也可能已执行 |
| `ProtocolError` | 收到校验正确且匹配的回复，但字段违反协议；不要当正常状态使用 |
| `NotConnectedError` | 尚未连接或端口已关闭；不会发送请求 |
| `StateUnknownError` | 当前 UNKNOWN，START / NEXT 被拦截；没有发送、没有消耗序号，先显式 STATUS / STOP |

超时、部分写入、读写异常或协议异常后，将界面状态显示为 **UNKNOWN**，不要恢复为“未发射”，也不要自动重发 START / NEXT。客户端会强制阻止 START / NEXT，直至合法匹配 ACK 重新确认状态；由用户或明确的应用恢复流程选择：

1. 显式 `get_status()`，读取当前状态；STATUS 为只读，若需要重试，也必须由调用者主动决定。
2. 或显式 `stop()`，收到成功 ACK 后确认停止。如果串口已经失效，需要用户先处理连接再显式查询/停止。

部分写入可能留下不完整请求，固件的包间超时为 10 ms。当且仅当调用者在 UNKNOWN 状态下**显式调用 STATUS / STOP**，客户端先尝试清除本地发送缓冲（transport 支持 `reset_output_buffer` 时），再等待 **30 ms 静默间隔**，然后只发送一次所请求的恢复命令。新连接首次显式查询也执行这一保护步骤。这不是后台重试或自动 STOP；正常已知状态的事务不增加此间隔。

30 ms 为解析超时留出余量，**不能保证 USB 驱动/桥接器中所有滞留字节都已清除**。若恢复命令仍失败，保持 UNKNOWN，由调用者处理连接、必要时关闭并重新连接后再显式 STATUS / STOP；不要拼接补发旧包剩余字节，也不要因为等待过就认定先前命令未执行。

收到合法匹配 ACK 后，`state_unknown` 恢复为 False（包括带 result=1/2 的合法拒绝回复，它仍报告状态）；`last_status` 保留最后合法快照，**即使 state_unknown=True 时也可能非空，不能把旧快照当作当前硬件状态**。close 会令 state_unknown=True。超时后 STATUS 只说明查询时状态，无法证明先前哪一轮 START 是否执行或采集是否完整。

协议没有设备 ID、固件版本 ID、鉴权或硬件急停 ACK。STATUS 成功不能确认选中了哪一块板或哪个固件版本；首次使用应核对烧录文件、COM 口及示波器测量。也不要与旧版调角度协议混用。

## 二进制协议

串口为 **115200、8N1、无流控**。请求 6 字节：`A5 5A cmd arg seq XOR(cmd,arg,seq)`。

| 操作 | cmd | arg |
|---|---:|---:|
| START | `10` | `01`～`04` |
| NEXT | `11` | `00` |
| STOP | `12` | `00` |
| STATUS | `13` | `00` |

回复 9 字节：`5A A5 cmd seq result active next flags XOR(cmd,seq,result,active,next,flags)`。flags bit0=RUNNING、bit1=COMPLETED。上述数字用十六进制表达。客户端忽略噪声、错误校验帧和不匹配的旧回复，整个读取的超时不会因噪声而延长。
