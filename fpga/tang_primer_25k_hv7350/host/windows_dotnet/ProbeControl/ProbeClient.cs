using System.Diagnostics;
using System.Security.Cryptography;

namespace Hv7350.ProbeControl;

public sealed class ProbeClientOptions
{
    public int ResponseTimeoutMs { get; init; } = 1000;
    public int WriteTimeoutMs { get; init; } = 250;
    public int ReadSliceMs { get; init; } = 20;
    public int QueueTimeoutMs { get; init; } = 1500;

    internal void Validate()
    {
        if (ResponseTimeoutMs is < 1 or > 10000 || WriteTimeoutMs is < 1 or > 10000 ||
            ReadSliceMs is < 1 or > 100 || QueueTimeoutMs is < 1 or > 30000)
            throw new ArgumentOutOfRangeException(nameof(ProbeClientOptions));
    }
}

public sealed class ProbeBusyException : InvalidOperationException
{
    public ProbeBusyException(string message) : base(message) { }
}

public sealed class ProbeRecoveryRequiredException : InvalidOperationException
{
    public ProbeRecoveryRequiredException() : base(
        "State is unconfirmed. Explicitly request STATUS or STOP before START/NEXT.") { }
}

public sealed class ProbeRejectedException : Exception
{
    public ProbeResponse Response { get; }
    public ProbeRejectedException(ProbeResponse response) : base(
        $"FPGA rejected {response.Command}: result={response.Result} " +
        "(1=unknown command, 2=bad argument). Status snapshot is still valid.") => Response = response;
}

/// <summary>
/// A write was attempted but no trustworthy matching ACK was received.
/// The FPGA may already be emitting. No command is automatically retried.
/// Deliberate cancellation after write also becomes THIS error, not ordinary cancellation.
/// </summary>
public sealed class ProbeStateUncertainException : IOException
{
    public ProbeCommand Command { get; }
    public byte Sequence { get; }
    public ProbeStateUncertainException(ProbeCommand command, byte sequence, Exception inner)
        : base($"No confirmed reply to {command} seq={sequence}; execution is UNKNOWN. " +
               "Do not repeat START/NEXT. Explicitly use STOP or STATUS; " +
               "USB disconnect does not stop the FPGA.", inner)
    {
        Command = command;
        Sequence = sequence;
    }
}

/// <summary>
/// Persistent connection, exactly one in-flight exchange and at most one
/// queued caller. Only the holder of _gate starts an I/O worker. UI callers
/// must await methods, never .Result/Wait(). No background polling or commands.
/// </summary>
public sealed class ProbeClient : IAsyncDisposable
{
    private readonly IProbeTransport _transport;
    private readonly ProbeClientOptions _options;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private byte _sequence = (byte)RandomNumberGenerator.GetInt32(256);
    private int _admitted;
    private volatile bool _disposed;
    private volatile bool _requiresRecovery = true;
    private volatile ProbeResponse? _lastResponse;

    public bool RequiresRecovery => _requiresRecovery;
    public ProbeResponse? LastResponse => _lastResponse;

    /// <summary>Takes ownership of an already-open transport; sends nothing.</summary>
    public ProbeClient(IProbeTransport transport, ProbeClientOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(transport);
        _options = options ?? new ProbeClientOptions();
        _options.Validate();
        _transport = transport;
    }

    public Task<ProbeResponse> StartAsync(int probe, CancellationToken cancellationToken = default)
    {
        if (probe is < 1 or > 4) throw new ArgumentOutOfRangeException(nameof(probe));
        return ExchangeAsync(ProbeCommand.Start, (byte)probe, cancellationToken);
    }

    public Task<ProbeResponse> NextAsync(CancellationToken cancellationToken = default) =>
        ExchangeAsync(ProbeCommand.Next, 0, cancellationToken);

    public Task<ProbeResponse> StopAsync(CancellationToken cancellationToken = default) =>
        ExchangeAsync(ProbeCommand.Stop, 0, cancellationToken);

    public Task<ProbeResponse> GetStatusAsync(CancellationToken cancellationToken = default) =>
        ExchangeAsync(ProbeCommand.Status, 0, cancellationToken);

