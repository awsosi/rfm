using System;
using System.Collections.Generic;
using System.Threading.Tasks;
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
                return CommandResponse.Failed("unknown", "Request is null");
            }

            Logger.Info("Executing command: {0} (ID: {1})", request.Command, request.CommandId);

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

                    default:
                        return CommandResponse.Failed(request.CommandId, $"Unknown command: {request.Command}");
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Command execution failed: {0}", request.CommandId);
                return CommandResponse.Failed(request.CommandId, ex.Message);
            }
        }

        /// <summary>
        /// Handles copy command with rollback support
        /// </summary>
        private async Task<CommandResponse> HandleCopyAsync(CommandRequest request)
        {
            if (!request.Parameters.ContainsKey("source") || !request.Parameters.ContainsKey("destination"))
            {
                return CommandResponse.Failed(request.CommandId, "Copy requires 'source' and 'destination' parameters");
            }

            var source = request.Parameters["source"];
            var destination = request.Parameters["destination"];

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
                        await _apiClient.SendProgressAsync(request.CommandId, percent);
                    }
                });

                // Execute copy
                var result = await _fileOps.CopyAsync(source, destination, progress);

                // Success - cleanup backups
                _rollbackManager.CleanupBackups(backups);

                return CommandResponse.Success(request.CommandId, result);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Copy operation failed");

                // Attempt rollback
                var rollbackSuccess = _rollbackManager.RestoreAll(backups);
                var rollbackStatus = rollbackSuccess ? "success" : "failed";

                return CommandResponse.Failed(request.CommandId, ex.Message, rollbackStatus);
            }
        }

        /// <summary>
        /// Handles move command with rollback support
        /// </summary>
        private async Task<CommandResponse> HandleMoveAsync(CommandRequest request)
        {
            if (!request.Parameters.ContainsKey("source") || !request.Parameters.ContainsKey("destination"))
            {
                return CommandResponse.Failed(request.CommandId, "Move requires 'source' and 'destination' parameters");
            }

            var source = request.Parameters["source"];
            var destination = request.Parameters["destination"];

            List<RollbackContext> backups = null;

            try
            {
                // Create backups of both source and destination
                backups = _rollbackManager.CreateBackups(source, destination);

                // Execute move
                var result = await _fileOps.MoveAsync(source, destination);

                // Success - cleanup backups
                _rollbackManager.CleanupBackups(backups);

                return CommandResponse.Success(request.CommandId, result);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Move operation failed");

                // Attempt rollback
                var rollbackSuccess = _rollbackManager.RestoreAll(backups);
                var rollbackStatus = rollbackSuccess ? "success" : "failed";

                return CommandResponse.Failed(request.CommandId, ex.Message, rollbackStatus);
            }
        }

        /// <summary>
        /// Handles delete command with rollback support
        /// </summary>
        private async Task<CommandResponse> HandleDeleteAsync(CommandRequest request)
        {
            if (!request.Parameters.ContainsKey("path"))
            {
                return CommandResponse.Failed(request.CommandId, "Delete requires 'path' parameter");
            }

            var path = request.Parameters["path"];

            RollbackContext backup = null;

            try
            {
                // Create backup before deletion
                backup = _rollbackManager.CreateBackup(path);

                // Execute delete
                var result = await _fileOps.DeleteAsync(path);

                // Success - cleanup backup
                _rollbackManager.CleanupBackup(backup);

                return CommandResponse.Success(request.CommandId, result);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Delete operation failed");

                // Attempt rollback
                var rollbackSuccess = _rollbackManager.Restore(backup);
                var rollbackStatus = rollbackSuccess ? "success" : "failed";

                return CommandResponse.Failed(request.CommandId, ex.Message, rollbackStatus);
            }
        }

        /// <summary>
        /// Handles mkdir command with rollback support
        /// </summary>
        private async Task<CommandResponse> HandleMkdirAsync(CommandRequest request)
        {
            if (!request.Parameters.ContainsKey("path"))
            {
                return CommandResponse.Failed(request.CommandId, "Mkdir requires 'path' parameter");
            }

            var path = request.Parameters["path"];

            RollbackContext backup = null;

            try
            {
                // Create backup (will note if directory didn't exist)
                backup = _rollbackManager.CreateBackup(path);

                // Execute mkdir
                var result = await _fileOps.MkdirAsync(path);

                // Success - cleanup backup
                _rollbackManager.CleanupBackup(backup);

                return CommandResponse.Success(request.CommandId, result);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Mkdir operation failed");

                // Attempt rollback
                var rollbackSuccess = _rollbackManager.Restore(backup);
                var rollbackStatus = rollbackSuccess ? "success" : "failed";

                return CommandResponse.Failed(request.CommandId, ex.Message, rollbackStatus);
            }
        }

        /// <summary>
        /// Handles list command (read-only, no rollback needed)
        /// </summary>
        private async Task<CommandResponse> HandleListAsync(CommandRequest request)
        {
            if (!request.Parameters.ContainsKey("path"))
            {
                return CommandResponse.Failed(request.CommandId, "List requires 'path' parameter");
            }

            var path = request.Parameters["path"];
            var recursive = request.Parameters.ContainsKey("recursive") &&
                           bool.TryParse(request.Parameters["recursive"], out var rec) && rec;

            try
            {
                var result = await _fileOps.ListAsync(path, recursive);
                return CommandResponse.Success(request.CommandId, result);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "List operation failed");
                return CommandResponse.Failed(request.CommandId, ex.Message);
            }
        }

        /// <summary>
        /// Handles search command (read-only, no rollback needed)
        /// </summary>
        private async Task<CommandResponse> HandleSearchAsync(CommandRequest request)
        {
            if (!request.Parameters.ContainsKey("path") || !request.Parameters.ContainsKey("pattern"))
            {
                return CommandResponse.Failed(request.CommandId, "Search requires 'path' and 'pattern' parameters");
            }

            var path = request.Parameters["path"];
            var pattern = request.Parameters["pattern"];
            var recursive = !request.Parameters.ContainsKey("recursive") ||
                           (bool.TryParse(request.Parameters["recursive"], out var rec) && rec);

            try
            {
                var result = await _fileOps.SearchAsync(path, pattern, recursive);
                return CommandResponse.Success(request.CommandId, result);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Search operation failed");
                return CommandResponse.Failed(request.CommandId, ex.Message);
            }
        }

        /// <summary>
        /// Handles info command (read-only, no rollback needed)
        /// </summary>
        private async Task<CommandResponse> HandleInfoAsync(CommandRequest request)
        {
            if (!request.Parameters.ContainsKey("path"))
            {
                return CommandResponse.Failed(request.CommandId, "Info requires 'path' parameter");
            }

            var path = request.Parameters["path"];

            try
            {
                var result = await _fileOps.GetInfoAsync(path);
                return CommandResponse.Success(request.CommandId, result);
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Info operation failed");
                return CommandResponse.Failed(request.CommandId, ex.Message);
            }
        }
    }
}
