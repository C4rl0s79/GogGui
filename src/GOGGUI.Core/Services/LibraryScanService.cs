using GOGGUI.Core.Models;

namespace GOGGUI.Core.Services;

public sealed class LibraryScanService
{
    private static readonly LogService Log = LogService.Instance;

    private static readonly HashSet<string> InstallerExts =
        new(StringComparer.OrdinalIgnoreCase) { ".exe", ".bin", ".sh", ".pkg" };
    private static readonly HashSet<string> ExtrasExts =
        new(StringComparer.OrdinalIgnoreCase) { ".pdf", ".mp3", ".flac", ".ogg", ".zip", ".cbz", ".cbr" };

    private readonly AppSettingsService _settings;

    public LibraryScanService(AppSettingsService settings) => _settings = settings;

    public Task<List<GameState>> ScanAsync(CancellationToken ct = default)
        => Task.Run(() => Scan(ct), ct);

    private List<GameState> Scan(CancellationToken ct)
    {
        var libraryDir = _settings.Current.LibraryDirWindows;
        var result = new List<GameState>();

        if (string.IsNullOrWhiteSpace(libraryDir) || !Directory.Exists(libraryDir))
        {
            Log.Warning("LibraryScan", $"Library dir not found: {libraryDir}");
            return result;
        }

        var dirs = Directory.EnumerateDirectories(libraryDir).ToList();
        Log.Info("LibraryScan", $"Scanning {dirs.Count} folders in {libraryDir}");

        foreach (var gameDir in dirs)
        {
            ct.ThrowIfCancellationRequested();
            var slug = Path.GetFileName(gameDir);
            var state = ScanGameFolder(slug, gameDir);
            result.Add(state);
        }

        Log.Info("LibraryScan", $"Scan complete: {result.Count} games, " +
            $"{result.Count(g => g.HasInstallers)} with installers, " +
            $"{result.Count(g => !g.NoCover)} with covers");

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

        var cover = ResolveCoverPath(dirPath, slug);
        Log.Debug("LibraryScan", $"{slug}: installers={installerFiles.Count} cover={(cover ?? "none")}");

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
            CoverPath          = cover,
        };
    }

    private static string? ResolveCoverPath(string dirPath, string slug)
    {
        var logo = Path.Combine(dirPath, $"logo_{slug}.jpg");
        if (File.Exists(logo)) return logo;
        var icon = Path.Combine(dirPath, $"icon_{slug}.png");
        if (File.Exists(icon)) return icon;
        return null;
    }

    private static string SlugToTitle(string slug)
    {
        if (string.IsNullOrEmpty(slug)) return slug;
        return string.Join(" ",
            slug.Split('_', '-')
                .Select(w => w.Length > 0 ? char.ToUpperInvariant(w[0]) + w[1..] : w));
    }
}
