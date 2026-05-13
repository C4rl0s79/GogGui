using GOGGUI.Core.Models;
using System.Collections.ObjectModel;
using System.Text.RegularExpressions;

namespace GOGGUI.Core.Services;

/// <summary>
/// Sequential download queue — one lgogdownloader process at a time.
/// lgogdownloader handles parallel chunk downloading internally,
/// running multiple instances would cause race conditions on the same game folder.
///
/// Progress parsing:
///   lgogdownloader outputs lines like:
///   "Downloading: setup_game_1.0.exe [##########      ] 64% 12.3 MB/s"
///   We extract the percent with a regex.
/// </summary>
public sealed class DownloadQueueService
{
    // One lgogdownloader process at a time — it handles its own parallel chunk downloads
    private readonly SemaphoreSlim _sem = new(1, 1);
    private readonly WslProcessService _wsl;
    private readonly AppSettingsService _settingsService;

    private static readonly Regex PercentRx =
        new(@"(\d{1,3})%", RegexOptions.Compiled);

    public ObservableCollection<DownloadJob> Queue { get; } = new();

    public DownloadQueueService(WslProcessService wsl, AppSettingsService settingsService)
    {
        _wsl = wsl;
        _settingsService = settingsService;
    }

    /// <summary>Enqueue a game for download. Returns the job immediately.</summary>
    public DownloadJob Enqueue(string slug, string title, bool includeExtras = false)
    {
        var job = new DownloadJob
        {
            Slug = slug,
            Title = title,
            IncludeExtras = includeExtras
        };
        Queue.Add(job);
        _ = RunJobAsync(job);
        return job;
    }

    /// <summary>Cancel a specific job.</summary>
    public void Cancel(DownloadJob job)
    {
        job.Cts.Cancel();
        if (job.Status == DownloadJobStatus.Queued)
            job.Status = DownloadJobStatus.Cancelled;
    }

    /// <summary>Cancel all queued/active jobs.</summary>
    public void CancelAll()
    {
        foreach (var job in Queue.Where(j =>
            j.Status is DownloadJobStatus.Queued or DownloadJobStatus.Downloading))
            Cancel(job);
    }

    /// <summary>Remove completed/cancelled/failed jobs from the visible queue.</summary>
    public void ClearFinished()
    {
        var finished = Queue.Where(j =>
            j.Status is DownloadJobStatus.Complete
                     or DownloadJobStatus.Failed
                     or DownloadJobStatus.Cancelled)
            .ToList();
        foreach (var j in finished)
            Queue.Remove(j);
    }

    private async Task RunJobAsync(DownloadJob job)
    {
        var ct = job.Cts.Token;
        try
        {
            await _sem.WaitAsync(ct);
        }
        catch (OperationCanceledException)
        {
            job.Status = DownloadJobStatus.Cancelled;
            return;
        }

        try
        {
            job.Status = DownloadJobStatus.Downloading;
            var s = _settingsService.Current;
            var extras = job.IncludeExtras ? " --extras" : string.Empty;
            var cmd = $"{s.LgogBinary} --download --game {job.Slug}{extras}";

            var exitCode = await _wsl.RunStreamingAsync(
                s.WslDistro,
                cmd,
                line => ParseProgress(job, line),
                ct);

            job.Status = exitCode == 0
                ? DownloadJobStatus.Complete
                : DownloadJobStatus.Failed;

            if (exitCode == 0)
                job.ProgressPercent = 100;
        }
        catch (OperationCanceledException)
        {
            job.Status = DownloadJobStatus.Cancelled;
        }
        catch
        {
            job.Status = DownloadJobStatus.Failed;
        }
        finally
        {
            _sem.Release();
        }
    }

    private static void ParseProgress(DownloadJob job, string line)
    {
        var matches = PercentRx.Matches(line);
        if (matches.Count > 0 && int.TryParse(matches[^1].Groups[1].Value, out var pct))
            job.ProgressPercent = Math.Clamp(pct, 0, 100);

        var text = line.Trim();
        if (!string.IsNullOrEmpty(text))
            job.ProgressText = text.Length > 80 ? text[..80] + "…" : text;
    }
}
