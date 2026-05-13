using GOGGUI.Core.Services;
using Microsoft.UI.Xaml;

namespace GOGGUI;

public partial class App : Application
{
    /// <summary>
    /// Singleton download queue shared across LibraryView, GameDetailsView and DownloadQueueView.
    /// </summary>
    public static DownloadQueueService DownloadQueue { get; private set; } = null!;

    public App()
    {
        this.InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        // Bootstrap shared services
        var wsl = new WslProcessService();
        var settings = new AppSettingsService();
        _ = settings.LoadAsync();
        DownloadQueue = new DownloadQueueService(wsl, settings);

        var window = new MainWindow();
        window.Activate();
    }
}
