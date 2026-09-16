using System;
using System.Configuration;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CredentialManagement;
using FileManagerWorker.Models;
using NLog;

namespace FileManagerWorker
{
    /// <summary>
    /// Main worker service implementation
    /// </summary>
    public class WorkerService
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();

        /// <summary>
        /// Service lifecycle and connectivity state changes (started, stopped, active
        /// again, API reachable again). App.config routes this logger's Info entries to
        /// the Windows Event Log, which otherwise only receives warnings and above.
        /// </summary>
        internal static readonly Logger Lifecycle = LogManager.GetLogger("Lifecycle");

        private CertificateManager _certManager;
        private ApiClient _apiClient;
        private FileOperations _fileOps;
        private CommandHandler _commandHandler;
        private ServiceConfiguration _config;

        /// <summary>
        /// How long to wait before polling again while the API is rejecting this
        /// worker (PENDING approval, SUSPENDED). Deliberately much longer than the
        /// normal polling interval: nothing changes until the server-side status does.
        /// </summary>
        internal const int UnauthorizedRetrySeconds = 30;

        private CancellationTokenSource _cancellationTokenSource;
        private Task _pollingTask;
        private Task _heartbeatTask;

        private readonly object _commandLock = new object();

        public WorkerService()
        {
            Logger.Info("FileManagerWorker service constructed");
        }

        /// <summary>
        /// Starts the worker service
        /// </summary>
        public bool Start()
        {
            try
            {
                Logger.Info("Starting FileManagerWorker service...");

                // Load configuration
                var config = LoadConfiguration();
                if (config == null)
                {
                    Logger.Error("Failed to load configuration");
                    return false;
                }

                _config = config;

                // Initialize certificate manager (read-only mode)
                _certManager = new CertificateManager();
				_certManager.StoreMode = Debugger.IsAttached || Environment.GetCommandLineArgs().Contains("/debug")
	                ? CertificateManager.CertStoreMode.CurrentUser
	                : CertificateManager.CertStoreMode.LocalMachine;
				Logger.Info("Using certificate store: {0}", _certManager.StoreMode);

                // Get certificate (read-only - must be generated during /config)
                var certificate = _certManager.GetCertificateReadOnly();
                if (certificate == null)
                {
                    Logger.Error("Cannot start: no mTLS certificate in the {0} certificate store. " +
                                 "Run 'FileManagerWorker.exe /config' as Administrator to generate it, then start the service again.",
                                 _certManager.StoreMode);
                    return false;
                }

                Logger.Info("Certificate loaded successfully (Thumbprint: {0})", certificate.Thumbprint);

                // Initialize components
				_apiClient = new ApiClient(config.ApiUrl, _certManager, config);
                _fileOps = new FileOperations(
                    config.PathAPrefix,
                    config.PathBPrefix,
                    config.PathCPrefix,
                    config.ServiceUser,      // Samba username for file operations
                    config.ServicePassword   // Samba password for file operations
                );
                _commandHandler = new CommandHandler(_fileOps, _apiClient);

                // Register with Central API
                var registrationTask = _apiClient.RegisterWorkerAsync();
                registrationTask.Wait();

                if (!registrationTask.Result)
                {
                    // RegisterWorkerAsync has already logged why; polling retries it.
                    Logger.Debug("Initial registration did not succeed, will retry while polling");
                }

                // Start background tasks
                _cancellationTokenSource = new CancellationTokenSource();

                _pollingTask = Task.Run(() => PollingLoop(_cancellationTokenSource.Token));
                _heartbeatTask = Task.Run(() => HeartbeatLoop(_cancellationTokenSource.Token));

                Lifecycle.Info("FileManagerWorker started (worker {0}, API {1})", Environment.MachineName, config.ApiUrl);
                return true;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to start service");
                return false;
            }
        }

        /// <summary>
        /// Stops the worker service
        /// </summary>
        public bool Stop()
        {
            try
            {
                Logger.Info("Stopping FileManagerWorker service...");

                _cancellationTokenSource?.Cancel();

                // Wait for tasks to complete
                Task.WaitAll(new[] { _pollingTask, _heartbeatTask }, TimeSpan.FromSeconds(10));

                // Dispose resources
                _apiClient?.Dispose();

                Lifecycle.Info("FileManagerWorker stopped");
                return true;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Error stopping service");
                return false;
            }
        }

