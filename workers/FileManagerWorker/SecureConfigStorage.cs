using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using NLog;
using Newtonsoft.Json;

namespace FileManagerWorker
{
    /// <summary>
    /// Secure configuration storage using DPAPI with LocalMachine scope
    /// This allows Network Service and other accounts to decrypt the data
    /// </summary>
    public class SecureConfigStorage
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();
        private static readonly string ConfigDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "FileManagerWorker"
        );
        private static readonly string ConfigFilePath = Path.Combine(ConfigDirectory, "config.dat");

        /// <summary>
        /// Configuration data structure
        /// </summary>
        private class ConfigData
        {
            public string ApiUrl { get; set; }
            public string ServiceUser { get; set; }
            public string ServicePassword { get; set; }
        }

        /// <summary>
        /// Save configuration securely
        /// </summary>
        public static bool SaveConfiguration(string apiUrl, string serviceUser, string servicePassword)
        {
            try
            {
                // Create directory if it doesn't exist
                if (!Directory.Exists(ConfigDirectory))
                {
                    Directory.CreateDirectory(ConfigDirectory);
                    Logger.Info("Created configuration directory: {0}", ConfigDirectory);
                }

                // Create configuration object
                var config = new ConfigData
                {
                    ApiUrl = apiUrl,
                    ServiceUser = serviceUser ?? "",
                    ServicePassword = servicePassword ?? ""
                };

                // Serialize to JSON
                string json = JsonConvert.SerializeObject(config);
                byte[] plainBytes = Encoding.UTF8.GetBytes(json);

                // Encrypt using DPAPI with LocalMachine scope
                // This allows any account on the machine to decrypt (including Network Service)
                byte[] encryptedBytes = ProtectedData.Protect(
                    plainBytes,
                    null, // No additional entropy
                    DataProtectionScope.LocalMachine // Machine-wide encryption
                );

                // Write to file
                File.WriteAllBytes(ConfigFilePath, encryptedBytes);

                Logger.Info("Configuration saved securely to: {0}", ConfigFilePath);
                Logger.Info("Using DPAPI with LocalMachine scope (accessible by all accounts including Network Service)");

                return true;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to save configuration to secure storage");
                return false;
            }
        }

        /// <summary>
        /// Load configuration securely
        /// </summary>
        public static bool LoadConfiguration(out string apiUrl, out string serviceUser, out string servicePassword)
        {
            apiUrl = null;
            serviceUser = null;
            servicePassword = null;

            try
            {
                // Check if configuration file exists
                if (!File.Exists(ConfigFilePath))
                {
                    Logger.Debug("Configuration file not found: {0}", ConfigFilePath);
                    return false;
                }

                // Read encrypted bytes
                byte[] encryptedBytes = File.ReadAllBytes(ConfigFilePath);

                // Decrypt using DPAPI
                byte[] plainBytes = ProtectedData.Unprotect(
                    encryptedBytes,
                    null, // No additional entropy
                    DataProtectionScope.LocalMachine // Machine-wide decryption
                );

                // Deserialize from JSON
                string json = Encoding.UTF8.GetString(plainBytes);
                var config = JsonConvert.DeserializeObject<ConfigData>(json);

                apiUrl = config.ApiUrl;
                serviceUser = config.ServiceUser;
                servicePassword = config.ServicePassword;

                Logger.Info("Configuration loaded from secure storage: {0}", ConfigFilePath);
                return true;
            }
            catch (CryptographicException ex)
            {
                Logger.Error(ex, "Failed to decrypt configuration (may have been encrypted on different machine)");
                return false;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to load configuration from secure storage");
                return false;
            }
        }

        /// <summary>
        /// Check if configuration exists
        /// </summary>
        public static bool ConfigurationExists()
        {
            return File.Exists(ConfigFilePath);
        }

        /// <summary>
        /// Delete configuration file
        /// </summary>
        public static bool DeleteConfiguration()
        {
            try
            {
                if (File.Exists(ConfigFilePath))
                {
                    File.Delete(ConfigFilePath);
                    Logger.Info("Configuration file deleted: {0}", ConfigFilePath);
                }
                return true;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to delete configuration file");
                return false;
            }
        }

        /// <summary>
        /// Get configuration file path for diagnostics
        /// </summary>
        public static string GetConfigFilePath()
        {
            return ConfigFilePath;
        }
    }
}
