using System.Diagnostics;

namespace GOGGUI.Core.Services;

public sealed class WslProcessService
{
    private static readonly LogService Log = LogService.Instance;

    /// <summary>
    /// Timeout for non-streaming commands (check-login, update-cache, etc.).
    /// Downloads use RunStreamingAsync which does NOT apply this timeout — they
    /// run for as long as needed, but can be cancelled via CancellationToken.
    /// </summary>
    public TimeSpan CommandTimeout { get; set; } = TimeSpan.FromMinutes(5);

    public async Task<(int ExitCode, string StdOut, string StdErr)> RunAsync(
        string distro,
        string arguments,
        CancellationToken cancellationToken = default)
    {
        Log.Debug("WslProcess", $"Run: wsl -d {distro} {arguments}");
        var startInfo = BuildStartInfo(distro, arguments);
        using var process = new Process { StartInfo = startInfo };
        process.Start();

        var stdOutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stdErrTask = process.StandardError.ReadToEndAsync(cancellationToken);

        // FIX #2: apply timeout via CancellationTokenSource
        using var timeoutCts = new CancellationTokenSource(CommandTimeout);
        using var linkedCts  = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken, timeoutCts.Token);

        try
        {
            await process.WaitForExitAsync(linkedCts.Token);
        }
        catch (OperationCanceledException) when (timeoutCts.IsCancellationRequested)
        {
            Log.Warning("WslProcess", $"Timeout after {CommandTimeout} — killing process");
            try { process.Kill(entireProcessTree: true); } catch { /* already exited */ }
            return (-1, string.Empty, $"Process timed out after {CommandTimeout}");
        }

        var (stdout, stderr) = (await stdOutTask, await stdErrTask);
        if (process.ExitCode != 0)
            Log.Warning("WslProcess", $"ExitCode={process.ExitCode} stderr={stderr.Trim()}");
        else
            Log.Debug("WslProcess", "ExitCode=0");

        return (process.ExitCode, stdout, stderr);
    }

    public async Task<int> RunStreamingAsync(
        string distro,
        string arguments,
        Action<string> onLine,
        CancellationToken cancellationToken = default)
    {
        Log.Info("WslProcess", $"Streaming: wsl -d {distro} {arguments}");
        var startInfo = BuildStartInfo(distro, arguments);
        using var process = new Process { StartInfo = startInfo };

        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is not null)
                onLine(e.Data);
        };

        process.Start();
        process.BeginOutputReadLine();
        var stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);
        var stderr = await stderrTask;

        if (process.ExitCode != 0)
            Log.Warning("WslProcess", $"Streaming ExitCode={process.ExitCode} stderr={stderr.Trim()}");
        else
            Log.Info("WslProcess", "Streaming done ExitCode=0");

        return process.ExitCode;
    }

    private static ProcessStartInfo BuildStartInfo(string distro, string arguments) => new()
    {
        FileName               = "wsl.exe",
        Arguments              = $"-d {distro} {arguments}",
        RedirectStandardOutput = true,
        RedirectStandardError  = true,
        UseShellExecute        = false,
        CreateNoWindow         = true,
    };
}
