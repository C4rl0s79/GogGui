using GOGGUI.Core.Services;
using GOGGUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage.Pickers;

namespace GOGGUI.Views;

public sealed partial class SettingsView : Page
{
    private readonly SettingsViewModel _vm;

    public SettingsView()
    {
        this.InitializeComponent();
        var wsl  = new WslProcessService();
        var lgog = new LgogService(wsl);

        // BUG FIX #4: use the shared app-level settings service instead of creating a
        // new instance with a fire-and-forget LoadAsync.  This ensures that changes
        // saved here are immediately visible in LibraryView (same instance).
        _vm = new SettingsViewModel(App.Settings, lgog);
        BindUi();
    }

    private void BindUi()
    {
        WslDistroBox.Text          = _vm.WslDistro;
        LgogBinaryBox.Text         = _vm.LgogBinary;
        LibraryDirWindowsBox.Text  = _vm.LibraryDirWindows;
        LibraryDirWslBox.Text      = _vm.LibraryDirWsl;
        MetadataCacheDirBox.Text   = _vm.MetadataCacheDir;
        XmlCacheDirBox.Text        = _vm.XmlCacheDir;
        ExtrasToggle.IsOn          = _vm.DownloadExtrasByDefault;
        AutoRefreshToggle.IsOn     = _vm.AutoRefreshOnStart;
        LoginStatusLabel.Text      = _vm.LoginStatus;
        FirstRunBanner.Visibility  = _vm.IsFirstRun ? Visibility.Visible : Visibility.Collapsed;
        SteamGridDbApiKeyBox.Password = _vm.SteamGridDbApiKey;
        CoverCacheDirBox.Text      = _vm.CoverCacheDir;

        LibraryDirWindowsBox.TextChanged += (s, e) =>
        {
            _vm.LibraryDirWindows = LibraryDirWindowsBox.Text;
            LibraryDirWslBox.Text = _vm.LibraryDirWsl;
        };
    }

    private async void CheckLoginButton_Click(object sender, RoutedEventArgs e)
    {
        LoginProgress.IsActive = true;
        await _vm.CheckLoginCommand.ExecuteAsync(null);
        LoginStatusLabel.Text  = _vm.LoginStatus;
        LoginProgress.IsActive = false;
    }

    private async void LoginButton_Click(object sender, RoutedEventArgs e)
    {
        LoginProgress.IsActive = true;
        await _vm.LoginCommand.ExecuteAsync(null);
        LoginStatusLabel.Text  = _vm.LoginStatus;
        LoginProgress.IsActive = false;
    }

    private async void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        _vm.WslDistro               = WslDistroBox.Text;
        _vm.LgogBinary              = LgogBinaryBox.Text;
        _vm.LibraryDirWindows       = LibraryDirWindowsBox.Text;
        _vm.LibraryDirWsl           = LibraryDirWslBox.Text;
        _vm.MetadataCacheDir        = MetadataCacheDirBox.Text;
        _vm.XmlCacheDir             = XmlCacheDirBox.Text;
        _vm.DownloadExtrasByDefault = ExtrasToggle.IsOn;
        _vm.AutoRefreshOnStart      = AutoRefreshToggle.IsOn;
        _vm.SteamGridDbApiKey       = SteamGridDbApiKeyBox.Password;
        _vm.CoverCacheDir           = CoverCacheDirBox.Text;
        await _vm.SaveSettingsCommand.ExecuteAsync(null);
        StatusLabel.Text = _vm.StatusMessage;
    }

    private async void BrowseButton_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        picker.SuggestedStartLocation = PickerLocationId.ComputerFolder;
        picker.FileTypeFilter.Add("*");

        // BUG FIX #1: App.Current is a Microsoft.UI.Xaml.Application and does NOT
        // implement IWindowNative.  Passing it to GetWindowHandle throws a COMException
        // at runtime (the handle is either zero or the interop call fails).
        // App.MainWindow is set in App.OnLaunched before the first window is activated,
        // so it is always non-null here.
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindow!);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder != null)
        {
            LibraryDirWindowsBox.Text = folder.Path;
            _vm.LibraryDirWindows     = folder.Path;
            LibraryDirWslBox.Text     = _vm.LibraryDirWsl;
        }
    }
}
