using GOGGUI.Core.Models;

namespace GOGGUI.Core.Services;

/// <summary>
/// Scans the Windows GOG library directory and returns a list of GameState objects.
/// Each subfolder in LibraryDirWindows is treated as a game (slug = folder name).
/// lgogdownloader saves covers as:
///   logo_&lt;slug&gt;.jpg  — primary (used as card cover)
///   icon_&lt;slug&gt;.png  — fallback
/// </summary>
public sealed class LibraryScanService
{
    private static readonly HashSet<string> InstallerExts =
        new(StringComparer.OrdinalIgnoreCase) { ".exe", ".bin", ".sh", ".pkg" };

    private static readonly HashSet<string> ExtrasExts =
        new(StringComparer.OrdinalIgnoreCase) { ".pdf", ".mp3", ".flac", ".ogg", ".zip", ".cbz", ".cbr" };

    private readonly AppSettingsService _settings;

    public LibraryScanService(AppSettingsService settings)
    {
        _settings = settings;
    }

    public Task<List<GameState>> ScanAsync(CancellationToken ct = default)
        => Task.Run(() => Scan(ct), ct);

    private List<GameState> Scan(CancellationToken ct)
    {
        var libraryDir = _settings.Current.LibraryDirWindows;
        var result = new List<GameState>();

        if (string.IsNullOrWhiteSpace(libraryDir) || !Directory.Exists(libraryDir))
            return result;

        foreach (var gameDir in Directory.EnumerateDirectories(libraryDir))
        {
            ct.ThrowIfCancellationRequested();
            var slug = Path.GetFileName(gameDir);
            result.Add(ScanGameFolder(slug, gameDir));
        }

        return result.OrderBy(g => g.Slug).ToList();
    }

    private GameState ScanGameFolder(string slug, string dirPath)
    {
        var files = Directory.EnumerateFiles(dirPath, "*", SearchOption.AllDirectories).ToList();

        var installerFiles = files.Where(f => InstallerExts.Contains(Path.GetExtension(f))).ToList();
        var extrasFiles    = files.Where(f => ExtrasExts.Contains(Path.GetExtension(f))).ToList();
        var xmlFiles       = files.Where(f => Path.GetExtension(f).Equals(".xml", StringComparison.OrdinalIgnoreCase)).ToList();

        var hasMetadata = files.Any(f =>
            Path.GetExtension(f).Equals(".json", StringComparison.OrdinalIgnoreCase) ||
            Path.GetFileName(f).Equals("gameinfo", StringComparison.OrdinalIgnoreCase));

        var hasAssets = files.Any(f =>
        {
            var ext = Path.GetExtension(f);
            return ext.Equals(".png", StringComparison.OrdinalIgnoreCase) ||
                   ext.Equals(".jpg", StringComparison.OrdinalIgnoreCase) ||
                   ext.Equals(".jpeg", StringComparison.OrdinalIgnoreCase);
        });

        long installersBytes = installerFiles.Sum(f =>
        {
            try { return new FileInfo(f).Length; }
            catch { return 0L; }
        });

        return new GameState
        {
            Slug               = slug,
            Title              = SlugToTitle(slug),
            SourceDirWindows   = dirPath,
            SourceDirWsl       = AppSettingsService.WindowsToWslPath(dirPath),
            HasMetadata        = hasMetadata,
            HasAssets          = hasAssets,
            HasXml             = xmlFiles.Count > 0,
            HasInstallers      = installerFiles.Count > 0,
            HasExtras          = extrasFiles.Count > 0,
            InstallersBytes    = installersBytes,
            InstallersComplete = installerFiles.Count > 0,
            LastScanUtc        = DateTimeOffset.UtcNow,
            Status             = installerFiles.Count > 0 ? GameStatus.Complete : GameStatus.NotDownloaded,
            CoverPath          = ResolveCoverPath(dirPath, slug),
        };
    }

    /// <summary>
    /// Looks for lgogdownloader cover files in order:
    /// 1. logo_&lt;slug&gt;.jpg   (product logo, best for card)
    /// 2. icon_&lt;slug&gt;.png   (icon fallback)
    /// Returns null if neither found — XAML will show initials instead.
    /// </summary>
    private static string? ResolveCoverPath(string dirPath, string slug)
    {
        var logo = Path.Combine(dirPath, $"logo_{slug}.jpg");
        if (File.Exists(logo)) return logo;

        var icon = Path.Combine(dirPath, $"icon_{slug}.png");
        if (File.Exists(icon)) return icon;

        return null;
    }

    /// <summary>Converts "the_witcher_3" → "The Witcher 3"</summary>
    private static string SlugToTitle(string slug)
    {
        if (string.IsNullOrEmpty(slug)) return slug;
        return string.Join(" ",
            slug.Split('_', '-')
                .Select(w => w.Length > 0
                    ? char.ToUpperInvariant(w[0]) + w[1..]
                    : w));
    }
}
