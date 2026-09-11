using System.IO.Ports;

namespace Hv7350.ProbeControl;

/// <summary>
/// Owned exclusively by one ProbeClient. Implementations must provide bounded
/// synchronous reads/writes. A successful Write means OS acceptance, not ACK.
/// Inject a fake implementation for tests; do not share a real port with a UI.
/// </summary>
public interface IProbeTransport : IDisposable
{
    int Read(byte[] buffer, int offset, int count, int timeoutMs);
    int Write(byte[] buffer, int offset, int count, int timeoutMs);
    void DiscardInput();
    void DiscardOutput();
}

public sealed class SerialPortTransport : IProbeTransport
{
    private readonly SerialPort _port;

    private SerialPortTransport(SerialPort port) => _port = port;

    public static string[] GetPortNames() => SerialPort.GetPortNames()
        .OrderBy(name => name, StringComparer.OrdinalIgnoreCase).ToArray();

    /// <summary>Opens only. Never sends START, STOP, STATUS or any text.</summary>
    public static Task<SerialPortTransport> OpenAsync(
        string portName, CancellationToken cancellationToken = default) => Task.Run(() =>
    {
        cancellationToken.ThrowIfCancellationRequested();
        var port = new SerialPort(portName, 115200, Parity.None, 8, StopBits.One)
        {
            Handshake = Handshake.None,
            DtrEnable = false,
            RtsEnable = false,
            ReadTimeout = 20,
            WriteTimeout = 250,
            DiscardNull = false
        };
        try
        {
            port.Open();
            cancellationToken.ThrowIfCancellationRequested();
            return new SerialPortTransport(port);
        }
        catch
        {
            port.Dispose();
            throw;
        }
    }, CancellationToken.None);

    public int Read(byte[] buffer, int offset, int count, int timeoutMs)
    {
        _port.ReadTimeout = timeoutMs;
        return _port.Read(buffer, offset, count);
    }

    public int Write(byte[] buffer, int offset, int count, int timeoutMs)
    {
        _port.WriteTimeout = timeoutMs;
        // SerialPort.Write has no byte-count return. An exception could occur
        // after partial transmission. Only a matching reply proves acceptance.
        _port.Write(buffer, offset, count);
        return count;
    }

    public void DiscardInput() => _port.DiscardInBuffer();
    public void DiscardOutput() => _port.DiscardOutBuffer();
    public void Dispose() => _port.Dispose(); // Disconnect is NOT STOP.
}
