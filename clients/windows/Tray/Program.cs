using System;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using RFMLauncher;

namespace RFMTray
{
    /// <summary>
    /// RFM Tray: watches the user's hand-off folders and PUSHes each new catalog
    /// through the RFM API once it has finished copying, under the user's own
    /// RFM sign-in. RFM validates, logs and publishes exactly as for the WebUI.
    ///
    ///   RFMTray.exe                   start (Start menu)
    ///   RFMTray.exe --autostart       start at sign-in (scheduled task); exits
    ///                                 quietly when no folder is watched
    ///   RFMTray.exe --install-task    register the sign-in task (installer, elevated)
    ///   RFMTray.exe --uninstall-task  remove it
    /// </summary>
    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            if (args.Contains("--install-task"))
                return ScheduledTask.Install(Application.ExecutablePath);
            if (args.Contains("--uninstall-task"))
                return ScheduledTask.Uninstall();

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            var config = ConfigurationManager.LoadConfig();
            if (config == null)
            {
                MessageBox.Show("RFM Tray: config.json is missing or invalid.", "RFM Tray",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            L.Load(config.Language);

            var settings = TraySettings.Load(config);
            if (args.Contains("--autostart") && settings.WatchFolders.Count == 0)
                return 0;

            // One instance per signed-in user session
            using (var mutex = new Mutex(true, @"Local\RFMTray", out bool first))
            {
                if (!first)
                {
                    if (!args.Contains("--autostart"))
                        MessageBox.Show(L.T("tray.alreadyRunning"), "RFM Tray",
                            MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return 0;
                }

                Application.Run(new TrayContext(config, settings));
            }
            return 0;
        }
    }
}
