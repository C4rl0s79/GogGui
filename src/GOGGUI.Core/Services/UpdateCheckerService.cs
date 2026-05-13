using GOGGUI.Core.Models;
using System.Text.Json;

namespace GOGGUI.Core.Services;

/// <summary>
/// Compares locally downloaded installer files against metadata cache
/// to detect games that have a newer version available on GOG.
/// Logic: if metadata JSON has a version string different from what
/// is encoded in the local filename, mark as UpdateAvailable.
/// </summary>
public sealed class UpdateCheckerService
{
    private static readonly JsonSerializerOptions _json = new() { PropertyNameCaseInsensitive = true };

    public record UpdateCheckResult(
        string Slug,
        string LocalVersion,
        string RemoteVersion,
        bool UpdateAvailable
    );

    /// <summary>
    /// Checks all games for available updates.
    /// Returns one result per game that has metadata.
    /// </summary>
    public Task<List<UpdateCheckResult>> CheckAllAsync(
        IReadOnlyList<GameState> games,
        IProgress<string>? progress = null,
        CancellationToken ct = default)
    {
        return Task.Run(() => CheckAll(games, progress, ct), ct);
    }

    private List<UpdateCheckResult> CheckAll(
        IReadOnlyList<GameState> games,
        IProgress<string>? progress,
        CancellationToken ct)
    {
        var results = new List<UpdateCheckResult>();

        foreach (var game in games)
        {
            ct.ThrowIfCancellationRequested();
            progress?.Report($"Checking {game.Title}...");
            var result = CheckGame(game);
            if (result is not null)
                results.Add(result);
        }

        return results;
    }

    private UpdateCheckResult? CheckGame(GameState game)
    {
        if (!Directory.Exists(game.SourceDirWindows)) return null;

        var jsonPath = Path.Combine(game.SourceDirWindows, $"{game.Slug}.json");
        if (!File.Exists(jsonPath)) return null;

        string remoteVersion;
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(jsonPath));
            var root = doc.RootElement;

            // lgogdownloader stores version in installers[0].version
            remoteVersion = TryGetVersion(root) ?? string.Empty;
        }
        catch { return null; }

        if (string.IsNullOrEmpty(remoteVersion)) return null;

        // Find local installer and extract version from filename
        // lgogdownloader names files like: setup_game_title_1.2.0.3_(gog-3).exe
        var localVersion = GetLocalInstallerVersion(game.SourceDirWindows);

        var updateAvailable = !string.IsNullOrEmpty(localVersion)
            && !VersionsMatch(localVersion, remoteVersion);

        return new UpdateCheckResult(game.Slug, localVersion, remoteVersion, updateAvailable);
    }

    private static string? TryGetVersion(JsonElement root)
    {
        // Try installers[0].version
        if (root.TryGetProperty("installers", out var installers)
            && installers.ValueKind == JsonValueKind.Array
            && installers.GetArrayLength() > 0)
        {
            var first = installers[0];
            if (first.TryGetProperty("version", out var ver))
                return ver.GetString();
        }

        // Fallback: top-level "version"
        if (root.TryGetProperty("version", out var topVer))
            return topVer.GetString();

        return null;
    }

    private static string GetLocalInstallerVersion(string dir)
    {
        // setup_game_1.2.3_(gog-4).exe  →  extract "1.2.3"
        var exeFiles = Directory.EnumerateFiles(dir, "setup_*.exe",
            SearchOption.TopDirectoryOnly);

        foreach (var f in exeFiles)
        {
            var name = Path.GetFileNameWithoutExtension(f);
            // Find version pattern: digits.digits (e.g. 1.0, 2.1.3, 1.2.0.3)
            var match = System.Text.RegularExpressions.Regex.Match(
                name, @"(\d+\.\d[\d\.]*)");
            if (match.Success)
                return match.Groups[1].Value;
        }
        return string.Empty;
    }

    private static bool VersionsMatch(string local, string remote)
    {
        // Normalize: strip spaces, "v" prefix, gog suffix
        static string Normalize(string v) =>
            v.Trim().TrimStart('v')
             .Replace(" ", "")
             .Split('(')[0]  // strip (gog-X)
             .TrimEnd('.');

        return string.Equals(
            Normalize(local),
            Normalize(remote),
            StringComparison.OrdinalIgnoreCase);
    }
}
