using GOGGUI.Core.Models;

namespace GOGGUI.Core.Services;

public sealed class LgogService
{
    private readonly WslProcessService _wsl;

    public LgogService(WslProcessService wsl) => _wsl = wsl;

    public Task<(int ExitCode, string StdOut, string StdErr)> CheckLoginStatusAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --check-login-status");

    public Task<(int ExitCode, string StdOut, string StdErr)> GuiLoginAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --gui-login");

    public Task<(int ExitCode, string StdOut, string StdErr)> UpdateCacheAsync(AppSettings s) =>
        _wsl.RunAsync(s.WslDistro, $"{s.LgogBinary} --update-cache");

    /// <param name="slug">Game slug as stored by lgogdownloader. Always quoted to prevent shell injection.</param>
    public Task<(int ExitCode, string StdOut, string StdErr)> DownloadGameAsync(
        AppSettings s, string slug, bool extras, bool extrasOnly = false)
    {
        // FIX #5: wrap slug in single-quotes so slugs containing spaces or special
        // characters are passed as one argument to lgogdownloader.
        var quotedSlug = $"'{slug.Replace("'", "'\\''")}'"; // safe single-quote escaping

        var cmd = extrasOnly
            ? $"{s.LgogBinary} --download --game {quotedSlug} --no-installers --extras"
            : extras
                ? $"{s.LgogBinary} --download --game {quotedSlug} --extras"
                : $"{s.LgogBinary} --download --game {quotedSlug}";

        return _wsl.RunAsync(s.WslDistro, cmd);
    }
}
