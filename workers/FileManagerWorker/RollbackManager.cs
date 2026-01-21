using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using NLog;

namespace FileManagerWorker
{
    /// <summary>
    /// Manages rollback operations for failed file operations
    /// </summary>
    public class RollbackManager
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();
        private readonly string _tempDirectory;

        public RollbackManager()
        {
            _tempDirectory = Path.Combine(Path.GetTempPath(), "FileManagerWorker_Rollback");
            Directory.CreateDirectory(_tempDirectory);
        }

        /// <summary>
        /// Creates a backup before performing an operation
        /// </summary>
        public RollbackContext CreateBackup(string path)
        {
            try
            {
                var context = new RollbackContext
                {
                    OriginalPath = path,
                    BackupId = Guid.NewGuid().ToString("N"),
                    Timestamp = DateTime.UtcNow
                };

                if (File.Exists(path))
                {
                    context.WasFile = true;
                    context.BackupPath = Path.Combine(_tempDirectory, context.BackupId);
                    File.Copy(path, context.BackupPath, true);
                    Logger.Debug("File backup created: {0} -> {1}", path, context.BackupPath);
                }
                else if (Directory.Exists(path))
                {
                    context.WasDirectory = true;
                    context.BackupPath = Path.Combine(_tempDirectory, context.BackupId);
                    CopyDirectory(path, context.BackupPath);
                    Logger.Debug("Directory backup created: {0} -> {1}", path, context.BackupPath);
                }
                else
                {
                    context.DidNotExist = true;
                    Logger.Debug("Path did not exist, no backup needed: {0}", path);
                }

                return context;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to create backup for: {0}", path);
                throw;
            }
        }

        /// <summary>
        /// Creates backups for multiple paths
        /// </summary>
        public List<RollbackContext> CreateBackups(params string[] paths)
        {
            var contexts = new List<RollbackContext>();

            foreach (var path in paths)
            {
                try
                {
                    contexts.Add(CreateBackup(path));
                }
                catch (Exception ex)
                {
                    Logger.Error(ex, "Failed to backup {0}, rolling back previous backups", path);
                    // Rollback any backups we've already created
                    foreach (var ctx in contexts)
                    {
                        CleanupBackup(ctx);
                    }
                    throw;
                }
            }

            return contexts;
        }

        /// <summary>
        /// Restores from backup
        /// </summary>
        public bool Restore(RollbackContext context)
        {
            try
            {
                if (context == null)
                {
                    Logger.Warn("Rollback context is null");
                    return false;
                }

                Logger.Info("Restoring from backup: {0}", context.OriginalPath);

                // Remove any new files/directories that were created
                if (File.Exists(context.OriginalPath))
                {
                    File.Delete(context.OriginalPath);
                    Logger.Debug("Deleted modified file: {0}", context.OriginalPath);
                }
                else if (Directory.Exists(context.OriginalPath))
                {
                    Directory.Delete(context.OriginalPath, true);
                    Logger.Debug("Deleted modified directory: {0}", context.OriginalPath);
                }

                // Restore from backup
                if (context.WasFile && !string.IsNullOrEmpty(context.BackupPath))
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(context.OriginalPath));
                    File.Copy(context.BackupPath, context.OriginalPath, true);
                    Logger.Info("File restored from backup: {0}", context.OriginalPath);
                }
                else if (context.WasDirectory && !string.IsNullOrEmpty(context.BackupPath))
                {
                    CopyDirectory(context.BackupPath, context.OriginalPath);
                    Logger.Info("Directory restored from backup: {0}", context.OriginalPath);
                }
                else if (context.DidNotExist)
                {
                    Logger.Info("Path was created during operation, removal is the rollback: {0}", context.OriginalPath);
                }

                return true;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to restore from backup: {0}", context?.OriginalPath);
                return false;
            }
        }

        /// <summary>
        /// Restores multiple backups
        /// </summary>
        public bool RestoreAll(List<RollbackContext> contexts)
        {
            if (contexts == null || contexts.Count == 0)
            {
                return true;
            }

            Logger.Info("Rolling back {0} operations", contexts.Count);

            var allSuccessful = true;

            // Restore in reverse order
            for (int i = contexts.Count - 1; i >= 0; i--)
            {
                if (!Restore(contexts[i]))
                {
                    allSuccessful = false;
                }
            }

            return allSuccessful;
        }

        /// <summary>
        /// Cleans up backup after successful operation
        /// </summary>
        public void CleanupBackup(RollbackContext context)
        {
            try
            {
                if (context != null && !string.IsNullOrEmpty(context.BackupPath))
                {
                    if (File.Exists(context.BackupPath))
                    {
                        File.Delete(context.BackupPath);
                    }
                    else if (Directory.Exists(context.BackupPath))
                    {
                        Directory.Delete(context.BackupPath, true);
                    }

                    Logger.Debug("Backup cleaned up: {0}", context.BackupPath);
                }
            }
            catch (Exception ex)
            {
                Logger.Warn(ex, "Failed to cleanup backup: {0}", context?.BackupPath);
            }
        }

        /// <summary>
        /// Cleans up multiple backups
        /// </summary>
        public void CleanupBackups(List<RollbackContext> contexts)
        {
            if (contexts == null)
            {
                return;
            }

            foreach (var context in contexts)
            {
                CleanupBackup(context);
            }
        }

        /// <summary>
        /// Cleans up old backup files (older than 24 hours)
        /// </summary>
        public void CleanupOldBackups()
        {
            try
            {
                if (!Directory.Exists(_tempDirectory))
                {
                    return;
                }

                var cutoffTime = DateTime.UtcNow.AddHours(-24);
                var files = Directory.GetFiles(_tempDirectory);
                var directories = Directory.GetDirectories(_tempDirectory);

                foreach (var file in files)
                {
                    if (File.GetCreationTimeUtc(file) < cutoffTime)
                    {
                        File.Delete(file);
                        Logger.Debug("Deleted old backup file: {0}", file);
                    }
                }

                foreach (var dir in directories)
                {
                    if (Directory.GetCreationTimeUtc(dir) < cutoffTime)
                    {
                        Directory.Delete(dir, true);
                        Logger.Debug("Deleted old backup directory: {0}", dir);
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Warn(ex, "Error cleaning up old backups");
            }
        }

        /// <summary>
        /// Copies a directory recursively
        /// </summary>
        private void CopyDirectory(string sourceDir, string destDir)
        {
            Directory.CreateDirectory(destDir);

            foreach (var file in Directory.GetFiles(sourceDir))
            {
                var destFile = Path.Combine(destDir, Path.GetFileName(file));
                File.Copy(file, destFile, true);
            }

            foreach (var subDir in Directory.GetDirectories(sourceDir))
            {
                var destSubDir = Path.Combine(destDir, Path.GetFileName(subDir));
                CopyDirectory(subDir, destSubDir);
            }
        }
    }

    /// <summary>
    /// Context information for rollback operations
    /// </summary>
    public class RollbackContext
    {
        public string OriginalPath { get; set; }
        public string BackupPath { get; set; }
        public string BackupId { get; set; }
        public DateTime Timestamp { get; set; }
        public bool WasFile { get; set; }
        public bool WasDirectory { get; set; }
        public bool DidNotExist { get; set; }
    }
}
