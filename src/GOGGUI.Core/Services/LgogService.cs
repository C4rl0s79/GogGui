using GOGGUI.Core.Models;

namespace GOGGUI.Core.Services;

public sealed class LgogService
{
    private readonly WslProcessService _wsl;

    public LgogService(WslProcessService wsl)
    {
        _wsl = wsl;
    }

    public Task<(int ExitCode, string StdOut, string StdErr)> CheckLoginStatusAsync(AppSettings settings, CancellationToken ct = default) =>
        _wsl.RunAsync(settings.WslDistro, $"{settings.LgogBinary} --check-login-status", ct);

    public Task<(int ExitCode, string StdOut, string StdErr)> LoginAsync(AppSettings settings, CancellationToken ct = default) =>
        _wsl.RunAsync(settings.WslDistro, $"{settings.LgogBinary} --login", ct);

    public Task<(int ExitCode, string StdOut, string StdErr)> GuiLoginAsync(AppSettings settings, CancellationToken ct = default) =>
        _wsl.RunAsync(settings.WslDistro, $"{settings.LgogBinary} --gui-login", ct);

    public Task<(int ExitCode, string StdOut, string StdErr)> UpdateCacheAsync(AppSettings settings, CancellationToken ct = default) =>
        _wsl.RunAsync(settings.WslDistro, $"{settings.LgogBinary} --update-cache", ct);

    public Task<(int ExitCode, string StdOut, string StdErr)> ListAsync(AppSettings settings, CancellationToken ct = default) =>
        _wsl.RunAsync(settings.WslDistro, $"{settings.LgogBinary} --list", ct);

    public Task<(int ExitCode, string StdOut, string StdErr)> DownloadGameAsync(AppSettings settings, string slug, bool includeExtras, CancellationToken ct = default)
    {
        var extrasArg = includeExtras ? string.Empty : " --exclude extras";
        return _wsl.RunAsync(settings.WslDistro, $"{settings.LgogBinary} --download --game {slug}{extrasArg}", ct);
    }
}
