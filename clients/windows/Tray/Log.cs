using System;
using System.IO;
using System.Text;

namespace RFMTray
{
    public enum LogLevel
    {
        Off,
        /// <summary>Sign-in, state changes, every push and its answer, errors.</summary>
        Info,
        /// <summary>Also every scan, lock check and token check.</summary>
        Debug,
    }

    /// <summary>
    /// Diagnostic log, off unless the user turns it on in Settings:
    /// %LOCALAPPDATA%\RFM\Logs\RFMTray.log, one previous file kept as .1.
    /// </summary>
    static class Log
    {
        private const long MaxBytes = 5 * 1024 * 1024;
        private static readonly object _lock = new object();

        public static LogLevel Level { get; set; }

        public static string FolderPath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RFM", "Logs");

        public static string FilePath => Path.Combine(FolderPath, "RFMTray.log");

        public static void Info(string message) => Write(LogLevel.Info, message);

        public static void Debug(string message) => Write(LogLevel.Debug, message);

        public static void Error(string message, Exception ex) => Write(LogLevel.Info, $"{message}: {ex}");

        private static void Write(LogLevel level, string message)
        {
            if (Level < level)
                return;
            string line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} [{System.Threading.Thread.CurrentThread.ManagedThreadId}] {message}{Environment.NewLine}";
            lock (_lock)
            {
                try
                {
                    Directory.CreateDirectory(FolderPath);
                    var file = new FileInfo(FilePath);
                    if (file.Exists && file.Length > MaxBytes)
                    {
                        File.Delete(FilePath + ".1");
                        File.Move(FilePath, FilePath + ".1");
                    }
                    File.AppendAllText(FilePath, line, Encoding.UTF8);
                }
                catch (Exception)
                {
                    // Logging must never break sending
                }
            }
        }

        /// <summary>
        /// Console output of the code shared with RFMLauncher (token checks and
        /// refreshes), which a Windows app otherwise discards.
        /// </summary>
        public class ConsoleWriter : TextWriter
        {
            private readonly StringBuilder _line = new StringBuilder();

            public override Encoding Encoding => Encoding.UTF8;

            public override void Write(char value)
            {
                if (value == '\n')
                {
                    Debug("auth: " + _line.ToString().TrimEnd('\r'));
                    _line.Clear();
                }
                else
                {
                    _line.Append(value);
                }
            }

            public override void WriteLine(string value) => Debug("auth: " + value);
        }
    }
}
