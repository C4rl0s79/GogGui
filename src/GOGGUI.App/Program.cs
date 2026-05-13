using Microsoft.Windows.AppLifecycle;
using Microsoft.WindowsAppSDK.Runtime;

// Unpackaged WinUI 3 requires explicit Bootstrap initialization before App() is created.
// https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/deploy-unpackaged-apps

var bootstrapResult = Bootstrap.Initialize(0x00010005); // major=1, minor=5
if (bootstrapResult != 0)
{
    // If bootstrap fails, show a message and exit gracefully.
    Console.Error.WriteLine($"[GogGui] Windows App SDK Bootstrap failed: 0x{bootstrapResult:X8}");
    Console.Error.WriteLine("Install Windows App SDK 1.5 runtime: https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/downloads");
    MessageBox(0, $"Failed to initialize Windows App SDK runtime (0x{bootstrapResult:X8}).\n\nPlease install Windows App SDK 1.5:\nhttps://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/downloads",
        "GogGui - Runtime missing", 0x10);
    return 1;
}

try
{
    Microsoft.UI.Xaml.Application.Start(p =>
    {
        var context = new DispatcherQueueSynchronizationContext(
            Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread());
        SynchronizationContext.SetSynchronizationContext(context);
        _ = new GOGGUI.App();
    });
}
finally
{
    Bootstrap.Uninitialize();
}

return 0;

[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
static extern int MessageBox(nint hWnd, string text, string caption, uint type);
