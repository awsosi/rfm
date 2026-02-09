using System;
using System.Diagnostics;
using System.Linq;

namespace RFMLauncher
{
    /// <summary>
    /// Main entry point for RFM Windows Context Menu Launcher
    /// </summary>
    class Program
    {
        static void Main(string[] args)
        {
            try
            {
                // Parse command-line arguments
                //   RFMLauncher.exe --prepare "\\server\share\folder"
                //   RFMLauncher.exe --push "\\server\share\folder"

                if (args.Length < 2)
                {
                    Console.WriteLine("Usage: RFMLauncher.exe --prepare|--push <path>");
                    Console.WriteLine("Example: RFMLauncher.exe --prepare \"\\\\server\\share\\folder\"");
                    return;
                }

                string action = args[0].TrimStart('-'); // "prepare" or "push"
                string selectedPath = args[1];

                // Validate action
                if (action != "prepare" && action != "push")
                {
                    Console.WriteLine("Invalid action. Use --prepare or --push");
                    return;
                }

                // Load configuration
                var config = ConfigurationManager.LoadConfig();
                if (config == null)
                {
                    Console.WriteLine("Failed to load configuration. Please check config.json");
                    return;
                }

                // Load localization
                var localization = LocalizationManager.Load(config.Language);
                if (localization == null)
                {
                    Console.WriteLine("Failed to load localization for language: " + config.Language);
                    return;
                }

                // Check if path is allowed
                if (!IsPathAllowed(selectedPath, config))
                {
                    Console.WriteLine("Path not allowed: " + selectedPath);
                    Console.WriteLine("Allowed paths:");
                    foreach (var allowedPath in config.AllowedPaths)
                    {
                        Console.WriteLine("  - " + allowedPath);
                    }
                    return;
                }

                // Check authentication (token valid?)
                var authManager = new AuthenticationManager(config);
                string accessToken = authManager.GetValidToken();

                if (accessToken == null)
                {
                    // Not authenticated or token expired
                    Console.WriteLine(localization["auth.browserOpening"]);
                    accessToken = authManager.PerformDeviceFlow(localization);

                    if (accessToken == null)
                    {
                        Console.WriteLine(localization["auth.authFailed"]);
                        Console.WriteLine("\nPress any key to exit...");
                        Console.ReadKey();
                        return;
                    }
                }

                // Build deep link URL
                // Use frontend URL if available, otherwise fall back to API URL
                string frontendUrl = !string.IsNullOrEmpty(config.FrontendBaseUrl)
                    ? config.FrontendBaseUrl
                    : config.ApiBaseUrl;

                var deepLink = DeepLinkBuilder.Build(
                    frontendUrl,
                    action,
                    selectedPath,
                    accessToken
                );

                Console.WriteLine("Opening RFM in browser...");
                Console.WriteLine("URL: " + deepLink);

                // Open browser
                Process.Start(new ProcessStartInfo
                {
                    FileName = deepLink,
                    UseShellExecute = true
                });

                Console.WriteLine("Browser opened successfully.");
            }
            catch (Exception ex)
            {
                Console.WriteLine("Error: " + ex.Message);
                Console.WriteLine("\nPress any key to exit...");
                Console.ReadKey();
            }
        }

        /// <summary>
        /// Check if the selected path is allowed based on configuration
        /// </summary>
        private static bool IsPathAllowed(string selectedPath, Config config)
        {
            if (config.AllowedPaths == null || config.AllowedPaths.Count == 0)
            {
                return false;
            }

            // Normalize path separators for comparison
            string normalizedPath = selectedPath.Replace('/', '\\').ToLowerInvariant();

            foreach (var allowedPath in config.AllowedPaths)
            {
                string normalizedAllowedPath = allowedPath.Replace('/', '\\').ToLowerInvariant();

                // Check if selected path starts with allowed path
                if (normalizedPath.StartsWith(normalizedAllowedPath))
                {
                    return true;
                }
            }

            return false;
        }
    }
}
