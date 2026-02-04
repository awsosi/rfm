using System;
using System.Configuration;
using System.Linq;
using CredentialManagement;
using NLog;
using Topshelf;
using FileManagerWorker.Models;

namespace FileManagerWorker
{
    class Program
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();

        static int Main(string[] args)
        {
            try
            {
                // Parse command-line arguments
                if (args.Length == 0 || args.Contains("/?") || args.Contains("/help"))
                {
                    ShowUsage();
                    return 0;
                }

                // Handle configuration setup
                if (args.Contains("/config"))
                {
                    return HandleConfig();
                }

                // Handle custom installation with parameters
                if (args.Contains("/install") || args.Contains("install"))
                {
                    return HandleInstall(args);
                }

                if (args.Contains("/uninstall") || args.Contains("uninstall"))
                {
                    return HandleUninstall();
                }

                if (args.Contains("/debug"))
                {
                    return RunInDebugMode();
                }

                // Default: Run as TopShelf service
                return RunAsService();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Fatal error: {ex.Message}");
                Logger.Fatal(ex, "Fatal error in main program");
                return 1;
            }
        }

        static void ShowUsage()
        {
            Console.WriteLine("FileManagerWorker - Remote File Management Worker Service");
            Console.WriteLine();
            Console.WriteLine("==============================================================================");
            Console.WriteLine("2-STAGE DEPLOYMENT PROCESS:");
            Console.WriteLine("==============================================================================");
            Console.WriteLine();
            Console.WriteLine("STEP 1: Configure service settings (saves to Windows Credential Manager)");
            Console.WriteLine("  FileManagerWorker.exe /config");
            Console.WriteLine();
            Console.WriteLine("STEP 2: Install and start the Windows service");
            Console.WriteLine("  FileManagerWorker.exe install --interactive");
            Console.WriteLine();
            Console.WriteLine("==============================================================================");
            Console.WriteLine();
            Console.WriteLine("USAGE:");
            Console.WriteLine("  FileManagerWorker.exe /config            Configure API URL and credentials");
            Console.WriteLine("  FileManagerWorker.exe install            Install service (requires /config first)");
            Console.WriteLine("  FileManagerWorker.exe uninstall          Uninstall the service");
            Console.WriteLine("  FileManagerWorker.exe /debug             Run in console mode for testing");
            Console.WriteLine("  FileManagerWorker.exe /? or /help        Show this usage information");
            Console.WriteLine();
            Console.WriteLine("COMMANDS:");
            Console.WriteLine("  /config               Interactive configuration wizard");
            Console.WriteLine("                        - Prompts for API URL");
            Console.WriteLine("                        - Prompts for service credentials (secure input)");
            Console.WriteLine("                        - Saves to Windows Credential Manager (ENCRYPTED)");
            Console.WriteLine();
            Console.WriteLine("  install               Standard Topshelf service installation");
            Console.WriteLine("    --interactive       Launch GUI for service account selection");
            Console.WriteLine("                        OR use default Network Service account");
            Console.WriteLine();
            Console.WriteLine("  uninstall             Remove the Windows service");
            Console.WriteLine();
            Console.WriteLine("  /debug                Run in console mode for development/testing");
            Console.WriteLine("                        - Loads config from Windows Credential Manager");
            Console.WriteLine("                        - Uses CurrentUser certificate store");
            Console.WriteLine("                        - Press any key to stop");
            Console.WriteLine();
            Console.WriteLine("==============================================================================");
            Console.WriteLine("SECURITY FEATURES:");
            Console.WriteLine("==============================================================================");
            Console.WriteLine("  - NO plaintext passwords in config files");
            Console.WriteLine("  - Windows Credential Manager storage (encrypted by OS)");
            Console.WriteLine("  - mTLS certificate-based authentication");
            Console.WriteLine("  - Secure password input (masked during /config)");
            Console.WriteLine();
            Console.WriteLine("EXAMPLE DEPLOYMENT:");
            Console.WriteLine("  1. FileManagerWorker.exe /config");
            Console.WriteLine("     Enter API URL: https://api.example.com");
            Console.WriteLine("     Enter service username: DOMAIN\\ServiceUser");
            Console.WriteLine("     Enter password: ********** (hidden)");
            Console.WriteLine("     Configuration saved to Windows Credential Manager!");
            Console.WriteLine();
            Console.WriteLine("  2. FileManagerWorker.exe install --interactive");
            Console.WriteLine("     [Topshelf GUI opens for service account selection]");
            Console.WriteLine("     Service installed successfully!");
            Console.WriteLine();
            Console.WriteLine("==============================================================================");
        }

