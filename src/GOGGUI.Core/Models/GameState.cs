using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace GOGGUI.Core.Models;

/// <summary>
/// FIX #6: Implements INotifyPropertyChanged so UI bindings automatically
/// refresh when Status, CoverPath or other properties change at runtime.
/// Intentionally avoids CommunityToolkit.Mvvm — GOGGUI.Core is a plain
/// .NET library and should not depend on a UI-layer NuGet package.
/// </summary>
public sealed class GameState : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    private void SetField<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    private string _slug = string.Empty;
    public string Slug { get => _slug; set => SetField(ref _slug, value); }

    private string _title = string.Empty;
    public string Title
    {
        get => _title;
        set
        {
            SetField(ref _title, value);
            // TitleInitials depends on Title
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(TitleInitials)));
        }
    }

    private string _sourceDirWindows = string.Empty;
    public string SourceDirWindows { get => _sourceDirWindows; set => SetField(ref _sourceDirWindows, value); }

    private string _sourceDirWsl = string.Empty;
    public string SourceDirWsl { get => _sourceDirWsl; set => SetField(ref _sourceDirWsl, value); }

    private bool _hasMetadata;
    public bool HasMetadata { get => _hasMetadata; set => SetField(ref _hasMetadata, value); }

    private bool _hasAssets;
    public bool HasAssets { get => _hasAssets; set => SetField(ref _hasAssets, value); }

    private bool _hasXml;
    public bool HasXml { get => _hasXml; set => SetField(ref _hasXml, value); }

    private bool _hasInstallers;
    public bool HasInstallers { get => _hasInstallers; set => SetField(ref _hasInstallers, value); }

    private bool _hasExtras;
    public bool HasExtras { get => _hasExtras; set => SetField(ref _hasExtras, value); }

    private bool _installersComplete;
    public bool InstallersComplete { get => _installersComplete; set => SetField(ref _installersComplete, value); }

    private long _installersBytes;
    public long InstallersBytes
    {
        get => _installersBytes;
        set
        {
            SetField(ref _installersBytes, value);
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(InstallersSize)));
        }
    }

    public DateTimeOffset LastScanUtc { get; set; }
    public DateTimeOffset LastMetadataSyncUtc { get; set; }

    private GameStatus _status;
    public GameStatus Status
    {
        get => _status;
        set
        {
            SetField(ref _status, value);
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(IsUpdateAvailable)));
        }
    }

    // FIX #7: CoverPath notifies NoCover when it changes; File.Exists result
    // is cached so it is not called on every XAML binding evaluation.
    private string? _coverPath;
    private bool? _noCoverCached;

    public string? CoverPath
    {
        get => _coverPath;
        set
        {
            if (_coverPath == value) return;
            _coverPath = value;
            _noCoverCached = null; // invalidate cache
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(CoverPath)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(NoCover)));
        }
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
    /// FIX #7: File.Exists is called at most once per CoverPath value.
    /// </summary>
    public bool NoCover
    {
        get
        {
            _noCoverCached ??= string.IsNullOrEmpty(_coverPath) || !File.Exists(_coverPath);
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
