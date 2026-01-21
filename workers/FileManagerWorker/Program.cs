using System;
using System.Configuration;
using System.Linq;
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

                // Handle custom installation with parameters
                if (args.Contains("/install"))
                {
                    return HandleInstall(args);
                }

                if (args.Contains("/uninstall"))
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
            Console.WriteLine("USAGE:");
            Console.WriteLine("  FileManagerWorker.exe /install /url <api-url> /user <service-user> /pass <service-pass>");
            Console.WriteLine("  FileManagerWorker.exe /uninstall");
            Console.WriteLine("  FileManagerWorker.exe /debug");
            Console.WriteLine("  FileManagerWorker.exe /? or /help");
            Console.WriteLine();
            Console.WriteLine("PARAMETERS:");
            Console.WriteLine("  /install              Install the service with specified parameters");
            Console.WriteLine("  /url <api-url>        Central API URL (required for install)");
            Console.WriteLine("  /user <username>      Windows user account for service (required for install)");
            Console.WriteLine("  /pass <password>      Password for service account (required for install)");
            Console.WriteLine("  /uninstall            Uninstall the service");
            Console.WriteLine("  /debug                Run in console mode for testing");
            Console.WriteLine("  /? or /help           Show this usage information");
            Console.WriteLine();
            Console.WriteLine("EXAMPLES:");
            Console.WriteLine("  FileManagerWorker.exe /install /url https://api.example.com /user DOMAIN\\ServiceUser /pass P@ssw0rd");
            Console.WriteLine("  FileManagerWorker.exe /debug");
        }

        static int HandleInstall(string[] args)
        {
            try
            {
                // Parse installation parameters
                string apiUrl = GetArgValue(args, "/url");
                string serviceUser = GetArgValue(args, "/user");
                string servicePass = GetArgValue(args, "/pass");

                if (string.IsNullOrEmpty(apiUrl) || string.IsNullOrEmpty(serviceUser) || string.IsNullOrEmpty(servicePass))
                {
                    Console.WriteLine("ERROR: /install requires /url, /user, and /pass parameters");
                    ShowUsage();
                    return 1;
                }

                // Save configuration to App.config before installation
                SaveConfiguration(apiUrl, serviceUser, servicePass);

                Console.WriteLine("Installing FileManagerWorker service...");
                Console.WriteLine($"API URL: {apiUrl}");
                Console.WriteLine($"Service User: {serviceUser}");

                // Install using TopShelf with custom credentials
                var exitCode = (int)HostFactory.Run(x =>
                {
                    x.Service<WorkerService>(s =>
                    {
                        s.ConstructUsing(name => new WorkerService());
                        s.WhenStarted(tc => tc.Start());
                        s.WhenStopped(tc => tc.Stop());
                    });

                    x.RunAsNetworkService();
                    // For custom user: x.RunAs(serviceUser, servicePass);

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

                if (exitCode == TopshelfExitCode.Ok)
                {
                    Console.WriteLine("Service installed successfully.");
                    return 0;
                }
                else
                {
                    Console.WriteLine($"Service installation failed with code: {exitCode}");
                    return 1;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Installation failed: {ex.Message}");
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

        static void SaveConfiguration(string apiUrl, string serviceUser, string servicePass)
        {
            try
            {
                var config = ConfigurationManager.OpenExeConfiguration(ConfigurationUserLevel.None);

                config.AppSettings.Settings.Remove("ApiUrl");
                config.AppSettings.Settings.Add("ApiUrl", apiUrl);

                config.AppSettings.Settings.Remove("ServiceUser");
                config.AppSettings.Settings.Add("ServiceUser", serviceUser);

                config.AppSettings.Settings.Remove("ServicePassword");
                config.AppSettings.Settings.Add("ServicePassword", servicePass);

                config.Save(ConfigurationSaveMode.Modified);
                ConfigurationManager.RefreshSection("appSettings");

                Console.WriteLine("Configuration saved successfully.");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not save configuration: {ex.Message}");
                Logger.Warn(ex, "Could not save configuration");
            }
        }
    }
}
