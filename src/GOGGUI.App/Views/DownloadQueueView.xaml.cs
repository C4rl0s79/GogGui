using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace GOGGUI.Views;

public sealed partial class DownloadQueueView : Page
{
    // Singleton queue service — shared across the app via App.DownloadQueue
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
        var active = _queue.Queue.Count(j => j.Status == DownloadJobStatus.Downloading);
        var queued = _queue.Queue.Count(j => j.Status == DownloadJobStatus.Queued);
        ActiveCountLabel.Text = $"{active} active / {queued} queued";
        SlotLabel.Text = $"Max 4 concurrent games";
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
        if (sender is Button btn && btn.Tag is DownloadJob job)
            _queue.Cancel(job);
    }
}
