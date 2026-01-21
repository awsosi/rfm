using System;
using System.Configuration;
using System.Threading;
using System.Threading.Tasks;
using NLog;
using FileManagerWorker.Models;

namespace FileManagerWorker
{
    /// <summary>
    /// Main worker service implementation
    /// </summary>
    public class WorkerService
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();

        private CertificateManager _certManager;
        private ApiClient _apiClient;
        private FileOperations _fileOps;
        private RollbackManager _rollbackManager;
        private CommandHandler _commandHandler;

        private CancellationTokenSource _cancellationTokenSource;
        private Task _pollingTask;
        private Task _heartbeatTask;
        private Task _cleanupTask;

        private bool _isRunning;
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

                // Initialize components
                _certManager = new CertificateManager();
                _apiClient = new ApiClient(config.ApiUrl, _certManager);
                _fileOps = new FileOperations(config.PathAPrefix, config.PathBPrefix);
                _rollbackManager = new RollbackManager();
                _commandHandler = new CommandHandler(_fileOps, _rollbackManager, _apiClient);

                // Register with Central API
                var registrationTask = _apiClient.RegisterWorkerAsync();
                registrationTask.Wait();

                if (!registrationTask.Result)
                {
                    Logger.Warn("Worker registration failed, will retry during operation");
                }

                // Start background tasks
                _cancellationTokenSource = new CancellationTokenSource();
                _isRunning = true;

                _pollingTask = Task.Run(() => PollingLoop(_cancellationTokenSource.Token));
                _heartbeatTask = Task.Run(() => HeartbeatLoop(_cancellationTokenSource.Token));
                _cleanupTask = Task.Run(() => CleanupLoop(_cancellationTokenSource.Token));

                Logger.Info("FileManagerWorker service started successfully");
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

                _isRunning = false;
                _cancellationTokenSource?.Cancel();

                // Wait for tasks to complete
                Task.WaitAll(new[] { _pollingTask, _heartbeatTask, _cleanupTask }, TimeSpan.FromSeconds(10));

                // Dispose resources
                _apiClient?.Dispose();

                Logger.Info("FileManagerWorker service stopped");
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
                    }
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
        /// Cleanup loop for old backups
        /// </summary>
        private async Task CleanupLoop(CancellationToken cancellationToken)
        {
            Logger.Info("Cleanup loop started");

            while (!cancellationToken.IsCancellationRequested)
            {
                try
                {
                    await Task.Delay(TimeSpan.FromHours(6), cancellationToken);
                    _rollbackManager.CleanupOldBackups();
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    Logger.Warn(ex, "Error in cleanup loop");
                }
            }

            Logger.Info("Cleanup loop stopped");
        }

        /// <summary>
        /// Loads configuration from App.config
        /// </summary>
        private ServiceConfiguration LoadConfiguration()
        {
            try
            {
                var config = new ServiceConfiguration
                {
                    ApiUrl = ConfigurationManager.AppSettings["ApiUrl"] ?? "https://localhost:5001",
                    ServiceUser = ConfigurationManager.AppSettings["ServiceUser"],
                    ServicePassword = ConfigurationManager.AppSettings["ServicePassword"],
                    PathAPrefix = ConfigurationManager.AppSettings["PathAPrefix"] ?? @"C:\PathA",
                    PathBPrefix = ConfigurationManager.AppSettings["PathBPrefix"] ?? @"C:\PathB",
                    PollingIntervalSeconds = int.Parse(ConfigurationManager.AppSettings["PollingIntervalSeconds"] ?? "5"),
                    UseMtls = bool.Parse(ConfigurationManager.AppSettings["UseMtls"] ?? "true")
                };

                Logger.Info("Configuration loaded:");
                Logger.Info("  API URL: {0}", config.ApiUrl);
                Logger.Info("  Path A Prefix: {0}", config.PathAPrefix);
                Logger.Info("  Path B Prefix: {0}", config.PathBPrefix);
                Logger.Info("  Polling Interval: {0}s", config.PollingIntervalSeconds);
                Logger.Info("  Use mTLS: {0}", config.UseMtls);

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
