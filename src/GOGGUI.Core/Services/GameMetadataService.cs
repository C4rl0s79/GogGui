using GOGGUI.Core.Models;
using System.Text.Json;

namespace GOGGUI.Core.Services;

public sealed class GameMetadataService
{
    private static readonly JsonSerializerOptions _json = new()
    {
        PropertyNameCaseInsensitive = true
    };

    /// <summary>
    /// Tries to load <slug>.json from the game's folder.
    /// Returns null if file doesn't exist or can't be parsed.
    /// </summary>
    public async Task<GameMetadata?> LoadAsync(GameState game)
    {
        if (string.IsNullOrWhiteSpace(game.SourceDirWindows)) return null;

        var jsonPath = Path.Combine(game.SourceDirWindows, $"{game.Slug}.json");
        if (!File.Exists(jsonPath)) return null;

        try
        {
            await using var stream = File.OpenRead(jsonPath);
            return await JsonSerializer.DeserializeAsync<GameMetadata>(stream, _json);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Returns all local installer files for the game (*.exe, *.bin, *.sh).
    /// </summary>
    public List<FileInfo> GetLocalInstallerFiles(GameState game)
    {
        if (!Directory.Exists(game.SourceDirWindows)) return new();

        return Directory
            .EnumerateFiles(game.SourceDirWindows, "*",
                SearchOption.TopDirectoryOnly)
            .Where(f =>
            {
                var ext = Path.GetExtension(f);
                return ext.Equals(".exe", StringComparison.OrdinalIgnoreCase)
                    || ext.Equals(".bin", StringComparison.OrdinalIgnoreCase)
                    || ext.Equals(".sh",  StringComparison.OrdinalIgnoreCase);
            })
            .Select(f => new FileInfo(f))
            .OrderBy(f => f.Name)
            .ToList();
    }

    public static string FormatBytes(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F2} GB",
        >= 1_048_576     => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024         => $"{bytes / 1_024.0:F0} KB",
        _                => $"{bytes} B"
    };
}
