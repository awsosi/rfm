using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using Newtonsoft.Json.Converters;
using Newtonsoft.Json.Serialization;
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

        /// <summary>Raise when the onboarding changes enough to show it again to everyone.</summary>
        public const int OnboardingVersion = 1;

        [JsonProperty("watch_folders")]
        public List<string> WatchFolders { get; set; } = new List<string>();

        /// <summary>
        /// A folder is pushed only after nothing in it changed for this long.
        /// </summary>
        [JsonProperty("quiet_seconds")]
        public int QuietSeconds { get; set; } = 60;

        [JsonProperty("paused")]
        public bool Paused { get; set; }

        /// <summary>Diagnostic log (off, info, debug), see <see cref="Log"/>.</summary>
        [JsonProperty("log_level")]
        [JsonConverter(typeof(StringEnumConverter), typeof(CamelCaseNamingStrategy))]
        public LogLevel LogLevel { get; set; }

        /// <summary>The onboarding version the user finished (0: never).</summary>
        [JsonProperty("onboarded")]
        public int Onboarded { get; set; }

        /// <summary>A notification for every folder sent, not only for problems.</summary>
        [JsonProperty("notify_sent")]
        public bool NotifySent { get; set; } = true;

        /// <summary>The first successful push was announced as proof that sending works.</summary>
        [JsonProperty("first_push_confirmed")]
        public bool FirstPushConfirmed { get; set; }

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
