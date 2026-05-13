using System.Text.Json.Serialization;

namespace GOGGUI.Core.Models;

/// <summary>
/// Deserialized from <slug>.json written by lgogdownloader --update-cache.
/// Only the fields we actually use in the UI.
/// </summary>
public sealed class GameMetadata
{
    [JsonPropertyName("title")]
    public string Title { get; set; } = string.Empty;

    [JsonPropertyName("slug")]
    public string Slug { get; set; } = string.Empty;

    [JsonPropertyName("cdKey")]
    public string CdKey { get; set; } = string.Empty;

    /// <summary>Game version string from JSON (may be null if not present).</summary>
    [JsonPropertyName("version")]
    public string? Version { get; set; }

    /// <summary>Release date string from JSON e.g. "2009-03-26".</summary>
    [JsonPropertyName("releaseDate")]
    public string? ReleaseDate { get; set; }

    [JsonPropertyName("description")]
    public GameDescription? Description { get; set; }

    [JsonPropertyName("images")]
    public GameImages? Images { get; set; }

    [JsonPropertyName("dlcs")]
    public List<DlcInfo> Dlcs { get; set; } = new();

    [JsonPropertyName("installers")]
    public List<InstallerInfo> Installers { get; set; } = new();

    [JsonPropertyName("extras")]
    public List<ExtraInfo> Extras { get; set; } = new();
}

public sealed class GameDescription
{
    [JsonPropertyName("full")]
    public string Full { get; set; } = string.Empty;

    [JsonPropertyName("lead")]
    public string Lead { get; set; } = string.Empty;
}

public sealed class GameImages
{
    [JsonPropertyName("background")]
    public string Background { get; set; } = string.Empty;

    [JsonPropertyName("logo")]
    public string Logo { get; set; } = string.Empty;

    [JsonPropertyName("icon")]
    public string Icon { get; set; } = string.Empty;
}

public sealed class DlcInfo
{
    [JsonPropertyName("slug")]
    public string Slug { get; set; } = string.Empty;

    [JsonPropertyName("title")]
    public string Title { get; set; } = string.Empty;
}

public sealed class InstallerInfo
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("os")]
    public string Os { get; set; } = string.Empty;

    [JsonPropertyName("language")]
    public string Language { get; set; } = string.Empty;

    [JsonPropertyName("version")]
    public string Version { get; set; } = string.Empty;

    [JsonPropertyName("total_size")]
    public long TotalSize { get; set; }

    public string TotalSizeHuman => TotalSize > 0
        ? $"{TotalSize / 1_073_741_824.0:F2} GB"
        : "?";
}

public sealed class ExtraInfo
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;

    [JsonPropertyName("total_size")]
    public long TotalSize { get; set; }

    public string TotalSizeHuman => TotalSize > 0
        ? $"{TotalSize / 1024.0 / 1024.0:F1} MB"
        : "?";
}