        static int HandleConfig()
        {
            try
            {
                Console.WriteLine("==============================================================================");
                Console.WriteLine("FileManagerWorker Configuration Wizard");
                Console.WriteLine("==============================================================================");
                Console.WriteLine();

                // Check for elevation
                if (!CertificateManager.IsElevated())
                {
                    Console.WriteLine("ERROR: This wizard must be run as Administrator");
                    Console.WriteLine();
                    Console.WriteLine("The configuration wizard generates an mTLS certificate which requires");
                    Console.WriteLine("elevated privileges to store in the LocalMachine certificate store.");
                    Console.WriteLine();
                    Console.WriteLine("Please run again with Administrator privileges:");
                    Console.WriteLine("  Right-click Command Prompt -> Run as Administrator");
                    Console.WriteLine("  Then: FileManagerWorker.exe /config");
                    Console.WriteLine();
                    return 1;
                }

                Console.WriteLine("This wizard will:");
                Console.WriteLine("  1. Generate mTLS certificate for API authentication");
                Console.WriteLine("  2. Configure samba credentials for file operations");
                Console.WriteLine("  3. Securely store configuration in Windows Credential Manager");
                Console.WriteLine();

                // Prompt for API URL
                Console.Write("Enter Central API URL: ");
                string apiUrl = Console.ReadLine();
                if (string.IsNullOrWhiteSpace(apiUrl))
                {
                    Console.WriteLine("ERROR: API URL cannot be empty");
                    return 1;
                }

                // Prompt for Samba User (for file operations)
                Console.WriteLine();
                Console.WriteLine("--- Samba Credentials (for file operations) ---");
                Console.WriteLine("These credentials will be used to access network shares (\\\\server\\share).");
                Console.WriteLine("Leave empty if using Network Service account permissions.");
                Console.WriteLine();
                Console.Write("Enter samba username (e.g., DOMAIN\\User): ");
                string serviceUser = Console.ReadLine();

                // Prompt for Samba Password (secure input)
                string servicePassword = "";
                if (!string.IsNullOrWhiteSpace(serviceUser))
                {
                    Console.Write("Enter samba password (input hidden): ");
                    servicePassword = ReadPasswordSecurely();
                    Console.WriteLine();
                }

                // Prompt for Path Prefixes
                Console.WriteLine();
                Console.WriteLine("--- Path Prefix Configuration ---");
                Console.WriteLine("Configure the base paths for virtual drives A:, B:, and C:");
                Console.WriteLine("  - Path A: Source files");
                Console.WriteLine("  - Path B: Target (destination for PUSH operations)");
                Console.WriteLine("  - Path C: Archive (final storage after PUSH)");
                Console.WriteLine();
                Console.WriteLine("Operation logic:");
                Console.WriteLine("  - PUSH: A -> B (copy) + A -> C (move)");
                Console.WriteLine("  - PULL: B -> A (restore from target)");
                Console.WriteLine();
                Console.Write("Enter Path A Prefix (default: C:\\PathA): ");
                string pathAPrefix = Console.ReadLine();
                if (string.IsNullOrWhiteSpace(pathAPrefix))
                    pathAPrefix = @"C:\PathA";

                Console.Write("Enter Path B Prefix (default: C:\\PathB): ");
                string pathBPrefix = Console.ReadLine();
                if (string.IsNullOrWhiteSpace(pathBPrefix))
                    pathBPrefix = @"C:\PathB";

                Console.Write("Enter Path C Prefix (default: C:\\PathC): ");
                string pathCPrefix = Console.ReadLine();
                if (string.IsNullOrWhiteSpace(pathCPrefix))
                    pathCPrefix = @"C:\PathC";

                // Generate mTLS certificate
                Console.WriteLine();
                Console.WriteLine("--- Generating mTLS Certificate ---");
                Console.WriteLine("Generating self-signed certificate for API authentication...");

                var certManager = new CertificateManager
                {
                    StoreMode = CertificateManager.CertStoreMode.LocalMachine
                };

                var certificate = certManager.GetOrCreateCertificate();
                if (certificate == null)
                {
                    Console.WriteLine("ERROR: Failed to generate certificate");
                    return 1;
                }

                Console.WriteLine($"Certificate generated successfully!");
                Console.WriteLine($"  Thumbprint: {certificate.Thumbprint}");
                Console.WriteLine($"  Subject: {certificate.Subject}");
                Console.WriteLine($"  Valid from: {certificate.NotBefore:yyyy-MM-dd} to {certificate.NotAfter:yyyy-MM-dd}");

                // Save to secure storage using DPAPI
                Console.WriteLine();
                Console.WriteLine("--- Saving Configuration ---");
                if (!SecureConfigStorage.SaveConfiguration(apiUrl, serviceUser, servicePassword, pathAPrefix, pathBPrefix, pathCPrefix))
                {
                    Console.WriteLine("ERROR: Failed to save configuration to secure storage");
                    return 1;
                }

                // Also save API URL to App.config as fallback
                if (!UpdateAppConfig(apiUrl))
                {
                    Console.WriteLine("WARNING: Failed to update App.config, but secure storage was saved successfully");
                    // Don't fail - Secure storage is primary
                }

                Console.WriteLine();
                Console.WriteLine("==============================================================================");
                Console.WriteLine("Configuration completed successfully!");
                Console.WriteLine("==============================================================================");
                Console.WriteLine();
                Console.WriteLine("WHAT WAS CONFIGURED:");
                Console.WriteLine($"  ✓ mTLS certificate generated and stored in LocalMachine\\My");
                Console.WriteLine($"  ✓ Configuration saved to: {SecureConfigStorage.GetConfigFilePath()}");
                Console.WriteLine($"  ✓ API URL encrypted and stored");
                Console.WriteLine($"  ✓ Samba credentials encrypted and stored");
                Console.WriteLine();
                Console.WriteLine("SECURITY MODEL:");
                Console.WriteLine("  • Service runs as Network Service (least privilege)");
                Console.WriteLine("  • Certificate used for API authentication (mTLS)");
                Console.WriteLine("  • Samba credentials used ONLY for file operations (impersonation)");
                Console.WriteLine("  • All credentials encrypted by Windows DPAPI (LocalMachine scope)");
                Console.WriteLine("  • Network Service account CAN access these encrypted credentials");
                Console.WriteLine();
                Console.WriteLine("NEXT STEP:");
                Console.WriteLine("  Run: FileManagerWorker.exe install --interactive");
                Console.WriteLine("  This will install the Windows service using the saved configuration.");
                Console.WriteLine();

                return 0;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"ERROR: Configuration failed: {ex.Message}");
                Logger.Error(ex, "Configuration wizard failed");
                return 1;
            }
        }

        static string ReadPasswordSecurely()
        {
            var password = "";
            ConsoleKeyInfo key;

            do
            {
                key = Console.ReadKey(true);

                if (key.Key == ConsoleKey.Backspace && password.Length > 0)
                {
                    password = password.Substring(0, password.Length - 1);
                    Console.Write("\b \b");
                }
                else if (key.Key != ConsoleKey.Enter && key.Key != ConsoleKey.Backspace)
                {
                    password += key.KeyChar;
                    Console.Write("*");
                }
            } while (key.Key != ConsoleKey.Enter);

            return password;
        }

        static bool SaveToCredentialManager(string apiUrl, string serviceUser, string servicePassword)
        {
            try
            {
                // Save API URL
                using (var cred = new Credential())
                {
                    cred.Target = "FileManagerWorker_ApiUrl";
                    cred.Username = "FileManagerWorker";
                    cred.Password = apiUrl;
                    cred.Type = CredentialType.Generic;
                    cred.PersistanceType = PersistanceType.LocalComputer;
                    cred.Save();
                }

                // Save Service User
                using (var cred = new Credential())
                {
                    cred.Target = "FileManagerWorker_ServiceUser";
                    cred.Username = "FileManagerWorker";
                    cred.Password = serviceUser ?? "";
                    cred.Type = CredentialType.Generic;
                    cred.PersistanceType = PersistanceType.LocalComputer;
                    cred.Save();
                }

                // Save Service Password
                using (var cred = new Credential())
                {
                    cred.Target = "FileManagerWorker_ServicePassword";
                    cred.Username = "FileManagerWorker";
                    cred.Password = servicePassword ?? "";
                    cred.Type = CredentialType.Generic;
                    cred.PersistanceType = PersistanceType.LocalComputer;
                    cred.Save();
                }

                Logger.Info("Configuration saved to Windows Credential Manager");
                return true;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to save credentials to Windows Credential Manager");
                return false;
            }
        }

        static bool LoadFromCredentialManager(out string apiUrl, out string serviceUser, out string servicePassword)
        {
            apiUrl = null;
            serviceUser = null;
            servicePassword = null;

            try
            {
                // Load API URL
                using (var cred = new Credential { Target = "FileManagerWorker_ApiUrl" })
                {
                    if (cred.Load())
                    {
                        apiUrl = cred.Password;
                    }
                }

                // Load Service User
                using (var cred = new Credential { Target = "FileManagerWorker_ServiceUser" })
                {
                    if (cred.Load())
                    {
                        serviceUser = cred.Password;
                    }
                }

                // Load Service Password
                using (var cred = new Credential { Target = "FileManagerWorker_ServicePassword" })
                {
                    if (cred.Load())
                    {
                        servicePassword = cred.Password;
                    }
                }

                return !string.IsNullOrEmpty(apiUrl);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to load credentials from Windows Credential Manager");
                return false;
            }
        }

        static bool UpdateAppConfig(string apiUrl)
        {
            try
            {
                var configFile = AppDomain.CurrentDomain.SetupInformation.ConfigurationFile;
                var configFileMap = new ExeConfigurationFileMap { ExeConfigFilename = configFile };
                var config = ConfigurationManager.OpenMappedExeConfiguration(configFileMap, ConfigurationUserLevel.None);

                // Update ApiUrl in appSettings
                if (config.AppSettings.Settings["ApiUrl"] != null)
                {
                    config.AppSettings.Settings["ApiUrl"].Value = apiUrl;
                }
                else
                {
                    config.AppSettings.Settings.Add("ApiUrl", apiUrl);
                }

                config.Save(ConfigurationSaveMode.Modified);
                ConfigurationManager.RefreshSection("appSettings");

                Logger.Info("App.config updated with API URL: {0}", apiUrl);
                return true;
            }
            catch (Exception ex)
            {
                Logger.Warn(ex, "Failed to update App.config");
                return false;
            }
        }

        static int HandleInstall(string[] args)
        {
            try
            {
                Console.WriteLine("==============================================================================");
                Console.WriteLine("FileManagerWorker Service Installation");
                Console.WriteLine("==============================================================================");
                Console.WriteLine();

                // Verify configuration exists in secure storage
                if (!SecureConfigStorage.LoadConfiguration(out string apiUrl, out string serviceUser, out string servicePassword,
                    out string pathAPrefix, out string pathBPrefix, out string pathCPrefix))
                {
                    Console.WriteLine("ERROR: Configuration not found in secure storage");
                    Console.WriteLine();
                    Console.WriteLine("Please run the configuration wizard first:");
                    Console.WriteLine("  FileManagerWorker.exe /config");
                    Console.WriteLine();
                    Console.WriteLine($"Expected configuration at: {SecureConfigStorage.GetConfigFilePath()}");
                    Console.WriteLine();
                    return 1;
                }

                Console.WriteLine("Configuration loaded from secure storage:");
                Console.WriteLine($"  Config file: {SecureConfigStorage.GetConfigFilePath()}");
                Console.WriteLine($"  API URL: {apiUrl}");
                Console.WriteLine($"  Samba User: {(string.IsNullOrWhiteSpace(serviceUser) ? "(none - will use Network Service permissions)" : serviceUser)}");
                Console.WriteLine($"  Path A: {pathAPrefix}");
                Console.WriteLine($"  Path B: {pathBPrefix}");
                Console.WriteLine($"  Path C: {pathCPrefix}");
                Console.WriteLine();
                Console.WriteLine("Installing service...");
                Console.WriteLine();

                // Install using standard Topshelf - NO custom args passed to HostFactory
                var exitCode = (int)HostFactory.Run(x =>
                {
                    x.Service<WorkerService>(s =>
                    {
                        s.ConstructUsing(name => new WorkerService());
                        s.WhenStarted(tc => tc.Start());
                        s.WhenStopped(tc => tc.Stop());
                    });

                    // Use Network Service by default (secure and recommended)
                    // User can change via --interactive flag to launch Topshelf GUI
                    x.RunAsNetworkService();

                    x.SetDescription("Remote File Management Worker Service");
                    x.SetDisplayName("FileManager Worker");
                    x.SetServiceName("FileManagerWorker");

                    x.StartAutomatically();
                    x.EnableServiceRecovery(r =>
                    {
                        r.RestartService(1); // Restart after 1 minute
                        r.SetResetPeriod(1); // Reset failure count after 1 day
                    });

                    x.UseNLog();
                });

                Console.WriteLine();
                if ((int)exitCode == (int)TopshelfExitCode.Ok)
                {
                    Console.WriteLine("==============================================================================");
                    Console.WriteLine("Service installed successfully!");
                    Console.WriteLine("==============================================================================");
                    Console.WriteLine();
                    Console.WriteLine("The service is now installed and will start automatically.");
                    Console.WriteLine("You can manage it using Windows Services (services.msc).");
                    Console.WriteLine();
                    return 0;
                }
                else
                {
                    Console.WriteLine("==============================================================================");
                    Console.WriteLine($"Service installation failed with code: {exitCode}");
                    Console.WriteLine("==============================================================================");
                    Console.WriteLine();
                    return 1;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"ERROR: Installation failed: {ex.Message}");
                Logger.Error(ex, "Service installation failed");
                return 1;
            }
        }

        static int HandleUninstall()
        {
            try
            {
                Console.WriteLine("Uninstalling FileManagerWorker service...");

                var exitCode = (int)HostFactory.Run(x =>
                {
                    x.Service<WorkerService>(s =>
                    {
                        s.ConstructUsing(name => new WorkerService());
                        s.WhenStarted(tc => tc.Start());
                        s.WhenStopped(tc => tc.Stop());
                    });

                    x.SetServiceName("FileManagerWorker");
                });

                Console.WriteLine("Service uninstalled successfully.");
                return 0;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Uninstallation failed: {ex.Message}");
                Logger.Error(ex, "Service uninstallation failed");
                return 1;
            }
        }

        static int RunInDebugMode()
        {
            Console.WriteLine("Running in DEBUG mode. Press Ctrl+C to stop.");
            Console.WriteLine();

            try
            {
                var service = new WorkerService();
                service.Start();

                Console.WriteLine("Service started. Monitoring for commands...");
                Console.WriteLine("Press any key to stop.");
                Console.ReadKey();

                service.Stop();
                Console.WriteLine("Service stopped.");

                return 0;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Error in debug mode: {ex.Message}");
                Logger.Error(ex, "Error in debug mode");
                return 1;
            }
        }

        static int RunAsService()
        {
            var exitCode = HostFactory.Run(x =>
            {
                x.Service<WorkerService>(s =>
                {
                    s.ConstructUsing(name => new WorkerService());
                    s.WhenStarted(tc => tc.Start());
                    s.WhenStopped(tc => tc.Stop());
                });

                x.RunAsLocalSystem();

                x.SetDescription("Remote File Management Worker Service");
                x.SetDisplayName("FileManager Worker");
                x.SetServiceName("FileManagerWorker");

                x.StartAutomatically();
                x.UseNLog();
            });

            return (int)exitCode;
        }

    }
}
