using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using GOGGUI.Core.Models;
using GOGGUI.Core.Services;

namespace GOGGUI.ViewModels;

public partial class GameDetailsViewModel : ObservableObject
{
    private readonly LgogService _lgogService;
    private readonly GameMetadataService _metadataService;
    private readonly AppSettings _settings;

    [ObservableProperty] private GameState _game = new();
    [ObservableProperty] private GameMetadata? _metadata;
    [ObservableProperty] private string _status = string.Empty;
    [ObservableProperty] private bool _isLoading = false;
    [ObservableProperty] private bool _hasMetadata = false;
    [ObservableProperty] private List<FileInfo> _localFiles = new();
    [ObservableProperty] private string _totalLocalSize = string.Empty;
    [ObservableProperty] private bool _downloadExtras = false;

    public GameDetailsViewModel(
        GameState game,
        LgogService lgogService,
        GameMetadataService metadataService,
        AppSettingsService settingsService)
    {
        _lgogService = lgogService;
        _metadataService = metadataService;
        _settings = settingsService.Current;
        DownloadExtras = _settings.DownloadExtrasByDefault;
        Game = game;
    }

    public async Task InitAsync()
    {
        IsLoading = true;
        Metadata = await _metadataService.LoadAsync(Game);
        HasMetadata = Metadata is not null;
        LocalFiles = _metadataService.GetLocalInstallerFiles(Game);
        var totalBytes = LocalFiles.Sum(f => f.Length);
        TotalLocalSize = GameMetadataService.FormatBytes(totalBytes);
        IsLoading = false;
    }

    [RelayCommand]
    private async Task DownloadAsync()
    {
        IsLoading = true;
        Status = $"Downloading {Game.Title}...";
        Game.Status = GameStatus.Downloading;
        var result = await _lgogService.DownloadGameAsync(_settings, Game.Slug, DownloadExtras);
        Game.Status = result.ExitCode == 0 ? GameStatus.Complete : GameStatus.Error;
        Status = result.ExitCode == 0 ? "✅ Download complete" : $"❌ Failed: {result.StdErr}";
        LocalFiles = _metadataService.GetLocalInstallerFiles(Game);
        IsLoading = false;
    }

    [RelayCommand]
    private async Task DownloadExtrasOnlyAsync()
    {
        IsLoading = true;
        Status = $"Downloading extras for {Game.Title}...";
        var result = await _lgogService.DownloadGameAsync(_settings, Game.Slug, extras: true, extrasOnly: true);
        Status = result.ExitCode == 0 ? "✅ Extras downloaded" : $"❌ Failed: {result.StdErr}";
        LocalFiles = _metadataService.GetLocalInstallerFiles(Game);
        IsLoading = false;
    }

    [RelayCommand]
    private void OpenFolder()
    {
        if (Directory.Exists(Game.SourceDirWindows))
            System.Diagnostics.Process.Start("explorer.exe", Game.SourceDirWindows);
    }
}
