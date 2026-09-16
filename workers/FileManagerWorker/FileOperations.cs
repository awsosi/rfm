using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using NLog;

namespace FileManagerWorker
{
    /// <summary>
    /// Implements file operations: copy, move, delete, mkdir, list, search
    /// </summary>
    public class FileOperations
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();
        private string _pathAPrefix;
        private string _pathBPrefix;
        private string _pathCPrefix;
        private string _sambaUsername;
        private string _sambaPassword;

        /// <summary>
        /// Path A prefix - can be updated by admin
        /// </summary>
        public string PathAPrefix
        {
            get => _pathAPrefix;
            set
            {
                Logger.Info("PathAPrefix changed from '{0}' to '{1}'", _pathAPrefix, value);
                _pathAPrefix = value;
            }
        }

        /// <summary>
        /// Path B prefix - can be updated by admin
        /// </summary>
        public string PathBPrefix
        {
            get => _pathBPrefix;
            set
            {
                Logger.Info("PathBPrefix changed from '{0}' to '{1}'", _pathBPrefix, value);
                _pathBPrefix = value;
            }
        }

        /// <summary>
        /// Path C prefix - can be updated by admin
        /// </summary>
        public string PathCPrefix
        {
            get => _pathCPrefix;
            set
            {
                Logger.Info("PathCPrefix changed from '{0}' to '{1}'", _pathCPrefix, value);
                _pathCPrefix = value;
            }
        }

        public FileOperations(string pathAPrefix, string pathBPrefix, string pathCPrefix, string sambaUsername = null, string sambaPassword = null)
        {
            _pathAPrefix = pathAPrefix;
            _pathBPrefix = pathBPrefix;
            _pathCPrefix = pathCPrefix;
            _sambaUsername = sambaUsername;
            _sambaPassword = sambaPassword;

            // Validate that credentials are provided for network shares
            var networkPaths = new List<string>();
            if (IsNetworkPath(pathAPrefix)) networkPaths.Add($"PathA: {pathAPrefix}");
            if (IsNetworkPath(pathBPrefix)) networkPaths.Add($"PathB: {pathBPrefix}");
            if (IsNetworkPath(pathCPrefix)) networkPaths.Add($"PathC: {pathCPrefix}");

            if (networkPaths.Count > 0 && string.IsNullOrWhiteSpace(_sambaUsername))
            {
                Logger.Error("Cannot start: network share paths ({0}) require samba credentials, and the service account " +
                             "cannot access network shares by default. Run 'FileManagerWorker.exe /config' as Administrator, " +
                             "enter the credentials (e.g. DOMAIN\\username), then restart the service.",
                             string.Join("; ", networkPaths));
                throw new InvalidOperationException(
                    $"Samba credentials required for network share access. " +
                    $"Run 'FileManagerWorker.exe /config' to configure credentials.");
            }

            if (!string.IsNullOrWhiteSpace(_sambaUsername))
            {
                Logger.Info("File operations will use impersonation with user: {0}", _sambaUsername);
            }
            else
            {
                Logger.Info("File operations will use Network Service account permissions");
            }
        }

        /// <summary>
        /// Checks if a path is a network share (UNC path)
        /// </summary>
        private bool IsNetworkPath(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return false;
            }

