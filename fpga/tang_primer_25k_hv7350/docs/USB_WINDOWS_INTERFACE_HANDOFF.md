# FPGA 四探头发射板：Windows 上位机 USB 接口交接文档

文档版本：1.0 / 2026-09-11。适用固件：`pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs`。

本文是上位机开发接口约定，而不是仅供串口助手操作的说明。交付包含 FPGA RTL、已编译 FS/BIN、Python 客户端、C# 参考客户端、协议测试向量和离线测试。**未在用户 Windows 电脑、真实串口或高压板上完成联调；不得把仿真通过等同于实际声学输出已验收。**

## 1. 开发者先看这十条

1. USB-C → 板载调试器 USB-UART → FPGA；Windows 上表现为 COM 串口，**不是直接对 FPGA 使用 USB Bulk/HID 命令**。
2. 串口配置：115200、8N1、无流控、DTR/RTS 关闭。B3 是 FPGA RX，C3 是 FPGA TX。
3. 请求固定 6 字节，回复固定 9 字节；均为原始二进制，无回车换行、无字符串编码。
4. `START(1..4)` 指定一路立即开始 5 秒发射；`NEXT` 等同一次 S2；`STOP` 停止；`STATUS` 查询。
5. 上电不发射。一次只发射一路，5 秒满后停机，不自动切到下一探头。
6. 重复 START（即使同一路、同一 SEQ）也会重新计时。**SEQ 只是回显，不提供去重或“恰好执行一次”保证。**
7. 一次只允许一个普通请求在途；等匹配回复后再发送下一条。不要让 GUI 定时器排队积累 STATUS。
8. 超时/断线/部分写入后状态未知，禁止自动重发 START/NEXT；先显式 STATUS 或 STOP 恢复判断。关闭串口不等于停止发射。
9. AFE/TSW 必须先准备接收，再发 START；**每次超声采样以 J11 硬件触发为准，不能使用 USB ACK 的到达时刻。**
10. 本协议不传 ADC 数据、不选择 AFE 通道、不上传采样、不提供每帧探头编号/会话 ID，也没有固件版本和板卡 ID 查询命令。

## 2. 交付物和版本确认

| 文件/目录 | 用途 |
| --- | --- |
| `burn_test/pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs` | Gowin 可烧录位流 |
| 同名 `.bin` | 同次构建生成的二进制位流；不要当串口升级包发送 |
| `pmod_led.gprj`、`src/pmod_led.v`、`src/probe_uart_control.v` | 可重新构建的工程、四路状态机和 UART 协议逻辑 |
| `host/python/` | 可嵌入 Python/PyQt 上位机的持久连接客户端与示例 |
| `host/windows_dotnet/` | C#/.NET 参考客户端、控制台示例和离线自测；见其 README 的编译验证范围 |
| `scripts/control_probes.py` | 一次一条命令的联调工具，不建议 GUI 每次操作都启动一个进程 |
| `tests/probe_protocol_vectors.json` | 与 RTL 语义一致的请求/回复黄金向量 |
| `docs/four_probe_control.md` | 原理、波形及接线补充说明 |

目标 FPGA：`GW5A-LV25MG121NC1/I0`，50 MHz 系统时钟，3.3 V I/O。若换成不同型号/封装核心板，先核对器件和引脚约束，不能仅凭“25K”直接烧录。

本交付 FS 的 SHA-256：

```text
a4dfe8bd5030e336c011ed138eb02b064a19936257fac45c7c2f24a8aea0be63
```

Windows PowerShell 校验：

```powershell
Get-FileHash .\burn_test\pmod_led_4probe_5s_2p2mhz_2cycles_10khz_uart.fs -Algorithm SHA256
```

这是文件版本校验，不能通过 STATUS 判断实际板上正在运行哪个 FS。协议“v1”是本文约定，不是帧内字段。旧八通道角度配置协议及 `configure_beamformer.py` 不适用于本版本。

## 3. USB 连接与 Windows 串口初始化

### 3.1 物理连接

