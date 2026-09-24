using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using RFMLauncher;

namespace RFMTray
{
    /// <summary>
    /// Per-user settings, %APPDATA%\RFM\tray.json. The first run starts from
    /// config.json's watch_folders, so an installer can preset them per PC.
    /// </summary>
    public class TraySettings
    {
        public const int MinQuietSeconds = 15;

        [JsonProperty("watch_folders")]
        public List<string> WatchFolders { get; set; } = new List<string>();

        /// <summary>
        /// A folder is pushed only after nothing in it changed for this long.
        /// </summary>
        [JsonProperty("quiet_seconds")]
        public int QuietSeconds { get; set; } = 60;

        [JsonProperty("paused")]
        public bool Paused { get; set; }

        private static string FilePath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RFM", "tray.json");

        public static TraySettings Load(Config config)
        {
            TraySettings settings = null;
            try
            {
                if (File.Exists(FilePath))
                    settings = JsonConvert.DeserializeObject<TraySettings>(File.ReadAllText(FilePath));
            }
            catch (Exception)
            {
                // Unreadable file: start over from the defaults below
            }

            if (settings == null)
            {
                settings = new TraySettings();
                if (config.WatchFolders != null)
                    settings.WatchFolders.AddRange(config.WatchFolders);
            }
            settings.WatchFolders = settings.WatchFolders ?? new List<string>();
            settings.QuietSeconds = Math.Max(MinQuietSeconds, settings.QuietSeconds);
            return settings;
        }

        public void Save()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath));
            File.WriteAllText(FilePath, JsonConvert.SerializeObject(this, Formatting.Indented));
        }
    }
}
