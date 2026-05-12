using GOGGUI.Core.Models;
using System.Text.Json;

namespace GOGGUI.Core.Services;

public sealed class AppSettingsService
{
    /// <summary>
    /// settings.json is stored next to the running executable.
    /// e.g. D:\GIT\GogGui\src\GOGGUI.App\bin\x64\Release\...\settings.json
    /// </summary>
    private static readonly string SettingsPath =
        Path.Combine(AppContext.BaseDirectory, "settings.json");

    private static readonly JsonSerializerOptions _json = new() { WriteIndented = true };

    public AppSettings Current { get; private set; } = new();

    public bool IsFirstRun => !File.Exists(SettingsPath);

    public async Task LoadAsync()
    {
        if (!File.Exists(SettingsPath)) return;
        await using var stream = File.OpenRead(SettingsPath);
        Current = await JsonSerializer.DeserializeAsync<AppSettings>(stream, _json) ?? new AppSettings();
    }

    public async Task SaveAsync()
    {
        // No need to create directory - AppContext.BaseDirectory always exists
        await using var stream = File.Create(SettingsPath);
        await JsonSerializer.SerializeAsync(stream, Current, _json);
    }

    public async Task SaveAsync(AppSettings settings)
    {
        Current = settings;
        await SaveAsync();
    }

    /// <summary>Converts Windows path like D:\GOGInstall to /mnt/d/GOGInstall</summary>
    public static string WindowsToWslPath(string windowsPath)
    {
        if (string.IsNullOrWhiteSpace(windowsPath)) return string.Empty;
        var normalized = windowsPath.Replace('\\', '/');
        if (normalized.Length >= 2 && normalized[1] == ':')
        {
            var driveLetter = char.ToLower(normalized[0]);
            return $"/mnt/{driveLetter}{normalized[2..]}";
        }
        return normalized;
    }
}
