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
    private readonly UpdateCheckerService _updateChecker;

    // FIX #3: keep reference to the service (not a snapshot) so changes
    // saved in SettingsView are immediately visible without restarting.
    private readonly AppSettingsService _settingsService;

    // FIX #4: route single-game downloads through the shared queue.
    private readonly DownloadQueueService _downloadQueue;

    // Full unfiltered list
    private List<GameState> _allGames = new();

    // FIX #10: CancellationTokenSource for the current scan operation.
    private CancellationTokenSource? _scanCts;

    [ObservableProperty] private ObservableCollection<GameState> _games = new();
    [ObservableProperty] private string _status = "Ready";
    [ObservableProperty] private bool _isLoading = false;
    [ObservableProperty] private int _gameCount = 0;
    [ObservableProperty] private int _totalCount = 0;
    [ObservableProperty] private string _libraryDir = string.Empty;
    [ObservableProperty] private string _searchText = string.Empty;
    [ObservableProperty] private string _filterStatus = "All";
    [ObservableProperty] private string _sortBy = "Title";
    [ObservableProperty] private bool _isGridView = true;
    [ObservableProperty] private int _updatesAvailable = 0;

    public LibraryViewModel(
        LgogService lgogService,
        LibraryScanService scanService,
        CacheSyncService cacheSyncService,
        UpdateCheckerService updateChecker,
        AppSettingsService settingsService,
        DownloadQueueService downloadQueue)
    {
        _lgogService     = lgogService;
        _scanService     = scanService;
        _cacheSyncService = cacheSyncService;
        _updateChecker   = updateChecker;
        _settingsService = settingsService;
        _downloadQueue   = downloadQueue;

        // Read the current library dir for display; reflects latest saved settings.
        LibraryDir = _settingsService.Current.LibraryDirWindows;
    }

    partial void OnSearchTextChanged(string value) => ApplyFilter();
    partial void OnFilterStatusChanged(string value) => ApplyFilter();
    partial void OnSortByChanged(string value) => ApplyFilter();

    [RelayCommand]
    private async Task ScanLibraryAsync()
    {
        // FIX #10: cancel any ongoing scan before starting a new one.
        _scanCts?.Cancel();
        _scanCts?.Dispose();
        _scanCts = new CancellationTokenSource();
        var ct = _scanCts.Token;

        IsLoading = true;
        LibraryDir = _settingsService.Current.LibraryDirWindows; // always fresh
        Status = $"Scanning {LibraryDir}...";

        try
        {
            _allGames = await _scanService.ScanAsync(ct);
        }
        catch (OperationCanceledException)
        {
            Status = "Scan cancelled";
            IsLoading = false;
            return;
        }

        TotalCount = _allGames.Count;
        ApplyFilter();
        Status = TotalCount > 0
            ? $"Found {TotalCount} games"
            : "No games found — check Settings";
        IsLoading = false;
    }

    /// <summary>FIX #10: exposes cancellation to the View (e.g., a Cancel button).</summary>
    [RelayCommand]
    private void CancelScan() => _scanCts?.Cancel();

    [RelayCommand]
    private async Task CheckUpdatesAsync()
    {
        if (_allGames.Count == 0) { Status = "Scan library first"; return; }
        IsLoading = true;
        Status = "Checking for updates...";
        var progress = new Progress<string>(msg => Status = msg);
        var results = await _updateChecker.CheckAllAsync(_allGames, progress);

        int updated = 0;
        foreach (var r in results.Where(r => r.UpdateAvailable))
        {
            var game = _allGames.FirstOrDefault(g => g.Slug == r.Slug);
            if (game is not null)
            {
                game.Status = GameStatus.UpdateAvailable;
                updated++;
            }
        }

        UpdatesAvailable = updated;
        ApplyFilter();
        Status = updated > 0
            ? $"🔄 {updated} update(s) available"
            : "✅ All games up to date";
        IsLoading = false;
    }

    [RelayCommand]
    private async Task SyncCacheAsync()
    {
        if (_allGames.Count == 0) { Status = "Scan library first"; return; }
        IsLoading = true;
        Status = "Syncing metadata cache...";
        var progress = new Progress<string>(msg => Status = msg);
        var result = await _cacheSyncService.SyncAsync(_allGames, progress);
        Status = $"Sync: {result.Synced} updated, {result.Skipped} unchanged, {result.Errors} errors";
        await ScanLibraryAsync();
    }

    [RelayCommand]
    private async Task RefreshLibraryAsync()
    {
        IsLoading = true;
        Status = "Checking login...";
        var result = await _lgogService.CheckLoginStatusAsync(_settingsService.Current);
        if (result.ExitCode == 0)
            await ScanLibraryAsync();
        else
        {
            Status = "Please log in first (go to Settings)";
            IsLoading = false;
        }
    }

    [RelayCommand]
    private async Task UpdateMetadataAsync()
    {
        IsLoading = true;
        Status = "Updating metadata from GOG...";
        var result = await _lgogService.UpdateCacheAsync(_settingsService.Current);
        if (result.ExitCode == 0)
            await SyncCacheAsync();
        else
        {
            Status = $"lgog error: {result.StdErr}";
            IsLoading = false;
        }
    }

    /// <summary>
    /// FIX #4: enqueue the game in DownloadQueueService instead of calling
    /// LgogService directly — provides real progress reporting and a
    /// consistent queue UI.
    /// </summary>
    [RelayCommand]
    private async Task DownloadGameAsync(GameState game)
    {
        Status = $"Queuing {game.Title}...";
        game.Status = GameStatus.Downloading;
        ApplyFilter();

        _downloadQueue.Enqueue(game.Slug, game.Title, includeExtras: false);
        await _downloadQueue.StartAsync();

        // After the queue finishes, re-scan so status badges update.
        await ScanLibraryAsync();
    }

    private void ApplyFilter()
    {
        var filtered = _allGames.AsEnumerable();

        if (!string.IsNullOrWhiteSpace(SearchText))
            filtered = filtered.Where(g =>
                g.Title.Contains(SearchText, StringComparison.OrdinalIgnoreCase) ||
                g.Slug.Contains(SearchText, StringComparison.OrdinalIgnoreCase));

        filtered = FilterStatus switch
        {
            "Complete"        => filtered.Where(g => g.Status == GameStatus.Complete),
            "NotDownloaded"   => filtered.Where(g => g.Status == GameStatus.NotDownloaded),
            "UpdateAvailable" => filtered.Where(g => g.Status == GameStatus.UpdateAvailable),
            "HasExtras"       => filtered.Where(g => g.HasExtras),
            _                 => filtered
        };

        filtered = SortBy switch
        {
            "Size"   => filtered.OrderByDescending(g => g.InstallersBytes),
            "Status" => filtered.OrderBy(g => g.Status.ToString()),
            _        => filtered.OrderBy(g => g.Title)
        };

        Games = new ObservableCollection<GameState>(filtered);
        GameCount = Games.Count;
    }
}
