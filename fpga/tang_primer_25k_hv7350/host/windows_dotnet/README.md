# Windows / C# 上位机集成参考

这是 HV7350 四探头发射控制协议的独立 C# 库和命令行示例，不依赖 WPF、WinForms 或 AFE/TSW 的采集 SDK。USB 只承载控制命令，**不通过此接口传输超声采样数据**。

交付状态：源码已按当前 RTL 协议核对；开发环境没有 `dotnet`、`csc`、`mcs`、`msbuild`，因此 **C# 项目尚未在本机编译，自测尚未执行，也没有做 Windows + 真板串口联调**。下面的测试命令应由 Windows 集成人员执行，不能把此目录视为已验证的二进制驱动。

## 1. 文件与平台

| 文件 | 用途 |
|---|---|
| `ProbeControl/ProbeProtocol.cs` | 请求封包、响应解码、固定容量字节流解析器 |
| `ProbeControl/SerialPortTransport.cs` | `System.IO.Ports.SerialPort` 适配，115200 / 8N1 |
| `ProbeControl/ProbeClient.cs` | 持久连接、异步命令、互斥、超时与不确定状态处理 |
| `ProbeControl.Cli/Program.cs` | 无 GUI 的实际串口操作示例 |
| `ProbeControl.Tests/Program.cs` | 不连接设备的协议及假 transport 自测 |

示例目标框架是 `net8.0`，NuGet 包固定为 `System.IO.Ports 8.0.0`，便于已有 .NET 8 Windows 上位机直接引用。更新框架或包版本时应重新做编译和串口联调。本示例不是 .NET Framework 4.x 直接可编译项目；若旧上位机使用 .NET Framework 4.8，需要移植语言/API 特性，或者把此库放在独立进程并明确设计进程间接口。

在 Windows 安装匹配 SDK 后，于仓库根目录执行 PowerShell 命令：

```powershell
dotnet restore host/windows_dotnet/ProbeControl.Cli/ProbeControl.Cli.csproj
dotnet build host/windows_dotnet/ProbeControl.Cli/ProbeControl.Cli.csproj -c Release
dotnet run --project host/windows_dotnet/ProbeControl.Tests/ProbeControl.Tests.csproj -c Release
```

自测不打开 COM 口，不触发发射；但首次构建需要恢复 Microsoft 的 `System.IO.Ports` NuGet 包。它覆盖黄金字节、碎片/粘包/噪声/坏校验、匹配 CMD/SEQ、超时不重发、部分写入、取消、明确拒绝、恢复状态及并发上限。

## 2. 接口和基本操作

连接发射板 Dock 的板载 USB-C 调试口，在 Windows 设备管理器选择它对应的 COM 口。不要把 AFE/TSW 的采集接口误当成本接口。不要同时用串口助手、下载工具和上位机占用同一个串口；枚举 COM 口并不能证明连接的是正确设备。

串口配置固定：115200 baud、8 data bits、No parity、1 stop bit；`Handshake.None`、`DtrEnable=false`、`RtsEnable=false`，无需 CTS/RTS/DTR。使用二进制 `byte[]`，不能 `WriteLine()`，不能把 `"A5 5A ..."` 作为 ASCII 字符发出。

```powershell
# 只枚举，不发数据
dotnet run --project host/windows_dotnet/ProbeControl.Cli -- list

# 只读取发射状态
dotnet run --project host/windows_dotnet/ProbeControl.Cli -- COM5 status

# 显式启动 HV1 持续发射；此一次性命令先做 STATUS 确认，再发 START
dotnet run --project host/windows_dotnet/ProbeControl.Cli -- COM5 start 1

# 显式停止
dotnet run --project host/windows_dotnet/ProbeControl.Cli -- COM5 stop

# 集成验证建议用持久连接；进入 shell 本身不发命令
dotnet run --project host/windows_dotnet/ProbeControl.Cli -- COM5 shell
```

`shell` 中先输入 `status`，之后才能输入 `start 1`、`start 2`、`start 3`、`start 4`、`next`、`stop`。输入 `quit` 仅关闭串口，不会发送 STOP。若出现“状态不确定”，必须明确输入 `status` 或 `stop`；shell 不会偷偷补发原 START/NEXT。

注意：每次新建一次性 CLI 进程都先打开串口；正式上位机应始终复用一个连接，避免频繁开关 COM、相互抢占和恢复状态丢失。

## 3. 引入已有上位机

