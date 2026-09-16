using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using NLog;
using FileManagerWorker.Models;

namespace FileManagerWorker
{
    /// <summary>
    /// Handles command parsing and execution.
    /// Failed commands are undone by the Central API (see operation_service.py), not here.
    /// </summary>
    public class CommandHandler
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();
        private readonly FileOperations _fileOps;
        private readonly ApiClient _apiClient;

        public CommandHandler(FileOperations fileOps, ApiClient apiClient)
        {
            _fileOps = fileOps;
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

                    case "validate_dir":
                        return await HandleValidateDirAsync(request);

                    case "fetch_file":
                        return await HandleFetchFileAsync(request);

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
        /// Handles copy command
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

            try
            {
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

                // Extract file count and size from result
                int? fileCount = result?.ContainsKey("file_count") == true ? Convert.ToInt32(result["file_count"]) : null;
                long? totalSize = result?.ContainsKey("total_size_bytes") == true ? Convert.ToInt64(result["total_size_bytes"]) : null;

                return CommandResponse.Success(cmdId, "Copy completed successfully", fileCount, totalSize);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Copy operation failed");
                return CommandResponse.Failed(cmdId, ex.Message, ErrorDetails(ex));
            }
        }

        /// <summary>
        /// Handles move command
        /// </summary>
        private async Task<CommandResponse> HandleMoveAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (string.IsNullOrEmpty(request.SourcePath) || string.IsNullOrEmpty(request.DestPath))
            {
                return CommandResponse.Failed(cmdId, "Move requires source_path and dest_path");
            }

