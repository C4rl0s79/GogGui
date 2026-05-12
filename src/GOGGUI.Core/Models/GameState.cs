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
}
