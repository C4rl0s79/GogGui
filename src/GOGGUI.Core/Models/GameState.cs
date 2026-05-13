namespace GOGGUI.Core.Models;

public sealed class GameState
{
    public string Slug { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string SourceDirWindows { get; set; } = string.Empty;
    public string SourceDirWsl { get; set; } = string.Empty;
    public bool HasMetadata { get; set; }
    public bool HasAssets { get; set; }
    public bool HasXml { get; set; }
    public bool HasInstallers { get; set; }
    public bool HasExtras { get; set; }
    public bool InstallersComplete { get; set; }
    public long InstallersBytes { get; set; }
    public DateTimeOffset LastScanUtc { get; set; }
    public DateTimeOffset LastMetadataSyncUtc { get; set; }
    public GameStatus Status { get; set; }

    // Cover image path - set by LibraryScanService if found locally
    public string? CoverPath { get; set; }

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

    /// <summary>True when no local cover image exists — shows initials fallback.</summary>
    public bool NoCover => string.IsNullOrEmpty(CoverPath) || !File.Exists(CoverPath);

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
