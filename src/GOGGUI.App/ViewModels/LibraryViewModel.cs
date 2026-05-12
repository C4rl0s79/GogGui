using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using System.Collections.ObjectModel;

namespace GOGGUI.ViewModels;

public partial class LibraryViewModel : ObservableObject
{
    private readonly LgogService _lgogService;
    private readonly LibraryScanService _scanService;
    private readonly CacheSyncService _cacheSyncService;
    private readonly AppSettings _settings;

    [ObservableProperty] private ObservableCollection<GameState> _games = new();
    [ObservableProperty] private string _status = "Ready";
    [ObservableProperty] private string _loginStatus = "Not checked";
    [ObservableProperty] private bool _isLoading = false;
    [ObservableProperty] private int _gameCount = 0;
    [ObservableProperty] private string _libraryDir = string.Empty;

    public LibraryViewModel(
        LgogService lgogService,
        LibraryScanService scanService,
        CacheSyncService cacheSyncService,
        AppSettingsService settingsService)
    {
        _lgogService = lgogService;
        _scanService = scanService;
        _cacheSyncService = cacheSyncService;
        _settings = settingsService.Current;
        LibraryDir = _settings.LibraryDirWindows;
    }

    [RelayCommand]
    private async Task ScanLibraryAsync()
    {
        IsLoading = true;
        Status = $"Scanning {LibraryDir}...";
        var found = await _scanService.ScanAsync();
        Games.Clear();
        foreach (var g in found) Games.Add(g);
        GameCount = Games.Count;
        Status = GameCount > 0
            ? $"Found {GameCount} games"
            : $"No games found in {LibraryDir} — check Settings";
        IsLoading = false;
    }

    [RelayCommand]
    private async Task SyncCacheAsync()
    {
        if (Games.Count == 0)
        {
            Status = "Scan library first";
            return;
        }
        IsLoading = true;
        Status = "Syncing metadata cache...";
        var progress = new Progress<string>(msg => Status = msg);
        var result = await _cacheSyncService.SyncAsync(Games, progress);
        Status = $"Cache sync: {result.Synced} updated, {result.Skipped} unchanged, {result.Errors} errors";
        if (result.Errors > 0)
            Status += $" | First error: {result.ErrorMessages.FirstOrDefault()}";
        // Refresh HasMetadata/HasXml badges
        await ScanLibraryAsync();
    }

    [RelayCommand]
    private async Task RefreshLibraryAsync()
    {
        IsLoading = true;
        Status = "Checking login status...";
        var result = await _lgogService.CheckLoginStatusAsync(_settings);
        LoginStatus = result.ExitCode == 0 ? "Logged in" : "Not logged in";
        if (result.ExitCode == 0)
            await ScanLibraryAsync();
        else
            Status = "Please log in first (go to Settings)";
        IsLoading = false;
    }

    [RelayCommand]
    private async Task UpdateMetadataAsync()
    {
        IsLoading = true;
        Status = "Updating metadata from GOG...";
        var result = await _lgogService.UpdateCacheAsync(_settings);
        if (result.ExitCode == 0)
        {
            Status = "Metadata updated from GOG, syncing to library...";
            await SyncCacheAsync();
        }
        else
        {
            Status = $"lgog error: {result.StdErr}";
            IsLoading = false;
        }
    }

    [RelayCommand]
    private async Task LoginAsync()
    {
        IsLoading = true;
        Status = "Opening login...";
        var result = await _lgogService.GuiLoginAsync(_settings);
        LoginStatus = result.ExitCode == 0 ? "Logged in" : "Login failed";
        Status = LoginStatus;
        IsLoading = false;
    }

    [RelayCommand]
    private async Task DownloadGameAsync(GameState game)
    {
        Status = $"Downloading {game.Title}...";
        game.Status = GameStatus.Downloading;
        var result = await _lgogService.DownloadGameAsync(_settings, game.Slug, false);
        game.Status = result.ExitCode == 0 ? GameStatus.Complete : GameStatus.Error;
        Status = result.ExitCode == 0
            ? $"{game.Title} downloaded"
            : $"Download failed: {result.StdErr}";
    }
}
