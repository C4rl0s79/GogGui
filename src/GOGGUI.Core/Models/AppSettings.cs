namespace GOGGUI.Core.Models;

public sealed class AppSettings
{
    public string WslDistro { get; set; } = "Ubuntu";
    public string LgogBinary { get; set; } = "lgogdownloader";
    public string LibraryDirWindows { get; set; } = @"D:\\GOGInstall";
    public string LibraryDirWsl { get; set; } = "/mnt/d/GOGInstall";
    public string MetadataCacheDir { get; set; } = @"D:\\GOGG\\cache\\games";
    public string XmlCacheDir { get; set; } = @"D:\\GOGG\\xml\\games";
    public bool DownloadExtrasByDefault { get; set; } = false;
    public string PreferredLoginMode { get; set; } = "gui";
    public bool? SupportsGuiLogin { get; set; }
    public bool AutoRefreshOnStart { get; set; } = true;
    public string UpdateMode { get; set; } = "changed_only";

    // SteamGridDB fallback covers (optional)
    // Get free API key at https://www.steamgriddb.com/profile/preferences/api
    public string SteamGridDbApiKey { get; set; } = string.Empty;

    // Where to cache downloaded covers locally (defaults to MetadataCacheDir\covers)
    public string CoverCacheDir { get; set; } = string.Empty;

    public string ResolvedCoverCacheDir =>
        string.IsNullOrWhiteSpace(CoverCacheDir)
            ? Path.Combine(MetadataCacheDir, "covers")
            : CoverCacheDir;
}
