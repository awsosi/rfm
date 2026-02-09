using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using Newtonsoft.Json;

namespace RFMLauncher
{
    /// <summary>
    /// Configuration model
    /// </summary>
    public class Config
    {
        [JsonProperty("api_base_url")]
        public string ApiBaseUrl { get; set; }

        [JsonProperty("frontend_base_url")]
        public string FrontendBaseUrl { get; set; }

        [JsonProperty("allowed_paths")]
        public List<string> AllowedPaths { get; set; }

        [JsonProperty("language")]
        public string Language { get; set; }

        [JsonProperty("credential_target_prefix")]
        public string CredentialTargetPrefix { get; set; }
    }

    /// <summary>
    /// Manages configuration file loading
    /// </summary>
    public static class ConfigurationManager
    {
        private const string ConfigFileName = "config.json";

        /// <summary>
        /// Load configuration from config.json
        /// </summary>
        public static Config LoadConfig()
        {
            try
            {
                // Load from same directory as executable
                string exeDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                string configPath = Path.Combine(exeDir, ConfigFileName);

                if (!File.Exists(configPath))
                {
                    Console.WriteLine($"Configuration file not found: {configPath}");
                    return null;
                }

                string json = File.ReadAllText(configPath);
                var config = JsonConvert.DeserializeObject<Config>(json);

                // Validate required fields
                if (string.IsNullOrWhiteSpace(config.ApiBaseUrl))
                {
                    Console.WriteLine("Invalid configuration: api_base_url is required");
                    return null;
                }

                if (config.AllowedPaths == null || config.AllowedPaths.Count == 0)
                {
                    Console.WriteLine("Invalid configuration: allowed_paths is required and must contain at least one path");
                    return null;
                }

                if (string.IsNullOrWhiteSpace(config.Language))
                {
                    config.Language = "en-US"; // Default language
                }

                if (string.IsNullOrWhiteSpace(config.CredentialTargetPrefix))
                {
                    config.CredentialTargetPrefix = "RFM_ContextMenu"; // Default
                }

                return config;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to load configuration: {ex.Message}");
                return null;
            }
        }
    }
}
