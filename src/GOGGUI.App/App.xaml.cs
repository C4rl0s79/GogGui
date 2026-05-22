using Microsoft.UI.Xaml;
using Microsoft.Windows.ApplicationModel.DynamicDependency;
using GOGGUI.Core.Services;
using System.Runtime.InteropServices;

namespace GOGGUI;

public partial class App : Application
{
    public static DownloadQueueService DownloadQueue { get; private set; } = null!;
    public static AppSettingsService   Settings      { get; private set; } = null!;

    private static readonly LogService Log = LogService.Instance;

    // P/Invoke for a last-resort error dialog that works before WinUI is alive.
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr hWnd, string text, string caption, uint type);

    private static void Fatal(string context, Exception ex)
    {
        var msg = $"{context}\n\n{ex.GetType().Name}: {ex.Message}\n\n{ex.StackTrace}";
        try { Log.Error(context, ex); } catch { /* log may itself be broken */ }
        MessageBox(IntPtr.Zero, msg, $"GogGui — Fatal error in {context}", 0x10 /* MB_ICONERROR */);
        Environment.Exit(1);
    }

    public App()
    {
        // Hook unhandled exceptions as early as possible — before InitializeComponent.
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
            Fatal("AppDomain.UnhandledException", (Exception)e.ExceptionObject);

        TaskScheduler.UnobservedTaskException += (_, e) =>
        {
            e.SetObserved();
            Fatal("TaskScheduler.UnobservedTaskException", e.Exception);
        };

        // Bootstrap MUST run before InitializeComponent so WinUI XAML resources resolve.
        // Version 1.5.x == 0x00010005; if the exact version is absent the runtime
        // will fall back to the nearest compatible one when WindowsAppSDKSelfContained=true.
        try
        {
            Bootstrap.Initialize(0x00010005);
            Log.Info("App", "Windows App SDK Bootstrap OK");
        }
        catch (Exception ex)
        {
            Fatal("Bootstrap.Initialize", ex);
            return; // unreachable — satisfies compiler
        }

        try
        {
            this.InitializeComponent();
        }
        catch (Exception ex)
        {
            Fatal("App.InitializeComponent", ex);
        }
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            Log.Info("App", "OnLaunched");

            var wsl      = new WslProcessService();
            var settings = new AppSettingsService();
            await settings.LoadAsync();

            Settings      = settings;
            DownloadQueue = new DownloadQueueService(wsl, settings);

            Log.Info("App", $"Log file: {Log.LogFilePath}");

            var window = new MainWindow();
            window.Activate();
        }
        catch (Exception ex)
        {
            Fatal("OnLaunched", ex);
        }
    }
}