推荐添加 `ProjectReference` 指向 `ProbeControl.csproj`，然后 `using Hv7350.ProbeControl;`。也可以将 `ProbeControl` 目录内三个 `.cs` 文件复制到现有 `net8.0` 项目，并添加 `System.IO.Ports` 包；如果原工程没有启用隐式 using，需要补齐 `System`、`System.IO`、`System.Linq`、`System.Threading` 和 `System.Threading.Tasks` 等命名空间。

连接按钮只打开串口并主动读取状态，不能隐含 START：

```csharp
using Hv7350.ProbeControl;

ProbeClient? fpga; // 窗体/应用级字段：所有按钮、采集流程复用它。

async Task ConnectFpgaAsync(string comPort)
{
    if (fpga is not null) throw new InvalidOperationException("Already connected.");
    var candidate = new ProbeClient(await SerialPortTransport.OpenAsync(comPort));
    try
    {
        ProbeResponse status = await candidate.GetStatusAsync();
        // 根据 status 更新 UI；这只是响应时刻的快照，可能已被 S2 改变。
        fpga = candidate;
    }
    catch
    {
        await candidate.DisposeAsync(); // 不会发送 STOP，也不能假定板卡已停止。
        throw;
    }
}

async Task StartSelectedProbeAsync(int probe)
{
    if (fpga is null) throw new InvalidOperationException("Not connected.");
    // 此前先让 AFE/TSW 进入可接收 J11 触发的采集状态。
    ProbeResponse accepted = await fpga.StartAsync(probe);
    // ACK 表示命令已处理；持续发射，不存在五秒完成事件。
}

async Task StopAndDisconnectAsync()
{
    if (fpga is null) return;
    ProbeResponse stopped = await fpga.StopAsync();
    if (stopped.Running) throw new InvalidOperationException("STOP not confirmed.");
    await fpga.DisposeAsync();
    fpga = null;
}
```

如果 STOP 失败，例子不会把异常吞掉并显示“已安全停止”。应用应提示“停止未确认”，保留明确重试 STOP/查询 STATUS 的入口；若决定强制关闭 COM，仍不得宣称发射已停止。关闭 COM、退出进程、拔 USB、取消 `CancellationToken` 都不是硬件停止指令，**新固件没有五秒自动停止兜底，会一直发射**。S2 只切换探头，不是停止按钮。

在 WPF/WinForms 事件里直接 `await` 这些方法，不能用 `.Result` 或 `.Wait()` 卡住 UI。库内部只让持锁请求创建一个同步串口 I/O 工作任务；库不会回调 UI，也不执行后台轮询。取消令牌只取消等待，不会替用户发送 STOP。

## 4. 命令语义和状态

| API | 作用 |
|---|---|
| `GetStatusAsync()` | 获取状态，不改变发射、不重启帧 |
| `StartAsync(1..4)` | 持续启动所选一路；正在发射也立即切换/重启所选路，从新触发帧开始 |
| `NextAsync()` | 与一次 S2 按下事件等效，持续启动 NEXT 指定通道 |
| `StopAsync()` | 明确停止当前输出，NEXT 游标保留；接收软件可继续录制 |
| `DisposeAsync()` | 等待正在进行的交换退出后关闭串口；绝不隐含 STOP |

“立即”指 FPGA 解析有效命令后执行，不包括 Windows 排队、USB 和 UART 传输延迟；它不是硬实时急停。S2 另有约 20ms 防抖。STOP 与更换通道可以截断正在发射的 burst；不是等待当前 burst 完成。

`ProbeResponse` 是每次命令处理后的快照：

- `ActiveProbe=0` 表示空闲，1～4 表示正在发射的通道。
- `NextProbe=1..4` 表示下一次 NEXT/S2 要启动的通道。START(n) 将 NEXT 更新为 n+1，4 后回到 1。
- `Running=true` 表示会话正在进行。
- `Completed` 是旧限时固件的兼容字段，**当前持续版恒 false**；新流程不能轮询该字段等待结束。解码器仍接受旧版合法的空闲 COMPLETED=1 回复，不表示本示例会等待自然完成。
- 协议没有上电 ID、固件版本、会话号、剩余时间、完成事件或 S2 推送消息。SEQ 只用于回包匹配，8bit 回绕，固件不靠它做去重。

