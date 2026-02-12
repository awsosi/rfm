using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using NLog;
using FileManagerWorker.Models;

namespace FileManagerWorker
{
    /// <summary>
    /// Handles command parsing and execution with rollback support
    /// </summary>
    public class CommandHandler
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();
        private readonly FileOperations _fileOps;
        private readonly RollbackManager _rollbackManager;
        private readonly ApiClient _apiClient;

        public CommandHandler(FileOperations fileOps, RollbackManager rollbackManager, ApiClient apiClient)
        {
            _fileOps = fileOps;
            _rollbackManager = rollbackManager;
            _apiClient = apiClient;
        }

        /// <summary>
        /// Executes a command request
        /// </summary>
        public async Task<CommandResponse> ExecuteAsync(CommandRequest request)
        {
            if (request == null)
            {
                return CommandResponse.Failed(0, "Request is null");
            }

            if (!request.CommandId.HasValue)
            {
                return CommandResponse.Failed(0, "Command ID is missing");
            }

            int cmdId = request.CommandId.Value;

            Logger.Info("Executing command: {0} (ID: {1})", request.Command, cmdId);

            try
            {
                switch (request.Command?.ToLowerInvariant())
                {
                    case "copy":
                        return await HandleCopyAsync(request);

                    case "move":
                        return await HandleMoveAsync(request);

                    case "delete":
                        return await HandleDeleteAsync(request);

                    case "mkdir":
                        return await HandleMkdirAsync(request);

                    case "list":
                        return await HandleListAsync(request);

                    case "search":
                        return await HandleSearchAsync(request);

                    case "info":
                        return await HandleInfoAsync(request);

                    case "ping":
                        return await HandlePingAsync(request);

                    case "get_status":
                        return await HandleGetStatusAsync(request);

                    case "push_cleanup":
                        return await HandlePushCleanupAsync(request);

                    case "update_config":
                        return await HandleUpdateConfigAsync(request);

                    case "reload_config":
                        return await HandleReloadConfigAsync(request);

                    default:
                        return CommandResponse.Failed(cmdId, $"Unknown command: {request.Command}");
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Command execution failed: {0}", cmdId);
                return CommandResponse.Failed(cmdId, ex.Message);
            }
        }

        /// <summary>
        /// Handles copy command with rollback support
        /// </summary>
        private async Task<CommandResponse> HandleCopyAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (string.IsNullOrEmpty(request.SourcePath) || string.IsNullOrEmpty(request.DestPath))
            {
                return CommandResponse.Failed(cmdId, "Copy requires source_path and dest_path");
            }

            var source = request.SourcePath;
            var destination = request.DestPath;

            // Extract optional PUSH params (flatten, ignore_masks)
            bool flatten = request.Parameters?.ContainsKey("flatten") == true
                && Convert.ToBoolean(request.Parameters["flatten"]);
            List<string> ignoreMasks = null;
            if (request.Parameters?.ContainsKey("ignore_masks") == true)
            {
                ignoreMasks = ParseIgnoreMasks(request.Parameters["ignore_masks"]);
            }

            List<RollbackContext> backups = null;

            try
            {
                // Create backup of destination if it exists
                backups = _rollbackManager.CreateBackups(destination);

                // Progress reporter
                var progress = new Progress<int>(async percent =>
                {
                    if (percent % 10 == 0) // Report every 10%
                    {
                        await _apiClient.SendProgressAsync(cmdId, percent);
                    }
                });

                // Execute copy (with optional flatten and ignore_masks)
                var result = await _fileOps.CopyAsync(source, destination, progress, flatten, ignoreMasks);

                // Success - cleanup backups
                _rollbackManager.CleanupBackups(backups);

                // Extract file count and size from result
                int? fileCount = result?.ContainsKey("file_count") == true ? Convert.ToInt32(result["file_count"]) : null;
                long? totalSize = result?.ContainsKey("total_size_bytes") == true ? Convert.ToInt64(result["total_size_bytes"]) : null;

                return CommandResponse.Success(cmdId, "Copy completed successfully", fileCount, totalSize);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Copy operation failed");

                // Attempt rollback
                var rollbackSuccess = _rollbackManager.RestoreAll(backups);

                var errorDetails = new Dictionary<string, object>
                {
                    { "rollback_status", rollbackSuccess ? "success" : "failed" },
                    { "error_type", ex.GetType().Name }
                };

                return CommandResponse.Failed(cmdId, ex.Message, errorDetails);
            }
        }

        /// <summary>
        /// Handles move command with rollback support
        /// </summary>
        private async Task<CommandResponse> HandleMoveAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (string.IsNullOrEmpty(request.SourcePath) || string.IsNullOrEmpty(request.DestPath))
            {
                return CommandResponse.Failed(cmdId, "Move requires source_path and dest_path");
            }

