using Hv7350.ProbeControl;

// No test framework and no serial port needed. Execute with dotnet run.
static void Check(bool condition, string message)
{
    if (!condition) throw new Exception("FAIL: " + message);
}

static async Task<T> Expect<T>(Func<Task> action) where T : Exception
{
    try { await action(); }
    catch (T error) { return error; }
    throw new Exception("Expected " + typeof(T).Name);
}

static byte[] Reply(byte[] request, byte result = 0, byte active = 0, byte next = 1, byte flags = 0)
{
    byte[] frame = { 0x5A, 0xA5, request[2], request[4], result, active, next, flags, 0 };
    for (int i = 2; i < 8; i++) frame[8] ^= frame[i];
    return frame;
}

var request = ProbeProtocol.Encode(ProbeCommand.Start, 1, 0);
Check(request.SequenceEqual(new byte[] { 0xA5, 0x5A, 0x10, 1, 0, 0x11 }), "START golden vector");
Check(ProbeProtocol.Encode(ProbeCommand.Status, 0, 0x2A)
    .SequenceEqual(new byte[] { 0xA5, 0x5A, 0x13, 0, 0x2A, 0x39 }), "STATUS golden vector");
byte[] good = Reply(request, active: 1, next: 2, flags: 1);
Check(ProbeProtocol.TryDecode(good, out var decoded) && decoded!.ActiveProbe == 1 && decoded.Running,
      "response fields");
byte[] bad = (byte[])good.Clone();
bad[8] ^= 1;
Check(!ProbeProtocol.TryDecode(bad, out _), "bad checksum rejected");
Check(!ProbeProtocol.TryDecode(Reply(request, active: 0, flags: 1), out _), "inconsistent flags rejected");
Check(!ProbeProtocol.TryDecode(Reply(request, active: 1, flags: 3), out _), "running/completed rejected");
Check(!ProbeProtocol.TryDecode(Reply(request, next: 0), out _), "invalid NEXT rejected");
var parser = new ProbeResponseParser();
var parsed = new List<ProbeResponse>();
foreach (byte value in new byte[] { 0x01, 0x5A, 0x00, 0x5A }.Concat(bad).Concat(good).Concat(good))
    if (parser.Feed(value, out var response)) parsed.Add(response!);
Check(parsed.Count == 2 && parsed.All(x => x.ActiveProbe == 1), "noise, split bytes, checksum, concatenation");
Console.WriteLine("PASS protocol golden vectors and parser");

var options = new ProbeClientOptions { ResponseTimeoutMs = 30, WriteTimeoutMs = 20,
                                      ReadSliceMs = 2, QueueTimeoutMs = 300 };
