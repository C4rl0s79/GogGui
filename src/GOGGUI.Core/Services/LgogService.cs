using GOGGUI.Core.Models;

namespace GOGGUI.Core.Services;

public sealed class LgogService
{
    private readonly WslProcessService _wsl;

    public LgogService(WslProcessService wsl)
    {
        _wsl = wsl;
    }

    public Task<ProcessResult> CheckLoginStatusAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --check-login-status");

    public Task<ProcessResult> GuiLoginAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --gui-login");

    public Task<ProcessResult> UpdateCacheAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --update-cache");

    public Task<ProcessResult> DownloadGameAsync(AppSettings s, string slug, bool extras, bool extrasOnly = false)
    {
        var cmd = extrasOnly
            ? $"{s.LgogBinary} --download --game {slug} --no-installers --extras"
            : extras
                ? $"{s.LgogBinary} --download --game {slug} --extras"
                : $"{s.LgogBinary} --download --game {slug}";

        return _wsl.RunAsync(s.WslDistro, cmd);
    }
}
