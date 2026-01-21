using System;
using System.IO;
using System.Net;
using System.Security.Principal;
using System.Text.RegularExpressions;
using System.Configuration.Install;
using System.Collections;
using System.Reflection;
using System.DirectoryServices.AccountManagement;
using Microsoft.Win32;

namespace FileManagerWorkerInstaller
{
    /// <summary>
    /// Main installer class for FileManagerWorker
    /// Handles command-line parsing, validation, and orchestration
    /// </summary>
    class Installer
    {
        private const string SERVICE_NAME = "FileManagerWorker";
        private const string SERVICE_DISPLAY_NAME = "File Manager Worker Service";
        private const string SERVICE_DESCRIPTION = "Manages file operations for centralized file manager";
        private const string INSTALL_PATH = @"C:\Program Files\FileManager\Worker";

        static int Main(string[] args)
        {
            try
            {
                // Check for administrator privileges
                if (!IsAdministrator())
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine("ERROR: This installer must be run as Administrator.");
                    Console.ResetColor();
                    return 1;
                }

                // Parse command-line arguments
                if (args.Length == 0 || HasHelpFlag(args))
                {
                    ShowUsage();
                    return 0;
                }

                if (HasFlag(args, "/install"))
                {
                    return HandleInstall(args);
                }

                if (HasFlag(args, "/uninstall"))
                {
                    return HandleUninstall();
                }

                if (HasFlag(args, "/debug"))
                {
                    return HandleDebug();
                }

                // Unknown command
                Console.WriteLine("ERROR: Unknown command. Use /? for help.");
                return 1;
            }
            catch (Exception ex)
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine($"FATAL ERROR: {ex.Message}");
                Console.WriteLine($"Stack Trace: {ex.StackTrace}");
                Console.ResetColor();
                return 1;
            }
        }

        static void ShowUsage()
        {
            Console.WriteLine("=============================================================================");
            Console.WriteLine("  FileManagerWorker Installer");
            Console.WriteLine("  Self-Installing Windows Service for Remote File Management");
            Console.WriteLine("=============================================================================");
            Console.WriteLine();
            Console.WriteLine("USAGE:");
            Console.WriteLine("  FileManagerWorker.exe [OPTIONS]");
            Console.WriteLine();
            Console.WriteLine("OPTIONS:");
            Console.WriteLine("  /install   Install as Windows Service");
            Console.WriteLine("  /uninstall Uninstall service");
            Console.WriteLine("  /debug     Run in console mode (debugging)");
            Console.WriteLine("  /?         Show this help");
            Console.WriteLine();
            Console.WriteLine("INSTALL EXAMPLE:");
            Console.WriteLine("  FileManagerWorker.exe /install /url https://api.local:8000 /user svc_filemanager /pass MyPassword123");
            Console.WriteLine();
            Console.WriteLine("INSTALL PARAMETERS:");
            Console.WriteLine("  /url <api-url>       Central API URL (required, must be HTTPS)");
            Console.WriteLine("  /user <username>     Service account username (required, must exist on machine)");
            Console.WriteLine("  /pass <password>     Service account password (required)");
            Console.WriteLine();
            Console.WriteLine("UNINSTALL EXAMPLE:");
            Console.WriteLine("  FileManagerWorker.exe /uninstall");
            Console.WriteLine();
            Console.WriteLine("DEBUG MODE:");
            Console.WriteLine("  FileManagerWorker.exe /debug");
            Console.WriteLine("  Runs the worker in console mode for testing without service installation.");
            Console.WriteLine();
            Console.WriteLine("NOTES:");
            Console.WriteLine("  - Must be run as Administrator");
            Console.WriteLine("  - Service will be installed to: " + INSTALL_PATH);
            Console.WriteLine("  - Service Name: " + SERVICE_NAME);
            Console.WriteLine("  - Start Type: Manual (can be changed to Automatic after installation)");
            Console.WriteLine();
        }

        static int HandleInstall(string[] args)
        {
            Console.WriteLine("=============================================================================");
            Console.WriteLine("  Installing FileManagerWorker Service");
            Console.WriteLine("=============================================================================");
            Console.WriteLine();

            try
            {
                // Extract parameters
                string apiUrl = GetArgValue(args, "/url");
                string serviceUser = GetArgValue(args, "/user");
                string servicePass = GetArgValue(args, "/pass");

                // Validate required parameters
                if (string.IsNullOrEmpty(apiUrl))
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine("ERROR: /url parameter is required");
                    Console.ResetColor();
                    ShowUsage();
                    return 1;
                }

                if (string.IsNullOrEmpty(serviceUser))
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine("ERROR: /user parameter is required");
                    Console.ResetColor();
                    ShowUsage();
                    return 1;
                }

                if (string.IsNullOrEmpty(servicePass))
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine("ERROR: /pass parameter is required");
                    Console.ResetColor();
                    ShowUsage();
                    return 1;
                }

                // Validate URL
                Console.Write("Validating API URL... ");
                if (!ValidateUrl(apiUrl))
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine("FAILED");
                    Console.WriteLine("ERROR: URL must be a valid HTTPS URL");
                    Console.ResetColor();
                    return 1;
                }
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Validate user account
                Console.Write("Validating user account... ");
                if (!ValidateUserAccount(serviceUser, servicePass))
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine("FAILED");
                    Console.WriteLine("ERROR: User account does not exist on this machine or credentials are invalid");
                    Console.ResetColor();
                    return 1;
                }
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Create installation directory
                Console.Write("Creating installation directory... ");
                CreateInstallDirectory();
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Copy executable
                Console.Write("Copying executable... ");
                CopyExecutable();
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Save configuration
                Console.Write("Saving configuration... ");
                SaveConfiguration(apiUrl, serviceUser, servicePass);
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Install service
                Console.Write("Installing Windows Service... ");
                ServiceManager.InstallService(serviceUser, servicePass);
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Create registry entries
                Console.Write("Creating registry entries... ");
                CreateRegistryEntries(apiUrl);
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                Console.WriteLine();
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("=============================================================================");
                Console.WriteLine("  Installation completed successfully!");
                Console.WriteLine("=============================================================================");
                Console.ResetColor();
                Console.WriteLine();
                Console.WriteLine("Service Details:");
                Console.WriteLine($"  Name:         {SERVICE_NAME}");
                Console.WriteLine($"  Display Name: {SERVICE_DISPLAY_NAME}");
                Console.WriteLine($"  Location:     {INSTALL_PATH}\\FileManagerWorker.exe");
                Console.WriteLine($"  API URL:      {apiUrl}");
                Console.WriteLine($"  Run As:       {serviceUser}");
                Console.WriteLine();
                Console.WriteLine("To start the service, run:");
                Console.WriteLine($"  net start {SERVICE_NAME}");
                Console.WriteLine();
                Console.WriteLine("Or use Services.msc to start it manually.");
                Console.WriteLine();

                return 0;
            }
            catch (Exception ex)
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine("FAILED");
                Console.WriteLine($"ERROR: {ex.Message}");
                Console.WriteLine($"Stack Trace: {ex.StackTrace}");
                Console.ResetColor();
                return 1;
            }
        }

        static int HandleUninstall()
        {
            Console.WriteLine("=============================================================================");
            Console.WriteLine("  Uninstalling FileManagerWorker Service");
            Console.WriteLine("=============================================================================");
            Console.WriteLine();

            try
            {
                // Stop service if running
                Console.Write("Stopping service... ");
                ServiceManager.StopService();
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Uninstall service
                Console.Write("Uninstalling Windows Service... ");
                ServiceManager.UninstallService();
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Remove registry entries
                Console.Write("Removing registry entries... ");
                RemoveRegistryEntries();
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                // Clean up installation directory
                Console.Write("Cleaning up installation directory... ");
                CleanupInstallDirectory();
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("OK");
                Console.ResetColor();

                Console.WriteLine();
                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("=============================================================================");
                Console.WriteLine("  Uninstallation completed successfully!");
                Console.WriteLine("=============================================================================");
                Console.ResetColor();
                Console.WriteLine();

                return 0;
            }
            catch (Exception ex)
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine("FAILED");
                Console.WriteLine($"ERROR: {ex.Message}");
                Console.ResetColor();
                return 1;
            }
        }

        static int HandleDebug()
        {
            Console.WriteLine("=============================================================================");
            Console.WriteLine("  FileManagerWorker - DEBUG MODE");
            Console.WriteLine("=============================================================================");
            Console.WriteLine();
            Console.WriteLine("Running in console mode for testing...");
            Console.WriteLine("Press Ctrl+C to stop.");
            Console.WriteLine();

            try
            {
                // Load configuration
                var config = LoadConfiguration();
                if (config == null)
                {
                    Console.ForegroundColor = ConsoleColor.Red;
                    Console.WriteLine("ERROR: Configuration not found. Please run /install first.");
                    Console.ResetColor();
                    return 1;
                }

                Console.WriteLine("Configuration:");
                Console.WriteLine($"  API URL: {config["ApiUrl"]}");
                Console.WriteLine($"  Service User: {config["ServiceUser"]}");
                Console.WriteLine();

                // In a real implementation, this would start the worker service
                Console.WriteLine("Worker service would start here...");
                Console.WriteLine("(Actual worker implementation should be integrated)");
                Console.WriteLine();
                Console.WriteLine("Press any key to stop.");
                Console.ReadKey();

                return 0;
            }
            catch (Exception ex)
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine($"ERROR: {ex.Message}");
                Console.ResetColor();
                return 1;
            }
        }

        #region Validation Methods

        static bool ValidateUrl(string url)
        {
            try
            {
                if (string.IsNullOrWhiteSpace(url))
                    return false;

                Uri uri = new Uri(url);

                // Must be HTTPS
                if (uri.Scheme != Uri.UriSchemeHttps)
                {
                    Console.WriteLine($"    ERROR: URL must use HTTPS protocol, got: {uri.Scheme}");
                    return false;
                }

                return true;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    ERROR: Invalid URL format: {ex.Message}");
                return false;
            }
        }

        static bool ValidateUserAccount(string username, string password)
        {
            try
            {
                // Parse domain\user format
                string domain = Environment.MachineName;
                string user = username;

                if (username.Contains("\\"))
                {
                    var parts = username.Split('\\');
                    domain = parts[0];
                    user = parts[1];
                }
                else if (username.Contains("@"))
                {
                    // Handle UPN format
                    var parts = username.Split('@');
                    user = parts[0];
                    domain = parts[1];
                }

                // Try to validate using PrincipalContext
                try
                {
                    using (PrincipalContext context = new PrincipalContext(ContextType.Machine))
                    {
                        // Check if user exists
                        UserPrincipal userPrincipal = UserPrincipal.FindByIdentity(context, user);
                        if (userPrincipal == null)
                        {
                            Console.WriteLine($"    ERROR: User '{user}' not found on local machine");
                            return false;
                        }

                        // Validate credentials
                        bool isValid = context.ValidateCredentials(user, password);
                        if (!isValid)
                        {
                            Console.WriteLine($"    ERROR: Invalid password for user '{user}'");
                            return false;
                        }

                        return true;
                    }
                }
                catch
                {
                    // Fallback: just check if user exists
                    using (PrincipalContext context = new PrincipalContext(ContextType.Machine))
                    {
                        UserPrincipal userPrincipal = UserPrincipal.FindByIdentity(context, user);
                        if (userPrincipal != null)
                        {
                            Console.WriteLine($"    WARNING: Could not fully validate credentials, but user exists");
                            return true;
                        }
                    }
                }

                return false;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    ERROR: Failed to validate user account: {ex.Message}");
                return false;
            }
        }

        #endregion

        #region Installation Methods

        static void CreateInstallDirectory()
        {
            if (!Directory.Exists(INSTALL_PATH))
            {
                Directory.CreateDirectory(INSTALL_PATH);
            }
        }

        static void CopyExecutable()
        {
            string sourceFile = Assembly.GetExecutingAssembly().Location;
            string destFile = Path.Combine(INSTALL_PATH, "FileManagerWorker.exe");

            // Copy the executable
            File.Copy(sourceFile, destFile, true);

            // Copy any config files if they exist
            string sourceConfig = sourceFile + ".config";
            if (File.Exists(sourceConfig))
            {
                string destConfig = destFile + ".config";
                File.Copy(sourceConfig, destConfig, true);
            }
        }

        static void SaveConfiguration(string apiUrl, string serviceUser, string servicePass)
        {
            string configPath = Path.Combine(INSTALL_PATH, "worker.config");

            string configContent = $@"<?xml version=""1.0"" encoding=""utf-8""?>
<configuration>
  <appSettings>
    <add key=""ApiUrl"" value=""{apiUrl}"" />
    <add key=""ServiceUser"" value=""{serviceUser}"" />
    <add key=""ServicePassword"" value=""{EncryptPassword(servicePass)}"" />
    <add key=""PathAPrefix"" value=""C:\PathA"" />
    <add key=""PathBPrefix"" value=""C:\PathB"" />
    <add key=""PollingIntervalSeconds"" value=""5"" />
    <add key=""UseMtls"" value=""true"" />
  </appSettings>
</configuration>";

            File.WriteAllText(configPath, configContent);
        }

        static System.Collections.Generic.Dictionary<string, string> LoadConfiguration()
        {
            try
            {
                string configPath = Path.Combine(INSTALL_PATH, "worker.config");
                if (!File.Exists(configPath))
                    return null;

                var config = new System.Collections.Generic.Dictionary<string, string>();

                // Simple XML parsing (in production, use XmlDocument)
                string content = File.ReadAllText(configPath);
                var matches = Regex.Matches(content, @"<add key=""(\w+)"" value=""([^""]*)"" />");
                foreach (Match match in matches)
                {
                    config[match.Groups[1].Value] = match.Groups[2].Value;
                }

                return config;
            }
            catch
            {
                return null;
            }
        }

        static string EncryptPassword(string password)
        {
            // Simple Base64 encoding (in production, use proper encryption)
            byte[] bytes = System.Text.Encoding.UTF8.GetBytes(password);
            return Convert.ToBase64String(bytes);
        }

        static void CreateRegistryEntries(string apiUrl)
        {
            try
            {
                using (RegistryKey key = Registry.LocalMachine.CreateSubKey(@"SOFTWARE\FileManager\Worker"))
                {
                    key.SetValue("InstallPath", INSTALL_PATH);
                    key.SetValue("ServiceName", SERVICE_NAME);
                    key.SetValue("ApiUrl", apiUrl);
                    key.SetValue("Version", "1.0.0");
                    key.SetValue("InstalledDate", DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
                }
            }
            catch (Exception ex)
            {
                throw new Exception($"Failed to create registry entries: {ex.Message}");
            }
        }

        static void CleanupInstallDirectory()
        {
            try
            {
                if (Directory.Exists(INSTALL_PATH))
                {
                    Directory.Delete(INSTALL_PATH, true);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    WARNING: Could not fully clean up directory: {ex.Message}");
            }
        }

        static void RemoveRegistryEntries()
        {
            try
            {
                Registry.LocalMachine.DeleteSubKeyTree(@"SOFTWARE\FileManager\Worker", false);
            }
            catch
            {
                // Ignore if key doesn't exist
            }
        }

        #endregion

        #region Helper Methods

        static bool IsAdministrator()
        {
            WindowsIdentity identity = WindowsIdentity.GetCurrent();
            WindowsPrincipal principal = new WindowsPrincipal(identity);
            return principal.IsInRole(WindowsBuiltInRole.Administrator);
        }

        static bool HasFlag(string[] args, string flag)
        {
            foreach (string arg in args)
            {
                if (arg.Equals(flag, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        static bool HasHelpFlag(string[] args)
        {
            return HasFlag(args, "/?") || HasFlag(args, "/help") || HasFlag(args, "-h") || HasFlag(args, "--help");
        }

        static string GetArgValue(string[] args, string parameter)
        {
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i].Equals(parameter, StringComparison.OrdinalIgnoreCase))
                {
                    return args[i + 1];
                }
            }
            return null;
        }

        #endregion
    }
}