            try
            {
                var result = await _fileOps.MoveAsync(request.SourcePath, request.DestPath);

                // Extract file count and size from result
                int? fileCount = result?.ContainsKey("file_count") == true ? Convert.ToInt32(result["file_count"]) : null;
                long? totalSize = result?.ContainsKey("total_size_bytes") == true ? Convert.ToInt64(result["total_size_bytes"]) : null;

                return CommandResponse.Success(cmdId, "Move completed successfully", fileCount, totalSize);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Move operation failed");
                return CommandResponse.Failed(cmdId, ex.Message, ErrorDetails(ex));
            }
        }

        /// <summary>
        /// Handles delete command
        /// </summary>
        private async Task<CommandResponse> HandleDeleteAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (string.IsNullOrEmpty(request.SourcePath))
            {
                return CommandResponse.Failed(cmdId, "Delete requires source_path");
            }

            try
            {
                // Execute delete (always recursive for directories)
                var result = await _fileOps.DeleteAsync(request.SourcePath);

                int? fileCount = result?.ContainsKey("file_count") == true ? Convert.ToInt32(result["file_count"]) : null;

                return CommandResponse.Success(cmdId, "Delete completed successfully", fileCount);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Delete operation failed");
                return CommandResponse.Failed(cmdId, ex.Message, ErrorDetails(ex));
            }
        }

        /// <summary>
        /// Handles mkdir command
        /// </summary>
        private async Task<CommandResponse> HandleMkdirAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            if (string.IsNullOrEmpty(request.SourcePath))
            {
                return CommandResponse.Failed(cmdId, "Mkdir requires source_path");
            }

            try
            {
                await _fileOps.MkdirAsync(request.SourcePath);
                return CommandResponse.Success(cmdId, "Directory created successfully");
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Mkdir operation failed");
                return CommandResponse.Failed(cmdId, ex.Message, ErrorDetails(ex));
            }
        }

        private static Dictionary<string, object> ErrorDetails(Exception ex)
        {
            return new Dictionary<string, object> { { "error_type", ex.GetType().Name } };
        }

        /// <summary>
        /// Handles list command (read-only)
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
        /// Handles validate_dir command (read-only): inspects the top level of a
        /// directory for the PUSH/UPDATE content rules and returns both the verdict
        /// and the full basename list used for PIM signalling.
        /// </summary>
        private async Task<CommandResponse> HandleValidateDirAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            // Accept the path from source_path, falling back to a "path" parameter
            // so the command matches both the list and copy call conventions.
            var path = request.SourcePath;
            if (string.IsNullOrEmpty(path) && request.Parameters != null
                && request.Parameters.ContainsKey("path"))
            {
                path = request.Parameters["path"]?.ToString();
            }

            if (string.IsNullOrEmpty(path))
            {
                return CommandResponse.Failed(cmdId, "validate_dir requires source_path or a 'path' parameter");
            }

            var allowedExtensions = new List<string>();
            if (request.Parameters != null && request.Parameters.ContainsKey("allowed_extensions"))
            {
                var raw = request.Parameters["allowed_extensions"];
                if (raw is Newtonsoft.Json.Linq.JArray jArray)
                {
                    foreach (var token in jArray)
                    {
                        var v = token?.ToString();
                        if (!string.IsNullOrWhiteSpace(v)) allowedExtensions.Add(v);
                    }
                }
                else if (raw is System.Collections.IEnumerable enumerable && !(raw is string))
                {
                    foreach (var item in enumerable)
                    {
                        var v = item?.ToString();
                        if (!string.IsNullOrWhiteSpace(v)) allowedExtensions.Add(v);
                    }
                }
                else if (raw != null)
                {
                    foreach (var v in raw.ToString().Split(','))
                    {
                        if (!string.IsNullOrWhiteSpace(v)) allowedExtensions.Add(v.Trim());
                    }
                }
            }

            bool verifyContent = true;
            if (request.Parameters != null && request.Parameters.ContainsKey("verify_content"))
            {
                bool parsed;
                if (bool.TryParse(request.Parameters["verify_content"]?.ToString(), out parsed))
                {
                    verifyContent = parsed;
                }
            }

            try
            {
                var result = await _fileOps.ValidateDirectoryAsync(path, allowedExtensions, verifyContent);

                var response = CommandResponse.Success(
                    cmdId,
                    "Directory validation completed",
                    result.ContainsKey("total_files") ? Convert.ToInt32(result["total_files"]) : (int?)null,
                    result.ContainsKey("total_size_bytes") ? Convert.ToInt64(result["total_size_bytes"]) : (long?)null
                );
                // Full result travels in ErrorDetails, matching HandleListAsync.
                response.ErrorDetails = result;
                return response;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Directory validation failed");
                return CommandResponse.Failed(cmdId, ex.Message);
            }
        }

        /// <summary>
        /// Handles fetch_file command: downloads a file uploaded through the WebUI from the
        /// Central API and places it at dest_path, which must not exist yet. The download
        /// is verified before the share is touched.
        /// </summary>
        private async Task<CommandResponse> HandleFetchFileAsync(CommandRequest request)
        {
            int cmdId = request.CommandId.Value;

            var parameters = request.Parameters ?? new Dictionary<string, object>();
            var destination = request.DestPath;
            var url = parameters.ContainsKey("url") ? parameters["url"]?.ToString() : null;
            var expectedSha256 = parameters.ContainsKey("sha256") ? parameters["sha256"]?.ToString() : null;
            var sizeValue = parameters.ContainsKey("size_bytes") ? parameters["size_bytes"] : null;

            if (string.IsNullOrEmpty(destination) || string.IsNullOrEmpty(url)
                || string.IsNullOrEmpty(expectedSha256) || sizeValue == null)
            {
                return CommandResponse.Failed(cmdId, "fetch_file requires dest_path and 'url', 'sha256', 'size_bytes' parameters");
            }

            // Only paths on the configured API: an absolute URL in a command could point the
            // worker (and its client certificate) at another host.
            if (!url.StartsWith("/api/", StringComparison.Ordinal))
            {
                return CommandResponse.Failed(cmdId, "fetch_file 'url' must be a relative path starting with /api/");
            }

            if (!Regex.IsMatch(expectedSha256, "^[0-9a-fA-F]{64}$"))
            {
                return CommandResponse.Failed(cmdId, "fetch_file 'sha256' must be 64 hex characters");
            }

            long expectedSize;
            try
            {
                expectedSize = Convert.ToInt64(sizeValue);
            }
            catch (Exception ex) when (ex is FormatException || ex is InvalidCastException || ex is OverflowException)
            {
                return CommandResponse.Failed(cmdId, "fetch_file 'size_bytes' must be an integer");
            }

            if (expectedSize < 0)
            {
                return CommandResponse.Failed(cmdId, "fetch_file 'size_bytes' must not be negative");
            }

            // The query string carries the signed token, a credential: log the path only.
            var urlPath = url.Split('?')[0];
            var tempFile = Path.Combine(Path.GetTempPath(), "FileManagerWorker_Downloads", Guid.NewGuid().ToString("N") + ".tmp");
            var stopwatch = Stopwatch.StartNew();

            try
            {
                _fileOps.EnsureAllowedPath(destination);

                // Downloaded as the service account: share credentials are for the shares only.
                Directory.CreateDirectory(Path.GetDirectoryName(tempFile));
                var download = await _apiClient.DownloadToFileAsync(url, tempFile, CancellationToken.None);

                if (download.Bytes != expectedSize
                    || !string.Equals(download.Sha256, expectedSha256, StringComparison.OrdinalIgnoreCase))
                {
                    Logger.Error("fetch_file {0} for {1} failed verification: expected {2} bytes / {3}, got {4} bytes / {5}",
                        urlPath, destination, expectedSize, expectedSha256, download.Bytes, download.Sha256);

                    return CommandResponse.Failed(cmdId,
                        $"Downloaded file failed size/SHA-256 verification: expected {expectedSize} bytes / {expectedSha256}, " +
                        $"got {download.Bytes} bytes / {download.Sha256}",
                        new Dictionary<string, object> { { "error_type", "VerificationFailed" } });
                }

                await _fileOps.ReceiveFileAsync(destination, tempFile);

                Logger.Info("fetch_file {0} -> {1}: {2} bytes, SHA-256 {3}, {4} ms",
                    urlPath, destination, download.Bytes, download.Sha256, stopwatch.ElapsedMilliseconds);

                return CommandResponse.Success(cmdId, "File fetched", fileCount: 1, totalSizeBytes: download.Bytes);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "fetch_file {0} -> {1} failed after {2} ms", urlPath, destination, stopwatch.ElapsedMilliseconds);

                return CommandResponse.Failed(cmdId, ex.Message, ErrorDetails(ex));
            }
            finally
            {
                try
                {
                    if (File.Exists(tempFile))
                    {
                        File.Delete(tempFile);
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warn("Could not remove downloaded temp file {0}: {1}", tempFile, ex.Message);
                }
            }
        }

        /// <summary>
        /// Handles search command (read-only)
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
        /// Handles info command (read-only)
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
