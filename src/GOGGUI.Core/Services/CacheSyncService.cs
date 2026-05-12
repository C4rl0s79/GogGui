using GOGGUI.Core.Models;

namespace GOGGUI.Core.Services;

/// <summary>
/// Syncs lgogdownloader metadata (JSON) and XML files from cache directories
/// into each game's folder inside LibraryDirWindows.
/// 
/// lgogdownloader stores metadata in:
///   MetadataCacheDir\<slug>.json   (game info, DLC list, download URLs)
///   XmlCacheDir\<slug>\*.xml       (file checksums for download verification)
/// </summary>
public sealed class CacheSyncService
{
    private readonly AppSettingsService _settingsService;

    public CacheSyncService(AppSettingsService settingsService)
    {
        _settingsService = settingsService;
    }

    public record SyncResult(
        int Synced,
        int Skipped,
        int Errors,
        List<string> ErrorMessages
    );

    /// <summary>
    /// For each GameState, copies matching metadata JSON and XML files
    /// from cache dirs into the game's SourceDirWindows folder.
    /// </summary>
    public Task<SyncResult> SyncAsync(
        IReadOnlyList<GameState> games,
        IProgress<string>? progress = null,
        CancellationToken ct = default)
    {
        return Task.Run(() => Sync(games, progress, ct), ct);
    }

    private SyncResult Sync(
        IReadOnlyList<GameState> games,
        IProgress<string>? progress,
        CancellationToken ct)
    {
        var s = _settingsService.Current;
        int synced = 0, skipped = 0, errors = 0;
        var errorMessages = new List<string>();

        foreach (var game in games)
        {
            ct.ThrowIfCancellationRequested();
            progress?.Report($"Syncing cache for {game.Title}...");

            // --- JSON metadata ---
            var jsonSrc = Path.Combine(s.MetadataCacheDir, $"{game.Slug}.json");
            if (File.Exists(jsonSrc))
            {
                var jsonDst = Path.Combine(game.SourceDirWindows, $"{game.Slug}.json");
                try
                {
                    if (NeedsUpdate(jsonSrc, jsonDst))
                    {
                        File.Copy(jsonSrc, jsonDst, overwrite: true);
                        game.HasMetadata = true;
                        game.LastMetadataSyncUtc = DateTimeOffset.UtcNow;
                        synced++;
                    }
                    else
                    {
                        skipped++;
                    }
                }
                catch (Exception ex)
                {
                    errors++;
                    errorMessages.Add($"{game.Slug} JSON: {ex.Message}");
                }
            }

            // --- XML files ---
            var xmlSrcDir = Path.Combine(s.XmlCacheDir, game.Slug);
            if (Directory.Exists(xmlSrcDir))
            {
                var xmlDstDir = Path.Combine(game.SourceDirWindows, "xml");
                Directory.CreateDirectory(xmlDstDir);

                foreach (var xmlFile in Directory.EnumerateFiles(xmlSrcDir, "*.xml"))
                {
                    ct.ThrowIfCancellationRequested();
                    var xmlDst = Path.Combine(xmlDstDir, Path.GetFileName(xmlFile));
                    try
                    {
                        if (NeedsUpdate(xmlFile, xmlDst))
                        {
                            File.Copy(xmlFile, xmlDst, overwrite: true);
                            game.HasXml = true;
                            synced++;
                        }
                        else
                        {
                            skipped++;
                        }
                    }
                    catch (Exception ex)
                    {
                        errors++;
                        errorMessages.Add($"{game.Slug} XML {Path.GetFileName(xmlFile)}: {ex.Message}");
                    }
                }
            }
        }

        return new SyncResult(synced, skipped, errors, errorMessages);
    }

    /// <summary>
    /// Returns true if dst doesn't exist or src is newer/larger than dst.
    /// </summary>
    private static bool NeedsUpdate(string src, string dst)
    {
        if (!File.Exists(dst)) return true;
        var srcInfo = new FileInfo(src);
        var dstInfo = new FileInfo(dst);
        return srcInfo.LastWriteTimeUtc > dstInfo.LastWriteTimeUtc
            || srcInfo.Length != dstInfo.Length;
    }

    /// <summary>
    /// Scans MetadataCacheDir and XmlCacheDir to find slugs that have cache
    /// but no matching folder in LibraryDirWindows (not yet downloaded).
    /// </summary>
    public List<string> FindUnsyncedSlugs(IReadOnlyList<GameState> existingGames)
    {
        var s = _settingsService.Current;
        var knownSlugs = new HashSet<string>(existingGames.Select(g => g.Slug),
                                             StringComparer.OrdinalIgnoreCase);
        var result = new List<string>();

        if (Directory.Exists(s.MetadataCacheDir))
        {
            foreach (var file in Directory.EnumerateFiles(s.MetadataCacheDir, "*.json"))
            {
                var slug = Path.GetFileNameWithoutExtension(file);
                if (!knownSlugs.Contains(slug))
                    result.Add(slug);
            }
        }

        return result.OrderBy(x => x).ToList();
    }
}
