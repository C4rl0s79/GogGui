using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using GOGGUI.Core.Models;

namespace GOGGUI.Core.Services;

/// <summary>
/// Fetches game cover art from SteamGridDB as a fallback when lgogdownloader
/// did not download any cover image (logo_slug.jpg / icon_slug.png missing).
///
/// Priority:
///   1. portrait grid (e.g. 600x900) — best for card UI
///   2. landscape grid (460x215)     — if no portrait available
///
/// Covers are cached locally in AppSettings.ResolvedCoverCacheDir so
/// we never re-download the same cover.
/// </summary>
public sealed class GameCoverService
{
    private static readonly HttpClient _http = new();
    private const string BaseUrl = "https://www.steamgriddb.com/api/v2";

    // SteamGridDB grid dimensions we accept in priority order
    private static readonly string[] PortraitDimensions  = { "600x900", "342x482", "660x930" };
    private static readonly string[] LandscapeDimensions = { "460x215", "920x430" };

    public record CoverResult(string Slug, string? LocalPath, bool WasCached);

    /// <summary>
    /// For each game that has no local cover, tries to fetch one from SteamGridDB.
    /// Skips games that already have CoverPath set.
    /// Returns only games where a cover was found/cached.
    /// </summary>
    public async Task<List<CoverResult>> FetchMissingCoversAsync(
        IReadOnlyList<GameState> games,
        AppSettings settings,
        IProgress<string>? progress = null,
        CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(settings.SteamGridDbApiKey))
            return new List<CoverResult>();

        ConfigureHttpClient(settings.SteamGridDbApiKey);
        Directory.CreateDirectory(settings.ResolvedCoverCacheDir);

        var results = new List<CoverResult>();
        var missing = games.Where(g => g.NoCover).ToList();

        foreach (var game in missing)
        {
            ct.ThrowIfCancellationRequested();
            progress?.Report($"Fetching cover: {game.Title}...");

            var result = await FetchCoverAsync(game, settings, ct);
            if (result is not null)
            {
                game.CoverPath = result.LocalPath;
                results.Add(result);
            }
        }

        return results;
    }

    private async Task<CoverResult?> FetchCoverAsync(
        GameState game,
        AppSettings settings,
        CancellationToken ct)
    {
        // Check local cache first
        var cachedPath = FindInCache(settings.ResolvedCoverCacheDir, game.Slug);
        if (cachedPath is not null)
            return new CoverResult(game.Slug, cachedPath, WasCached: true);

        try
        {
            // 1. Search for the game by name
            var gameId = await SearchGameIdAsync(game.Title, ct);
            if (gameId is null) return null;

            // 2. Try portrait grids first, then landscape
            var imageUrl = await FindGridUrlAsync(gameId.Value, PortraitDimensions, ct)
                        ?? await FindGridUrlAsync(gameId.Value, LandscapeDimensions, ct);

            if (imageUrl is null) return null;

            // 3. Download and cache
            var ext = Path.GetExtension(new Uri(imageUrl).LocalPath).TrimStart('.');
            if (string.IsNullOrEmpty(ext)) ext = "jpg";
            var localPath = Path.Combine(settings.ResolvedCoverCacheDir, $"{game.Slug}.{ext}");

            var bytes = await _http.GetByteArrayAsync(imageUrl, ct);
            await File.WriteAllBytesAsync(localPath, bytes, ct);

            return new CoverResult(game.Slug, localPath, WasCached: false);
        }
        catch
        {
            return null;
        }
    }

    private async Task<int?> SearchGameIdAsync(string title, CancellationToken ct)
    {
        var url = $"{BaseUrl}/search/autocomplete/{Uri.EscapeDataString(title)}";
        using var resp = await _http.GetAsync(url, ct);
        if (!resp.IsSuccessStatusCode) return null;

        using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync(ct));
        var data = doc.RootElement.GetProperty("data");
        if (data.ValueKind != JsonValueKind.Array || data.GetArrayLength() == 0) return null;

        return data[0].GetProperty("id").GetInt32();
    }

    private async Task<string?> FindGridUrlAsync(
        int gameId,
        string[] dimensions,
        CancellationToken ct)
    {
        foreach (var dim in dimensions)
        {
            var url = $"{BaseUrl}/grids/game/{gameId}?dimensions={dim}&limit=1";
            using var resp = await _http.GetAsync(url, ct);
            if (!resp.IsSuccessStatusCode) continue;

            using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync(ct));
            var data = doc.RootElement.GetProperty("data");
            if (data.ValueKind == JsonValueKind.Array && data.GetArrayLength() > 0)
            {
                var imageUrl = data[0].GetProperty("url").GetString();
                if (!string.IsNullOrEmpty(imageUrl)) return imageUrl;
            }
        }
        return null;
    }

    private static string? FindInCache(string cacheDir, string slug)
    {
        foreach (var ext in new[] { "jpg", "jpeg", "png", "webp" })
        {
            var path = Path.Combine(cacheDir, $"{slug}.{ext}");
            if (File.Exists(path)) return path;
        }
        return null;
    }

    private static void ConfigureHttpClient(string apiKey)
    {
        _http.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", apiKey);
        if (_http.DefaultRequestHeaders.UserAgent.Count == 0)
            _http.DefaultRequestHeaders.UserAgent.ParseAdd("GogGui/1.0");
    }
}
