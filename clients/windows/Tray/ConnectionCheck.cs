using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using RFMLauncher;

namespace RFMTray
{
    public enum CheckStatus
    {
        Ok,
        /// <summary>Works, but worth knowing (e.g. no start at sign-in).</summary>
        Warning,
        Failed,
        /// <summary>Not checked because an earlier step failed.</summary>
        Skipped,
    }

    public class CheckStep
    {
        public string Title;
        public CheckStatus Status;
        public string Detail;
    }

    /// <summary>
    /// Everything RFM Tray needs to send a folder, checked against the real
    /// server rather than assumed: RFM answers, RFM confirms the sign-in, a
    /// worker is there, and the worker sees each watched folder. Runs on a
    /// background thread (network calls).
    /// </summary>
    public static class ConnectionCheck
    {
        public static List<CheckStep> Run(RfmClient client, Config config, IEnumerable<string> folders)
        {
            var steps = new List<CheckStep>();
            bool blocked = false;

            void Step(string title, Func<string> check)
            {
                if (blocked)
                {
                    steps.Add(new CheckStep { Title = title, Status = CheckStatus.Skipped, Detail = L.T("tray.check.skipped") });
                    return;
                }
                try
                {
                    steps.Add(new CheckStep { Title = title, Status = CheckStatus.Ok, Detail = check() });
                }
                catch (Exception ex)
                {
                    blocked = true;
                    steps.Add(new CheckStep { Title = title, Status = CheckStatus.Failed, Detail = RfmClient.Describe(ex) });
                }
            }

            Step(L.T("tray.check.server"), () =>
            {
                string problem = client.ServerProblem();
                if (problem != null)
                    throw new RfmException(L.T("tray.check.serverFailed", ("url", client.ServerUrl), ("error", problem)));
                return L.T("tray.check.serverOk", ("url", client.ServerUrl));
            });
            Step(L.T("tray.check.signIn"), () => L.T("tray.check.signInOk", ("user", client.ConfirmedUser())));
            Step(L.T("tray.check.worker"), () => client.WorkerName());

            var list = folders.ToList();
            if (list.Count == 0)
            {
                steps.Add(new CheckStep { Title = L.T("tray.check.folders"), Status = CheckStatus.Failed, Detail = L.T("tray.check.noFolder") });
                blocked = true;
            }
            foreach (var folder in list)
            {
                Step(L.T("tray.check.folder", ("folder", folder)), () =>
                {
                    if (!PathRules.IsPathAllowed(folder, config))
                        throw new RfmException(L.T("tray.settings.notAllowed", ("paths", string.Join(", ", config.AllowedPaths))));
                    if (!Directory.Exists(folder))
                        throw new RfmException(L.T("tray.check.folderMissing"));
                    var (virtualPath, entries) = client.Locate(folder);
                    return L.T("tray.check.folderOk", ("path", virtualPath), ("count", entries));
                });
            }

            // Local and not needed to send now, so it never blocks
            bool autostart = ScheduledTask.IsInstalled();
            steps.Add(new CheckStep
            {
                Title = L.T("tray.check.autostart"),
                Status = autostart ? CheckStatus.Ok : CheckStatus.Warning,
                Detail = L.T(autostart ? "tray.check.autostartOk" : "tray.check.autostartMissing"),
            });

            foreach (var step in steps)
                Log.Info($"Check: {step.Title}: {step.Status}: {step.Detail}");
            return steps;
        }

        public static bool Passed(IEnumerable<CheckStep> steps) =>
            steps.All(s => s.Status == CheckStatus.Ok || s.Status == CheckStatus.Warning);

        /// <summary>Plain text for "Copy results", to paste to whoever helps.</summary>
        public static string Report(IEnumerable<CheckStep> steps)
        {
            var text = new StringBuilder();
            text.AppendLine($"RFM Tray {typeof(ConnectionCheck).Assembly.GetName().Version}, {Environment.UserDomainName}\\{Environment.UserName} @ {Environment.MachineName}, {DateTime.Now:yyyy-MM-dd HH:mm}");
            foreach (var step in steps)
                text.AppendLine($"[{step.Status}] {step.Title}: {step.Detail}");
            return text.ToString();
        }
    }
}
