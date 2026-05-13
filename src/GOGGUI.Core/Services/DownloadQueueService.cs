using GOGGUI.Core.Models;
using System.Collections.ObjectModel;
using System.Text.RegularExpressions;

namespace GOGGUI.Core.Services;

/// <summary>
/// Download queue that batches all pending games into a single lgogdownloader call:
///   lgogdownloader --download --game "slug1|slug2|slug3"
/// lgogdownloader handles all parallelism internally (4 threads by default).
/// No SemaphoreSlim needed — one process, no race conditions.
/// </summary>
public sealed class DownloadQueueService
{
    private readonly WslProcessService _wsl;
    private readonly AppSettingsService _settingsService;

    private static readonly Regex PercentRx = new(@"(\d{1,3})%", RegexOptions.Compiled);
    // lgogdownloader prefixes each file line with the filename before the progress bar
    // e.g. "setup_braid_1.0.exe [####    ] 42% 8.1 MB/s"
    private static readonly Regex FileRx = new(@"^(\S+\.(?:exe|bin|sh|pkg))", RegexOptions.Compiled | RegexOptions.IgnoreCase);

    public ObservableCollection<DownloadJob> Queue { get; } = new();

    private CancellationTokenSource? _activeCts;
    private Task? _activeTask;

    public bool IsRunning => _activeTask is { IsCompleted: false };

    public DownloadQueueService(WslProcessService wsl, AppSettingsService settingsService)
    {
        _wsl = wsl;
        _settingsService = settingsService;
    }

    /// <summary>
    /// Add a game to the queue. If a download is already running,
    /// it will be picked up in the next batch (after current finishes).
    /// Call StartAsync() to kick off the batch.
    /// </summary>
    public void Enqueue(string slug, string title, bool includeExtras = false)
    {
        // Avoid duplicates
        if (Queue.Any(j => j.Slug == slug &&
            j.Status is DownloadJobStatus.Queued or DownloadJobStatus.Downloading))
            return;

        Queue.Add(new DownloadJob
        {
            Slug = slug,
            Title = title,
            IncludeExtras = includeExtras
        });
    }

    /// <summary>
    /// Start downloading all queued games as a single lgogdownloader invocation.
    /// Calling while already running is a no-op.
    /// </summary>
    public Task StartAsync()
    {
        if (IsRunning) return _activeTask!;

        var pending = Queue.Where(j => j.Status == DownloadJobStatus.Queued).ToList();
        if (pending.Count == 0) return Task.CompletedTask;

        _activeCts = new CancellationTokenSource();
        _activeTask = RunBatchAsync(pending, _activeCts.Token);
        return _activeTask;
    }

    /// <summary>Cancel the running batch and mark all active jobs as Cancelled.</summary>
    public void CancelAll()
    {
        _activeCts?.Cancel();
        foreach (var job in Queue.Where(j =>
            j.Status is DownloadJobStatus.Queued or DownloadJobStatus.Downloading))
            job.Status = DownloadJobStatus.Cancelled;
    }

    /// <summary>Remove completed/failed/cancelled jobs from the queue.</summary>
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
        // Build pipe-separated slug list: "braid|butcher|cayne"
        var slugList = string.Join("|", jobs.Select(j => j.Slug));
        var s = _settingsService.Current;
        var extras = jobs.Any(j => j.IncludeExtras) ? " --extras" : string.Empty;
        var cmd = $"{s.LgogBinary} --download --game \"{slugList}\"{extras}";

        foreach (var job in jobs)
            job.Status = DownloadJobStatus.Downloading;

        DownloadJob? currentJob = null;

        try
        {
            var exitCode = await _wsl.RunStreamingAsync(
                s.WslDistro,
                cmd,
                line =>
                {
                    // Detect which game lgogdownloader is currently working on
                    var fileMatch = FileRx.Match(line);
                    if (fileMatch.Success)
                    {
                        var fileName = fileMatch.Groups[1].Value.ToLower();
                        currentJob = jobs.FirstOrDefault(j =>
                            fileName.Contains(j.Slug.Replace('-', '_'))) ?? currentJob;
                    }

                    // Parse percent and update the current job
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
                },
                ct);

            var finalStatus = exitCode == 0
                ? DownloadJobStatus.Complete
                : DownloadJobStatus.Failed;

            foreach (var job in jobs.Where(j => j.Status == DownloadJobStatus.Downloading))
                job.Status = finalStatus;
        }
        catch (OperationCanceledException)
        {
            foreach (var job in jobs.Where(j => j.Status == DownloadJobStatus.Downloading))
                job.Status = DownloadJobStatus.Cancelled;
        }
        catch
        {
            foreach (var job in jobs)
                job.Status = DownloadJobStatus.Failed;
        }
    }
}
