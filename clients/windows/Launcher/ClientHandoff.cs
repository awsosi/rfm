using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace RFMLauncher
{
    /// <summary>
    /// Hands a context-menu action to an RFM tab the user already has open,
    /// so a click does not open yet another tab (POST /api/client-actions).
    /// </summary>
    public static class ClientHandoff
    {
        // How long the server waits for an open tab to claim the action
        private const double WaitSeconds = 3;

        // Browser window titles show the active tab's title (explorer.pageTitle)
        private static readonly string[] DefaultWindowTitles = { "File Manager", "Menedżer plików" };

        private static readonly string[] BrowserProcesses = { "chrome", "msedge", "firefox", "brave", "opera", "vivaldi" };

        /// <summary>
        /// True when an open tab took the action; false means open the deep link.
        /// Any failure (older server, Redis down, network) also returns false.
        /// </summary>
        public static bool TryHandOff(Config config, string accessToken, string action, IList<string> paths)
        {
            try
            {
                using (var client = new HttpClient { Timeout = TimeSpan.FromSeconds(WaitSeconds + 7) })
                {
                    var request = new HttpRequestMessage(HttpMethod.Post, $"{config.ApiBaseUrl.TrimEnd('/')}/api/client-actions");
                    request.Headers.Add("Authorization", $"Bearer {accessToken}");
                    request.Content = new StringContent(
                        JsonConvert.SerializeObject(new { action, paths, wait_seconds = WaitSeconds }),
                        Encoding.UTF8,
                        "application/json");

                    var response = client.SendAsync(request).Result;
                    if (!response.IsSuccessStatusCode)
                    {
                        Console.WriteLine($"Hand-off not available: {(int)response.StatusCode}");
                        return false;
                    }

                    var body = JObject.Parse(response.Content.ReadAsStringAsync().Result);
                    return (string)body["handled_by"] == "tab";
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Hand-off failed: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Best effort: bring the browser window showing the RFM tab to the front.
        /// Only finds it while RFM is the active tab of its window.
        /// </summary>
        public static void BringBrowserToFront(Config config)
        {
            var titles = config.BrowserWindowTitles != null && config.BrowserWindowTitles.Count > 0
                ? config.BrowserWindowTitles.ToArray()
                : DefaultWindowTitles;

            IntPtr found = IntPtr.Zero;
            EnumWindows((hWnd, _) =>
            {
                if (!IsWindowVisible(hWnd))
                    return true;

                var text = new StringBuilder(512);
                GetWindowText(hWnd, text, text.Capacity);
                string title = text.ToString();
                if (!titles.Any(t => title.IndexOf(t, StringComparison.OrdinalIgnoreCase) >= 0))
                    return true;

                GetWindowThreadProcessId(hWnd, out uint pid);
                try
                {
                    string name = Process.GetProcessById((int)pid).ProcessName;
                    if (BrowserProcesses.Contains(name, StringComparer.OrdinalIgnoreCase))
                    {
                        found = hWnd;
                        return false;
                    }
                }
                catch (ArgumentException)
                {
                    // Process exited meanwhile
                }
                return true;
            }, IntPtr.Zero);

            if (found == IntPtr.Zero)
                return;

            if (IsIconic(found))
                ShowWindow(found, SW_RESTORE);
            SetForegroundWindow(found);
        }

        private const int SW_RESTORE = 9;

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsIconic(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    }
}
