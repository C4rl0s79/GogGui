using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using System.Collections.ObjectModel;

namespace GOGGUI.ViewModels;

public partial class LibraryViewModel : ObservableObject
{
    private readonly LgogService _lgogService;

    [ObservableProperty]
    private ObservableCollection<GameState> _games = new();

    [ObservableProperty]
    private string _status = "Ready";

    public LibraryViewModel(LgogService lgogService)
    {
        _lgogService = lgogService;
    }

    [RelayCommand]
    private async Task RefreshLibraryAsync()
    {
        Status = "Refreshing library...";
        // Scan local directory and load games
        await Task.Delay(500); // Placeholder
        Status = "Library refreshed";
    }

    [RelayCommand]
    private async Task UpdateMetadataAsync()
    {
        Status = "Updating metadata from GOG...";
        // Call lgogdownloader --update-cache
        await Task.Delay(500); // Placeholder
        Status = "Metadata updated";
    }

    [RelayCommand]
    private async Task DownloadGameAsync(GameState game)
    {
        Status = $"Downloading {game.Title}...";
        // Call lgogdownloader --download --game {slug}
        game.Status = GameStatus.Downloading;
        await Task.Delay(1000); // Placeholder
        game.Status = GameStatus.Complete;
        Status = $"{game.Title} downloaded";
    }
}
