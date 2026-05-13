using System.Diagnostics;

namespace GOGGUI.Core.Services;

public sealed class WslProcessService
{
    /// <summary>Fire-and-forget run, collects all output at end.</summary>
    public async Task<(int ExitCode, string StdOut, string StdErr)> RunAsync(
        string distro,
        string arguments,
        CancellationToken cancellationToken = default)
    {
        var startInfo = BuildStartInfo(distro, arguments);
        using var process = new Process { StartInfo = startInfo };
        process.Start();

        var stdOutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stdErrTask = process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);

        return (process.ExitCode, await stdOutTask, await stdErrTask);
    }

    /// <summary>
    /// Streaming run — calls <paramref name="onLine"/> for every line of stdout.
    /// Used by DownloadQueueService to parse lgogdownloader progress in real time.
    /// </summary>
    public async Task<int> RunStreamingAsync(
        string distro,
        string arguments,
        Action<string> onLine,
        CancellationToken cancellationToken = default)
    {
        var startInfo = BuildStartInfo(distro, arguments);
        using var process = new Process { StartInfo = startInfo };

        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is not null)
                onLine(e.Data);
        };

        process.Start();
        process.BeginOutputReadLine();

        // Drain stderr silently (avoid deadlock)
        var stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);

        await process.WaitForExitAsync(cancellationToken);
        await stderrTask;

        return process.ExitCode;
    }

    private static ProcessStartInfo BuildStartInfo(string distro, string arguments) => new()
    {
        FileName = "wsl.exe",
        Arguments = $"-d {distro} {arguments}",
        RedirectStandardOutput = true,
        RedirectStandardError = true,
        UseShellExecute = false,
        CreateNoWindow = true
    };
}
