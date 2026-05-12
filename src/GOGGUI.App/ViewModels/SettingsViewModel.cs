using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using GOGGUI.Core.Models;
using GOGGUI.Core.Services;

namespace GOGGUI.ViewModels;

public partial class SettingsViewModel : ObservableObject
{
    private readonly AppSettingsService _settingsService;
    private readonly LgogService _lgogService;

    [ObservableProperty] private string _wslDistro = "Ubuntu";
    [ObservableProperty] private string _libraryDirWindows = @"D:\GOGInstall";
    [ObservableProperty] private string _libraryDirWsl = "/mnt/d/GOGInstall";
    [ObservableProperty] private string _metadataCacheDir = @"D:\GOGG\cache\games";
    [ObservableProperty] private string _xmlCacheDir = @"D:\GOGG\xml\games";
    [ObservableProperty] private string _lgogBinary = "lgogdownloader";
    [ObservableProperty] private bool _downloadExtrasByDefault = false;
    [ObservableProperty] private bool _autoRefreshOnStart = true;
    [ObservableProperty] private string _loginStatus = "Not checked";
    [ObservableProperty] private bool _isLoginChecking = false;
    [ObservableProperty] private string _statusMessage = string.Empty;
    [ObservableProperty] private bool _isSaving = false;
    [ObservableProperty] private bool _isFirstRun = false;

    public SettingsViewModel(AppSettingsService settingsService, LgogService lgogService)
    {
        _settingsService = settingsService;
        _lgogService = lgogService;
        IsFirstRun = settingsService.IsFirstRun;
        LoadFromSettings(settingsService.Current);
    }

    private void LoadFromSettings(AppSettings s)
    {
        WslDistro = s.WslDistro;
        LibraryDirWindows = s.LibraryDirWindows;
        LibraryDirWsl = s.LibraryDirWsl;
        MetadataCacheDir = s.MetadataCacheDir;
        XmlCacheDir = s.XmlCacheDir;
        LgogBinary = s.LgogBinary;
        DownloadExtrasByDefault = s.DownloadExtrasByDefault;
        AutoRefreshOnStart = s.AutoRefreshOnStart;
    }

    partial void OnLibraryDirWindowsChanged(string value)
    {
        LibraryDirWsl = AppSettingsService.WindowsToWslPath(value);
    }

    [RelayCommand]
    private async Task CheckLoginAsync()
    {
        IsLoginChecking = true;
        LoginStatus = "Checking...";
        var result = await _lgogService.CheckLoginStatusAsync(BuildSettings());
        LoginStatus = result.ExitCode == 0 ? "✅ Logged in" : "❌ Not logged in";
        IsLoginChecking = false;
    }

    [RelayCommand]
    private async Task LoginAsync()
    {
        IsLoginChecking = true;
        LoginStatus = "Opening login window...";
        var result = await _lgogService.GuiLoginAsync(BuildSettings());
        LoginStatus = result.ExitCode == 0 ? "✅ Logged in" : "❌ Login failed";
        IsLoginChecking = false;
    }

    [RelayCommand]
    private async Task SaveSettingsAsync()
    {
        IsSaving = true;
        StatusMessage = "Saving...";
        await _settingsService.SaveAsync(BuildSettings());
        StatusMessage = "✅ Settings saved!";
        IsFirstRun = false;
        IsSaving = false;
    }

    private AppSettings BuildSettings() => new()
    {
        WslDistro = WslDistro,
        LgogBinary = LgogBinary,
        LibraryDirWindows = LibraryDirWindows,
        LibraryDirWsl = LibraryDirWsl,
        MetadataCacheDir = MetadataCacheDir,
        XmlCacheDir = XmlCacheDir,
        DownloadExtrasByDefault = DownloadExtrasByDefault,
        AutoRefreshOnStart = AutoRefreshOnStart,
    };
}