    private async Task<ProbeResponse> ExchangeAsync(
        ProbeCommand command, byte argument, CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        cancellationToken.ThrowIfCancellationRequested();
        if (Interlocked.Increment(ref _admitted) > 2)
        {
            Interlocked.Decrement(ref _admitted);
            throw new ProbeBusyException("One exchange and one waiter already exist; nothing was sent.");
        }
        bool acquired = false;
        try
        {
            acquired = await _gate.WaitAsync(_options.QueueTimeoutMs, cancellationToken)
                                  .ConfigureAwait(false);
            if (!acquired)
                throw new ProbeBusyException("Timed out waiting for the connection; nothing was sent.");
            ObjectDisposedException.ThrowIf(_disposed, this);
            cancellationToken.ThrowIfCancellationRequested();
            if (_requiresRecovery && command is (ProbeCommand.Start or ProbeCommand.Next))
                throw new ProbeRecoveryRequiredException();
            byte sequence = _sequence;
            _sequence = unchecked((byte)(_sequence + 1));
            // Cancellation is checked INSIDE the worker. Never abandon a live
            // I/O task and release the gate while it may still write to the port.
            return await Task.Run(() => ExchangeBlocking(command, argument, sequence, cancellationToken),
                                  CancellationToken.None).ConfigureAwait(false);
        }
        finally
        {
            if (acquired) _gate.Release();
            Interlocked.Decrement(ref _admitted);
        }
    }

    private ProbeResponse ExchangeBlocking(
        ProbeCommand command, byte argument, byte sequence, CancellationToken cancellationToken)
    {
        bool writeAttempted = false;
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (_requiresRecovery)
            {
                // Caller explicitly asked STATUS/STOP. Purge any pending host
                // output, then allow the FPGA's 10 ms partial-frame timeout.
                // This is framing recovery, NOT a guarantee about broken USB drivers.
                _transport.DiscardOutput();
                if (cancellationToken.WaitHandle.WaitOne(30))
                    cancellationToken.ThrowIfCancellationRequested();
            }
            _transport.DiscardInput();
            cancellationToken.ThrowIfCancellationRequested();
            byte[] request = ProbeProtocol.Encode(command, argument, sequence);
            writeAttempted = true;
            if (_transport.Write(request, 0, request.Length, _options.WriteTimeoutMs) != request.Length)
                throw new IOException("Partial serial write.");

            var elapsed = Stopwatch.StartNew();
            var parser = new ProbeResponseParser();
            var buffer = new byte[64];
            while (elapsed.ElapsedMilliseconds < _options.ResponseTimeoutMs)
            {
                cancellationToken.ThrowIfCancellationRequested();
                int remaining = _options.ResponseTimeoutMs - (int)elapsed.ElapsedMilliseconds;
                int count;
                try
                {
                    count = _transport.Read(buffer, 0, buffer.Length,
                                            Math.Max(1, Math.Min(_options.ReadSliceMs, remaining)));
                }
                catch (TimeoutException)
                {
                    continue; // A read slice expired; the TOTAL deadline is unchanged.
                }
                cancellationToken.ThrowIfCancellationRequested();
                for (int i = 0; i < count; i++)
                {
                    if (!parser.Feed(buffer[i], out var response) || response is null ||
                        response.Command != command || response.Sequence != sequence)
                        continue; // Skip stale/unrelated frames, never accept by checksum alone.
                    _lastResponse = response;
                    _requiresRecovery = false;
                    if (response.Result != 0) throw new ProbeRejectedException(response);
                    return response;
                }
            }
            throw new TimeoutException("Response deadline elapsed.");
        }
        catch (ProbeRejectedException) { throw; }
        catch (Exception error) when (error is IOException or TimeoutException or
                                      OperationCanceledException or InvalidOperationException)
        {
            if (!writeAttempted)
            {
                // A pre-write cancellation sent nothing and leaves a previously
                // confirmed snapshot intact. A transport fault, however, means
                // this connection can no longer be treated as confirmed.
                if (error is not OperationCanceledException) _requiresRecovery = true;
                throw;
            }
            _requiresRecovery = true;
            throw new ProbeStateUncertainException(command, sequence, error);
        }
    }

    /// <summary>
    /// Waits for an existing bounded exchange, then closes. Does NOT send STOP.
    /// To stop intentionally: await StopAsync(), check its ACK, then DisposeAsync().
    /// </summary>
    public async ValueTask DisposeAsync()
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (_disposed) return;
            _disposed = true;
            _requiresRecovery = true;
            await Task.Run(() => _transport.Dispose()).ConfigureAwait(false);
        }
        finally { _gate.Release(); }
        // Keep the semaphore alive so already-admitted waiters can observe disposal.
    }
}