            // UNC paths start with \\
            return path.StartsWith(@"\\") || path.StartsWith("//");
        }

        /// <summary>
        /// Execute action with samba impersonation if credentials are configured
        /// </summary>
        private void LogImpersonationFailure(Exception ex)
        {
            Logger.Error("Impersonation failed for user {0}: {1}. Likely causes: invalid samba credentials, a disabled or " +
                         "locked account, an expired password, or an unreachable domain controller. Verify with " +
                         "'FileManagerWorker.exe /config' as Administrator.",
                         _sambaUsername, ex.Message);
        }

        private T ExecuteWithImpersonation<T>(Func<T> action)
        {
            if (!string.IsNullOrWhiteSpace(_sambaUsername))
            {
                Logger.Debug("Executing with impersonation as user: {0}", _sambaUsername);
                try
                {
                    return WindowsImpersonation.ExecuteWithImpersonation(_sambaUsername, _sambaPassword, action);
                }
                catch (InvalidOperationException ex)
                {
                    LogImpersonationFailure(ex);
                    throw;
                }
            }
            else
            {
                // No impersonation - use current process identity (Network Service)
                Logger.Debug("Executing without impersonation (using Network Service account)");
                return action();
            }
        }

        /// <summary>
        /// Execute action with samba impersonation if credentials are configured (void version)
        /// </summary>
        private void ExecuteWithImpersonation(Action action)
        {
            if (!string.IsNullOrWhiteSpace(_sambaUsername))
            {
                Logger.Debug("Executing with impersonation as user: {0}", _sambaUsername);
                try
                {
                    WindowsImpersonation.ExecuteWithImpersonation(_sambaUsername, _sambaPassword, action);
                }
                catch (InvalidOperationException ex)
                {
                    LogImpersonationFailure(ex);
                    throw;
                }
            }
            else
            {
                // No impersonation - use current process identity (Network Service)
                Logger.Debug("Executing without impersonation (using Network Service account)");
                action();
            }
        }

        /// <summary>
        /// Resolves a path with A:, B:, or C: prefix to actual file system path
        /// </summary>
        private string ResolvePath(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                throw new ArgumentException("Path cannot be empty or null");
            }

            // Check if path starts with valid prefix
            if (path.StartsWith("A:", StringComparison.OrdinalIgnoreCase))
            {
                var relativePath = path.Length > 2 ? path.Substring(2).TrimStart('\\', '/') : string.Empty;
                return Path.Combine(_pathAPrefix, relativePath);
            }
            else if (path.StartsWith("B:", StringComparison.OrdinalIgnoreCase))
            {
                var relativePath = path.Length > 2 ? path.Substring(2).TrimStart('\\', '/') : string.Empty;
                return Path.Combine(_pathBPrefix, relativePath);
            }
            else if (path.StartsWith("C:", StringComparison.OrdinalIgnoreCase))
            {
                var relativePath = path.Length > 2 ? path.Substring(2).TrimStart('\\', '/') : string.Empty;
                return Path.Combine(_pathCPrefix, relativePath);
            }
            else
            {
                throw new ArgumentException($"Path must start with A:, B:, or C: prefix. Got: {path}");
            }
        }

        /// <summary>
        /// Validates that path is within allowed boundaries and no path traversal
        /// </summary>
        private void ValidatePath(string resolvedPath)
        {
            var fullPath = Path.GetFullPath(resolvedPath);

            // Ensure resolved path is within allowed prefixes
            if (!fullPath.StartsWith(_pathAPrefix, StringComparison.OrdinalIgnoreCase) &&
                !fullPath.StartsWith(_pathBPrefix, StringComparison.OrdinalIgnoreCase) &&
                !fullPath.StartsWith(_pathCPrefix, StringComparison.OrdinalIgnoreCase))
            {
                throw new UnauthorizedAccessException($"Path is outside allowed boundaries: {fullPath}");
            }

			// Additional check: ensure no system directories are accessed
			var systemDirs = new[] { "Windows", "System32", "Program Files", "ProgramData" };
			foreach (var sysDir in systemDirs)
			{
				if (fullPath.IndexOf(sysDir, StringComparison.OrdinalIgnoreCase) >= 0)
				{
					Logger.Warn("Attempted access to system directory: {0}", fullPath);
					throw new UnauthorizedAccessException($"Access to system directories is forbidden: {fullPath}");
				}
			}
		}

        /// <summary>
        /// Copies file or directory
        /// </summary>
        public async Task<Dictionary<string, object>> CopyAsync(
            string source, string destination, IProgress<int> progress = null,
            bool flatten = false, List<string> ignoreMasks = null)
        {
            var resolvedSource = ResolvePath(source);
            var resolvedDest = ResolvePath(destination);

            ValidatePath(resolvedSource);
            ValidatePath(resolvedDest);

            Logger.Info("Copying from {0} to {1} (flatten={2}, ignoreMasks={3})",
                resolvedSource, resolvedDest, flatten,
                ignoreMasks != null ? string.Join(",", ignoreMasks) : "none");

            var result = new Dictionary<string, object>
            {
                { "source", source },
                { "destination", destination }
            };

            return await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    if (File.Exists(resolvedSource))
                    {
                        // Single file: check ignore mask
                        if (ignoreMasks != null && MatchesIgnoreMask(Path.GetFileName(resolvedSource), ignoreMasks))
                        {
                            Logger.Info("File {0} matches ignore mask, skipping copy", resolvedSource);
                            result["type"] = "file";
                            result["file_count"] = 0;
                            result["total_size_bytes"] = 0L;
                            return result;
                        }

                        // Copy single file
                        Directory.CreateDirectory(Path.GetDirectoryName(resolvedDest));
                        File.Copy(resolvedSource, resolvedDest, true);

                        var fileSize = new FileInfo(resolvedDest).Length;
                        result["type"] = "file";
                        result["size"] = fileSize;
                        // Backend expects these keys
                        result["file_count"] = 1;
                        result["total_size_bytes"] = fileSize;
                        Logger.Info("File copied successfully: {0} bytes", fileSize);
                    }
                    else if (Directory.Exists(resolvedSource))
                    {
                        // Copy directory (includes validation, respects flatten and ignoreMasks)
                        var filesCopied = CopyDirectorySync(resolvedSource, resolvedDest, progress, flatten, ignoreMasks);

                        // Calculate total size of all files copied
                        long totalSize = 0;
                        var searchOption = flatten ? SearchOption.TopDirectoryOnly : SearchOption.AllDirectories;
                        var destFiles = Directory.Exists(resolvedDest)
                            ? Directory.GetFiles(resolvedDest, "*", searchOption)
                            : new string[0];
                        foreach (var file in destFiles)
                        {
                            totalSize += new FileInfo(file).Length;
                        }

                        result["type"] = "directory";
                        // Keep legacy key for backward compatibility
                        result["filesCopied"] = filesCopied;
                        // Backend expects these keys
                        result["file_count"] = filesCopied;
                        result["total_size_bytes"] = totalSize;

                        Logger.Info("Directory copied successfully: {0} files, {1} bytes", filesCopied, totalSize);
                    }
                    else
                    {
                        throw new FileNotFoundException($"Source not found: {resolvedSource}");
                    }

                    return result;
                });
            });
        }

        /// <summary>
        /// Copies directory recursively with progress reporting (synchronous for impersonation).
        /// Supports flatten mode (root-level files only) and ignore masks (skip matching files).
        /// </summary>
        private int CopyDirectorySync(string sourceDir, string destDir, IProgress<int> progress = null,
            bool flatten = false, List<string> ignoreMasks = null)
        {
            // Normalize paths to full paths to ensure consistent path calculations
            sourceDir = Path.GetFullPath(sourceDir);
            destDir = Path.GetFullPath(destDir);

            Logger.Info("CopyDirectorySync: Copying '{0}' to '{1}' (flatten={2}, ignoreMasks={3})",
                sourceDir, destDir, flatten,
                ignoreMasks != null ? string.Join(",", ignoreMasks) : "none");

            try
            {
                // Create destination root directory
                Directory.CreateDirectory(destDir);

                // Determine search scope based on flatten
                var searchOption = flatten ? SearchOption.TopDirectoryOnly : SearchOption.AllDirectories;

                // Get source files based on flatten mode
                var allSourceFiles = Directory.GetFiles(sourceDir, "*", searchOption);

                // Filter out ignored files
                if (ignoreMasks != null && ignoreMasks.Count > 0)
                {
                    allSourceFiles = allSourceFiles
                        .Where(f => !MatchesIgnoreMask(Path.GetFileName(f), ignoreMasks))
                        .ToArray();
                    Logger.Info("CopyDirectorySync: After ignore mask filtering, {0} files to copy", allSourceFiles.Length);
                }

                if (!flatten)
                {
                    // Get ALL subdirectories for full recursive copy
                    var allSourceDirs = Directory.GetDirectories(sourceDir, "*", SearchOption.AllDirectories);

                    Logger.Info("CopyDirectorySync: Found {0} subdirectories and {1} files to copy",
                        allSourceDirs.Length, allSourceFiles.Length);

                    // Create ALL subdirectories first (including empty ones)
                    var createdDirs = new List<string>();
                    foreach (var dir in allSourceDirs)
                    {
                        var normalizedSourceDir = sourceDir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                        var relativePath = dir.Substring(normalizedSourceDir.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                        var destDirPath = Path.Combine(destDir, relativePath);

                        Logger.Debug("Creating directory: {0} (from {1})", destDirPath, relativePath);
                        Directory.CreateDirectory(destDirPath);
                        createdDirs.Add(destDirPath);
                    }

                    Logger.Info("CopyDirectorySync: Created {0} subdirectories", createdDirs.Count);

                    // Validate all directories were created
                    if (createdDirs.Count != allSourceDirs.Length)
                    {
                        throw new IOException(
                            $"Directory creation validation failed: Expected {allSourceDirs.Length} directories, " +
                            $"but only created {createdDirs.Count}");
                    }
                }
                else
                {
                    Logger.Info("CopyDirectorySync: Flatten mode - skipping subdirectory creation, {0} root files to copy",
                        allSourceFiles.Length);
                }

                // Copy files
                var totalFiles = allSourceFiles.Length;
                var copiedFiles = 0;

                foreach (var file in allSourceFiles)
                {
                    // Calculate relative path
                    var normalizedSourceDir = sourceDir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                    var relativePath = file.Substring(normalizedSourceDir.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                    var destFile = Path.Combine(destDir, relativePath);

                    Logger.Debug("Copying file: {0} -> {1}", file, destFile);

                    // Ensure destination directory exists (defensive)
                    var destFileDir = Path.GetDirectoryName(destFile);
                    if (!Directory.Exists(destFileDir))
                    {
                        Directory.CreateDirectory(destFileDir);
                    }

                    File.Copy(file, destFile, true);

                    copiedFiles++;
                    if (totalFiles > 0)
                        progress?.Report((copiedFiles * 100) / totalFiles);
                }

                Logger.Info("CopyDirectorySync: Copied {0} files", copiedFiles);

                // CRITICAL VALIDATION: Verify all intended files were copied
                if (copiedFiles != totalFiles)
                {
                    throw new IOException(
                        $"File copy validation failed: Expected {totalFiles} files, " +
                        $"but only copied {copiedFiles}");
                }

                // Final validation (only for full recursive copy without filters)
                if (!flatten && (ignoreMasks == null || ignoreMasks.Count == 0))
                {
                    var allSourceDirs = Directory.GetDirectories(sourceDir, "*", SearchOption.AllDirectories);
                    Logger.Info("CopyDirectorySync: Running final validation...");
                    ValidateCopyCompleteness(sourceDir, destDir, allSourceDirs.Length, totalFiles);
                }

                Logger.Info("CopyDirectorySync: Successfully copied {0} files", copiedFiles);

                return copiedFiles;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "CopyDirectorySync FAILED: Error during copy from '{0}' to '{1}'", sourceDir, destDir);
                throw new IOException(
                    $"Failed to copy directory from '{sourceDir}' to '{destDir}': {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Validates that all directories and files from source were copied to destination
        /// </summary>
        private void ValidateCopyCompleteness(string sourceDir, string destDir, int expectedDirs, int expectedFiles)
        {
            try
            {
                // Normalize paths
                sourceDir = Path.GetFullPath(sourceDir).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                destDir = Path.GetFullPath(destDir).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

                // Count directories in destination
                var destDirs = Directory.GetDirectories(destDir, "*", SearchOption.AllDirectories);
                if (destDirs.Length != expectedDirs)
                {
                    Logger.Error(
                        "VALIDATION FAILED: Expected {0} directories in destination, but found {1}",
                        expectedDirs, destDirs.Length);
                    throw new IOException(
                        $"Copy validation failed: Expected {expectedDirs} directories in '{destDir}', " +
                        $"but found {destDirs.Length}. DATA LOSS PREVENTED!");
                }

                // Count files in destination
                var destFiles = Directory.GetFiles(destDir, "*", SearchOption.AllDirectories);
                if (destFiles.Length != expectedFiles)
                {
                    Logger.Error(
                        "VALIDATION FAILED: Expected {0} files in destination, but found {1}",
                        expectedFiles, destFiles.Length);
                    throw new IOException(
                        $"Copy validation failed: Expected {expectedFiles} files in '{destDir}', " +
                        $"but found {destFiles.Length}. DATA LOSS PREVENTED!");
                }

                Logger.Info("Validation passed: {0} directories and {1} files in destination match source",
                    destDirs.Length, destFiles.Length);
            }
            catch (IOException)
            {
                throw; // Re-throw validation errors
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Error during copy validation");
                throw new IOException($"Copy validation error: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Throws when a virtual path does not resolve inside the allowed boundaries.
        /// Lets a command reject a bad destination before doing expensive work for it.
        /// </summary>
        public void EnsureAllowedPath(string path)
        {
            ValidatePath(ResolvePath(path));
        }

        /// <summary>
        /// Places a local file (e.g. downloaded from the API) at a destination that must not
        /// exist yet. The content is written to "&lt;destination&gt;.partial" and renamed, so a
        /// half-written file never carries the final name.
        /// </summary>
        public async Task<Dictionary<string, object>> ReceiveFileAsync(string destination, string localFile)
        {
            var resolvedDest = ResolvePath(destination);
            ValidatePath(resolvedDest);

            if (string.IsNullOrEmpty(Path.GetFileName(resolvedDest)))
            {
                throw new ArgumentException($"Destination must be a file path: {destination}");
            }

            var partialPath = resolvedDest + ".partial";

            Logger.Info("Receiving file into {0}", resolvedDest);

            return await Task.Run(() =>
            {
                // The local file sits in the service account's temp folder, which the share
                // credentials may not be allowed to read, so open it before impersonating.
                using (var source = new FileStream(localFile, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    return ExecuteWithImpersonation(() =>
                    {
                        try
                        {
                            if (File.Exists(resolvedDest) || Directory.Exists(resolvedDest))
                            {
                                throw new IOException($"Destination already exists: {resolvedDest}");
                            }

                            Directory.CreateDirectory(Path.GetDirectoryName(resolvedDest));

                            using (var target = new FileStream(partialPath, FileMode.Create, FileAccess.Write, FileShare.None))
                            {
                                source.CopyTo(target, 81920);
                            }

                            // Fails if the destination appeared meanwhile: never overwrite.
                            File.Move(partialPath, resolvedDest);

                            var fileSize = new FileInfo(resolvedDest).Length;
                            Logger.Info("File received: {0} ({1} bytes)", resolvedDest, fileSize);

                            return new Dictionary<string, object>
                            {
                                { "destination", destination },
                                { "type", "file" },
                                { "file_count", 1 },
                                { "total_size_bytes", fileSize }
                            };
                        }
                        finally
                        {
                            try
                            {
                                if (File.Exists(partialPath))
                                {
                                    File.Delete(partialPath);
                                }
                            }
                            catch (Exception ex)
                            {
                                Logger.Warn("Could not remove partial file {0}: {1}", partialPath, ex.Message);
                            }
                        }
                    });
                }
            });
        }

        /// <summary>
        /// Moves file or directory
        /// </summary>
        public async Task<Dictionary<string, object>> MoveAsync(string source, string destination)
        {
            var resolvedSource = ResolvePath(source);
            var resolvedDest = ResolvePath(destination);

            ValidatePath(resolvedSource);
            ValidatePath(resolvedDest);

            Logger.Info("Moving from {0} to {1}", resolvedSource, resolvedDest);

            var result = new Dictionary<string, object>
            {
                { "source", source },
                { "destination", destination }
            };

            return await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    // Check if source and destination are on different volumes
                    var sourceRoot = Path.GetPathRoot(resolvedSource);
                    var destRoot = Path.GetPathRoot(resolvedDest);
                    var isCrossVolume = !string.Equals(sourceRoot, destRoot, StringComparison.OrdinalIgnoreCase);

                    if (isCrossVolume)
                    {
                        Logger.Info("Cross-volume move detected ({0} -> {1}), using copy+delete instead", sourceRoot, destRoot);
                    }

                    if (File.Exists(resolvedSource))
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(resolvedDest));

                        if (isCrossVolume)
                        {
                            // Cross-volume: use copy + delete
                            File.Copy(resolvedSource, resolvedDest, true);
                            File.Delete(resolvedSource);
                            Logger.Info("Cross-volume file move completed using copy+delete");
                        }
                        else
                        {
                            // Same volume: use fast move
                            File.Move(resolvedSource, resolvedDest);
                            Logger.Info("Same-volume file move completed");
                        }

                        var fileSize = new FileInfo(resolvedDest).Length;
                        result["type"] = "file";
                        result["size"] = fileSize;
                        // Backend expects these keys
                        result["file_count"] = 1;
                        result["total_size_bytes"] = fileSize;
                    }
                    else if (Directory.Exists(resolvedSource))
                    {
                        if (isCrossVolume)
                        {
                            // Cross-volume: use copy + delete
                            Logger.Info("Cross-volume directory move: copying '{0}' to '{1}'", resolvedSource, resolvedDest);

                            // Count source items BEFORE copy for validation
                            var sourceDirs = Directory.GetDirectories(resolvedSource, "*", SearchOption.AllDirectories);
                            var sourceFiles = Directory.GetFiles(resolvedSource, "*", SearchOption.AllDirectories);
                            Logger.Info("Source directory has {0} subdirectories and {1} files", sourceDirs.Length, sourceFiles.Length);

                            // Copy directory (includes validation)
                            var filesCopied = CopyDirectorySync(resolvedSource, resolvedDest);

                            // CopyDirectorySync already validates, but double-check before deleting source
                            // This is CRITICAL to prevent data loss
                            Logger.Info("CRITICAL: Validating copy before deleting source directory...");
                            ValidateCopyCompleteness(resolvedSource, resolvedDest, sourceDirs.Length, sourceFiles.Length);

                            // Only delete source if validation passed
                            Logger.Info("Validation passed, safe to delete source directory '{0}'", resolvedSource);
                            Directory.Delete(resolvedSource, true);

                            // Calculate total size of all files moved
                            var destFiles = Directory.GetFiles(resolvedDest, "*", SearchOption.AllDirectories);
                            long totalSize = 0;
                            foreach (var file in destFiles)
                            {
                                totalSize += new FileInfo(file).Length;
                            }

                            Logger.Info("Cross-volume directory move completed using copy+delete: {0} files, {1} bytes", filesCopied, totalSize);
                            // Keep legacy key for backward compatibility
                            result["filesMoved"] = filesCopied;
                            // Backend expects these keys
                            result["file_count"] = filesCopied;
                            result["total_size_bytes"] = totalSize;
                        }
                        else
                        {
                            // Same volume: use fast move
                            Logger.Info("Same-volume directory move: '{0}' to '{1}'", resolvedSource, resolvedDest);

                            // Count items for validation
                            var sourceDirs = Directory.GetDirectories(resolvedSource, "*", SearchOption.AllDirectories);
                            var sourceFiles = Directory.GetFiles(resolvedSource, "*", SearchOption.AllDirectories);
                            Logger.Info("Moving directory with {0} subdirectories and {1} files", sourceDirs.Length, sourceFiles.Length);

                            Directory.CreateDirectory(Path.GetDirectoryName(resolvedDest));
                            Directory.Move(resolvedSource, resolvedDest);

                            // Validate the move completed successfully
                            Logger.Info("Validating move operation...");
                            // For move validation, we check the destination has the expected counts
                            var destDirs = Directory.GetDirectories(resolvedDest, "*", SearchOption.AllDirectories);
                            var destFiles = Directory.GetFiles(resolvedDest, "*", SearchOption.AllDirectories);

                            if (destDirs.Length != sourceDirs.Length || destFiles.Length != sourceFiles.Length)
                            {
                                throw new IOException(
                                    $"Move validation failed: Expected {sourceDirs.Length} dirs and {sourceFiles.Length} files, " +
                                    $"but destination has {destDirs.Length} dirs and {destFiles.Length} files. DATA LOSS PREVENTED!");
                            }

                            // Calculate total size
                            long totalSize = 0;
                            foreach (var file in destFiles)
                            {
                                totalSize += new FileInfo(file).Length;
                            }

                            Logger.Info("Same-volume directory move completed and validated: {0} files, {1} bytes", destFiles.Length, totalSize);

                            // Backend expects these keys
                            result["file_count"] = destFiles.Length;
                            result["total_size_bytes"] = totalSize;
                        }

                        result["type"] = "directory";
                    }
                    else
                    {
                        throw new FileNotFoundException($"Source not found: {resolvedSource}");
                    }

                    Logger.Info("Move completed successfully");
                    return result;
                });
            });
        }

        /// <summary>
        /// Deletes file or directory
        /// </summary>
        public async Task<Dictionary<string, object>> DeleteAsync(string path)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            Logger.Info("Deleting {0}", resolvedPath);

            var result = new Dictionary<string, object>
            {
                { "path", path }
            };

            return await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    if (File.Exists(resolvedPath))
                    {
                        var fileSize = new FileInfo(resolvedPath).Length;
                        File.Delete(resolvedPath);

                        result["type"] = "file";
                        result["file_count"] = 1;
                        result["total_size_bytes"] = fileSize;

                        Logger.Info("File deleted successfully: {0} bytes", fileSize);
                    }
                    else if (Directory.Exists(resolvedPath))
                    {
                        // Count files and calculate size BEFORE deletion
                        var files = Directory.GetFiles(resolvedPath, "*", SearchOption.AllDirectories);
                        var fileCount = files.Length;
                        long totalSize = 0;
                        foreach (var file in files)
                        {
                            totalSize += new FileInfo(file).Length;
                        }

                        Directory.Delete(resolvedPath, true);

                        result["type"] = "directory";
                        result["file_count"] = fileCount;
                        result["total_size_bytes"] = totalSize;

                        Logger.Info("Directory deleted successfully: {0} files, {1} bytes", fileCount, totalSize);
                    }
                    else
                    {
                        throw new FileNotFoundException($"Path not found: {resolvedPath}");
                    }

                    Logger.Info("Delete completed successfully");
                    return result;
                });
            });
        }

        /// <summary>
        /// Creates directory
        /// </summary>
        public async Task<Dictionary<string, object>> MkdirAsync(string path)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            Logger.Info("Creating directory {0}", resolvedPath);

            return await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    Directory.CreateDirectory(resolvedPath);

                    var result = new Dictionary<string, object>
                    {
                        { "path", path },
                        { "created", true }
                    };

                    Logger.Info("Directory created successfully");
                    return result;
                });
            });
        }

        /// <summary>
        /// Lists files and directories with optional pagination
        /// </summary>
        public async Task<Dictionary<string, object>> ListAsync(string path, bool recursive = false, int offset = 0, int limit = 0)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            Logger.Info("Listing {0} (recursive: {1}, offset: {2}, limit: {3})", resolvedPath, recursive, offset, limit);

            // Determine which prefix to use for relative path construction
            string prefixToRemove;
            string virtualPrefix;
            if (path.StartsWith("A:", StringComparison.OrdinalIgnoreCase))
            {
                prefixToRemove = _pathAPrefix;
                virtualPrefix = "A:";
            }
            else if (path.StartsWith("B:", StringComparison.OrdinalIgnoreCase))
            {
                prefixToRemove = _pathBPrefix;
                virtualPrefix = "B:";
            }
            else if (path.StartsWith("C:", StringComparison.OrdinalIgnoreCase))
            {
                prefixToRemove = _pathCPrefix;
                virtualPrefix = "C:";
            }
            else
            {
                throw new ArgumentException($"Invalid path prefix: {path}");
            }

            var result = await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    if (!Directory.Exists(resolvedPath))
                    {
                        throw new DirectoryNotFoundException($"Directory not found: {resolvedPath}");
                    }

                    var searchOption = recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly;

                    // Create a list to hold all items
                    var allItems = new List<object>();

                    // Add ".." parent directory navigation if not at root
                    // Root is when path equals just the prefix (e.g., "A:", "B:", "C:")
                    bool isAtRoot = path.Length == 2 && path.EndsWith(":");
                    if (!isAtRoot && !recursive)
                    {
                        // Calculate parent path
                        var pathPart = path.Substring(2).TrimStart('/', '\\');
                        string parentPath;

                        if (string.IsNullOrEmpty(pathPart))
                        {
                            // Already at root
                            parentPath = virtualPrefix;
                        }
                        else
                        {
                            var pathParts = pathPart.Split(new[] { '/', '\\' }, StringSplitOptions.RemoveEmptyEntries);
                            if (pathParts.Length > 1)
                            {
                                // Remove last part to get parent
                                parentPath = virtualPrefix + "/" + string.Join("/", pathParts.Take(pathParts.Length - 1));
                            }
                            else
                            {
                                // Parent is root
                                parentPath = virtualPrefix;
                            }
                        }

                        allItems.Add(new
                        {
                            path = parentPath,
                            name = "..",
                            size = 0L,
                            modified = DateTime.UtcNow.ToString("o"),
                            type = "directory",
                            is_directory = true
                        });
                    }

                    var files = Directory.GetFiles(resolvedPath, "*", searchOption)
                        .Select(f => new
                        {
                            path = virtualPrefix + "/" + f.Substring(prefixToRemove.Length).TrimStart('\\', '/'),
                            name = Path.GetFileName(f),
                            size = new FileInfo(f).Length,
                            modified = File.GetLastWriteTimeUtc(f).ToString("o"),
                            type = "file",
                            is_directory = false
                        });

                    var directories = Directory.GetDirectories(resolvedPath, "*", searchOption)
                        .Select(d => new
                        {
                            path = virtualPrefix + "/" + d.Substring(prefixToRemove.Length).TrimStart('\\', '/'),
                            name = Path.GetFileName(d),
                            size = 0L,
                            modified = Directory.GetLastWriteTimeUtc(d).ToString("o"),
                            type = "directory",
                            is_directory = true
                        });

                    allItems.AddRange(files);
                    allItems.AddRange(directories);

                    var totalCount = allItems.Count;

                    // Apply pagination if limit > 0
                    var paginatedItems = (limit > 0) ? allItems.Skip(offset).Take(limit).ToList() : allItems;

                    return new Dictionary<string, object>
                    {
                        { "path", path },
                        { "count", paginatedItems.Count },
                        { "total", totalCount },
                        { "offset", offset },
                        { "limit", limit },
                        { "items", paginatedItems }
                    };
                });
            });

            Logger.Info("List completed: {0} items (total: {1})", result["count"], result["total"]);
            return result;
        }

        /// <summary>
        /// Canonical image type detected from a file's magic bytes, or null when the
        /// content is not a recognised image.
        /// </summary>
        private static string DetectImageType(string filePath)
        {
            try
            {
                var header = new byte[12];
                int read;
                using (var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    read = fs.Read(header, 0, header.Length);
                }

                if (read >= 3 && header[0] == 0xFF && header[1] == 0xD8 && header[2] == 0xFF)
                    return "jpeg";

                if (read >= 8 && header[0] == 0x89 && header[1] == 0x50 && header[2] == 0x4E && header[3] == 0x47
                    && header[4] == 0x0D && header[5] == 0x0A && header[6] == 0x1A && header[7] == 0x0A)
                    return "png";

                if (read >= 6 && header[0] == 'G' && header[1] == 'I' && header[2] == 'F'
                    && header[3] == '8' && (header[4] == '7' || header[4] == '9') && header[5] == 'a')
                    return "gif";

                if (read >= 2 && header[0] == 'B' && header[1] == 'M')
                    return "bmp";

                // TIFF: little-endian "II*\0" or big-endian "MM\0*"
                if (read >= 4 && ((header[0] == 0x49 && header[1] == 0x49 && header[2] == 0x2A && header[3] == 0x00)
                              || (header[0] == 0x4D && header[1] == 0x4D && header[2] == 0x00 && header[3] == 0x2A)))
                    return "tiff";

                // WEBP: "RIFF" .... "WEBP"
                if (read >= 12 && header[0] == 'R' && header[1] == 'I' && header[2] == 'F' && header[3] == 'F'
                    && header[8] == 'W' && header[9] == 'E' && header[10] == 'B' && header[11] == 'P')
                    return "webp";

                return null;
            }
            catch (Exception ex)
            {
                Logger.Warn("Could not read magic bytes from {0}: {1}", filePath, ex.Message);
                return null;
            }
        }

        /// <summary>
        /// Maps a file extension to the canonical image type its magic bytes should report.
        /// </summary>
        private static string ExpectedImageType(string extension)
        {
            switch (extension)
            {
                case "jpg":
                case "jpeg":
                    return "jpeg";
                case "tif":
                case "tiff":
                    return "tiff";
                case "png":
                    return "png";
                case "gif":
                    return "gif";
                case "bmp":
                    return "bmp";
                case "webp":
                    return "webp";
                default:
                    return null;
            }
        }

        /// <summary>
        /// Inspects the top level of a directory for the PUSH/UPDATE content rules.
        ///
        /// Returns every top-level basename (images and non-images alike, for the PIM
        /// payload), the count of genuine image files, and any file whose extension
        /// claims to be an image while its magic bytes say otherwise.
        /// </summary>
        public async Task<Dictionary<string, object>> ValidateDirectoryAsync(
            string path,
            List<string> allowedExtensions,
            bool verifyContent)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            var allowed = new HashSet<string>(
                (allowedExtensions ?? new List<string>()).Select(e => e.TrimStart('.').ToLowerInvariant()),
                StringComparer.OrdinalIgnoreCase);

            Logger.Info("Validating directory {0} (extensions: {1}, verifyContent: {2})",
                resolvedPath, string.Join(",", allowed), verifyContent);

            return await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    if (!Directory.Exists(resolvedPath))
                    {
                        throw new DirectoryNotFoundException($"Directory not found: {resolvedPath}");
                    }

                    var allFiles = new List<string>();
                    var nonImageFiles = new List<string>();
                    var invalidFiles = new List<object>();
                    int imageCount = 0;
                    long totalSize = 0;

                    foreach (var file in Directory.GetFiles(resolvedPath, "*", SearchOption.TopDirectoryOnly))
                    {
                        var name = Path.GetFileName(file);
                        allFiles.Add(name);

                        try { totalSize += new FileInfo(file).Length; } catch { }

                        var ext = Path.GetExtension(file).TrimStart('.').ToLowerInvariant();

                        if (!allowed.Contains(ext))
                        {
                            // Garbage as far as the minimum-count rule is concerned, but
                            // still reported and still shipped to PIM.
                            nonImageFiles.Add(name);
                            continue;
                        }

                        if (!verifyContent)
                        {
                            imageCount++;
                            continue;
                        }

                        var detected = DetectImageType(file);
                        var expected = ExpectedImageType(ext);

                        if (detected == null)
                        {
                            invalidFiles.Add(new Dictionary<string, object>
                            {
                                { "name", name },
                                { "extension", ext },
                                { "detected", "unknown" },
                                { "reason", "not_an_image" }
                            });
                            continue;
                        }

                        // An unknown-but-allowed extension has no expected type; accept
                        // whatever image format the bytes report.
                        if (expected != null && detected != expected)
                        {
                            invalidFiles.Add(new Dictionary<string, object>
                            {
                                { "name", name },
                                { "extension", ext },
                                { "detected", detected },
                                { "reason", "extension_mismatch" }
                            });
                            continue;
                        }

                        imageCount++;
                    }

                    var subdirCount = Directory.GetDirectories(resolvedPath, "*", SearchOption.TopDirectoryOnly).Length;

                    Logger.Info("Validation of {0}: {1} file(s), {2} image(s), {3} non-image, {4} mismatched",
                        resolvedPath, allFiles.Count, imageCount, nonImageFiles.Count, invalidFiles.Count);

                    return new Dictionary<string, object>
                    {
                        { "path", path },
                        { "files", allFiles },
                        { "total_files", allFiles.Count },
                        { "image_count", imageCount },
                        { "non_image_files", nonImageFiles },
                        { "invalid_files", invalidFiles },
                        { "subdirectory_count", subdirCount },
                        { "total_size_bytes", totalSize }
                    };
                });
            });
        }

        /// <summary>
        /// Searches for files and directories matching pattern
        /// </summary>
        public async Task<Dictionary<string, object>> SearchAsync(string path, string pattern, bool recursive = true)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            Logger.Info("Searching in {0} for pattern '{1}' (recursive: {2})", resolvedPath, pattern, recursive);

            // Determine which prefix to use for relative path construction
            string prefixToRemove;
            string virtualPrefix;
            if (path.StartsWith("A:", StringComparison.OrdinalIgnoreCase))
            {
                prefixToRemove = _pathAPrefix;
                virtualPrefix = "A:";
            }
            else if (path.StartsWith("B:", StringComparison.OrdinalIgnoreCase))
            {
                prefixToRemove = _pathBPrefix;
                virtualPrefix = "B:";
            }
            else if (path.StartsWith("C:", StringComparison.OrdinalIgnoreCase))
            {
                prefixToRemove = _pathCPrefix;
                virtualPrefix = "C:";
            }
            else
            {
                throw new ArgumentException($"Invalid path prefix: {path}");
            }

            var result = await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    if (!Directory.Exists(resolvedPath))
                    {
                        throw new DirectoryNotFoundException($"Directory not found: {resolvedPath}");
                    }

                    var searchOption = recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly;

                    // Search for both files and directories matching the pattern
                    var matchedFiles = Directory.GetFiles(resolvedPath, pattern, searchOption)
                        .Select(f => new
                        {
                            path = virtualPrefix + "/" + f.Substring(prefixToRemove.Length).TrimStart('\\', '/'),
                            name = Path.GetFileName(f),
                            size = new FileInfo(f).Length,
                            modified = File.GetLastWriteTimeUtc(f).ToString("o"),
                            is_directory = false
                        });

                    var matchedDirs = Directory.GetDirectories(resolvedPath, pattern, searchOption)
                        .Select(d => new
                        {
                            path = virtualPrefix + "/" + d.Substring(prefixToRemove.Length).TrimStart('\\', '/'),
                            name = Path.GetFileName(d),
                            size = 0L,
                            modified = Directory.GetLastWriteTimeUtc(d).ToString("o"),
                            is_directory = true
                        });

                    var results = matchedFiles.Concat(matchedDirs).ToList();

                    return new Dictionary<string, object>
                    {
                        { "path", path },
                        { "pattern", pattern },
                        { "count", results.Count },
                        { "files", results }
                    };
                });
            });

            Logger.Info("Search completed: {0} items found (files and directories)", result["count"]);
            return result;
        }

        /// <summary>
        /// Checks if a filename matches any of the ignore masks (case-insensitive).
        /// Supports exact match (e.g., "Thumbs.db") and wildcard patterns (e.g., "*.tmp").
        /// </summary>
        private bool MatchesIgnoreMask(string fileName, List<string> masks)
        {
            if (masks == null || masks.Count == 0 || string.IsNullOrEmpty(fileName))
                return false;

            foreach (var mask in masks)
            {
                if (string.IsNullOrEmpty(mask))
                    continue;

                if (mask.Contains("*") || mask.Contains("?"))
                {
                    // Wildcard pattern matching using simple glob-to-regex
                    // Convert glob pattern to regex: * -> .*, ? -> .
                    var pattern = "^" + System.Text.RegularExpressions.Regex.Escape(mask)
                        .Replace("\\*", ".*")
                        .Replace("\\?", ".") + "$";
                    if (System.Text.RegularExpressions.Regex.IsMatch(
                        fileName, pattern, System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                    {
                        return true;
                    }
                }
                else
                {
                    // Exact match (case-insensitive)
                    if (string.Equals(fileName, mask, StringComparison.OrdinalIgnoreCase))
                    {
                        return true;
                    }
                }
            }

            return false;
        }

        /// <summary>
        /// Best-effort cleanup of source directory after PUSH copy.
        /// Destroys subfolders (if flatten) and ignored files. Never throws.
        /// </summary>
        public async Task<Dictionary<string, object>> PushCleanupAsync(
            string sourcePath, bool flatten, List<string> ignoreMasks)
        {
            var resolvedSource = ResolvePath(sourcePath);
            ValidatePath(resolvedSource);

            Logger.Info("PushCleanup: source={0}, flatten={1}, ignoreMasks={2}",
                resolvedSource, flatten,
                ignoreMasks != null ? string.Join(",", ignoreMasks) : "none");

            return await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    var failures = new List<string>();
                    int destroyedDirs = 0;
                    int destroyedFiles = 0;

                    // Delete subfolders if flatten
                    if (flatten && Directory.Exists(resolvedSource))
                    {
                        foreach (var dir in Directory.GetDirectories(resolvedSource))
                        {
                            try
                            {
                                Directory.Delete(dir, true);
                                destroyedDirs++;
                                Logger.Info("PushCleanup: Destroyed subfolder {0}", dir);
                            }
                            catch (Exception ex)
                            {
                                Logger.Warn("PushCleanup: Failed to destroy subfolder {0}: {1}", dir, ex.Message);
                                failures.Add($"subfolder:{Path.GetFileName(dir)}:{ex.Message}");
                            }
                        }
                    }

                    // Delete ignored files (recursive)
                    if (ignoreMasks != null && ignoreMasks.Count > 0 && Directory.Exists(resolvedSource))
                    {
                        var dirs = new Stack<string>();
                        dirs.Push(resolvedSource);

                        while (dirs.Count > 0)
                        {
                            var currentDir = dirs.Pop();

                            try
                            {
                                foreach (var dir in Directory.GetDirectories(currentDir))
                                {
                                    dirs.Push(dir);
                                }
                            }
                            catch (Exception ex)
                            {
                                Logger.Warn("PushCleanup: Failed to enumerate subfolders in {0}: {1}", currentDir, ex.Message);
                                failures.Add($"dir:{currentDir}:{ex.Message}");
                                continue;
                            }

                            try
                            {
                                foreach (var file in Directory.GetFiles(currentDir))
                                {
                                    if (MatchesIgnoreMask(Path.GetFileName(file), ignoreMasks))
                                    {
                                        try
                                        {
                                            File.Delete(file);
                                            destroyedFiles++;
                                            Logger.Info("PushCleanup: Destroyed ignored file {0}", file);
                                        }
                                        catch (Exception ex)
                                        {
                                            Logger.Warn("PushCleanup: Failed to destroy ignored file {0}: {1}", file, ex.Message);
                                            failures.Add($"file:{Path.GetFileName(file)}:{ex.Message}");
                                        }
                                    }
                                }
                            }
                            catch (Exception ex)
                            {
                                Logger.Warn("PushCleanup: Failed to enumerate files in {0}: {1}", currentDir, ex.Message);
                                failures.Add($"filelist:{currentDir}:{ex.Message}");
                            }
                        }
                    }

                    var result = new Dictionary<string, object>
                    {
                        { "destroyed_dirs", destroyedDirs },
                        { "destroyed_files", destroyedFiles },
                        { "failure_count", failures.Count },
                        { "failures", failures }
                    };

                    Logger.Info("PushCleanup completed: {0} dirs destroyed, {1} files destroyed, {2} failures",
                        destroyedDirs, destroyedFiles, failures.Count);

                    return result;
                });
            });
        }

        /// <summary>
        /// Gets file or directory info
        /// </summary>
        public async Task<Dictionary<string, object>> GetInfoAsync(string path)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            return await Task.Run(() =>
            {
                return ExecuteWithImpersonation(() =>
                {
                    if (File.Exists(resolvedPath))
                    {
                        var fileInfo = new FileInfo(resolvedPath);
                        return new Dictionary<string, object>
                        {
                            { "path", path },
                            { "type", "file" },
                            { "size", fileInfo.Length },
                            { "created", fileInfo.CreationTimeUtc.ToString("o") },
                            { "modified", fileInfo.LastWriteTimeUtc.ToString("o") },
                            { "attributes", fileInfo.Attributes.ToString() }
                        };
                    }
                    else if (Directory.Exists(resolvedPath))
                    {
                        var dirInfo = new DirectoryInfo(resolvedPath);
                        return new Dictionary<string, object>
                        {
                            { "path", path },
                            { "type", "directory" },
                            { "created", dirInfo.CreationTimeUtc.ToString("o") },
                            { "modified", dirInfo.LastWriteTimeUtc.ToString("o") },
                            { "attributes", dirInfo.Attributes.ToString() }
                        };
                    }
                    else
                    {
                        throw new FileNotFoundException($"Path not found: {resolvedPath}");
                    }
                });
            });
        }
    }
}
