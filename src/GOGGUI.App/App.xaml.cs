using Microsoft.UI.Xaml;
using GOGGUI.Core.Services;
using System.Runtime.InteropServices;

namespace GOGGUI;

public partial class App : Application
{
    public static DownloadQueueService DownloadQueue { get; private set; } = null!;
    public static AppSettingsService   Settings      { get; private set; } = null!;

    // BUG FIX #1: expose the main window so views can pass it to pickers/dialogs that
    // require a real HWND (e.g. FolderPicker via WindowNative.GetWindowHandle).
    // Application does NOT implement IWindowNative; passing App.Current to
    // GetWindowHandle throws a COMException at runtime.
    public static Window? MainWindow { get; private set; }

    private static readonly LogService Log = LogService.Instance;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBox(IntPtr hWnd, string text, string caption, uint type);

    private static void Fatal(string context, Exception ex)
    {
        var msg = $"{context}\n\n{ex.GetType().Name}: {ex.Message}\n\n{ex.StackTrace}";
        try { Log.Error(context, ex); } catch { }
        MessageBox(IntPtr.Zero, msg, $"GogGui — Fatal error in {context}", 0x10);
        Environment.Exit(1);
    }

    public App()
    {
        // Bootstrap.Initialize is intentionally NOT called here.
        // When built with WindowsAppSDKSelfContained=true + WindowsPackageType=None
        // all Windows App SDK binaries are copied next to the EXE and are loaded
        // automatically by the OS loader. Calling Bootstrap.Initialize in that
        // configuration tries to register a packaged MSIX runtime that is absent
        // on plain Windows installs, causing a COMException on startup.

        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
            Fatal("AppDomain.UnhandledException", (Exception)e.ExceptionObject);

        TaskScheduler.UnobservedTaskException += (_, e) =>
        {
            e.SetObserved();
            Fatal("TaskScheduler.UnobservedTaskException", e.Exception);
        };

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
            // BUG FIX #1: assign before Activate so the window handle is available
            // the moment LibraryView / SettingsView constructors run.
            MainWindow = window;
            window.Activate();
        }
        catch (Exception ex)
        {
            Fatal("OnLaunched", ex);
        }
    }
}
