using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using GOGGUI.ViewModels;
using Microsoft.UI.Xaml.Controls;

namespace GOGGUI.Views;

public sealed partial class LibraryView : Page
{
    private readonly LibraryViewModel _vm;

    public LibraryView()
    {
        this.InitializeComponent();
        var wslService = new WslProcessService();
        var lgogService = new LgogService(wslService);
        var settingsService = new AppSettingsService();
        _ = settingsService.LoadAsync();
        var scanService = new LibraryScanService(settingsService);
        var cacheSyncService = new CacheSyncService(settingsService);
        _vm = new LibraryViewModel(lgogService, scanService, cacheSyncService, settingsService);

        LibraryDirLabel.Text = _vm.LibraryDir;

        if (settingsService.Current.AutoRefreshOnStart)
            _ = _vm.ScanLibraryCommand.ExecuteAsync(null);
    }

    private async void ScanButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        LoadingRing.IsActive = true;
        await _vm.ScanLibraryCommand.ExecuteAsync(null);
        RefreshGrid();
        LoadingRing.IsActive = false;
    }

    private async void SyncCacheButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        LoadingRing.IsActive = true;
        await _vm.SyncCacheCommand.ExecuteAsync(null);
        RefreshGrid();
        LoadingRing.IsActive = false;
    }

    private async void RefreshButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        LoadingRing.IsActive = true;
        await _vm.RefreshLibraryCommand.ExecuteAsync(null);
        RefreshGrid();
        LoadingRing.IsActive = false;
    }

    private async void UpdateMetadataButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        LoadingRing.IsActive = true;
        await _vm.UpdateMetadataCommand.ExecuteAsync(null);
        StatusLabel.Text = _vm.Status;
        LoadingRing.IsActive = false;
    }

    private async void DownloadButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        if (sender is Microsoft.UI.Xaml.Controls.Button btn && btn.Tag is string slug)
        {
            var game = _vm.Games.FirstOrDefault(g => g.Slug == slug)
                       ?? new GameState { Slug = slug, Title = slug };
            await _vm.DownloadGameCommand.ExecuteAsync(game);
            StatusLabel.Text = _vm.Status;
        }
    }

    private void GameCard_Tapped(object sender, Microsoft.UI.Xaml.Input.TappedRoutedEventArgs e)
    {
        if (sender is Microsoft.UI.Xaml.FrameworkElement el && el.DataContext is GameState game)
        {
            Frame.Navigate(typeof(GameDetailsView), game);
        }
    }

    private void RefreshGrid()
    {
        GamesRepeater.ItemsSource = null;
        GamesRepeater.ItemsSource = _vm.Games;
        StatusLabel.Text = _vm.Status;
        GameCountLabel.Text = _vm.GameCount > 0 ? $"{_vm.GameCount} games" : "";
    }
}
