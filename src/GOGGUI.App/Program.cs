using Microsoft.Windows.ApplicationModel.DynamicDependency;

// Unpackaged WinUI 3 — Bootstrap must be called before App() is created.
// https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/deploy-unpackaged-apps

var bootstrapResult = Bootstrap.Initialize(0x00010005); // Windows App SDK 1.5
if (bootstrapResult != 0)
{
    Console.Error.WriteLine($"[GogGui] Bootstrap failed: 0x{bootstrapResult:X8}");
    MessageBox(0,
        $"Failed to initialize Windows App SDK runtime (0x{bootstrapResult:X8}).\n\n" +
        "Please install Windows App SDK 1.5 runtime:\n" +
        "https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/downloads",
        "GogGui — Runtime missing", 0x10);
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