使用 Tang Primer 25K Dock 的 **USB-C 调试口** 和支持数据传输的 USB 线。该调试器提供 JTAG 与 UART 功能；板上 USB-A 是 Host 口，不用于这套控制协议。[Sipeed 官方板卡说明](https://wiki.sipeed.com/hardware/zh/tang/tang-primer-25k/primer-25k.html)

FPGA RX=B3、TX=C3 已与官方 UART 示例约束核对。正常底板通过内部连线连接调试器，不需要另加 USB-UART。不要同时把另一转换器的 TX 接到 B3，避免两个发送端互相驱动。[官方 UART 引脚约束](https://github.com/sipeed/TangPrimer-25K-example/blob/main/UART/simple_uart/src/top.cst)

### 3.2 识别 COM 口

1. 首次联调关闭高压电源，仅保留 FPGA/底板正常逻辑供电。
2. 插入 USB-C，在设备管理器的“端口（COM 和 LPT）”或端口枚举中确认对应设备。
3. 如果没有端口，检查数据线、USB-C 接口、设备枚举和对应底板调试器驱动。按该硬件版本的官方驱动说明处理，不要把未知驱动/未知 COM 口当作正确接口。
4. 同时连接 AFE/TSW 时会有其他 USB 设备，明确区分发射板 COM 口。不要向所有端口广播 START 来寻找板卡。
5. 允许用户选择并保存 COM 口；重新插拔后 COM 编号可能改变，重新枚举确认。当前交付不硬编码 VID/PID 或设备序列号。
6. 串口由一个上位机实例独占；关闭其他串口助手。烧录和运行时控制是不同操作，烧录结束后再打开运行时串口。

### 3.3 串口参数

| 项目 | 必须使用的值 |
| --- | --- |
| Baud rate | 115200 |
| Data / parity / stop | 8 / None / 1 |
| Hardware/software flow control | 全部关闭：无 RTS/CTS、无 DSR/DTR、无 XON/XOFF |
| DTR / RTS | False；不是复位或启动信号，不用来控制发射 |
| 读写模式 | 原始 bytes；不能用 ReadLine/WriteLine、UTF-8 字符串或终止字符 |
| 单次请求建议超时 | 写入最多 1 s，匹配回复最多 1 s；不是发射持续时间 |
| STATUS 轮询建议 | 100～200 ms 一次，并且上一条请求已结束；不要流水发送 |

打开 COM 本身不会复位 FPGA 或停止旧会话。SDK 在新连接后要求先 STATUS/STOP 确认状态，避免把“刚打开连接”当成“板卡已待机”。默认先用只读 STATUS，不自动发送 START。

pySerial 使用有限 `timeout`/`write_timeout`；读操作可能返回少于请求长度的字节，必须累计解析，不能假设一次 read 就是一帧。[pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)

## 4. 固件行为与状态模型

### 4.1 三种可报告状态

| 状态 | ACTIVE | FLAGS | READY / DONE | NEXT |
| --- | --- | --- | --- | --- |
| 上电待机或 STOP 后 | 0 | 00 | 灭 / 灭 | 上电为 1；STOP 后保留游标 |
| 正在发射 | 1～4 | 01 | 亮 / 灭 | 下一次 S2/NEXT 将启动的探头 |
| 自然满 5 秒 | 0 | 02 | 灭 / 亮 | 保留游标 |

FLAGS 值使用十六进制，只有 bit0 和 bit1 有效，正常不会同时为 1。上位机还应维护一个本地 **Unknown/未确认状态**：它不是 FPGA 返回值，而是连接刚建立或通信异常后的软件状态。Unknown 时显示“状态未确认”，不能显示“已停止”。

### 4.2 各操作的精确语义

| 操作 | 固件行为 |
| --- | --- |
| START N | 中止旧会话，选 N，开始全新 5 秒窗口；NEXT=N%4+1；清 DONE |
| START 当前 N | 也重新发 J11、重新计时，绝不是查询或保持运行 |
| NEXT | 启动 NEXT 所指探头，随后游标加一并在 4 后回到 1 |
| S2 有效按下 | 与 NEXT 相同；首次 HV1，随后 HV2/HV3/HV4/HV1 |
| STOP | 中止输出、清 DONE；NEXT 不变；待机时也允许 |
| STATUS | 不主动改变发射，返回处理时的状态快照 |
| 自然计时结束 | 停止输出、置 DONE；不自动启动下一路 |
| 无效命令/参数 | 返回错误，不因该命令改变发射；原计时仍继续 |

按键消抖 20 ms，长按只产生一次有效事件，释放也经过消抖。S1 不使用。S2 不再是开停切换键。

按键与 USB 共用同一游标。例如 USB `START 3` 后，下一次 S2/USB NEXT 启动 HV4。若事件恰好同一个系统时钟到达：有效 STOP 优先于 S2；有效指定 START 优先于 S2/NEXT。

本版本没有禁用 S2 的 USB 命令。自动采集期间应约定不操作 S2；否则仅靠稀疏 STATUS 轮询不能完整重建每次物理按键和会话边界。STATUS/无效请求本身不改变状态，不代表同时发生的按键或自然到期不会改变状态。

### 4.3 5 秒和波形

从新会话第一枚**对外 J11 上升沿**计时，连续发射窗口为 250,000,000 个系统时钟（50 MHz 标称下 5 秒）。10 kHz PRF，完整会话为 50,000 次触发和 50,000 组 burst。实际秒数/频率还受板上振荡器精度影响。

载波标称 2.2 MHz、2 cycles 正向主 burst、主 burst 结束后 140 ns 延时再加 100 ns 负向消振脉冲。只允许一个探头发射，HV5～HV8 固定不发射。未选中通道 PIN=NIN=0 对应原 HV7350 RTZ 状态，**不是高阻隔离**。

## 5. 请求帧：固定 6 字节

所有表内字节数值均为十六进制。各字段均为单字节，无多字节大小端问题；UART 按标准 LSB-first 发送。

| 偏移 | 字段 | 含义 |
| ---: | --- | --- |
| 0 | A5 | 请求帧头 1 |
| 1 | 5A | 请求帧头 2 |
| 2 | CMD | 命令码 |
| 3 | ARG | 参数 |
| 4 | SEQ | 请求序号 00～FF，回复原样回显 |
| 5 | XOR | CMD XOR ARG XOR SEQ；不包含帧头 |

| CMD | 名称 | 合法 ARG | 上位机入口 |
| --- | --- | --- | --- |
| 10 | START | 01、02、03、04 | 启动指定探头 5 秒 |
| 11 | NEXT | 00 | 启动游标所指的下一探头 |
| 12 | STOP | 00 | 停止发射 |
| 13 | STATUS | 00 | 查询状态 |

这里的 `10` 表示 `0x10`，不是十进制 10。发送 `A5 5A 10 01 00 11` 时应写入六个字节，**不是把这串字符编码后发出去**。串口助手需要 HEX 发送模式，不附加 CR/LF。

一次 write 发送整帧。解析器在接收半包时，若**相邻有效字节之间**超过约 10 ms 未到下一字节，将放弃半包；这不是“USB 打开后 10 ms”或“整个请求到回复 10 ms”。不要逐字节在 UI 线程 sleep 后发送。

### 5.1 SEQ 的限制

- 推荐客户端每条请求递增序号，FF 后回到 00；重连也不把它当硬件会话 ID。
- 固件不保存上一条 SEQ，不检测重复请求，不拒绝重复执行。
- 同一 START 或 NEXT 原样重发仍会执行，可能打断/延长采集或切换探头。
- 序号只有 8 位，不能用于跨长期会话、设备重连或跨设备唯一标识。

## 6. 回复帧：固定 9 字节

| 偏移 | 字段 | 含义 |
| ---: | --- | --- |
| 0 | 5A | 回复帧头 1，与请求反向 |
| 1 | A5 | 回复帧头 2 |
| 2 | CMD | 对应请求命令码 |
| 3 | SEQ | 对应请求序号 |
| 4 | RESULT | 00 成功；01 未知命令；02 已知命令但参数非法 |
| 5 | ACTIVE | 当前发射探头 01～04；不发射为 00 |
| 6 | NEXT | 下次 S2/NEXT 将启动的探头 01～04 |
| 7 | FLAGS | bit0=running，bit1=completed，bit2～7=0 |
| 8 | XOR | 偏移 2～7 六个字节异或；不包含帧头 |

有效回复必须同时满足：帧头和长度正确、XOR 正确、CMD/SEQ 匹配本次请求、RESULT 在 0～2、ACTIVE 在 0～4、NEXT 在 1～4、保留位为零、running 与 ACTIVE 非零一致、running 与 completed 不能同时为真。

RESULT=01/02 是明确的拒绝结果，不是成功 ACK；同时携带有效状态快照。上位机可以更新显示，但应向调用者报告命令被拒绝，而不是进入“已启动”分支。

错误 XOR、UART 起止位错误和超时半包被丢弃，**没有错误回复**。未知 CMD 则回复 RESULT=01（优先于参数错误）；已知 CMD 的非法 ARG 回复 RESULT=02。

正常结束没有主动 DONE 推送；物理 S2 也没有独立按键事件消息。需要知道结束时，轮询 STATUS 并结合采集端真实数据计数。ACTIVE=0、completed=1 仅说明当前可见的最近状态是自然结束，不证明某个上位机记录的会话 ID 已完成。

### 6.1 回复解析算法

1. 每次读取任意数量的 bytes，加入接收缓冲区。
2. 搜索 `5A A5`；移除前面的噪声，末尾单独一个 `5A` 留待下一次读取。
3. 不满 9 字节时继续等待；满 9 字节先验 XOR，再检查 CMD/SEQ 和字段。
4. 不合法或属于旧请求时继续寻找下一候选帧，不能把第一个 9 字节盲目当作回复。
5. 整个请求使用固定截止时间；持续垃圾数据不能无限延长等待。
6. 超时退出必须返回“执行结果未知”，不能据此断言“未发射”。

不能假设一次 SerialPort.DataReceived 事件等于一帧，也不能假设 read(9) 一定返回九字节。单请求在途时不需要把回复当连续 ADC 数据流处理。

## 7. 时序、超时与错误恢复

### 7.1 不把 ACK 当硬件触发

115200 8N1 每字节含 10 个串行位，6 字节请求约 0.521 ms，9 字节回复约 0.781 ms；这些仅为串行线占用时间，不包含 USB、Windows 驱动和线程调度延迟。建议 1 s 请求超时是工程默认值，不是 FPGA 响应时间保证。

固件校验完 START 就开始执行，随后发送状态回复。**在 Windows 收到完整 ACK 前，FPGA 已经可能发出多组超声 burst。** 因此必须先把接收设备置于等待 J11 的状态，最后才发送 START。

### 7.2 单请求串行化

上位机每块发射板只创建一个持久客户端实例。START/NEXT/STOP/STATUS 共用同一个互斥事务通道，覆盖“写整包 → 收到匹配回复/超时”的全过程。

固件可发送一包回复并缓存下一包，但这不是无限命令队列；继续灌包会丢回复，而命令可能仍执行。必须遵守单请求在途约定。FPGA 对 STOP 的执行不等待回复发送结束，但客户端 STOP 可能等待当前串口事务；它不是具有确定最大延迟的硬件急停。

UI 工作线程调用客户端，不在界面线程阻塞串口读写。一次 STATUS 完成后再安排下一次轮询；发射控制操作有优先级时，取消尚未发送的轮询/START，不要让它们排在 STOP 前面。

### 7.3 恢复流程

| 情况 | 上位机处理 |
| --- | --- |
| 新连接/重新连接 | 显示 Unknown；先显式 STATUS（或明确需要停止时 STOP） |
| START/NEXT 超时 | 不自动重发；显示 Unknown，禁止继续启动；发 STATUS 判断当前快照，必要时 STOP |
| 部分写入/写异常 | 可能留下半包；至少等待 20 ms 无新发送，再发恢复请求；不补发剩余半包 |
| STATUS 超时 | 本地状态仍 Unknown；由调用者决定再次 STATUS 或 STOP，不做无限重试 |
| STOP 超时 | 不能显示“已经停止”；保持 Unknown，重新建立通信并显式 STOP，电气异常时断高压 |
| 返回 RESULT=01/02 | 报告命令被拒绝，保留返回的有效状态；修正请求参数，不盲目重试 |
| 关闭应用/拔 USB | 不会即时停止 FPGA；若高压链路仍供电，当前会话会继续到原 5 秒期限 |
| 打开串口失败/被占用 | 不代表 FPGA 已停止；释放冲突程序或确认 COM，重新读取状态 |

此处 20 ms 是主机为等待固件半包解析超时留出的余量，不是停止的硬件时限。同步库的取消/Task 取消也不等于向 FPGA 发 STOP。

交付的持久客户端在 Unknown 状态下、调用者显式发起恢复 STATUS/STOP 时，会先清理主机待发送缓冲并留 30 ms 静默间隔；仍不保证异常 USB 驱动中的滞留数据一定被清空。持续通信异常时应重新确认连接并进行显式恢复，不继续启动新会话。

重连后即使 STATUS 报 running=1，也不能从协议获知已运行多久、该会话属于哪次 START。若此前采集关联已丢失，稳妥做法是显式 STOP，待接收端丢弃不完整数据、重新 arm 后再启动新的明确探头，而不是恢复一个无法识别的旧数据集。

## 8. Windows 开发调用方式

### 8.1 快速联调（Python CLI）

在交付包根目录运行：

```powershell
py -3 -m pip install pyserial
py -3 scripts\control_probes.py --list
py -3 scripts\control_probes.py --port COM5 status
py -3 scripts\control_probes.py --dry-run --seq 0 start 1
```

确认 COM 和逻辑测量正常、接收端已准备后，才发送实际动作：

```powershell
py -3 scripts\control_probes.py --port COM5 start 1
py -3 scripts\control_probes.py --port COM5 start 2
py -3 scripts\control_probes.py --port COM5 next
py -3 scripts\control_probes.py --port COM5 stop
```

上面四条是独立操作示例，**不是应当一口气粘贴执行的采集脚本**；连续 START 会马上切换，不会自动各等 5 秒。COM5 是占位，使用实际枚举值。CLI 每次独立开关端口，仅用于人工调试，不应作为主程序的并发控制架构。

### 8.2 Python/PyQt 集成

使用 `host/python/fpga_probe_client.py`，按其 README 初始化一次客户端并复用。提供连接、指定探头启动、NEXT、STOP、STATUS 和关闭方法。示例 `example_integration.py` 说明如何接入已有采集接口；其中 AFE/TSW API 只是适配位置，不是已经实现的采集驱动。

SDK 对整个事务加锁并递增 SEQ；出现通信异常后禁止再次 START/NEXT，先 STATUS/STOP 恢复。已有 GUI 应在工作线程中调用，把结果通过信号/事件发回 UI。业务层记录用户点击时间、CMD/SEQ、ACK、探头编号、采集文件名，但不要把主机时间戳当超声发射时间戳。

```python
from fpga_probe_client import FpgaProbeClient

fpga = FpgaProbeClient("COM5", timeout=1.0, write_timeout=1.0)
status = fpga.connect(check_status=True)  # 只打开连接并显式查询
print(status.active_probe, status.next_probe, status.running, status.completed)
# 由用户操作、且接收端已确认 armed 后才调用：
# ack = fpga.start_probe(1)
# ack = fpga.next_probe()
# stopped = fpga.stop()
status = fpga.get_status()
fpga.close()  # 不会发送STOP，不能据此判定停止
```

错误映射：`StateUnknownError` 表示未发送新START/NEXT；`ResponseTimeout`/`TransportError`/`ProtocolError` 表示不能确认硬件当前状态；`CommandRejected.response` 提供明确拒绝时的状态。`last_status` 可能是旧快照，显示状态时同时检查 `state_unknown`。

### 8.3 C#/.NET 集成

`host/windows_dotnet/` 提供 SerialPort 持久连接封装与控制台示例。依赖和调用方式以其 README 为准；在现有 WinForms/WPF 工程中引用客户端，使用异步调用方式，不在 UI 线程直接同步等待。

```csharp
using Hv7350.ProbeControl;

await using var fpga = new ProbeClient(await SerialPortTransport.OpenAsync("COM5"));
ProbeResponse status = await fpga.GetStatusAsync(); // 初次握手只读
// 接收端armed并由用户明确发起操作后：
// ProbeResponse ack = await fpga.StartAsync(1);
// ProbeResponse ack = await fpga.NextAsync();
// ProbeResponse stopped = await fpga.StopAsync();
// DisposeAsync仅关闭连接，不发送STOP。
```

WPF/WinForms 中应把客户端保存为应用/窗体级对象，而不是每次按钮都创建一个实例。`ProbeStateUncertainException` 后禁止继续启动；`ProbeRejectedException.Response` 是有效拒绝快照；`RequiresRecovery` 表示需先显式STATUS/STOP恢复，`ProbeBusyException` 表示当前命令没有发送。详细项目引用与取消语义见C#目录README。

C++/Qt、LabVIEW 等不需要更改 FPGA：按第 5～7 节实现同一字节协议即可。不能把 SDK 方法名误认为线上 ASCII 命令。若语言与示例不一致，黄金向量仍可作为语言无关的单元测试输入。

## 9. 与 AFE/TSW 采集系统的联合控制

推荐让同一个上位机控制两个独立对象：`TxBoardClient`（此协议）和 `AcquisitionAdapter`（已有 AFE/TSW 驱动）。它们不是同一个 USB 数据通道。

```text
上位机创建会话记录、选定探头 N
    → 配置对应 RX/ADC 通道与存储
    → 接收端 arm，确认已经在等待 J11
    → FPGA START N
    → 每枚 J11 硬件触发对应一次发射/采集
    → 采集端记录有效触发/帧数，上位机串行轮询 STATUS
    → FPGA 自然结束或显式 STOP
    → 接收端 drain/完成写盘，验证帧数与质量
    → 保存本探头结果，再开始下一探头
```

业务层若要“一键采完四个探头”，可以按 1～4 循环执行上述步骤；这是上位机编排，FPGA本身仍不会自动跨探头扫描。不能简单依靠四个 `Sleep(5000)`：主机延迟、提前切换和丢触发都需要采集端计数与状态确认。

完成一轮 5 秒理应有 50,000 组发射，但 STATUS 不返回已发帧数，必须由接收硬件/采集程序实际统计。若中途按 S2，可能截断原 J11、burst 或 J10，至少丢弃该旧边界帧，并标记旧会话未完整完成。协议不携带每帧通道 ID；高可靠自动采集期间不要混用物理按键。

### 9.1 每帧硬件时序

以选中探头对应的新 J11 上升沿为 0：

| 外部信号 | 高电平区间 |
| --- | --- |
| J11 | 0～0.200 μs |
| PIN | 2.000～2.240 μs，2.460～2.700 μs |
| NIN | 3.060～3.160 μs |
| J10 | 2.000～52.000 μs |
| 下一帧 J11 | 100.000 μs 起 |

所有输出共用寄存时序，通道切换有至少一拍 20 ns 全低间隔。切换会重置 PRF 相位，所以跨会话的 J11 间隔不保证 100 μs。J10是50 μs高电平的PRF参考，**不是“5秒采集使能”或“ADC必须只采50μs”的定义**。

J11只应接收端支持的、已核对电平与触发语义的数字输入。不能仅凭 AFE 或 TSW 的名称假定任意端口可外触发；其型号、采集固件和触发接口需要接收系统另行确认。

## 10. 接线速查

| 探头 | FPGA PIN → HV 板 H2 | FPGA NIN → HV 板 H2 | HV 板 TX 输出 |
| --- | --- | --- | --- |
| HV1 | B2 → H2.2 | F2 → H2.4 | H1.1 |
| HV2 | E1 → H2.6 | E3 → H2.8 | H1.5 |
| HV3 | J1 → H2.10 | G4 → H2.12 | H1.9 |
| HV4 | H1 → H2.14 | K7 → H2.16 | H1.13 |

FPGA 球位 H1 与驱动板连接器 H1 不是同一含义。B2/F2 等不是排针针序。CLK=H2.1、REN=H2.29、OEN=H2.31 维持原 3.3 V 逻辑使能接法；确认共地和实物第 1 脚方向。HV 输出不接 FPGA/USB 接口。未改变四路各自的 TR/RX 连接。

## 11. 联调验收清单

| 编号 | 操作 | 预期 |
| --- | --- | --- |
| A01 | 新固件上电，不按键不发送命令 | J11/J10/PIN/NIN全低；两灯灭 |
| A02 | STATUS | ACTIVE=0、NEXT=1、FLAGS=0 |
| A03 | START 1～4，逐路分别验收 | 只有指定路输出；其他三路和HV5～HV8无脉冲 |
| A04 | 一路不打断地运行 | READY约5秒；50,000枚J11；完成后DONE亮 |
| A05 | 运行中 NEXT / S2 | 旧路停止，新路开始新5秒与完整2μs提前触发 |
| A06 | START同一路 | 当前会话重启，计时重置，不是保持原期限 |
| A07 | HV4后NEXT | 回HV1；指定START 3后NEXT为HV4 |
| A08 | STOP后STATUS | ACTIVE=0、FLAGS=0，NEXT保留 |
| A09 | 自然完成后STATUS | ACTIVE=0、FLAGS=2，NEXT保留 |
| A10 | 错校验/不完整帧/错误停止位 | 不触发新操作，无正常ACK；原会话可继续 |
| A11 | 合法校验但START 5、未知CMD | 分别RESULT=2/1；原输出不因错误请求改变 |
| A12 | ACK丢失/串口拔掉 | 主机显示Unknown，不自动START重试；关闭串口不当作STOP |
| A13 | 先arm接收再START | 首枚J11被采集，帧数和探头标签一致 |

先关闭高压验证逻辑，再按已完成排障的安全接线恢复高压测量。USB STOP不是硬件急停；不应在未确认保护、接地和接收限幅的情况下进行人体测试。

## 12. 尚未提供的能力与后续扩展边界

当前没有：可变频率/PRF/持续时间、运行剩余时间、已发帧计数、会话编号、设备身份/固件版本查询、重复请求去重、S2禁用锁、异步开始/结束事件、ADC数据上传或接收多路复用控制。

如以后需要这些能力，应新增明确协议命令和兼容性/版本判断，不能让上位机向保留字段写入新含义并假设当前FPGA支持。本交付的开发与验收范围是：**Windows经USB串口选择HV1～HV4并启动/切换/停止5秒发射，同时为现有接收系统提供J11硬件同步。**

## 13. 黄金向量：上位机单元测试可直接使用

每行是独立用例，先建立相应初始状态，且处理时没有 S2/自然到期并发事件。`运行2→3` 表示 HV2 正在运行、NEXT=HV3。完整机器可读数据见 `tests/probe_protocol_vectors.json`。

| 场景/初始状态 | 请求 HEX | 预期回复 HEX |
| --- | --- | --- |
| 上电待机、NEXT=1；STATUS | `A5 5A 13 00 00 13` | `5A A5 13 00 00 00 01 00 12` |
| 待机；START HV1 | `A5 5A 10 01 01 10` | `5A A5 10 01 00 01 02 01 13` |
| 运行1→2；START HV2 | `A5 5A 10 02 02 10` | `5A A5 10 02 00 02 03 01 12` |
| 运行2→3；START HV3 | `A5 5A 10 03 03 10` | `5A A5 10 03 00 03 04 01 15` |
| 运行3→4；START HV4 | `A5 5A 10 04 04 10` | `5A A5 10 04 00 04 01 01 10` |
| 运行4→1；NEXT回HV1 | `A5 5A 11 00 05 14` | `5A A5 11 05 00 01 02 01 16` |
| 运行1→2；STOP保留NEXT=2 | `A5 5A 12 00 06 14` | `5A A5 12 06 00 00 02 00 16` |
| HV3已自然完成、NEXT=4；STATUS | `A5 5A 13 00 07 14` | `5A A5 13 07 00 00 04 02 12` |
| 运行2→3；未知CMD=FE | `A5 5A FE 00 08 F6` | `5A A5 FE 08 01 02 03 01 F7` |
| 运行2→3；START非法ARG=0 | `A5 5A 10 00 09 19` | `5A A5 10 09 02 02 03 01 1B` |
| HV3已完成、NEXT=4；NEXT非法ARG=1 | `A5 5A 11 01 0A 1A` | `5A A5 11 0A 02 00 04 02 1F` |
| HV2运行；重放相同START/SEQ，重新计时 | `A5 5A 10 02 02 10` | `5A A5 10 02 00 02 03 01 12` |

可在任意语言中验证：编码字节完全相同、分多次接收仍解码成功、校验错误不接受、SEQ不匹配不接受、两个flag矛盾不接受、超时不自动再发命令。以上不是让实物板连续执行的脚本，尤其重复 START 用例会重置硬件发射窗口。

## 14. 本次验证范围

- 已核对 RTL、引脚约束和上述 FS 的 SHA-256 对应关系；没有为了交接文档更改线上帧格式。
- 已完成 Gowin 综合/布局布线，50 MHz约束下setup/hold违规端点均为0。
- 本轮重跑真实 RTL：完整5秒，50,000次J11、100,000个正向脉冲、50,000个负尾；四路切换、开停、真实115200串口收发及错误输入回归通过。
- Python 客户端和协议向量通过离线假串口测试；不会在测试时启动实际发射。
- C# 客户端提供离线自测工程，但当前macOS环境无.NET SDK，未完成C#编译及Windows串口验证；接入前由Windows开发环境执行其README中的构建/自测。
- 未打开真实COM端口、未自动烧录、未声称完成AFE/TSW联合采集或高压实测。
