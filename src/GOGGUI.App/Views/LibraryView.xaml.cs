using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using GOGGUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace GOGGUI.Views;

public sealed partial class LibraryView : Page
{
    private readonly LibraryViewModel _vm;
    private readonly GameCoverService _coverService;
    private readonly AppSettingsService _settingsService;

    public LibraryView()
    {
        this.InitializeComponent();
        var wsl = new WslProcessService();
        var lgog = new LgogService(wsl);
        _settingsService = new AppSettingsService();
        _ = _settingsService.LoadAsync();
        var scan = new LibraryScanService(_settingsService);
        var cache = new CacheSyncService(_settingsService);
        var updates = new UpdateCheckerService();
        _coverService = new GameCoverService();
        _vm = new LibraryViewModel(lgog, scan, cache, updates, _settingsService);

        LibraryDirLabel.Text = _vm.LibraryDir;

        if (_settingsService.Current.AutoRefreshOnStart)
            _ = ScanAndFetchCoversAsync();
    }

    // --- Scan + cover fetch pipeline ---

    private async Task ScanAndFetchCoversAsync()
    {
        await RunAsync(() => _vm.ScanLibraryCommand.ExecuteAsync(null));

        var settings = _settingsService.Current;
        if (!string.IsNullOrWhiteSpace(settings.SteamGridDbApiKey))
        {
            LoadingRing.IsActive = true;
            StatusLabel.Text = "Fetching missing covers from SteamGridDB...";
            var progress = new Progress<string>(msg => StatusLabel.Text = msg);
            var results = await _coverService.FetchMissingCoversAsync(
                _vm.Games.ToList(), settings, progress);
            if (results.Count > 0)
            {
                StatusLabel.Text = $"🖼️ {results.Count} covers fetched";
                RefreshGrid();
            }
            LoadingRing.IsActive = false;
        }
    }

    // --- Toolbar events ---

    private async void ScanButton_Click(object sender, RoutedEventArgs e)
        => await ScanAndFetchCoversAsync();

    private async void CheckUpdatesButton_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => _vm.CheckUpdatesCommand.ExecuteAsync(null));

    private async void SyncCacheButton_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => _vm.SyncCacheCommand.ExecuteAsync(null));

    private async void UpdateMetadataButton_Click(object sender, RoutedEventArgs e)
        => await RunAsync(() => _vm.UpdateMetadataCommand.ExecuteAsync(null));

    // --- Search / filter / sort ---

    private void SearchBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        _vm.SearchText = SearchBox.Text;
        RefreshGrid();
    }

    private void FilterCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (FilterCombo.SelectedItem is ComboBoxItem item)
            _vm.FilterStatus = item.Tag?.ToString() ?? "All";
        RefreshGrid();
    }

    private void SortCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (SortCombo.SelectedItem is ComboBoxItem item)
            _vm.SortBy = item.Tag?.ToString() ?? "Title";
        RefreshGrid();
    }

    // --- View toggle (Grid / List) ---

    private void ViewToggle_Click(object sender, RoutedEventArgs e)
    {
        bool grid = sender == GridViewToggle;
        GridViewToggle.IsChecked = grid;
        ListViewToggle.IsChecked = !grid;
        GridScrollViewer.Visibility = grid ? Visibility.Visible : Visibility.Collapsed;
        GamesListView.Visibility   = grid ? Visibility.Collapsed : Visibility.Visible;
        RefreshGrid();
    }

    // --- Navigation ---

    private void GameCard_Tapped(object sender, Microsoft.UI.Xaml.Input.TappedRoutedEventArgs e)
    {
        if (sender is FrameworkElement el && el.DataContext is GameState game)
            Frame.Navigate(typeof(GameDetailsView), game);
    }

    private void GamesListView_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is GameState game)
            Frame.Navigate(typeof(GameDetailsView), game);
    }

    private async void DownloadButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is string slug)
        {
            var game = _vm.Games.FirstOrDefault(g => g.Slug == slug)
                       ?? new GameState { Slug = slug, Title = slug };
            await _vm.DownloadGameCommand.ExecuteAsync(game);
            RefreshStatus();
        }
    }

    // --- Helpers ---

    private async Task RunAsync(Func<Task> action)
    {
        LoadingRing.IsActive = true;
        await action();
        RefreshGrid();
        LoadingRing.IsActive = false;
    }

    private void RefreshGrid()
    {
        GamesRepeater.ItemsSource = null;
        GamesRepeater.ItemsSource = _vm.Games;
        GamesListView.ItemsSource = _vm.Games;
        RefreshStatus();
    }

    private void RefreshStatus()
    {
        StatusLabel.Text = _vm.Status;
        GameCountLabel.Text = _vm.GameCount > 0
            ? $"{_vm.GameCount} / {_vm.TotalCount} games"
            : string.Empty;
        UpdatesBadge.Visibility = _vm.UpdatesAvailable > 0
            ? Visibility.Visible : Visibility.Collapsed;
        UpdatesBadgeLabel.Text = $"🔄 {_vm.UpdatesAvailable} updates";
    }
}
