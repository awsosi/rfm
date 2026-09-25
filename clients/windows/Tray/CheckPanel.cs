using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace RFMTray
{
    /// <summary>
    /// Runs <see cref="ConnectionCheck"/> and shows each step with a mark,
    /// the verdict, and "Copy results" for whoever helps the user.
    /// Used by the onboarding and the "Check connection" window.
    /// </summary>
    public class CheckPanel : UserControl
    {
        private readonly TrayContext _context;
        private readonly Func<IEnumerable<string>> _folders;
        private readonly ListView _list;
        private readonly Label _verdict;
        private readonly Button _again, _copy;
        private List<CheckStep> _steps = new List<CheckStep>();

        /// <summary>Raised on the UI thread with whether every step passed.</summary>
        public event Action<bool> Finished;

        public bool Running { get; private set; }
        public bool Passed { get; private set; }

        public CheckPanel(TrayContext context, Func<IEnumerable<string>> folders)
        {
            _context = context;
            _folders = folders;

            _list = new ListView
            {
                Dock = DockStyle.Fill,
                View = View.Details,
                FullRowSelect = true,
                HeaderStyle = ColumnHeaderStyle.None,
                ShowItemToolTips = true,
            };
            _list.Columns.Add("", 28);
            _list.Columns.Add("", 190);
            _list.Columns.Add("", 380);
            _list.Resize += (s, e) => _list.Columns[2].Width = Math.Max(120, _list.ClientSize.Width - 28 - 190 - 4);

            _verdict = new Label { Dock = DockStyle.Bottom, AutoSize = false, Height = 44, Padding = new Padding(2, 6, 2, 0) };

            var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, AutoSize = true, FlowDirection = FlowDirection.LeftToRight };
            _again = new Button { Text = L.T("tray.check.again"), AutoSize = true };
            _copy = new Button { Text = L.T("tray.check.copy"), AutoSize = true, Enabled = false };
            _again.Click += (s, e) => Run();
            _copy.Click += (s, e) => Clipboard.SetText(ConnectionCheck.Report(_steps));
            buttons.Controls.Add(_again);
            buttons.Controls.Add(_copy);

            Controls.Add(_list);
            Controls.Add(_verdict);
            Controls.Add(buttons);
        }

        public void Run()
        {
            if (Running)
                return;
            Running = true;
            Passed = false;
            _again.Enabled = _copy.Enabled = false;
            _list.Items.Clear();
            _verdict.ForeColor = SystemColors.WindowText;
            _verdict.Text = L.T("tray.check.running");

            var folders = new List<string>(_folders());
            Task.Run(() => ConnectionCheck.Run(_context.Client, _context.Config, folders)).ContinueWith(t =>
            {
                if (IsDisposed)
                    return;
                BeginInvoke((Action)(() => Show(t.IsFaulted
                    ? new List<CheckStep> { new CheckStep { Title = L.T("tray.check.server"), Status = CheckStatus.Failed, Detail = RfmClient.Describe(t.Exception) } }
                    : t.Result)));
            });
        }

        private void Show(List<CheckStep> steps)
        {
            _steps = steps;
            _list.BeginUpdate();
            foreach (var step in steps)
            {
                var item = new ListViewItem(new[] { Mark(step.Status), step.Title, step.Detail }) { ToolTipText = step.Detail };
                item.UseItemStyleForSubItems = true;
                item.ForeColor = step.Status == CheckStatus.Failed ? Color.DarkRed
                    : step.Status == CheckStatus.Warning ? Color.DarkGoldenrod
                    : step.Status == CheckStatus.Skipped ? SystemColors.GrayText
                    : Color.DarkGreen;
                _list.Items.Add(item);
            }
            _list.EndUpdate();

            Passed = ConnectionCheck.Passed(steps);
            _verdict.Text = L.T(Passed ? "tray.check.passed" : "tray.check.failed");
            _verdict.ForeColor = Passed ? Color.DarkGreen : Color.DarkRed;
            Running = false;
            _again.Enabled = _copy.Enabled = true;
            _context.CheckCompleted(steps);
            Finished?.Invoke(Passed);
        }

        private static string Mark(CheckStatus status)
        {
            switch (status)
            {
                case CheckStatus.Ok: return "✔";
                case CheckStatus.Warning: return "!";
                case CheckStatus.Failed: return "✖";
                default: return "–";
            }
        }
    }

    /// <summary>"Check connection": the same check as the last onboarding step.</summary>
    public class CheckForm : Form
    {
        public CheckForm(TrayContext context)
        {
            Text = L.T("tray.check.title");
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            StartPosition = FormStartPosition.CenterScreen;
            Font = SystemFonts.MessageBoxFont;
            Size = new Size(860, 420);
            MinimumSize = new Size(520, 320);

            var panel = new CheckPanel(context, () => context.Settings.WatchFolders) { Dock = DockStyle.Fill, Padding = new Padding(12) };
            var close = new Button { Text = L.T("tray.issue.close"), AutoSize = true, DialogResult = DialogResult.Cancel };
            var bottom = new FlowLayoutPanel { Dock = DockStyle.Bottom, AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
            bottom.Controls.Add(close);
            CancelButton = close;
            close.Click += (s, e) => Close();

            Controls.Add(panel);
            Controls.Add(bottom);
            Shown += (s, e) => panel.Run();
        }
    }

    /// <summary>Choose a folder to watch, inside allowed_paths (Settings and onboarding).</summary>
    static class FolderPicker
    {
        public static string Pick(IWin32Window owner, RFMLauncher.Config config, string caption)
        {
            using (var dialog = new FolderBrowserDialog { Description = L.T("tray.settings.pick"), ShowNewFolderButton = false })
            {
                if (config.AllowedPaths.Count > 0)
                    dialog.SelectedPath = config.AllowedPaths[0];
                if (dialog.ShowDialog(owner) != DialogResult.OK)
                    return null;

                string path = dialog.SelectedPath.TrimEnd('\\');
                if (!RFMLauncher.PathRules.IsPathAllowed(path, config))
                {
                    MessageBox.Show(owner,
                        L.T("tray.settings.notAllowed", ("paths", string.Join("\n", config.AllowedPaths))),
                        caption, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return null;
                }
                return path;
            }
        }
    }
}
