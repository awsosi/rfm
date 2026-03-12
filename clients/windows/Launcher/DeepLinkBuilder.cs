using System;
using System.Collections.Generic;
using System.Linq;
using System.Web;

namespace RFMLauncher
{
    /// <summary>
    /// Builds deep link URLs for RFM web application
    /// </summary>
    public static class DeepLinkBuilder
    {
        /// <summary>
        /// Build deep link URL with action, path, and token
        /// </summary>
        /// <param name="frontendBaseUrl">Base URL of RFM frontend/WebUI</param>
        /// <param name="action">Action: "prepare" or "push"</param>
        /// <param name="paths">Real Windows paths</param>
        /// <param name="token">JWT access token</param>
        /// <returns>Complete deep link URL</returns>
        public static string Build(string frontendBaseUrl, string action, IEnumerable<string> paths, string token)
        {
            try
            {
                // Build URL: https://ff.vitkac.local/pages/explorer.html?action=prepare&path=...&token=...
                var uriBuilder = new UriBuilder(frontendBaseUrl);
                uriBuilder.Path = "/pages/explorer.html";

                var pathList = paths?
                    .Where(p => !string.IsNullOrWhiteSpace(p))
                    .ToList() ?? new List<string>();
                if (pathList.Count == 0)
                {
                    return null;
                }

                // Build query string
                var query = HttpUtility.ParseQueryString(string.Empty);
                query["action"] = action;
                query["paths"] = string.Join("|", pathList);
                query["token"] = token;
                uriBuilder.Query = query.ToString();

                return uriBuilder.ToString();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to build deep link: {ex.Message}");
                return null;
            }
        }
    }
}
