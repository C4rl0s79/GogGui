using CommunityToolkit.Mvvm.ComponentModel;

namespace GOGGUI.Core.Models;

/// <summary>
/// FIX #6: Changed from plain class to ObservableObject so that UI bindings
/// (e.g., game cards in LibraryView) automatically refresh when Status,
/// CoverPath or other properties change at runtime.
/// </summary>
public sealed partial class GameState : ObservableObject
{
    [ObservableProperty] private string _slug = string.Empty;
    [ObservableProperty] private string _title = string.Empty;
    [ObservableProperty] private string _sourceDirWindows = string.Empty;
    [ObservableProperty] private string _sourceDirWsl = string.Empty;
    [ObservableProperty] private bool _hasMetadata;
    [ObservableProperty] private bool _hasAssets;
    [ObservableProperty] private bool _hasXml;
    [ObservableProperty] private bool _hasInstallers;
    [ObservableProperty] private bool _hasExtras;
    [ObservableProperty] private bool _installersComplete;
    [ObservableProperty] private long _installersBytes;
    [ObservableProperty] private DateTimeOffset _lastScanUtc;
    [ObservableProperty] private DateTimeOffset _lastMetadataSyncUtc;
    [ObservableProperty] private GameStatus _status;

    // FIX #7: CoverPath is now an [ObservableProperty] so the
    // binding pipeline is notified when it changes, and NoCover
    // is recomputed lazily rather than calling File.Exists() on
    // every XAML binding pass.
    [ObservableProperty] private string? _coverPath;

    // Cache the result of File.Exists so it is not evaluated
    // on every UI binding tick (hundreds of calls at startup
    // for large libraries).
    private bool? _noCoverCached;

    partial void OnCoverPathChanged(string? value)
    {
        _noCoverCached = null; // invalidate cache when path changes
        OnPropertyChanged(nameof(NoCover));
        OnPropertyChanged(nameof(TitleInitials)); // may depend indirectly on Title
    }

    // --- Computed helpers for XAML bindings ---

    /// <summary>First 2 capital letters of title for cover fallback.</summary>
    public string TitleInitials
    {
        get
        {
            var words = Title.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            return words.Length >= 2
                ? $"{char.ToUpper(words[0][0])}{char.ToUpper(words[1][0])}"
                : Title.Length > 0 ? Title[..Math.Min(2, Title.Length)].ToUpper() : "?";
        }
    }

    /// <summary>
    /// True when no local cover image exists — shows initials fallback.
    /// FIX #7: result is cached per CoverPath value; File.Exists() is called
    /// at most once per scan, not on every XAML binding evaluation.
    /// </summary>
    public bool NoCover
    {
        get
        {
            _noCoverCached ??= string.IsNullOrEmpty(CoverPath) || !File.Exists(CoverPath);
            return _noCoverCached.Value;
        }
    }

    /// <summary>Visibility helper for UpdateAvailable badge.</summary>
    public bool IsUpdateAvailable => Status == GameStatus.UpdateAvailable;

    /// <summary>Human readable size of local installers.</summary>
    public string InstallersSize => InstallersBytes switch
    {
        >= 1_073_741_824 => $"{InstallersBytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576     => $"{InstallersBytes / 1_048_576.0:F0} MB",
        0                => string.Empty,
        _                => $"{InstallersBytes / 1024} KB"
    };
}
