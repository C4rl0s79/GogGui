using Microsoft.UI.Xaml;
using Microsoft.Windows.ApplicationModel.DynamicDependency;
using GOGGUI.Core.Services;

namespace GOGGUI;

public partial class App : Application
{
    public static DownloadQueueService DownloadQueue { get; private set; } = null!;
    private static readonly LogService Log = LogService.Instance;

    public App()
    {
        // Bootstrap Windows App SDK runtime for unpackaged apps
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

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        Log.Info("App", "OnLaunched");

        var wsl = new WslProcessService();
        var settings = new AppSettingsService();
        _ = settings.LoadAsync();
        DownloadQueue = new DownloadQueueService(wsl, settings);

        Log.Info("App", $"Log: {Log.LogFilePath}");

        var window = new MainWindow();
        window.Activate();
    }
}
