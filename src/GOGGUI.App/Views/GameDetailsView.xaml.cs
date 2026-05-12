using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using GOGGUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace GOGGUI.Views;

public sealed partial class GameDetailsView : Page
{
    private GameDetailsViewModel? _vm;

    public GameDetailsView()
    {
        this.InitializeComponent();
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);

        if (e.Parameter is not GameState game) return;

        var wsl = new WslProcessService();
        var lgog = new LgogService(wsl);
        var settingsService = new AppSettingsService();
        await settingsService.LoadAsync();
        var metadataService = new GameMetadataService();

        _vm = new GameDetailsViewModel(game, lgog, metadataService, settingsService);

        TitleLabel.Text = game.Title;
        SlugLabel.Text = game.Slug;
        ExtrasToggle.IsOn = _vm.DownloadExtras;

        LoadingRing.IsActive = true;
        await _vm.InitAsync();
        LoadingRing.IsActive = false;

        BindData();
    }

    private void BindData()
    {
        if (_vm is null) return;

        StatusLabel.Text = _vm.Game.Status.ToString();
        TotalSizeLabel.Text = _vm.TotalLocalSize;

        if (_vm.LocalFiles.Count > 0)
        {
            LocalFilesList.ItemsSource = _vm.LocalFiles.Select(f => new
            {
                f.Name,
                LengthHuman = GameMetadataService.FormatBytes(f.Length)
            }).ToList();
            NoFilesLabel.Visibility = Visibility.Collapsed;
        }
        else
        {
            LocalFilesList.Visibility = Visibility.Collapsed;
            NoFilesLabel.Visibility = Visibility.Visible;
        }

        if (_vm.HasMetadata && _vm.Metadata is not null)
        {
            MetadataPanel.Visibility = Visibility.Visible;
            NoMetadataLabel.Visibility = Visibility.Collapsed;
            DescriptionLabel.Text = _vm.Metadata.Description?.Lead ?? string.Empty;
            InstallersList.ItemsSource = _vm.Metadata.Installers;
            ExtrasList.ItemsSource = _vm.Metadata.Extras;
            DlcList.ItemsSource = _vm.Metadata.Dlcs;
        }
        else
        {
            MetadataPanel.Visibility = Visibility.Collapsed;
            NoMetadataLabel.Visibility = Visibility.Visible;
        }
    }

    private async void DownloadButton_Click(object sender, RoutedEventArgs e)
    {
        if (_vm is null) return;
        _vm.DownloadExtras = ExtrasToggle.IsOn;
        LoadingRing.IsActive = true;
        await _vm.DownloadCommand.ExecuteAsync(null);
        StatusLabel.Text = _vm.Status;
        BindData();
        LoadingRing.IsActive = false;
    }

    private async void DownloadExtrasButton_Click(object sender, RoutedEventArgs e)
    {
        if (_vm is null) return;
        LoadingRing.IsActive = true;
        await _vm.DownloadExtrasOnlyCommand.ExecuteAsync(null);
        StatusLabel.Text = _vm.Status;
        LoadingRing.IsActive = false;
    }

    private void OpenFolderButton_Click(object sender, RoutedEventArgs e)
    {
        _vm?.OpenFolderCommand.Execute(null);
    }
}
