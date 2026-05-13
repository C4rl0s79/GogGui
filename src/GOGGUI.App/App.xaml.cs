using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;
using GOGGUI.Core.Services;

namespace GOGGUI;

public partial class App : Application
{
    /// <summary>
    /// Singleton download queue shared across all views.
    /// </summary>
    public static DownloadQueueService DownloadQueue { get; private set; } = null!;

    private static readonly LogService Log = LogService.Instance;

    public App()
    {
        this.InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        Log.Info("App", "OnLaunched — bootstrapping services");

        // Bootstrap shared services
        var wsl = new WslProcessService();
        var settings = new AppSettingsService();
        _ = settings.LoadAsync();
        DownloadQueue = new DownloadQueueService(wsl, settings);

        Log.Info("App", $"Log file: {Log.LogFilePath}");

        var window = new MainWindow();
        window.Activate();
    }
}