四探头均由用户选择：界面 HV1～HV4 按钮分别绑定 `StartAsync(1)`～`StartAsync(4)`，下一路绑定 `NextAsync()`；实体 S2 改变同一 NEXT 游标。接收端启动一次持续录制，切换通道不重启接收。SDK 本身不做自动顺序扫描，也不自动轮询或停止。

以下是绑定显式用户操作的框架，不是依次自动调用的扫描循环。`ArmReceiverContinuousAsync`、`FinishReceiverAsync` 及保存数据功能由现有 AFE/TSW SDK 实现，不属于本库。接收应使用独立工作线程持续分块落盘，验证丢帧/溢出，不以固定 50,000 帧为结束条件：

```csharp
bool receiverArmed = false; // 应用层标志，不等于实时接收硬件健康状态。

async Task BeginRecordingAsync() // “开始录制”按钮，不自动发射。
{
    if (fpga is null) throw new InvalidOperationException("Not connected.");
    if (receiverArmed) throw new InvalidOperationException("Already recording.");
    if ((await fpga.GetStatusAsync()).Running)
        throw new InvalidOperationException("Explicitly STOP before initially arming reception.");
    if (!await ArmReceiverContinuousAsync()) // 必须真实确认已能接收 J11 触发。
        throw new InvalidOperationException("Receiver not armed; START was not sent.");
    receiverArmed = true;
}

async Task ChooseProbeAsync(int probe) // HV1～HV4 按钮；不重启接收。
{
    if (fpga is null || !receiverArmed) throw new InvalidOperationException("Arm receiver first.");
    ProbeResponse ack = await fpga.StartAsync(probe);
    if (!ack.Running || ack.ActiveProbe != probe)
        throw new InvalidOperationException("START not confirmed; mark UNKNOWN and recover explicitly.");
    // 记录请求前后主机时间及 ack，不把 ACK 当作精确换路采样时刻。
}

async Task NextProbeAsync() // “下一路”按钮；物理 S2 也可操作。
{
    if (fpga is null || !receiverArmed) throw new InvalidOperationException("Arm receiver first.");
    if (!(await fpga.NextAsync()).Running)
        throw new InvalidOperationException("NEXT not confirmed; recover explicitly.");
}

async Task StopTransmissionAsync() // “停止发射”按钮；接收仍继续。
{
    if (fpga is null) throw new InvalidOperationException("Not connected.");
    if ((await fpga.StopAsync()).Running)
        throw new InvalidOperationException("STOP not confirmed.");
}

async Task EndRecordingAsync() // 用户先停止发射，再点“结束录制”。
{
    if (fpga is null || !receiverArmed) throw new InvalidOperationException("Not recording.");
    if ((await fpga.GetStatusAsync()).Running)
        throw new InvalidOperationException("Explicitly STOP before closing reception.");
    // 此后也要避免其他人按 S2：查询并不能锁定物理按钮。
    await FinishReceiverAsync(); // 核对实际采样/触发计数、溢出和丢帧，完成落盘。
    receiverArmed = false;
}
```

界面操作要序列化，阻止反复点击堆积选择请求；接收 SDK 的取数线程不能被控制串口的等待堵塞。SDK 异常由应用显示并提供明确的 STOP/STATUS 恢复操作，不要在 `finally` 偷偷启动/重试/停止真实硬件。

J11 才是每个 burst 的硬件采样参考。FPGA 在处理 START 后即可产生首个 J11，串口 ACK 到 PC 时首个或多个触发可能早已发生。**J11 没有通道编号，本协议也没有 S2 事件推送，STATUS 无法精确识别按键换路对应哪一帧。** 记录连续原始数据与命令/状态日志，标记不确定换路区间；不能直接把最后一次 STATUS 的通道当作每帧确切标签。切换可能截断旧 J11/burst，新旧触发间隔不保证 100µs，应作废边界帧；接收 SDK 必须能处理这些间隔。需要精确逐帧通道标签须扩展硬件/协议。

## 5. 超时、取消、重连：必须按“不确定”处理

默认读切片 20ms、一次写入超时 250ms、写入返回后的总响应期限 1000ms；噪声和坏包不会延长总期限。最多允许一个正在交换的请求和一个排队请求，再多直接抛 `ProbeBusyException`，不会写串口。排队本身最多等待 1500ms。

STOP 也服从同一个互斥锁，不能穿插正在发送的命令。正常驱动行为下，它可能先等待前一条命令约 250+1000ms，再完成自己的交换；恢复分包还可能增加 30ms 安静窗口。若队列已满或等待超时，STOP 会明确失败，不能显示“已停止”。这些是软件超时设置，不是 Windows/USB 故障下的硬实时最坏时延承诺。真实安全急停应另有硬件措施。

