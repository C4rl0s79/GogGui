using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using GOGGUI.ViewModels;
using Microsoft.UI.Xaml.Controls;

namespace GOGGUI.Views;

public sealed partial class LibraryView : Page
{
    private readonly LibraryViewModel _viewModel;

    public LibraryView()
    {
        this.InitializeComponent();
        var wslService = new WslProcessService();
        var lgogService = new LgogService(wslService);
        _viewModel = new LibraryViewModel(lgogService);
    }

    private async void RefreshButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        await _viewModel.RefreshLibraryCommand.ExecuteAsync(null);
    }

    private async void LoginButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        await _viewModel.LoginCommand.ExecuteAsync(null);
    }

    private async void UpdateMetadataButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        await _viewModel.UpdateMetadataCommand.ExecuteAsync(null);
    }

    private async void DownloadButton_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is string slug)
        {
            var game = new GameState { Slug = slug, Title = slug };
            await _viewModel.DownloadGameCommand.ExecuteAsync(game);
        }
    }
}
