using System.Collections.ObjectModel;
using System.Text;

namespace GOGGUI.Core.Services;

public enum LogLevel { Debug, Info, Warning, Error }

public sealed record LogEntry(
    DateTimeOffset Timestamp,
    LogLevel Level,
    string Source,
    string Message);

/// <summary>
/// Lightweight structured logger.
/// - Writes to %LOCALAPPDATA%\GogGui\goggui.log (rolling, max 5 MB)
/// - Exposes ObservableCollection for in-app log viewer
/// - Thread-safe via lock
/// </summary>
public sealed class LogService
{
    private static readonly Lazy<LogService> _instance =
        new(() => new LogService());
    public static LogService Instance => _instance.Value;

    private readonly string _logPath;
    private readonly object _lock = new();
    private const long MaxLogBytes = 5 * 1024 * 1024; // 5 MB

    public ObservableCollection<LogEntry> Entries { get; } = new();

    private LogService()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "GogGui");
        Directory.CreateDirectory(dir);
        _logPath = Path.Combine(dir, "goggui.log");
        RollIfNeeded();
        Info("LogService", $"=== GogGui started — log: {_logPath} ===");
    }

    public void Debug(string source, string message)   => Write(LogLevel.Debug,   source, message);
    public void Info(string source, string message)    => Write(LogLevel.Info,    source, message);
    public void Warning(string source, string message) => Write(LogLevel.Warning, source, message);
    public void Error(string source, string message)   => Write(LogLevel.Error,   source, message);
    public void Error(string source, Exception ex)     => Write(LogLevel.Error,   source, $"{ex.GetType().Name}: {ex.Message}\n{ex.StackTrace}");

    private void Write(LogLevel level, string source, string message)
    {
        var entry = new LogEntry(DateTimeOffset.Now, level, source, message);

        lock (_lock)
        {
            // In-memory (keep last 500)
            if (Entries.Count >= 500)
                Entries.RemoveAt(0);
            Entries.Add(entry);

            // File
            try
            {
                var line = $"[{entry.Timestamp:yyyy-MM-dd HH:mm:ss.fff}] [{level,-7}] [{source}] {message}";
                File.AppendAllText(_logPath, line + Environment.NewLine, Encoding.UTF8);
            }
            catch { /* never crash because of logging */ }
        }
    }

    private void RollIfNeeded()
    {
        try
        {
            if (File.Exists(_logPath) && new FileInfo(_logPath).Length > MaxLogBytes)
            {
                var backup = _logPath + ".bak";
                if (File.Exists(backup)) File.Delete(backup);
                File.Move(_logPath, backup);
            }
        }
        catch { }
    }

    public string LogFilePath => _logPath;
}
