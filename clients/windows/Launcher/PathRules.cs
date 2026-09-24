using System;

namespace RFMLauncher
{
    /// <summary>
    /// allowed_paths rules shared by RFMLauncher and RFM Tray.
    /// </summary>
    public static class PathRules
    {
        /// <summary>
        /// Check if the selected path is allowed based on configuration
        /// </summary>
        public static bool IsPathAllowed(string selectedPath, Config config)
        {
            if (config.AllowedPaths == null || config.AllowedPaths.Count == 0)
            {
                return false;
            }

            // Normalize path separators for comparison
            string normalizedPath = selectedPath.Replace('/', '\\').ToLowerInvariant();

            foreach (var allowedPath in config.AllowedPaths)
            {
                string normalizedAllowedPath = allowedPath.Replace('/', '\\').ToLowerInvariant();

                // Check if selected path starts with allowed path
                if (normalizedPath.StartsWith(normalizedAllowedPath))
                {
                    return true;
                }
            }

            return false;
        }

        /// <summary>
        /// Normalize path to use the canonical (first) allowed path prefix.
        /// The first entry in allowed_paths must match the worker's path_a_prefix.
        /// All other entries are treated as aliases (hostname variants, mapped drives, etc.)
        /// that get rewritten to the canonical prefix before sending to the backend.
        /// </summary>
        public static string NormalizeToCanonicalPath(string selectedPath, Config config)
        {
            if (config.AllowedPaths == null || config.AllowedPaths.Count == 0)
                return selectedPath;

            string normalizedSelected = selectedPath.Replace('/', '\\');
            string canonical = config.AllowedPaths[0].Replace('/', '\\').TrimEnd('\\');

            foreach (var allowedPath in config.AllowedPaths)
            {
                string normalizedAllowed = allowedPath.Replace('/', '\\').TrimEnd('\\');

                if (normalizedSelected.StartsWith(normalizedAllowed, StringComparison.OrdinalIgnoreCase))
                {
                    return canonical + normalizedSelected.Substring(normalizedAllowed.Length);
                }
            }

            return selectedPath;
        }
    }
}