| 情况 | 库行为 / 上位机处理 |
|---|---|
| 参数错误、队列满、排队超时、写入前取消 | 未发送该命令，分别抛参数/Busy/取消异常 |
| 写入前清理缓冲等串口操作失败 | 未发送本条命令，但连接已失去确认，`RequiresRecovery=true`；显示串口故障 |
| 完整合法回包且 RESULT=1/2 | 保存状态并抛 `ProbeRejectedException`，这是明确拒绝，不是通信结果未知 |
| 发生写入后超时、部分写入、USB I/O 故障、取消 | 抛 `ProbeStateUncertainException`，`RequiresRecovery=true`；FPGA可能已经执行 |
| 新连接 | `RequiresRecovery=true`，只允许先明确查询 STATUS 或发送 STOP |
| 不确定状态下 START/NEXT | 抛 `ProbeRecoveryRequiredException`，不发数据 |
| 明确 STATUS/STOP 收到匹配且合法回包 | 恢复已确认通信状态；仍须检查 Running 等字段和拒绝结果 |

关闭连接也会设置 `RequiresRecovery=true`；`LastResponse` 保留的只是历史快照，不应被 UI 当成离线后的实时状态。

严禁超时后盲目重发 START/NEXT：固件不去重，再发会切换通道/重启发射帧。示例不会重试任何命令。恢复 STATUS/STOP 前会清除主机未发送缓冲，等待 30ms，使 FPGA 的 10ms 半包超时有机会复位，再清除旧接收数据并发送一个新 SEQ 的请求。这只能恢复普通串口分包，不能证明已损坏的 USB 驱动没有滞留数据；失败时应重新连接后再明确 STOP/STATUS。

使用者可以在日志记录时间、COM、CMD、SEQ、RESULT、ACTIVE、NEXT、FLAGS、异常；但 SEQ 不是认证或设备身份，XOR 也不是强 CRC。现场请使用短且可靠的 USB 连接。不要把某个 STATUS 成功当成发射高压、探头连接或接收数据正常的证明。

## 6. Windows 验收清单

1. 执行编译、自测；串口未连接时自测仍应通过。
2. 真板上电无输出，连接 COM 和 STATUS 不触发高压，两个进程不能同时占用端口。
3. 在低风险负载/测量条件下分别显式 START(1..4)，确认只有所选路持续发射，超过五秒仍有 J11，COMPLETED 始终为 0。
4. 工作中 START 另一通道、同通道 START、NEXT、STOP，核对换路/重启触发帧/明确停止行为；S2 同样测试，但 S2 只换路、不停止。
5. 工作中关闭 COM / 拔 USB，确认软件显示“未确认”，而不是假定停止；重新连接后先 STATUS/STOP，不自动 START。
6. 模拟回包丢失、错误 COM、串口被占用，UI保持响应，START/NEXT 不自动补发。
7. 用 AFE/TSW 实际确认先 Arm 后 START 可以保留第一个 J11，换路不重启接收，持续分块落盘无溢出；不确定换路边界正确标记，不冒充精确逐帧通道标签。结束录制前明确 STOP 并验证。

## 7. Microsoft API 依据

实现采用带有限 `ReadTimeout` / `WriteTimeout` 的同步二进制读写，并置于互斥后台任务。没有把 `BaseStream.ReadAsync` 的取消行为误当成串口超时，也没有把 `DataReceived` 事件当作完整一帧：Microsoft 明确说明该事件并非每字节触发，且发生于辅助线程。

- [SerialPort 官方 API/示例源代码](https://github.com/microsoft/referencesource/blob/main/System/sys/system/IO/ports/SerialPort.cs)
- [DataReceived 线程与事件边界说明](https://learn.microsoft.com/en-us/dotnet/api/system.io.ports.serialport.datareceived)
- [System.IO.Ports 当前实现](https://source.dot.net/System.IO.Ports/System/IO/Ports/SerialPort.cs.html)
- [Microsoft 记录的串口 WriteTimeout 驱动差异](https://github.com/dotnet/runtime/issues/20370)

Open/Close 也在工作任务执行以避免直接阻塞UI，但它们没有本库可保证的驱动级截止时间；不要用 Task 超时后遗弃尚未结束的串口任务，再另开同一个 COM 口。
