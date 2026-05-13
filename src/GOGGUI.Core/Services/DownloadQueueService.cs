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
        var slugList = string.Join("|", jobs.Select(j => j.Slug));
        var s = _settingsService.Current;
        var extras = jobs.Any(j => j.IncludeExtras) ? " --extras" : string.Empty;
        var cmd = $"{s.LgogBinary} --download --game \"{slugList}\"{extras}";

        foreach (var job in jobs) job.Status = DownloadJobStatus.Downloading;

        DownloadJob? currentJob = null;

        try
        {
            var exitCode = await _wsl.RunStreamingAsync(s.WslDistro, cmd, line =>
            {
                var fileMatch = FileRx.Match(line);
                if (fileMatch.Success)
                {
                    var fn = fileMatch.Groups[1].Value.ToLower();
                    currentJob = jobs.FirstOrDefault(j =>
                        fn.Contains(j.Slug.Replace('-', '_'))) ?? currentJob;
                }

                var pctMatches = PercentRx.Matches(line);
                if (pctMatches.Count > 0 &&
                    int.TryParse(pctMatches[^1].Groups[1].Value, out var pct) &&
                    currentJob is not null)
                {
                    currentJob.ProgressPercent = Math.Clamp(pct, 0, 100);
                    if (pct == 100) currentJob.Status = DownloadJobStatus.Complete;
                }

                var text = line.Trim();
                if (!string.IsNullOrEmpty(text) && currentJob is not null)
                    currentJob.ProgressText = text.Length > 80 ? text[..80] + "…" : text;
            }, ct);

            var finalStatus = exitCode == 0 ? DownloadJobStatus.Complete : DownloadJobStatus.Failed;
            foreach (var job in jobs.Where(j => j.Status == DownloadJobStatus.Downloading))
                job.Status = finalStatus;

            Log.Info("DownloadQueue", $"Batch finished exitCode={exitCode}");
        }
        catch (OperationCanceledException)
        {
            Log.Info("DownloadQueue", "Batch cancelled");
            foreach (var job in jobs.Where(j => j.Status == DownloadJobStatus.Downloading))
                job.Status = DownloadJobStatus.Cancelled;
        }
        catch (Exception ex)
        {
            Log.Error("DownloadQueue", ex);
            foreach (var job in jobs) job.Status = DownloadJobStatus.Failed;
        }
    }
}