            var source = request.SourcePath;
            var destination = request.DestPath;

            List<RollbackContext> backups = null;

            try
            {
                // Create backups of both source and destination
                backups = _rollbackManager.CreateBackups(source, destination);

                // Execute move
                var result = await _fileOps.MoveAsync(source, destination);

                // Success - cleanup backups
                _rollbackManager.CleanupBackups(backups);

                // Extract file count and size from result
                int? fileCount = result?.ContainsKey("file_count") == true ? Convert.ToInt32(result["file_count"]) : null;
                long? totalSize = result?.ContainsKey("total_size_bytes") == true ? Convert.ToInt64(result["total_size_bytes"]) : null;

                return CommandResponse.Success(cmdId, "Move completed successfully", fileCount, totalSize);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Move operation failed");

                // Attempt rollback
                var rollbackSuccess = _rollbackManager.RestoreAll(backups);

                var errorDetails = new Dictionary<string, object>
                {
                    { "rollback_status", rollbackSuccess ? "success" : "failed" },
                    { "error_type", ex.GetType().Name }
                };

                return CommandResponse.Failed(cmdId, ex.Message, errorDetails);
            }
        }

        /// <summary>
        /// Handles delete command with rollback support
        /// </summary>
        private async Task<CommandResponse> HandleDeleteAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (string.IsNullOrEmpty(request.SourcePath))
            {
                return CommandResponse.Failed(cmdId, "Delete requires source_path");
            }

            var path = request.SourcePath;

            RollbackContext backup = null;

            try
            {
                // Create backup before deletion
                backup = _rollbackManager.CreateBackup(path);

                // Execute delete (always recursive for directories)
                var result = await _fileOps.DeleteAsync(path);

                // Success - cleanup backup
                _rollbackManager.CleanupBackup(backup);

                int? fileCount = result?.ContainsKey("file_count") == true ? Convert.ToInt32(result["file_count"]) : null;

                return CommandResponse.Success(cmdId, "Delete completed successfully", fileCount);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Delete operation failed");

                // Attempt rollback
                var rollbackSuccess = _rollbackManager.Restore(backup);

                var errorDetails = new Dictionary<string, object>
                {
                    { "rollback_status", rollbackSuccess ? "success" : "failed" },
                    { "error_type", ex.GetType().Name }
                };

                return CommandResponse.Failed(cmdId, ex.Message, errorDetails);
            }
        }

        /// <summary>
        /// Handles mkdir command with rollback support
        /// </summary>
        private async Task<CommandResponse> HandleMkdirAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (string.IsNullOrEmpty(request.SourcePath))
            {
                return CommandResponse.Failed(cmdId, "Mkdir requires source_path");
            }

            var path = request.SourcePath;
            bool parents = request.Parameters?.ContainsKey("parents") != true ||
                          Convert.ToBoolean(request.Parameters["parents"]); // Default true

            RollbackContext backup = null;

            try
            {
                // Create backup (will note if directory didn't exist)
                backup = _rollbackManager.CreateBackup(path);

                // Execute mkdir
                var result = await _fileOps.MkdirAsync(path);

                // Success - cleanup backup
                _rollbackManager.CleanupBackup(backup);

                return CommandResponse.Success(cmdId, "Directory created successfully");
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Mkdir operation failed");

                // Attempt rollback
                var rollbackSuccess = _rollbackManager.Restore(backup);

                var errorDetails = new Dictionary<string, object>
                {
                    { "rollback_status", rollbackSuccess ? "success" : "failed" },
                    { "error_type", ex.GetType().Name }
                };

                return CommandResponse.Failed(cmdId, ex.Message, errorDetails);
            }
        }

        /// <summary>
        /// Handles list command (read-only, no rollback needed)
        /// </summary>
        private async Task<CommandResponse> HandleListAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (!request.Parameters.ContainsKey("path"))
            {
                return CommandResponse.Failed(cmdId, "List requires 'path' parameter");
            }

            var path = request.Parameters["path"]?.ToString();
            var recursive = request.Parameters.ContainsKey("recursive") &&
                           bool.TryParse(request.Parameters["recursive"]?.ToString(), out var rec) && rec;

            // Parse pagination parameters
            var offset = 0;
            var limit = 0;
            if (request.Parameters.ContainsKey("offset") && int.TryParse(request.Parameters["offset"]?.ToString(), out var off))
            {
                offset = off;
            }
            if (request.Parameters.ContainsKey("limit") && int.TryParse(request.Parameters["limit"]?.ToString(), out var lim))
            {
                limit = lim;
            }

            try
            {
                var result = await _fileOps.ListAsync(path, recursive, offset, limit);
                var response = CommandResponse.Success(
                    cmdId,
                    "List completed successfully",
                    result.ContainsKey("count") ? Convert.ToInt32(result["count"]) : (int?)null
                );
                // Include the full result data (items, total, offset, limit) in ErrorDetails
                response.ErrorDetails = result;
                return response;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "List operation failed");
                return CommandResponse.Failed(cmdId, ex.Message);
            }
        }

        /// <summary>
        /// Handles search command (read-only, no rollback needed)
        /// </summary>
        private async Task<CommandResponse> HandleSearchAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (!request.Parameters.ContainsKey("path") || !request.Parameters.ContainsKey("pattern"))
            {
                return CommandResponse.Failed(cmdId, "Search requires 'path' and 'pattern' parameters");
            }

            var path = request.Parameters["path"]?.ToString();
            var pattern = request.Parameters["pattern"]?.ToString();
            var recursive = !request.Parameters.ContainsKey("recursive") ||
                           (bool.TryParse(request.Parameters["recursive"]?.ToString(), out var rec) && rec);

            try
            {
                var result = await _fileOps.SearchAsync(path, pattern, recursive);
                var response = CommandResponse.Success(
                    cmdId,
                    "Search completed successfully",
                    result.ContainsKey("count") ? Convert.ToInt32(result["count"]) : (int?)null
                );
                // Include the full result data (results, total, count) in ErrorDetails
                response.ErrorDetails = result;
                return response;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Search operation failed");
                return CommandResponse.Failed(cmdId, ex.Message);
            }
        }

        /// <summary>
        /// Handles info command (read-only, no rollback needed)
        /// </summary>
        private async Task<CommandResponse> HandleInfoAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (!request.Parameters.ContainsKey("path"))
            {
                return CommandResponse.Failed(cmdId, "Info requires 'path' parameter");
            }

            var path = request.Parameters["path"]?.ToString();

            try
            {
                var result = await _fileOps.GetInfoAsync(path);
                return CommandResponse.Success(cmdId, "Info retrieved successfully");
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Info operation failed");
                return CommandResponse.Failed(cmdId, ex.Message);
            }
        }

        /// <summary>
        /// Handles ping command (admin - health check)
        /// </summary>
        private async Task<CommandResponse> HandlePingAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;
            Logger.Debug("Ping command received");
            return await Task.FromResult(CommandResponse.Success(cmdId, "pong"));
        }

        /// <summary>
        /// Handles get_status command (admin - returns worker status and metrics)
        /// </summary>
        private async Task<CommandResponse> HandleGetStatusAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;
            Logger.Debug("Get status command received");

            try
            {
                // Gather worker status information
                var status = new Dictionary<string, object>
                {
                    { "worker_name", Environment.MachineName },
                    { "uptime_seconds", (int)(DateTime.Now - System.Diagnostics.Process.GetCurrentProcess().StartTime).TotalSeconds },
                    { "operations_processed", 0 }, // TODO: Implement operation counter
                    { "operations_in_queue", 0 }, // TODO: Implement queue status
                    { "status", "online" },
                    { "version", System.Reflection.Assembly.GetExecutingAssembly().GetName().Version.ToString() },
                    { "timestamp", DateTimeOffset.UtcNow.ToUnixTimeSeconds() }
                };

                // Try to get performance metrics
                try
                {
                    var process = System.Diagnostics.Process.GetCurrentProcess();
                    var cpuCounter = new System.Diagnostics.PerformanceCounter("Processor", "% Processor Time", "_Total");
                    cpuCounter.NextValue(); // First call always returns 0
                    System.Threading.Thread.Sleep(100);

                    status["cpu_usage_percent"] = Math.Round(cpuCounter.NextValue(), 2);
                    status["memory_usage_mb"] = Math.Round(process.WorkingSet64 / 1024.0 / 1024.0, 2);

                    // Get disk space
                    var drive = new System.IO.DriveInfo(System.IO.Path.GetPathRoot(Environment.SystemDirectory));
                    status["disk_free_gb"] = Math.Round(drive.AvailableFreeSpace / 1024.0 / 1024.0 / 1024.0, 2);
                }
                catch (Exception ex)
                {
                    Logger.Warn(ex, "Failed to get performance metrics");
                }

                // Get current configuration
                var config = new Dictionary<string, object>();
                try
                {
                    config["path_a_prefix"] = _fileOps.PathAPrefix;
                    config["path_b_prefix"] = _fileOps.PathBPrefix;
                    config["path_c_prefix"] = _fileOps.PathCPrefix;
                }
                catch (Exception ex)
                {
                    Logger.Warn(ex, "Failed to get configuration");
                }

                status["config"] = config;

                var response = CommandResponse.Success(cmdId, "Status retrieved successfully");
                response.ErrorDetails = status;
                return await Task.FromResult(response);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Get status operation failed");
                return await Task.FromResult(CommandResponse.Failed(cmdId, ex.Message));
            }
        }

        /// <summary>
        /// Handles update_config command (admin - updates worker configuration)
        /// </summary>
        private async Task<CommandResponse> HandleUpdateConfigAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;
            Logger.Info("Update config command received");

            try
            {
                var updated = new List<string>();

                // Update path prefixes if provided
                if (request.Parameters.ContainsKey("path_a_prefix"))
                {
                    var newPath = request.Parameters["path_a_prefix"]?.ToString();
                    Logger.Info("Updating PathAPrefix to: {0}", newPath);
                    _fileOps.PathAPrefix = newPath;
                    updated.Add("path_a_prefix");
                }

                if (request.Parameters.ContainsKey("path_b_prefix"))
                {
                    var newPath = request.Parameters["path_b_prefix"]?.ToString();
                    Logger.Info("Updating PathBPrefix to: {0}", newPath);
                    _fileOps.PathBPrefix = newPath;
                    updated.Add("path_b_prefix");
                }

                if (request.Parameters.ContainsKey("path_c_prefix"))
                {
                    var newPath = request.Parameters["path_c_prefix"]?.ToString();
                    Logger.Info("Updating PathCPrefix to: {0}", newPath);
                    _fileOps.PathCPrefix = newPath;
                    updated.Add("path_c_prefix");
                }

                // TODO: Handle other configuration parameters (polling_interval, etc.)
                // These would require service restart or dynamic reconfiguration

                return await Task.FromResult(CommandResponse.Success(cmdId, $"Updated {updated.Count} configuration parameter(s)"));
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Update config operation failed");
                return await Task.FromResult(CommandResponse.Failed(cmdId, ex.Message));
            }
        }

        /// <summary>
        /// Handles push_cleanup command (best-effort cleanup of source after PUSH copy)
        /// </summary>
        private async Task<CommandResponse> HandlePushCleanupAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (string.IsNullOrEmpty(request.SourcePath))
            {
                return CommandResponse.Failed(cmdId, "push_cleanup requires source_path");
            }

            bool flatten = request.Parameters?.ContainsKey("flatten") == true
                && Convert.ToBoolean(request.Parameters["flatten"]);
            List<string> ignoreMasks = null;
            if (request.Parameters?.ContainsKey("ignore_masks") == true)
            {
                ignoreMasks = ParseIgnoreMasks(request.Parameters["ignore_masks"]);
            }

            try
            {
                var result = await _fileOps.PushCleanupAsync(request.SourcePath, flatten, ignoreMasks);

                int failureCount = result.ContainsKey("failure_count") ? Convert.ToInt32(result["failure_count"]) : 0;
                string message = failureCount > 0
                    ? $"Cleanup completed with {failureCount} failure(s)"
                    : "Cleanup completed successfully";

                var response = CommandResponse.Success(cmdId, message);
                response.ErrorDetails = result;
                return response;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Push cleanup failed");
                // Always return success for cleanup (best-effort)
                return CommandResponse.Success(cmdId, $"Cleanup failed (non-fatal): {ex.Message}");
            }
        }

        /// <summary>
        /// Parses ignore_masks from a parameter value (supports JSON array or comma-separated string)
        /// </summary>
        private List<string> ParseIgnoreMasks(object value)
        {
            if (value == null) return null;

            var masks = new List<string>();

            if (value is JArray jArray)
            {
                foreach (var item in jArray)
                {
                    var mask = item.ToString().Trim();
                    if (!string.IsNullOrEmpty(mask))
                        masks.Add(mask);
                }
            }
            else
            {
                // Treat as comma-separated string
                var str = value.ToString();
                foreach (var mask in str.Split(','))
                {
                    var trimmed = mask.Trim();
                    if (!string.IsNullOrEmpty(trimmed))
                        masks.Add(trimmed);
                }
            }

            return masks.Count > 0 ? masks : null;
        }

        /// <summary>
        /// Handles reload_config command (admin - reloads configuration from source)
        /// </summary>
        private async Task<CommandResponse> HandleReloadConfigAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;
            Logger.Info("Reload config command received");

            try
            {
                // TODO: Implement configuration reload logic
                // This would re-read from Windows Credential Manager or config file

                return await Task.FromResult(CommandResponse.Success(cmdId, "Configuration reload not yet implemented - restart service to reload config"));
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Reload config operation failed");
                return await Task.FromResult(CommandResponse.Failed(cmdId, ex.Message));
            }
        }
    }
}
