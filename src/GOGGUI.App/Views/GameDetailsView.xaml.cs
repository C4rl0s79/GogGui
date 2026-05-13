using GOGGUI.Core.Models;
using GOGGUI.Core.Services;
using GOGGUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Navigation;

namespace GOGGUI.Views;

public sealed partial class GameDetailsView : Page
{
    private static readonly LogService Log = LogService.Instance;
    private GameDetailsViewModel? _vm;

    public GameDetailsView()
    {
        this.InitializeComponent();
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is not GameState game) return;

        Log.Info("GameDetails", $"Opened: {game.Slug}");

        var wsl = new WslProcessService();
        var lgog = new LgogService(wsl);
        var settingsService = new AppSettingsService();
        await settingsService.LoadAsync();
        var metadataService = new GameMetadataService();

        _vm = new GameDetailsViewModel(game, lgog, metadataService, settingsService);

        TitleLabel.Text  = game.Title;
        SlugLabel.Text   = game.Slug;
        ExtrasToggle.IsOn = _vm.DownloadExtras;

        ApplyCover(game);

        LoadingRing.IsActive = true;
        await _vm.InitAsync();
        LoadingRing.IsActive = false;

        BindData();
    }

    private void ApplyCover(GameState game)
    {
        if (!game.NoCover && game.CoverPath is not null)
        {
            try
            {
                CoverImage.Source = new BitmapImage(new Uri(game.CoverPath));
                CoverInitials.Visibility = Visibility.Collapsed;
                Log.Debug("GameDetails", $"Cover loaded: {game.CoverPath}");
            }
            catch (Exception ex)
            {
                Log.Warning("GameDetails", $"Cover load failed: {ex.Message}");
                ShowInitials(game.Title);
            }
        }
        else
        {
            ShowInitials(game.Title);
        }
    }

    private void ShowInitials(string title)
    {
        CoverImage.Source = null;
        CoverInitials.Text = string.Concat(
            title.Split(' ', StringSplitOptions.RemoveEmptyEntries)
                 .Take(2)
                 .Select(w => char.ToUpperInvariant(w[0])));
        CoverInitials.Visibility = Visibility.Visible;
    }

    private void BindData()
    {
        if (_vm is null) return;

        // Status badge
        var (badgeColor, badgeText) = _vm.Game.Status switch
        {
            GameStatus.Complete       => ("#107c10", "✅ Complete"),
            GameStatus.UpdateAvailable => ("#e85e00", "🔄 Update available"),
            _                          => ("#555555", "⏳ Not downloaded")
        };
        StatusBadge.Background = new SolidColorBrush(
            Windows.UI.Color.FromArgb(255,
                Convert.ToByte(badgeColor[1..3], 16),
                Convert.ToByte(badgeColor[3..5], 16),
                Convert.ToByte(badgeColor[5..7], 16)));
        StatusBadgeLabel.Text = badgeText;

        SizeLabel.Text = _vm.TotalLocalSize;
        UpdateBadge.Visibility = _vm.Game.Status == GameStatus.UpdateAvailable
            ? Visibility.Visible : Visibility.Collapsed;

        if (_vm.HasMetadata && _vm.Metadata is not null)
        {
            var meta = _vm.Metadata;

            if (!string.IsNullOrWhiteSpace(meta.Description?.Lead))
            {
                DescriptionLabel.Text  = meta.Description.Lead;
                DescriptionPanel.Visibility = Visibility.Visible;
            }

            if (!string.IsNullOrWhiteSpace(meta.ReleaseDate))
                ReleaseDateLabel.Text = $"Released: {meta.ReleaseDate}";

            if (!string.IsNullOrWhiteSpace(meta.Version))
            {
                VersionLabel.Text = $"v{meta.Version}";
                VersionBadge.Visibility = Visibility.Visible;
            }

            MetadataPanel.Visibility = Visibility.Visible;
            NoMetadataLabel.Visibility = Visibility.Collapsed;
            InstallersList.ItemsSource = meta.Installers;
            ExtrasList.ItemsSource     = meta.Extras;
            DlcList.ItemsSource        = meta.Dlcs;

            Log.Info("GameDetails", $"{_vm.Game.Slug}: metadata loaded, " +
                $"installers={meta.Installers?.Count ?? 0} extras={meta.Extras?.Count ?? 0}");
        }
        else
        {
            MetadataPanel.Visibility = Visibility.Collapsed;
            NoMetadataLabel.Visibility = Visibility.Visible;
            Log.Warning("GameDetails", $"{_vm.Game.Slug}: no metadata found");
        }
    }

    private void AddToQueueButton_Click(object sender, RoutedEventArgs e)
    {
        if (_vm is null) return;
        App.DownloadQueue.Enqueue(_vm.Game.Slug, _vm.Game.Title, ExtrasToggle.IsOn);
        QueuedLabel.Text = $"✅ Added to queue — go to Download Queue to start";
        QueuedLabel.Visibility = Visibility.Visible;
        Log.Info("GameDetails", $"Queued: {_vm.Game.Slug}");
    }

    private void AddExtrasToQueueButton_Click(object sender, RoutedEventArgs e)
    {
        if (_vm is null) return;
        App.DownloadQueue.Enqueue(_vm.Game.Slug + "__extras", _vm.Game.Title + " (extras)", includeExtras: true);
        QueuedLabel.Text = $"✅ Extras added to queue";
        QueuedLabel.Visibility = Visibility.Visible;
        Log.Info("GameDetails", $"Queued extras: {_vm.Game.Slug}");
    }

    private void OpenFolderButton_Click(object sender, RoutedEventArgs e)
    {
        _vm?.OpenFolderCommand.Execute(null);
    }
}
