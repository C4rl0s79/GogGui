namespace GOGGUI.Core.Models;

public enum DownloadJobStatus
{
    Queued,
    Downloading,
    Complete,
    Failed,
    Cancelled
}

/// <summary>
/// Represents a single game download in the queue.
/// Observed by DownloadQueueView via INotifyPropertyChanged.
/// </summary>
public sealed class DownloadJob : System.ComponentModel.INotifyPropertyChanged
{
    public string Slug { get; init; } = string.Empty;
    public string Title { get; init; } = string.Empty;
    public bool IncludeExtras { get; init; }

    private DownloadJobStatus _status = DownloadJobStatus.Queued;
    public DownloadJobStatus Status
    {
        get => _status;
        set { _status = value; OnPropertyChanged(nameof(Status)); OnPropertyChanged(nameof(StatusLabel)); OnPropertyChanged(nameof(IsActive)); }
    }

    private int _progressPercent;
    public int ProgressPercent
    {
        get => _progressPercent;
        set { _progressPercent = value; OnPropertyChanged(nameof(ProgressPercent)); }
    }

    private string _progressText = string.Empty;
    public string ProgressText
    {
        get => _progressText;
        set { _progressText = value; OnPropertyChanged(nameof(ProgressText)); }
    }

    public string StatusLabel => Status switch
    {
        DownloadJobStatus.Queued      => "⏳ Queued",
        DownloadJobStatus.Downloading => "⬇️ Downloading",
        DownloadJobStatus.Complete    => "✅ Complete",
        DownloadJobStatus.Failed      => "❌ Failed",
        DownloadJobStatus.Cancelled   => "⛔ Cancelled",
        _                             => string.Empty
    };

    public bool IsActive => Status == DownloadJobStatus.Downloading;

    public CancellationTokenSource Cts { get; } = new();

    public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged(string name) =>
        PropertyChanged?.Invoke(this, new System.ComponentModel.PropertyChangedEventArgs(name));
}
