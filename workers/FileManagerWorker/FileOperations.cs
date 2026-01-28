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

        public FileOperations(string pathAPrefix, string pathBPrefix, string pathCPrefix)
        {
            _pathAPrefix = pathAPrefix;
            _pathBPrefix = pathBPrefix;
            _pathCPrefix = pathCPrefix;
        }

        /// <summary>
        /// Resolves a path with A:, B:, or C: prefix to actual file system path
        /// </summary>
        private string ResolvePath(string path)
        {
            // Check for path traversal attempts before processing
            if (path.Contains("..") || path.Contains("//") || path.Contains("\\\\"))
            {
                throw new ArgumentException($"Path contains invalid characters (path traversal attempt): {path}");
            }

            // Check for absolute paths or network paths
            if (Path.IsPathRooted(path.Substring(2)) || path.Contains(":") && !path.StartsWith("A:", StringComparison.OrdinalIgnoreCase) && !path.StartsWith("B:", StringComparison.OrdinalIgnoreCase) && !path.StartsWith("C:", StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException($"Absolute paths and network paths are not allowed: {path}");
            }

            if (path.StartsWith("A:", StringComparison.OrdinalIgnoreCase))
            {
                return Path.Combine(_pathAPrefix, path.Substring(2).TrimStart('\\', '/'));
            }
            else if (path.StartsWith("B:", StringComparison.OrdinalIgnoreCase))
            {
                return Path.Combine(_pathBPrefix, path.Substring(2).TrimStart('\\', '/'));
            }
            else if (path.StartsWith("C:", StringComparison.OrdinalIgnoreCase))
            {
                return Path.Combine(_pathCPrefix, path.Substring(2).TrimStart('\\', '/'));
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
        public async Task<Dictionary<string, object>> CopyAsync(string source, string destination, IProgress<int> progress = null)
        {
            var resolvedSource = ResolvePath(source);
            var resolvedDest = ResolvePath(destination);

            ValidatePath(resolvedSource);
            ValidatePath(resolvedDest);

            Logger.Info("Copying from {0} to {1}", resolvedSource, resolvedDest);

            var result = new Dictionary<string, object>
            {
                { "source", source },
                { "destination", destination }
            };

            if (File.Exists(resolvedSource))
            {
                // Copy single file
                await Task.Run(() =>
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(resolvedDest));
                    File.Copy(resolvedSource, resolvedDest, true);
                });

                result["type"] = "file";
                result["size"] = new FileInfo(resolvedDest).Length;
                Logger.Info("File copied successfully");
            }
            else if (Directory.Exists(resolvedSource))
            {
                // Copy directory recursively
                var filesCopied = await CopyDirectoryAsync(resolvedSource, resolvedDest, progress);
                result["type"] = "directory";
                result["filesCopied"] = filesCopied;
                Logger.Info("Directory copied successfully: {0} files", filesCopied);
            }
            else
            {
                throw new FileNotFoundException($"Source not found: {resolvedSource}");
            }

            return result;
        }

        /// <summary>
        /// Copies directory recursively with progress reporting
        /// </summary>
        private async Task<int> CopyDirectoryAsync(string sourceDir, string destDir, IProgress<int> progress = null)
        {
            Directory.CreateDirectory(destDir);

            var files = Directory.GetFiles(sourceDir, "*", SearchOption.AllDirectories);
            var totalFiles = files.Length;
            var copiedFiles = 0;

            await Task.Run(() =>
            {
                foreach (var file in files)
                {
                    var relativePath = file.Substring(sourceDir.Length).TrimStart('\\', '/');
                    var destFile = Path.Combine(destDir, relativePath);

                    Directory.CreateDirectory(Path.GetDirectoryName(destFile));
                    File.Copy(file, destFile, true);

                    copiedFiles++;
                    progress?.Report((copiedFiles * 100) / totalFiles);
                }
            });

            return copiedFiles;
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

            await Task.Run(() =>
            {
                if (File.Exists(resolvedSource))
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(resolvedDest));
                    File.Move(resolvedSource, resolvedDest);
                    result["type"] = "file";
                }
                else if (Directory.Exists(resolvedSource))
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(resolvedDest));
                    Directory.Move(resolvedSource, resolvedDest);
                    result["type"] = "directory";
                }
                else
                {
                    throw new FileNotFoundException($"Source not found: {resolvedSource}");
                }
            });

            Logger.Info("Move completed successfully");
            return result;
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

            await Task.Run(() =>
            {
                if (File.Exists(resolvedPath))
                {
                    File.Delete(resolvedPath);
                    result["type"] = "file";
                }
                else if (Directory.Exists(resolvedPath))
                {
                    Directory.Delete(resolvedPath, true);
                    result["type"] = "directory";
                }
                else
                {
                    throw new FileNotFoundException($"Path not found: {resolvedPath}");
                }
            });

            Logger.Info("Delete completed successfully");
            return result;
        }

        /// <summary>
        /// Creates directory
        /// </summary>
        public async Task<Dictionary<string, object>> MkdirAsync(string path)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            Logger.Info("Creating directory {0}", resolvedPath);

            await Task.Run(() =>
            {
                Directory.CreateDirectory(resolvedPath);
            });

            var result = new Dictionary<string, object>
            {
                { "path", path },
                { "created", true }
            };

            Logger.Info("Directory created successfully");
            return result;
        }

        /// <summary>
        /// Lists files and directories with optional pagination
        /// </summary>
        public async Task<Dictionary<string, object>> ListAsync(string path, bool recursive = false, int offset = 0, int limit = 0)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            Logger.Info("Listing {0} (recursive: {1}, offset: {2}, limit: {3})", resolvedPath, recursive, offset, limit);

            var result = await Task.Run(() =>
            {
                if (!Directory.Exists(resolvedPath))
                {
                    throw new DirectoryNotFoundException($"Directory not found: {resolvedPath}");
                }

                var searchOption = recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly;

                var files = Directory.GetFiles(resolvedPath, "*", searchOption)
                    .Select(f => new
                    {
                        path = f.Substring(_pathAPrefix.Length).TrimStart('\\', '/'),
                        name = Path.GetFileName(f),
                        size = new FileInfo(f).Length,
                        modified = File.GetLastWriteTimeUtc(f).ToString("o"),
                        type = "file"
                    });

                var directories = Directory.GetDirectories(resolvedPath, "*", searchOption)
                    .Select(d => new
                    {
                        path = d.Substring(_pathAPrefix.Length).TrimStart('\\', '/'),
                        name = Path.GetFileName(d),
                        size = 0L,
                        modified = Directory.GetLastWriteTimeUtc(d).ToString("o"),
                        type = "directory"
                    });

                var allItems = files.Concat(directories).ToList();
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

            Logger.Info("List completed: {0} items (total: {1})", result["count"], result["total"]);
            return result;
        }

        /// <summary>
        /// Searches for files matching pattern
        /// </summary>
        public async Task<Dictionary<string, object>> SearchAsync(string path, string pattern, bool recursive = true)
        {
            var resolvedPath = ResolvePath(path);
            ValidatePath(resolvedPath);

            Logger.Info("Searching in {0} for pattern '{1}' (recursive: {2})", resolvedPath, pattern, recursive);

            var result = await Task.Run(() =>
            {
                if (!Directory.Exists(resolvedPath))
                {
                    throw new DirectoryNotFoundException($"Directory not found: {resolvedPath}");
                }

                var searchOption = recursive ? SearchOption.AllDirectories : SearchOption.TopDirectoryOnly;

                var files = Directory.GetFiles(resolvedPath, pattern, searchOption)
                    .Select(f => new
                    {
                        path = f.Substring(_pathAPrefix.Length).TrimStart('\\', '/'),
                        name = Path.GetFileName(f),
                        size = new FileInfo(f).Length,
                        modified = File.GetLastWriteTimeUtc(f).ToString("o")
                    })
                    .ToList();

                return new Dictionary<string, object>
                {
                    { "path", path },
                    { "pattern", pattern },
                    { "count", files.Count },
                    { "files", files }
                };
            });

            Logger.Info("Search completed: {0} files found", result["count"]);
            return result;
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
        }
    }
}
