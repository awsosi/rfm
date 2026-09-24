using System;
using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;

namespace RFMLauncher
{
    /// <summary>
    /// Main entry point for RFM Windows Context Menu Launcher
    /// </summary>
    class Program
    {
        // Win32 API for console allocation (only used for error display)
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AllocConsole();

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool FreeConsole();

        /// <summary>
        /// Allocate a console window for error messages
        /// </summary>
        private static void ShowErrorConsole()
        {
            AllocConsole();
        }

        static void Main(string[] args)
        {
            try
            {
                // Parse command-line arguments
                //   RFMLauncher.exe --prepare "\\server\share\folder"
                //   RFMLauncher.exe --push "\\server\share\folder"
                //   RFMLauncher.exe --push "\\server\share\folder1" "\\server\share\folder2"

                if (args.Length < 2)
                {
                    ShowErrorConsole();
                    Console.WriteLine("Usage: RFMLauncher.exe --prepare|--push <path1> [path2 ...]");
                    Console.WriteLine("Example: RFMLauncher.exe --prepare \"\\\\server\\share\\folder\"");
                    Console.WriteLine("Example: RFMLauncher.exe --push \"\\\\server\\share\\folder1\" \"\\\\server\\share\\folder2\"");
                    Console.WriteLine("\nPress any key to exit...");
                    Console.ReadKey();
                    return;
                }

                string action = args[0].TrimStart('-'); // "prepare" or "push"
                var selectedPaths = args.Skip(1)
                    .Where(p => !string.IsNullOrWhiteSpace(p))
                    .ToList();

                // Validate action
                if (action != "prepare" && action != "push")
                {
                    ShowErrorConsole();
                    Console.WriteLine("Invalid action. Use --prepare or --push");
                    Console.WriteLine("\nPress any key to exit...");
                    Console.ReadKey();
                    return;
                }

                if (selectedPaths.Count == 0)
                {
                    ShowErrorConsole();
                    Console.WriteLine("No paths provided.");
                    Console.WriteLine("\nPress any key to exit...");
                    Console.ReadKey();
                    return;
                }

                // Load configuration
                var config = ConfigurationManager.LoadConfig();
                if (config == null)
                {
                    ShowErrorConsole();
                    Console.WriteLine("Failed to load configuration. Please check config.json");
                    Console.WriteLine("\nPress any key to exit...");
                    Console.ReadKey();
                    return;
                }

                // Load localization
                var localization = LocalizationManager.Load(config.Language);
                if (localization == null)
                {
                    ShowErrorConsole();
                    Console.WriteLine("Failed to load localization for language: " + config.Language);
                    Console.WriteLine("\nPress any key to exit...");
                    Console.ReadKey();
                    return;
                }

                // Check if path is allowed
                var disallowedPaths = selectedPaths
                    .Where(path => !PathRules.IsPathAllowed(path, config))
                    .ToList();
                if (disallowedPaths.Count > 0)
                {
                    ShowErrorConsole();
                    Console.WriteLine("Some paths are not allowed:");
                    foreach (var path in disallowedPaths)
                    {
                        Console.WriteLine("  - " + path);
                    }
                    Console.WriteLine("Allowed paths:");
                    foreach (var allowedPath in config.AllowedPaths)
                    {
                        Console.WriteLine("  - " + allowedPath);
                    }
                    Console.WriteLine("\nPress any key to exit...");
                    Console.ReadKey();
                    return;
                }

                // Check authentication (token valid?)
                var authManager = new AuthenticationManager(config);
                string accessToken = authManager.GetValidToken();

                if (accessToken == null)
                {
                    // Not authenticated or token expired - perform device flow (shows in browser, not console)
                    accessToken = authManager.PerformDeviceFlow(localization);

                    if (accessToken == null)
                    {
                        ShowErrorConsole();
                        Console.WriteLine(localization["auth.authFailed"]);
                        Console.WriteLine("\nPress any key to exit...");
                        Console.ReadKey();
                        return;
                    }
                    // Authentication successful - no need to show console for success
                }

                // Normalize path to canonical (first) allowed path prefix
                // so the backend receives a path matching the worker's path_a_prefix
                var canonicalPaths = selectedPaths
                    .Select(path => PathRules.NormalizeToCanonicalPath(path, config))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .ToList();

                // Reuse an RFM tab that is already open and signed in; only
                // when none takes the action is a new tab opened below
                if (ClientHandoff.TryHandOff(config, accessToken, action, canonicalPaths))
                {
                    ClientHandoff.BringBrowserToFront(config);
                    return;
                }

                // Build deep link URL
                // Use frontend URL if available, otherwise fall back to API URL
                string frontendUrl = !string.IsNullOrEmpty(config.FrontendBaseUrl)
                    ? config.FrontendBaseUrl
                    : config.ApiBaseUrl;

                var deepLink = DeepLinkBuilder.Build(
                    frontendUrl,
                    action,
                    canonicalPaths,
                    accessToken
                );

                // Open browser silently
                Process.Start(new ProcessStartInfo
                {
                    FileName = deepLink,
                    UseShellExecute = true
                });

                // Success - exit silently (no console window shown)
            }
            catch (Exception ex)
            {
                ShowErrorConsole();
                Console.WriteLine("Error: " + ex.Message);
                Console.WriteLine(ex.StackTrace);
                Console.WriteLine("\nPress any key to exit...");
                Console.ReadKey();
            }
        }
    }
}
