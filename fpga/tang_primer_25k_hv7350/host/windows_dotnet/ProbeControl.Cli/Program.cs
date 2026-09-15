using Hv7350.ProbeControl;

static void Print(ProbeResponse response) => Console.WriteLine(
    $"cmd=0x{(byte)response.Command:X2} seq={response.Sequence} result={response.Result} " +
    $"active={response.ActiveProbe} next={response.NextProbe} " +
    $"running={response.Running} completed={response.Completed}");

static void Usage() => Console.WriteLine(
    "Usage: ProbeControl.Cli list\n" +
    "       ProbeControl.Cli COM5 status|stop|next|start 1|shell\n" +
    "The start probe is 1..4. No command is sent without an explicit request.\n" +
    "shell keeps COM open: status, start 1..4, next, stop, quit.\n" +
    "quit/disconnect is NOT STOP; continuous TX has no automatic timeout. Send stop explicitly.");

static async Task Execute(ProbeClient client, string[] words)
{
    string command = words[0].ToLowerInvariant();
    switch (command)
    {
        case "status" when words.Length == 1: Print(await client.GetStatusAsync()); break;
        case "stop" when words.Length == 1: Print(await client.StopAsync()); break;
        case "next" when words.Length == 1:
            Print(await client.NextAsync());
            break;
        case "start" when words.Length == 2 && int.TryParse(words[1], out int probe) && probe is >= 1 and <= 4:
            Print(await client.StartAsync(probe));
            break;
        default: throw new ArgumentException("Use status, stop, next, start 1..4, or quit.");
    }
}

try
{
    if (args.Length == 1 && args[0].Equals("list", StringComparison.OrdinalIgnoreCase))
    {
        foreach (string name in SerialPortTransport.GetPortNames()) Console.WriteLine(name);
        return 0;
    }
    if (args.Length < 2) { Usage(); return 2; }
    bool shell = args[1].Equals("shell", StringComparison.OrdinalIgnoreCase);
    if (shell && args.Length != 2) { Usage(); return 2; }
    await using var client = new ProbeClient(await SerialPortTransport.OpenAsync(args[0]));
    if (!shell)
    {
        // A one-shot explicit START/NEXT first performs a read-only preflight.
        // The interactive shell never performs this automatically: after any
        // uncertainty the operator must explicitly enter status or stop.
        if (args[1].Equals("start", StringComparison.OrdinalIgnoreCase) ||
            args[1].Equals("next", StringComparison.OrdinalIgnoreCase))
            Print(await client.GetStatusAsync());
        await Execute(client, args[1..]);
        return 0;
    }
    Console.WriteLine("Connected. Enter status first; start/next may emit HIGH VOLTAGE. quit does NOT stop.");
    while (true)
    {
        Console.Write("probe> ");
        string? line = Console.ReadLine();
        if (line is null || line.Trim().Equals("quit", StringComparison.OrdinalIgnoreCase)) break;
        string[] words = line.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (words.Length == 0) continue;
        try { await Execute(client, words); }
        catch (ProbeStateUncertainException error)
        {
            Console.Error.WriteLine(error.Message);
            Console.Error.WriteLine("Explicitly enter status or stop next. Do not assume that emission stopped.");
        }
        catch (Exception error) { Console.Error.WriteLine(error.Message); }
    }
    return 0;
}
catch (ProbeRejectedException error)
{
    Print(error.Response);
    Console.Error.WriteLine(error.Message);
    return 2;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}
