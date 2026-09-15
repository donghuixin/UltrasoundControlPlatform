namespace Hv7350.ProbeControl;

public enum ProbeCommand : byte
{
    Start = 0x10,
    Next = 0x11,
    Stop = 0x12,
    Status = 0x13
}

/// <summary>A snapshot taken when the FPGA processed the request, not live state.</summary>
public sealed record ProbeResponse(
    ProbeCommand Command, byte Sequence, byte Result,
    byte ActiveProbe, byte NextProbe, byte Flags)
{
    public bool Running => (Flags & 1) != 0;
    // Legacy finite-session flag; always false on continuous firmware.
    public bool Completed => (Flags & 2) != 0;
}

public static class ProbeProtocol
{
    public static byte[] Encode(ProbeCommand command, byte argument, byte sequence)
    {
        if (command is not (ProbeCommand.Start or ProbeCommand.Next or
                            ProbeCommand.Stop or ProbeCommand.Status))
            throw new ArgumentOutOfRangeException(nameof(command));
        if (command == ProbeCommand.Start ? argument < 1 || argument > 4 : argument != 0)
            throw new ArgumentOutOfRangeException(nameof(argument));
        byte cmd = (byte)command;
        return new byte[] { 0xA5, 0x5A, cmd, argument, sequence,
                           (byte)(cmd ^ argument ^ sequence) };
    }

    public static bool TryDecode(ReadOnlySpan<byte> frame, out ProbeResponse? response)
    {
        response = null;
        if (frame.Length != 9 || frame[0] != 0x5A || frame[1] != 0xA5)
            return false;
        byte check = 0;
        for (int i = 2; i < 8; i++) check ^= frame[i];
        if (check != frame[8]) return false;
        if (frame[4] > 2 || frame[5] > 4 || frame[6] < 1 || frame[6] > 4)
            return false;
        byte flags = frame[7];
        if ((flags & ~3) != 0 || ((flags & 1) != 0) != (frame[5] != 0))
            return false;
        if ((flags & 3) == 3) return false; // Cannot run and be completed together.
        response = new ProbeResponse((ProbeCommand)frame[2], frame[3], frame[4],
                                     frame[5], frame[6], flags);
        return true;
    }
}

/// <summary>
/// Fixed nine-byte sliding window; accepts split/concatenated/noisy streams
/// without unbounded buffering. A corrupt candidate advances by one byte.
/// One Feed call is one byte, NOT one serial read/packet.
/// </summary>
public sealed class ProbeResponseParser
{
    private readonly byte[] _window = new byte[9];
    private int _count;

    public bool Feed(byte value, out ProbeResponse? response)
    {
        response = null;
        _window[_count++] = value;
        if (_count < 9) return false;
        if (ProbeProtocol.TryDecode(_window, out response))
        {
            _count = 0;
            return true;
        }
        Array.Copy(_window, 1, _window, 0, 8);
        _count = 8;
        return false;
    }
}
