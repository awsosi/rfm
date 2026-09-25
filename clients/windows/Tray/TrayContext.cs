using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;
using RFMLauncher;

namespace RFMTray
{
    /// <summary>
    /// The tray icon: status, menu, notifications and the windows behind them.
    /// </summary>
    public class TrayContext : ApplicationContext
    {
        private readonly Config _config;
        private readonly TraySettings _settings;
        private readonly RfmClient _client;
        private readonly CatalogWatcher _watcher;
        private readonly NotifyIcon _icon;
        private readonly Icon _appIcon;
        private readonly Timer _refresh;
        private readonly Control _ui = new Control();
        private readonly ToolStripMenuItem _userItem, _statusItem, _pauseItem, _signInItem;

        // Issues gathered for the next notification, so a batch of 30 bad
        // folders makes one notification rather than thirty
        private readonly List<Catalog> _pendingIssues = new List<Catalog>();
        private readonly Timer _notifyTimer = new Timer { Interval = 1500 };
        private Action _balloonClick;

        private ActivityForm _activity;
        private string _user;
        private bool _signingIn;

        public TrayContext(Config config, TraySettings settings)
        {
            _config = config;
            _settings = settings;
            _client = new RfmClient(config);
            _watcher = new CatalogWatcher(_client, settings);
            // A window handle to marshal watcher events onto this thread
            _ = _ui.Handle;

            _appIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

            _userItem = new ToolStripMenuItem { Enabled = false };
            _statusItem = new ToolStripMenuItem { Enabled = false };
            _pauseItem = new ToolStripMenuItem(L.T("tray.menu.pause"), null, (s, e) => TogglePause()) { CheckOnClick = true, Checked = settings.Paused };
            _signInItem = new ToolStripMenuItem("", null, (s, e) => SignInOrOut());
            var showItem = new ToolStripMenuItem(L.T("tray.menu.activity"), null, (s, e) => ShowActivity());
            showItem.Font = new Font(showItem.Font, FontStyle.Bold);

            var menu = new ContextMenuStrip();
            menu.Items.AddRange(new ToolStripItem[]
            {
                _userItem,
                _statusItem,
                new ToolStripSeparator(),
                showItem,
                _pauseItem,
                new ToolStripMenuItem(L.T("tray.menu.openRfm"), null, (s, e) => OpenRfm()),
                new ToolStripSeparator(),
                new ToolStripMenuItem(L.T("tray.menu.settings"), null, (s, e) => ShowSettings()),
                _signInItem,
                new ToolStripSeparator(),
                new ToolStripMenuItem(L.T("tray.menu.exit"), null, (s, e) => ExitThread()),
            });

            _icon = new NotifyIcon { Icon = _appIcon, ContextMenuStrip = menu, Visible = true };
            _icon.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) ShowActivity(); };
            _icon.BalloonTipClicked += (s, e) => _balloonClick?.Invoke();

            _watcher.AttentionNeeded += catalog => OnUi(() => QueueNotification(catalog));
            _watcher.SignInNeeded += () => OnUi(() => SetSignedIn(null, notify: true));
            _notifyTimer.Tick += (s, e) => FlushNotifications();

            _refresh = new Timer { Interval = 1000 };
            _refresh.Tick += (s, e) => RefreshStatus();
            _refresh.Start();

            RefreshStatus();
            _watcher.Start();
            CheckSignIn(notify: true);

