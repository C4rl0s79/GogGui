using GOGGUI.Core.Models;
using System.Collections.ObjectModel;
using System.Text.RegularExpressions;

namespace GOGGUI.Core.Services;

public sealed class DownloadQueueService
{
    private static readonly LogService Log = LogService.Instance;

    private readonly WslProcessService  _wsl;
    private readonly AppSettingsService _settingsService;

    // BUG FIX #7: capture the UI SynchronizationContext at construction time.
    // DownloadQueueService is created in App.OnLaunched, which runs on the UI thread,
    // so SynchronizationContext.Current here is the WinUI dispatcher context.
    // RunSingleJobAsync runs on the thread pool; without this marshaling, property
    // changes on DownloadJob fire INotifyPropertyChanged from a background thread and
    // cause InvalidOperationException in the WinUI binding engine.
    private readonly SynchronizationContext? _uiContext;

    private static readonly Regex PercentRx = new(@"(\d{1,3})%", RegexOptions.Compiled);
    private static readonly Regex FileRx    = new(@"^(\S+\.(?:exe|bin|sh|pkg))", RegexOptions.Compiled | RegexOptions.IgnoreCase);

    public ObservableCollection<DownloadJob> Queue { get; } = new();

    private CancellationTokenSource? _activeCts;
    private Task? _activeTask;

    public bool IsRunning => _activeTask is { IsCompleted: false };

    public DownloadQueueService(WslProcessService wsl, AppSettingsService settingsService)
    {
        _wsl             = wsl;
        _settingsService = settingsService;
        _uiContext       = SynchronizationContext.Current; // BUG FIX #7
    }

    /// <summary>
    /// BUG FIX #7: marshal a job property update onto the UI thread so that
    /// INotifyPropertyChanged notifications are always raised on the correct thread.
    /// </summary>
    private void UpdateJob(DownloadJob job, Action<DownloadJob> action)
    {
        if (_uiContext is not null)
            _uiContext.Post(_ => action(job), null);
        else
            action(job); // no UI context (e.g. unit tests) — update inline
    }

    // BUG FIX #3: added extrasOnly parameter.
    // BUG FIX #3: dedup now matches on slug + IncludeExtras + ExtrasOnly so that an
    //             extras-only job for a game that is already queued is not blocked.
    //             The old check matched slug alone.
    public void Enqueue(string slug, string title, bool includeExtras = false, bool extrasOnly = false)
    {
        if (Queue.Any(j => j.Slug          == slug         &&
                           j.IncludeExtras == includeExtras &&
                           j.ExtrasOnly    == extrasOnly    &&
                           j.Status is DownloadJobStatus.Queued or DownloadJobStatus.Downloading))
        {
            Log.Debug("DownloadQueue",
                $"Already queued: {slug} (extras={includeExtras}, extrasOnly={extrasOnly})");
            return;
        }

        Log.Info("DownloadQueue",
            $"Enqueued: {slug} (extras={includeExtras}, extrasOnly={extrasOnly})");

        Queue.Add(new DownloadJob
        {
            Slug          = slug,
            Title         = title,
            IncludeExtras = includeExtras,
            ExtrasOnly    = extrasOnly,
        });
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
        _activeCts  = new CancellationTokenSource();
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

        foreach (var job in jobs)
        {
            ct.ThrowIfCancellationRequested();
            await RunSingleJobAsync(job, s, ct);
        }

        Log.Info("DownloadQueue", "Batch finished");
    }

    private async Task RunSingleJobAsync(DownloadJob job, AppSettings s, CancellationToken ct)
    {
        var quotedSlug = $"'{job.Slug.Replace("'", "'\\''")}'"; // POSIX single-quote escaping

        // BUG FIX #3: honour ExtrasOnly (--no-installers --extras) separately from
        // IncludeExtras (--extras), and use the real slug in every case.
        // Previously the caller mangled the slug to "slug__extras", which lgogdownloader
        // could never match.
        var extrasFlag = job.ExtrasOnly    ? " --no-installers --extras"
                       : job.IncludeExtras ? " --extras"
                       : string.Empty;

        var cmd = $"{s.LgogBinary} --download --game {quotedSlug}{extrasFlag}";

        // BUG FIX #7: use UpdateJob so the property change fires on the UI thread.
        UpdateJob(job, j => j.Status = DownloadJobStatus.Downloading);
        Log.Info("DownloadQueue", $"Starting: {job.Slug}");

        try
        {
            var exitCode = await _wsl.RunStreamingAsync(s.WslDistro, cmd, line =>
            {
                var pctMatches = PercentRx.Matches(line);
                int? pct = null;
                if (pctMatches.Count > 0 &&
                    int.TryParse(pctMatches[^1].Groups[1].Value, out var p))
                    pct = Math.Clamp(p, 0, 100);

                var text = line.Trim();

                // Batch both updates into a single Post call to reduce dispatcher overhead.
                if (pct.HasValue || !string.IsNullOrEmpty(text))
                {
                    UpdateJob(job, j =>
                    {
                        if (pct.HasValue)
                            j.ProgressPercent = pct.Value;
                        if (!string.IsNullOrEmpty(text))
                            j.ProgressText = text.Length > 80 ? text[..80] + "…" : text;
                    });
                }
            }, ct);

            UpdateJob(job, j =>
            {
                j.Status = exitCode == 0 ? DownloadJobStatus.Complete : DownloadJobStatus.Failed;
                if (exitCode == 0) j.ProgressPercent = 100;
            });

            Log.Info("DownloadQueue", $"{job.Slug} finished exitCode={exitCode}");
        }
        catch (OperationCanceledException)
        {
            Log.Info("DownloadQueue", $"{job.Slug} cancelled");
            UpdateJob(job, j => j.Status = DownloadJobStatus.Cancelled);
        }
        catch (Exception ex)
        {
            Log.Error("DownloadQueue", ex);
            UpdateJob(job, j => j.Status = DownloadJobStatus.Failed);
        }
    }
}
