using GOGGUI.Core.Models;

namespace GOGGUI.Core.Services;

public sealed class LgogService
{
    private readonly WslProcessService _wsl;

    public LgogService(WslProcessService wsl)
    {
        _wsl = wsl;
    }

    public Task<(int ExitCode, string StdOut, string StdErr)> CheckLoginStatusAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --check-login-status");

    public Task<(int ExitCode, string StdOut, string StdErr)> GuiLoginAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --gui-login");

    public Task<(int ExitCode, string StdOut, string StdErr)> UpdateCacheAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --update-cache");

    public Task<(int ExitCode, string StdOut, string StdErr)> DownloadGameAsync(
        AppSettings s, string slug, bool extras, bool extrasOnly = false)
    {
        var cmd = extrasOnly
            ? $"{s.LgogBinary} --download --game {slug} --no-installers --extras"
            : extras
                ? $"{s.LgogBinary} --download --game {slug} --extras"
                : $"{s.LgogBinary} --download --game {slug}";

        return _wsl.RunAsync(s.WslDistro, cmd);
    }
}