var transport = new FakeTransport();
transport.OnWrite = bytes => transport.Enqueue(Reply(bytes));
await using (var client = new ProbeClient(transport, options))
{
    Check(client.RequiresRecovery, "new connection is unconfirmed");
    await Expect<ProbeRecoveryRequiredException>(() => client.StartAsync(1));
    Check(transport.Writes.Count == 0, "no initial START on wire");
    await client.GetStatusAsync();
    Check(!client.RequiresRecovery, "STATUS confirms connection");

    transport.FailDiscardInputOnce = true;
    int writesBeforeTransportFault = transport.Writes.Count;
    await Expect<IOException>(() => client.GetStatusAsync());
    Check(client.RequiresRecovery && transport.Writes.Count == writesBeforeTransportFault,
          "pre-write transport error invalidates connection without sending command");
    await client.GetStatusAsync();

    transport.OnWrite = bytes =>
    {
        // A valid but stale response precedes the matching response.
        byte[] stale = (byte[])bytes.Clone();
        stale[4]++;
        transport.Enqueue(Reply(stale));
        transport.Enqueue(Reply(bytes, active: 2, next: 3, flags: 1));
    };
    var started = await client.StartAsync(2);
    Check(started.ActiveProbe == 2 && started.Running, "match CMD and SEQ after stale packet");

    transport.OnWrite = _ => { }; // Device execution may have occurred; reply is lost.
    int before = transport.Writes.Count;
    await Expect<ProbeStateUncertainException>(() => client.NextAsync());
    Check(transport.Writes.Count == before + 1 && client.RequiresRecovery, "timeout does NOT retry");
    await Expect<ProbeRecoveryRequiredException>(() => client.StartAsync(3));
    Check(transport.Writes.Count == before + 1, "uncertainty blocks START");

    transport.OnWrite = bytes => transport.Enqueue(Reply(bytes, next: 3));
    var stopped = await client.StopAsync();
    Check(!stopped.Running && !client.RequiresRecovery, "explicit STOP recovers");

    transport.PartialWriteOnce = true;
    before = transport.Writes.Count;
    await Expect<ProbeStateUncertainException>(() => client.StartAsync(1));
    Check(transport.Writes.Count == before + 1 && client.RequiresRecovery, "partial write is uncertain");
    await client.GetStatusAsync();

    using var cancellation = new CancellationTokenSource();
    transport.OnWrite = _ => cancellation.Cancel();
    await Expect<ProbeStateUncertainException>(() => client.StartAsync(1, cancellation.Token));
    Check(client.RequiresRecovery, "cancel AFTER write is uncertain, not ordinary cancellation");

    transport.OnWrite = bytes => transport.Enqueue(Reply(bytes, result: 1));
    var rejected = await Expect<ProbeRejectedException>(() => client.GetStatusAsync());
    Check(rejected.Response.Result == 1 && !client.RequiresRecovery && client.LastResponse is not null,
          "valid explicit rejection preserves a confirmed status snapshot");
    transport.OnWrite = bytes => transport.Enqueue(Reply(bytes));
    await client.StartAsync(1);

    using var cancelledBefore = new CancellationTokenSource();
    cancelledBefore.Cancel();
    before = transport.Writes.Count;
    await Expect<OperationCanceledException>(() => client.StartAsync(1, cancelledBefore.Token));
    Check(transport.Writes.Count == before && !client.RequiresRecovery, "cancel BEFORE write sends nothing");
}
Check(transport.Disposed, "Dispose closes transport");
Check(transport.Writes[^1][2] == (byte)ProbeCommand.Start, "Dispose did NOT send implicit STOP");
Console.WriteLine("PASS client recovery, matching, rejection, timeout, partial write, cancellation, disposal");

// Exercise the one active + one queued bound without touching real hardware.
var concurrent = new FakeTransport();
concurrent.OnWrite = bytes => concurrent.Enqueue(Reply(bytes));
await using (var client = new ProbeClient(concurrent, options))
{
    await client.GetStatusAsync();
    using var entered = new ManualResetEventSlim();
    using var release = new ManualResetEventSlim();
    concurrent.OnWrite = bytes =>
    {
        entered.Set();
        if (!release.Wait(1000)) throw new TimeoutException("test synchronization failed");
        concurrent.Enqueue(Reply(bytes));
    };
    Task<ProbeResponse> first = client.GetStatusAsync();
    Check(entered.Wait(1000), "first worker started");
    Task<ProbeResponse> second = client.StopAsync();
    await Expect<ProbeBusyException>(() => client.GetStatusAsync());
    release.Set();
    await first;
    await second;
}
Console.WriteLine("PASS bounded concurrency; all tests passed (fake transport only)");

sealed class FakeTransport : IProbeTransport
{
    private readonly Queue<byte> _rx = new();
    public List<byte[]> Writes { get; } = new();
    public Action<byte[]>? OnWrite { get; set; }
    public bool PartialWriteOnce { get; set; }
    public bool FailDiscardInputOnce { get; set; }
    public bool Disposed { get; private set; }
    public void Enqueue(byte[] bytes) { foreach (byte value in bytes) _rx.Enqueue(value); }
    public int Write(byte[] bytes, int offset, int count, int timeoutMs)
    {
        byte[] copy = bytes.AsSpan(offset, count).ToArray();
        Writes.Add(copy);
        if (PartialWriteOnce) { PartialWriteOnce = false; return count - 1; }
        OnWrite?.Invoke(copy);
        return count;
    }
    public int Read(byte[] bytes, int offset, int count, int timeoutMs)
    {
        if (_rx.Count == 0)
        {
            Thread.Sleep(Math.Min(timeoutMs, 2));
            throw new TimeoutException();
        }
        int copied = Math.Min(Math.Min(count, _rx.Count), 2); // Force fragmented replies.
        for (int i = 0; i < copied; i++) bytes[offset + i] = _rx.Dequeue();
        return copied;
    }
    public void DiscardInput()
    {
        if (FailDiscardInputOnce)
        {
            FailDiscardInputOnce = false;
            throw new IOException("Simulated pre-write USB failure");
        }
        _rx.Clear();
    }
    public void DiscardOutput() { }
    public void Dispose() => Disposed = true;
}
