using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace GOGGUI.Views;

public sealed partial class DownloadQueueView : Page
{
    private readonly DownloadQueueService _queue;

    public DownloadQueueView()
    {
        this.InitializeComponent();
        _queue = App.DownloadQueue;
        QueueList.ItemsSource = _queue.Queue;
        _queue.Queue.CollectionChanged += (_, _) => RefreshHeader();
        RefreshHeader();
    }

    private void RefreshHeader()
    {
        var active  = _queue.Queue.Count(j => j.Status == DownloadJobStatus.Downloading);
        var queued  = _queue.Queue.Count(j => j.Status == DownloadJobStatus.Queued);
        ActiveCountLabel.Text = $"{active} downloading / {queued} queued";
        SlotLabel.Text = _queue.IsRunning ? "⬇️ Running" : "⏸️ Idle";
    }

    private async void StartButton_Click(object sender, RoutedEventArgs e)
    {
        RefreshHeader();
        await _queue.StartAsync();
        RefreshHeader();
    }

    private void CancelAllButton_Click(object sender, RoutedEventArgs e)
    {
        _queue.CancelAll();
        RefreshHeader();
    }

    private void ClearFinishedButton_Click(object sender, RoutedEventArgs e)
    {
        _queue.ClearFinished();
        RefreshHeader();
    }

    private void CancelJobButton_Click(object sender, RoutedEventArgs e)
    {
        // Individual cancel not possible mid-batch — cancel all instead
        // (lgogdownloader doesn't support cancelling a single game from a pipe list)
        if (sender is Button btn && btn.Tag is DownloadJob job &&
            job.Status == DownloadJobStatus.Queued)
        {
            Queue_RemoveQueued(job);
        }
    }

    private void Queue_RemoveQueued(DownloadJob job)
    {
        // Only jobs not yet started can be removed individually
        if (job.Status == DownloadJobStatus.Queued)
        {
            job.Status = DownloadJobStatus.Cancelled;
            _queue.Queue.Remove(job);
        }
    }
}
