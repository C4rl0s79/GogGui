using GOGGUI.Core.Models;
using System.Collections.ObjectModel;
using System.Text.RegularExpressions;

namespace GOGGUI.Core.Services;

public sealed class DownloadQueueService
{
    private static readonly LogService Log = LogService.Instance;

    private readonly WslProcessService _wsl;
    private readonly AppSettingsService _settingsService;

    private static readonly Regex PercentRx = new(@"(\d{1,3})%", RegexOptions.Compiled);
    private static readonly Regex FileRx    = new(@"^(\S+\.(?:exe|bin|sh|pkg))", RegexOptions.Compiled | RegexOptions.IgnoreCase);

    public ObservableCollection<DownloadJob> Queue { get; } = new();

    private CancellationTokenSource? _activeCts;
    private Task? _activeTask;

    public bool IsRunning => _activeTask is { IsCompleted: false };

    public DownloadQueueService(WslProcessService wsl, AppSettingsService settingsService)
    {
        _wsl = wsl;
        _settingsService = settingsService;
    }

    public void Enqueue(string slug, string title, bool includeExtras = false)
    {
        if (Queue.Any(j => j.Slug == slug &&
            j.Status is DownloadJobStatus.Queued or DownloadJobStatus.Downloading))
        {
            Log.Debug("DownloadQueue", $"Already queued: {slug}");
            return;
        }
        Log.Info("DownloadQueue", $"Enqueued: {slug} (extras={includeExtras})");
        Queue.Add(new DownloadJob { Slug = slug, Title = title, IncludeExtras = includeExtras });
    }

    public Task StartAsync()
    {
        if (IsRunning)
        {
            Log.Debug("DownloadQueue", "StartAsync called while already running — ignored");
            return _activeTask!;
        }
        var pending = Queue.Where(j => j.Status == DownloadJobStatus.Queued).ToList();
        if (pending.Count == 0) return Task.CompletedTask;

        Log.Info("DownloadQueue", $"Starting batch: {string.Join(", ", pending.Select(j => j.Slug))}");
        _activeCts = new CancellationTokenSource();
        _activeTask = RunBatchAsync(pending, _activeCts.Token);
        return _activeTask;
    }

    public void CancelAll()
    {
        Log.Info("DownloadQueue", "CancelAll requested");
        _activeCts?.Cancel();
        foreach (var job in Queue.Where(j =>
            j.Status is DownloadJobStatus.Queued or DownloadJobStatus.Downloading))
            job.Status = DownloadJobStatus.Cancelled;
    }

    public void ClearFinished()
    {
        foreach (var j in Queue.Where(j =>
            j.Status is DownloadJobStatus.Complete
                     or DownloadJobStatus.Failed
                     or DownloadJobStatus.Cancelled).ToList())
            Queue.Remove(j);
    }

    private async Task RunBatchAsync(List<DownloadJob> jobs, CancellationToken ct)
    {
        var s = _settingsService.Current;

        // FIX #9: run each job individually so its per-job extras flag is honoured.
        // Previously all jobs were merged into one slug-list which incorrectly applied
        // the extras flag from ANY job to ALL jobs.
        foreach (var job in jobs)
        {
            ct.ThrowIfCancellationRequested();
            await RunSingleJobAsync(job, s, ct);
        }

        Log.Info("DownloadQueue", "Batch finished");
    }

    private async Task RunSingleJobAsync(DownloadJob job, AppSettings s, CancellationToken ct)
    {
        // FIX #5 (also in DownloadQueue): quote slug for shell safety.
        var quotedSlug = $"'{job.Slug.Replace("'", "'\\''")}'"; // POSIX single-quote escaping
        var extrasFlag = job.IncludeExtras ? " --extras" : string.Empty;
        var cmd = $"{s.LgogBinary} --download --game {quotedSlug}{extrasFlag}";

        job.Status = DownloadJobStatus.Downloading;
        Log.Info("DownloadQueue", $"Starting: {job.Slug}");

        try
        {
            var exitCode = await _wsl.RunStreamingAsync(s.WslDistro, cmd, line =>
            {
                var pctMatches = PercentRx.Matches(line);
                if (pctMatches.Count > 0 &&
                    int.TryParse(pctMatches[^1].Groups[1].Value, out var pct))
                {
                    job.ProgressPercent = Math.Clamp(pct, 0, 100);
                }

                var text = line.Trim();
                if (!string.IsNullOrEmpty(text))
                    job.ProgressText = text.Length > 80 ? text[..80] + "…" : text;
            }, ct);

            // FIX #9: map exit-code to status individually per job.
            job.Status = exitCode == 0 ? DownloadJobStatus.Complete : DownloadJobStatus.Failed;
            if (exitCode == 100) job.ProgressPercent = 100;
            Log.Info("DownloadQueue", $"{job.Slug} finished exitCode={exitCode}");
        }
        catch (OperationCanceledException)
        {
            Log.Info("DownloadQueue", $"{job.Slug} cancelled");
            job.Status = DownloadJobStatus.Cancelled;
        }
        catch (Exception ex)
        {
            Log.Error("DownloadQueue", ex);
            job.Status = DownloadJobStatus.Failed;
        }
    }
}