            if (settings.WatchFolders.Count == 0)
                OnUi(ShowSettings);
        }

        public CatalogWatcher Watcher => _watcher;
        public TraySettings Settings => _settings;
        public string User => _user;

        public void OpenFolder(string path)
        {
            if (Directory.Exists(path))
                Process.Start("explorer.exe", $"\"{path}\"");
        }

        /// <summary>Select the folder in the RFM WebUI (reuses an open tab via RFMLauncher).</summary>
        public void OpenInRfm(string path)
        {
            string launcher = Path.Combine(Path.GetDirectoryName(Application.ExecutablePath), "RFMLauncher.exe");
            if (File.Exists(launcher))
                Process.Start(launcher, $"--prepare \"{path}\"");
            else
                OpenRfm();
        }

        public void ShowIssue(Catalog catalog)
        {
            new IssueForm(this, catalog).Show();
        }

        public void ShowSettings()
        {
            using (var form = new SettingsForm(_config, _settings))
            {
                if (form.ShowDialog() == DialogResult.OK)
                {
                    _settings.Save();
                    Log.Level = _settings.LogLevel;
                    Log.Info($"Settings saved: watching {string.Join(", ", _settings.WatchFolders)}; " +
                             $"quiet {_settings.QuietSeconds} s; paused {_settings.Paused}; log {_settings.LogLevel}");
                    _pauseItem.Checked = _settings.Paused;
                    _watcher.RestartWatchers();
                    RefreshStatus();
                }
            }
        }

        public void ShowActivity()
        {
            if (_activity == null || _activity.IsDisposed)
                _activity = new ActivityForm(this);
            _activity.Show();
            _activity.WindowState = FormWindowState.Normal;
            _activity.Activate();
        }

        private void OpenRfm()
        {
            string url = string.IsNullOrEmpty(_config.FrontendBaseUrl) ? _config.ApiBaseUrl : _config.FrontendBaseUrl;
            Process.Start(new ProcessStartInfo(url.TrimEnd('/') + "/pages/explorer.html") { UseShellExecute = true });
        }

        private void TogglePause()
        {
            _settings.Paused = _pauseItem.Checked;
            _settings.Save();
            Log.Info($"Paused: {_settings.Paused}");
            _watcher.Wake();
            RefreshStatus();
        }

        private void CheckSignIn(bool notify)
        {
            Task.Run(() => _client.CurrentUser()).ContinueWith(t =>
            {
                if (t.IsFaulted)
                    Log.Error("Reading the saved sign-in", t.Exception);
                OnUi(() => SetSignedIn(t.IsFaulted ? null : t.Result, notify));
            });
        }

        private void SetSignedIn(string user, bool notify)
        {
            _user = user;
            Log.Info($"RFM user: {user ?? "(none)"}");
            _watcher.SignedIn = user != null;
            RefreshStatus();
            if (user == null && notify && !_signingIn)
                Notify(L.T("tray.notify.signInTitle"), L.T("tray.notify.signIn"), ToolTipIcon.Warning, SignInOrOut);
        }

        private void SignInOrOut()
        {
            if (_signingIn)
                return;
            if (_user != null)
            {
                _client.SignOut();
                SetSignedIn(null, notify: false);
                return;
            }

            // Opens the browser for approval, like the context menu does
            _signingIn = true;
            RefreshStatus();
            Task.Run(() => _client.SignIn()).ContinueWith(t => OnUi(() =>
            {
                _signingIn = false;
                CheckSignIn(notify: false);
            }));
        }

        private void QueueNotification(Catalog catalog)
        {
            _pendingIssues.Add(catalog);
            _notifyTimer.Stop();
            _notifyTimer.Start();
        }

        private void FlushNotifications()
        {
            _notifyTimer.Stop();
            if (_pendingIssues.Count == 1)
            {
                var catalog = _pendingIssues[0];
                Notify(catalog.Name, ActivityForm.Describe(catalog, _settings), ToolTipIcon.Warning, () => ShowIssue(catalog));
            }
            else if (_pendingIssues.Count > 1)
            {
                Notify(L.T("tray.notify.manyTitle", ("count", _pendingIssues.Count)),
                    string.Join(", ", _pendingIssues.Select(c => c.Name).Take(5)),
                    ToolTipIcon.Warning, ShowActivity);
            }
            _pendingIssues.Clear();
        }

        private void Notify(string title, string text, ToolTipIcon icon, Action onClick)
        {
            _balloonClick = onClick;
            _icon.ShowBalloonTip(10000, title, text, icon);
        }

        private void RefreshStatus()
        {
            var catalogs = _watcher.Snapshot();
            int attention = catalogs.Count(c => c.State == CatalogState.NeedsAttention || c.State == CatalogState.Retrying);
            int waiting = catalogs.Count(c => c.State == CatalogState.Waiting || c.State == CatalogState.Queued || c.State == CatalogState.Pushing);

            _userItem.Text = _signingIn ? L.T("tray.status.signingIn")
                : _user != null ? L.T("tray.status.signedIn", ("user", _user))
                : L.T("tray.status.signedOut");
            _signInItem.Text = _user != null ? L.T("tray.menu.signOut") : L.T("tray.menu.signIn");
            _signInItem.Enabled = !_signingIn;

            string status = _settings.Paused ? L.T("tray.status.paused")
                : _settings.WatchFolders.Count == 0 ? L.T("tray.status.notConfigured")
                : L.T("tray.status.counts", ("waiting", waiting), ("attention", attention));
            _statusItem.Text = status;

            // Tooltips are limited to 63 characters
            string tip = "RFM – " + status;
            _icon.Text = tip.Length > 63 ? tip.Substring(0, 63) : tip;

            var icon = attention > 0 || _user == null ? SystemIcons.Warning : _appIcon;
            if (_icon.Icon != icon)
                _icon.Icon = icon;

            _activity?.RefreshList(catalogs);
        }

        private void OnUi(Action action)
        {
            if (!_ui.IsDisposed)
                _ui.BeginInvoke(action);
        }

        protected override void ExitThreadCore()
        {
            _refresh.Stop();
            _watcher.Dispose();
            _icon.Visible = false;
            _icon.Dispose();
            base.ExitThreadCore();
        }
    }
}
