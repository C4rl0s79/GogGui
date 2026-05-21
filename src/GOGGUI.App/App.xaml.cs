using Microsoft.UI.Xaml;
using Microsoft.Windows.ApplicationModel.DynamicDependency;
using GOGGUI.Core.Services;

namespace GOGGUI;

public partial class App : Application
{
    // Exposed for simple DI via App.Current — could be replaced with a full DI container later.
    public static DownloadQueueService DownloadQueue { get; private set; } = null!;
    public static AppSettingsService   Settings      { get; private set; } = null!;

    private static readonly LogService Log = LogService.Instance;

    public App()
    {
        try
        {
            Bootstrap.Initialize(0x00010005);
            Log.Info("App", "Windows App SDK Bootstrap OK");
        }
        catch (Exception ex)
        {
            Log.Error("App", $"Bootstrap failed: {ex.Message}");
        }

        this.InitializeComponent();
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        Log.Info("App", "OnLaunched");

        var wsl      = new WslProcessService();
        var settings = new AppSettingsService();

        // FIX #1: properly await settings load before creating the window
        await settings.LoadAsync();

        Settings      = settings;
        DownloadQueue = new DownloadQueueService(wsl, settings);

        Log.Info("App", $"Log: {Log.LogFilePath}");

        var window = new MainWindow();
        window.Activate();
    }
}
