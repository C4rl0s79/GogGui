using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using System.Collections.ObjectModel;

namespace GOGGUI.ViewModels;

public partial class LibraryViewModel : ObservableObject
{
    private readonly LgogService _lgogService;
    private readonly AppSettings _settings;

    [ObservableProperty]
    private ObservableCollection<GameState> _games = new();

    [ObservableProperty]
    private string _status = "Ready";

    [ObservableProperty]
    private string _loginStatus = "Not checked";

    [ObservableProperty]
    private bool _isLoading = false;

    public LibraryViewModel(LgogService lgogService)
    {
        _lgogService = lgogService;
        _settings = new AppSettings();
    }

    [RelayCommand]
    private async Task RefreshLibraryAsync()
    {
        IsLoading = true;
        Status = "Checking login status...";
        var result = await _lgogService.CheckLoginStatusAsync(_settings);
        LoginStatus = result.ExitCode == 0 ? "Logged in" : "Not logged in";
        Status = result.ExitCode == 0 ? "Library ready" : "Please log in first";
        IsLoading = false;
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
    private async Task UpdateMetadataAsync()
    {
        IsLoading = true;
        Status = "Updating metadata from GOG...";
        var result = await _lgogService.UpdateCacheAsync(_settings);
        Status = result.ExitCode == 0 ? "Metadata updated" : $"Error: {result.StdErr}";
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
            ? $"{game.Title} downloaded successfully"
            : $"Download failed: {result.StdErr}";
    }
}
