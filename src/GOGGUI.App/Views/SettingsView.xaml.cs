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
        var wsl = new WslProcessService();
        var lgog = new LgogService(wsl);
        var settingsService = new AppSettingsService();
        _ = settingsService.LoadAsync();
        _vm = new SettingsViewModel(settingsService, lgog, wsl);
        BindUi();
    }

    private void BindUi()
    {
        WslDistroBox.Text = _vm.WslDistro;
        LgogBinaryBox.Text = _vm.LgogBinary;
        LibraryDirWindowsBox.Text = _vm.LibraryDirWindows;
        LibraryDirWslBox.Text = _vm.LibraryDirWsl;
        MetadataCacheDirBox.Text = _vm.MetadataCacheDir;
        XmlCacheDirBox.Text = _vm.XmlCacheDir;
        ExtrasToggle.IsOn = _vm.DownloadExtrasByDefault;
        AutoRefreshToggle.IsOn = _vm.AutoRefreshOnStart;
        LoginStatusLabel.Text = _vm.LoginStatus;
        FirstRunBanner.Visibility = _vm.IsFirstRun ? Visibility.Visible : Visibility.Collapsed;

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
        LoginStatusLabel.Text = _vm.LoginStatus;
        LoginProgress.IsActive = false;
    }

    private async void LoginButton_Click(object sender, RoutedEventArgs e)
    {
        LoginProgress.IsActive = true;
        await _vm.LoginCommand.ExecuteAsync(null);
        LoginStatusLabel.Text = _vm.LoginStatus;
        LoginProgress.IsActive = false;
    }

    private async void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        _vm.WslDistro = WslDistroBox.Text;
        _vm.LgogBinary = LgogBinaryBox.Text;
        _vm.LibraryDirWindows = LibraryDirWindowsBox.Text;
        _vm.LibraryDirWsl = LibraryDirWslBox.Text;
        _vm.MetadataCacheDir = MetadataCacheDirBox.Text;
        _vm.XmlCacheDir = XmlCacheDirBox.Text;
        _vm.DownloadExtrasByDefault = ExtrasToggle.IsOn;
        _vm.AutoRefreshOnStart = AutoRefreshToggle.IsOn;
        await _vm.SaveSettingsCommand.ExecuteAsync(null);
        StatusLabel.Text = _vm.StatusMessage;
    }

    private async void BrowseButton_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        picker.SuggestedStartLocation = Windows.Storage.Pickers.PickerLocationId.ComputerFolder;
        picker.FileTypeFilter.Add("*");

        // WinUI 3 requires window handle
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.Current);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder != null)
        {
            LibraryDirWindowsBox.Text = folder.Path;
            _vm.LibraryDirWindows = folder.Path;
            LibraryDirWslBox.Text = _vm.LibraryDirWsl;
        }
    }
}
