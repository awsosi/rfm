using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace RFMLauncher
{
    /// <summary>
    /// Manages localization strings
    /// </summary>
    public static class LocalizationManager
    {
        /// <summary>
        /// Load localization strings for specified language
        /// </summary>
        /// <param name="language">Language code (e.g., "en-US", "pl-PL")</param>
        /// <returns>Dictionary of flattened localization strings</returns>
        public static Dictionary<string, string> Load(string language)
        {
            try
            {
                // Load from locales directory
                string exeDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                string localesDir = Path.Combine(exeDir, "locales");
                string localePath = Path.Combine(localesDir, $"{language}.json");

                if (!File.Exists(localePath))
                {
                    Console.WriteLine($"Localization file not found: {localePath}");
                    Console.WriteLine("Falling back to en-US");

                    // Fallback to en-US
                    localePath = Path.Combine(localesDir, "en-US.json");

                    if (!File.Exists(localePath))
                    {
                        Console.WriteLine("Default localization file not found");
                        return GetFallbackStrings();
                    }
                }

                string json = File.ReadAllText(localePath);
                var localeObject = JsonConvert.DeserializeObject<JObject>(json);

                // Flatten the nested JSON structure
                var flatDict = new Dictionary<string, string>();
                FlattenJson(localeObject, "", flatDict);

                return flatDict;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to load localization: {ex.Message}");
                return GetFallbackStrings();
            }
        }

        /// <summary>
        /// Flatten nested JSON object into dot-notation dictionary
        /// </summary>
        private static void FlattenJson(JObject obj, string prefix, Dictionary<string, string> result)
        {
            foreach (var property in obj.Properties())
            {
                string key = string.IsNullOrEmpty(prefix) ? property.Name : $"{prefix}.{property.Name}";

                if (property.Value is JObject nestedObj)
                {
                    FlattenJson(nestedObj, key, result);
                }
                else if (property.Value is JValue value)
                {
                    result[key] = value.ToString();
                }
            }
        }

        /// <summary>
        /// Get fallback English strings if localization files are missing
        /// </summary>
        private static Dictionary<string, string> GetFallbackStrings()
        {
            return new Dictionary<string, string>
            {
                { "auth.browserOpening", "Opening browser for authentication..." },
                { "auth.waitingApproval", "Waiting for approval. Please enter this code in your browser: {code}" },
                { "auth.authSuccess", "Authentication successful!" },
                { "auth.authFailed", "Authentication failed or timed out." },
                { "errors.configNotFound", "Configuration file not found: {path}" },
                { "errors.invalidConfig", "Invalid configuration file" },
                { "errors.networkError", "Network error: {error}" },
                { "errors.authTimeout", "Authentication timed out after 15 minutes" }
            };
        }
    }
}