        /// <summary>
        /// Main polling loop for commands
        /// </summary>
        private async Task PollingLoop(CancellationToken cancellationToken)
        {
            Logger.Info("Command polling loop started");

            while (!cancellationToken.IsCancellationRequested)
            {
                try
                {
                    // Poll for commands
                    var command = await _apiClient.PollForCommandAsync(cancellationToken);

                    if (command != null)
                    {
                        // Process command (one at a time)
                        lock (_commandLock)
                        {
                            Logger.Info("Processing command: {0}", command.CommandId);
                            var response = _commandHandler.ExecuteAsync(command).Result;
                            _apiClient.SendResponseAsync(response).Wait();
                        }

                        // Another command may already be queued behind this one.
                        continue;
                    }

                    // Nothing waiting. PollForCommandAsync is a long poll, so this
                    // usually just adds a short pause after a 30s server-side wait.
                    // It matters when the API answers immediately: a worker that is
                    // still PENDING approval gets an instant 403 on every poll, and
                    // without this delay the loop - and the re-registration it
                    // triggers - runs flat out against the API.
                    await Task.Delay(
                        _apiClient.IsRejected
                            ? TimeSpan.FromSeconds(UnauthorizedRetrySeconds)
                            : TimeSpan.FromSeconds(_config.PollingIntervalSeconds),
                        cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Logger.Error(ex, "Error in polling loop");
                    await Task.Delay(5000, cancellationToken); // Wait before retrying
                }
            }

            Logger.Info("Command polling loop stopped");
        }

        /// <summary>
        /// Heartbeat loop to keep connection alive
        /// </summary>
        private async Task HeartbeatLoop(CancellationToken cancellationToken)
        {
            Logger.Info("Heartbeat loop started");

            while (!cancellationToken.IsCancellationRequested)
            {
                try
                {
                    await Task.Delay(TimeSpan.FromMinutes(1), cancellationToken);
                    await _apiClient.SendHeartbeatAsync();
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Logger.Debug(ex, "Error in heartbeat loop");
                }
            }

            Logger.Info("Heartbeat loop stopped");
        }

        /// <summary>
        /// Loads configuration from Windows Credential Manager (secure) and App.config (non-sensitive settings)
        /// </summary>
        private ServiceConfiguration LoadConfiguration()
        {
            try
            {
                // Load sensitive data from secure storage (DPAPI with LocalMachine scope)
                string apiUrl = null;
                string serviceUser = null;
                string servicePassword = null;
                string pathAPrefix = null;
                string pathBPrefix = null;
                string pathCPrefix = null;

                try
                {
                    // Try to load from secure storage
                    if (SecureConfigStorage.LoadConfiguration(out apiUrl, out serviceUser, out servicePassword,
                        out pathAPrefix, out pathBPrefix, out pathCPrefix))
                    {
                        Logger.Info("Configuration loaded from secure storage: {0}", SecureConfigStorage.GetConfigFilePath());
                    }
                    else
                    {
                        Logger.Info("Configuration not found in secure storage, falling back to App.config");
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warn(ex, "Failed to load configuration from secure storage, falling back to App.config");
                }

                // Fallback to App.config if secure storage is not available (backward compatibility)
                if (string.IsNullOrEmpty(apiUrl))
                {
                    apiUrl = ConfigurationManager.AppSettings["ApiUrl"];
                    Logger.Warn("Using API URL from App.config (DEPRECATED - please use /config to save securely)");
                }

                // Validate API URL is configured (CRITICAL: don't use defaults that will fail silently)
                if (string.IsNullOrEmpty(apiUrl))
                {
                    Logger.Error("Cannot start: API URL is not configured in secure storage ({0}) or App.config. " +
                                 "Run 'FileManagerWorker.exe /config' as Administrator, then restart the service.",
                                 SecureConfigStorage.GetConfigFilePath());
                    return null;
                }

                // Fallback to App.config for path prefixes if not in secure storage
                if (string.IsNullOrEmpty(pathAPrefix))
                {
                    pathAPrefix = ConfigurationManager.AppSettings["PathAPrefix"] ?? @"C:\PathA";
                }
                if (string.IsNullOrEmpty(pathBPrefix))
                {
                    pathBPrefix = ConfigurationManager.AppSettings["PathBPrefix"] ?? @"C:\PathB";
                }
                if (string.IsNullOrEmpty(pathCPrefix))
                {
                    pathCPrefix = ConfigurationManager.AppSettings["PathCPrefix"] ?? @"C:\PathC";
                }

                // Load non-sensitive settings from App.config
                var config = new ServiceConfiguration
                {
                    ApiUrl = apiUrl,
                    ServiceUser = serviceUser,
                    ServicePassword = servicePassword,
                    PathAPrefix = pathAPrefix,
                    PathBPrefix = pathBPrefix,
                    PathCPrefix = pathCPrefix,
                    PollingIntervalSeconds = int.Parse(ConfigurationManager.AppSettings["PollingIntervalSeconds"] ?? "5"),
                    UseMtls = bool.Parse(ConfigurationManager.AppSettings["UseMtls"] ?? "true")
                };

                Logger.Info("========================================================================");
                Logger.Info("Configuration loaded successfully:");
                Logger.Info("========================================================================");
                Logger.Info("  API URL: {0}", config.ApiUrl);
                Logger.Info("  Service User: {0}", string.IsNullOrWhiteSpace(config.ServiceUser) ? "Network Service" : config.ServiceUser);
                Logger.Info("  Path A Prefix: {0}", config.PathAPrefix);
                Logger.Info("  Path B Prefix: {0}", config.PathBPrefix);
                Logger.Info("  Path C Prefix: {0}", config.PathCPrefix);
                Logger.Info("  Polling Interval: {0}s", config.PollingIntervalSeconds);
                Logger.Info("  Use mTLS: {0}", config.UseMtls);
                Logger.Info("  Current User Context: {0}", Environment.UserName);
                Logger.Info("  Machine Name: {0}", Environment.MachineName);
                Logger.Info("========================================================================");

                return config;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to load configuration");
                return null;
            }
        }
    }
}
