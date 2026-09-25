using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using RFMLauncher;

namespace RFMTray
{
    public enum TrayHealth
    {
        /// <summary>Not yet confirmed with RFM since start (or a sign-in is being approved).</summary>
        Checking,
        NotConfigured,
        NotSignedIn,
        /// <summary>RFM unreachable or answering with errors; retried automatically.</summary>
        ServerProblem,
        FolderUnreachable,
        Paused,
        Attention,
        Ok,
    }

    /// <summary>What RFM Tray is doing, in one sentence, with the one action that fixes it.</summary>
    public class TrayStatus
    {
        public TrayHealth Health;
        public string Text;
        public string ActionText;
        public Action Action;

        public bool Good => Health == TrayHealth.Ok || Health == TrayHealth.Checking;
    }

    /// <summary>
    /// The tray icon: status, menu, notifications and the windows behind them.
    /// </summary>
    public class TrayContext : ApplicationContext
    {
        // Confirm the sign-in with RFM this often; sooner while something is wrong
        private static readonly TimeSpan CheckWhenOk = TimeSpan.FromMinutes(10);
        private static readonly TimeSpan CheckWhenNot = TimeSpan.FromMinutes(1);
        private static readonly TimeSpan SignInReminder = TimeSpan.FromMinutes(30);
        private const string ShowEventName = @"Local\RFMTray.Show";

        private readonly Config _config;
        private readonly TraySettings _settings;
        private readonly RfmClient _client;
        private readonly CatalogWatcher _watcher;
        private readonly NotifyIcon _icon;
        private readonly Icon _appIcon;
        private readonly System.Windows.Forms.Timer _refresh;
        private readonly Control _ui = new Control();
        private readonly ToolStripMenuItem _userItem, _statusItem, _pauseItem, _signInItem;

        // Gathered for the next notification, so a batch of 30 folders makes
        // one notification rather than thirty
        private readonly List<Catalog> _pendingIssues = new List<Catalog>();
        private readonly List<Catalog> _pendingSent = new List<Catalog>();
        private readonly System.Windows.Forms.Timer _notifyTimer = new System.Windows.Forms.Timer { Interval = 1500 };
        private Action _balloonClick;

        private ActivityForm _activity;
        private OnboardingForm _onboarding;
        private string _user;
        private bool _signingIn;

        // What RFM itself last said
        private bool _serverConfirmed;
        private string _serverError;
        private DateTime _serverErrorSince;
        private bool _checking;
        private DateTime _nextCheckUtc;
        private DateTime _lastReminderUtc;
        private Catalog _lastSent;

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
            _statusItem = new ToolStripMenuItem("", null, (s, e) => Status.Action?.Invoke());
            _pauseItem = new ToolStripMenuItem(L.T("tray.menu.pause"), null, (s, e) => TogglePause()) { CheckOnClick = true, Checked = settings.Paused };
            _signInItem = new ToolStripMenuItem("", null, (s, e) => SignInOrOut());
            var showItem = new ToolStripMenuItem(L.T("tray.menu.activity"), null, (s, e) => ShowActivity());
            showItem.Font = new Font(showItem.Font, FontStyle.Bold);

            var menu = new ContextMenuStrip();
            menu.Items.AddRange(new ToolStripItem[]
            {
                _statusItem,
                _userItem,
                new ToolStripSeparator(),
                showItem,
                _pauseItem,
                new ToolStripMenuItem(L.T("tray.menu.openRfm"), null, (s, e) => OpenRfm()),
                new ToolStripSeparator(),
                new ToolStripMenuItem(L.T("tray.menu.check"), null, (s, e) => ShowCheck()),
                new ToolStripMenuItem(L.T("tray.menu.guide"), null, (s, e) => ShowOnboarding()),
                new ToolStripMenuItem(L.T("tray.menu.settings"), null, (s, e) => ShowSettings()),
                _signInItem,
                new ToolStripSeparator(),
                new ToolStripMenuItem(L.T("tray.menu.exit"), null, (s, e) => ExitThread()),
            });

            _icon = new NotifyIcon { Icon = _appIcon, ContextMenuStrip = menu, Visible = true };
            _icon.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) ShowActivity(); };
            _icon.BalloonTipClicked += (s, e) => _balloonClick?.Invoke();

            _watcher.AttentionNeeded += catalog => OnUi(() => QueueNotification(_pendingIssues, catalog));
            _watcher.Sent += catalog => OnUi(() => OnSent(catalog));
            _watcher.SignInNeeded += () => OnUi(() => SetSignedIn(null, notify: true));
            _notifyTimer.Tick += (s, e) => FlushNotifications();

            Status = new TrayStatus { Health = TrayHealth.Checking, Text = L.T("tray.health.checking") };
            _refresh = new System.Windows.Forms.Timer { Interval = 1000 };
            _refresh.Tick += (s, e) => RefreshStatus();
            _refresh.Start();

            // Until RFM answers, trust the saved sign-in so folders are not held at logon
            Task.Run(() => _client.CurrentUser()).ContinueWith(t => OnUi(() =>
            {
                if (_user == null && !t.IsFaulted)
                    SetSignedIn(t.Result, notify: false);
                CheckServer(notify: true);
            }));
            RefreshStatus();
            _watcher.Start();

            if (settings.Onboarded < TraySettings.OnboardingVersion)
                OnUi(ShowOnboarding);
            ListenForShow();
        }

        /// <summary>Ask the instance already running in this session to show its window.</summary>
        public static void SignalShow()
        {
            try
            {
                using (var show = EventWaitHandle.OpenExisting(ShowEventName))
                    show.Set();
            }
            catch (WaitHandleCannotBeOpenedException)
            {
                // Still starting up: nothing to show yet
            }
        }

        private void ListenForShow()
        {
            var show = new EventWaitHandle(false, EventResetMode.AutoReset, ShowEventName);
            new Thread(() =>
            {
                while (show.WaitOne())
                    OnUi(() =>
                    {
                        if (_settings.Onboarded < TraySettings.OnboardingVersion)
                            ShowOnboarding();
                        else
                            ShowActivity();
                    });
            }) { IsBackground = true, Name = "RFM Tray show requests" }.Start();
        }

        public CatalogWatcher Watcher => _watcher;
        public TraySettings Settings => _settings;
        public RfmClient Client => _client;
        public Config Config => _config;
        public string User => _user;
        public TrayStatus Status { get; private set; }
        public Catalog LastSent => _lastSent;

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
                    SettingsChanged();
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

        public void ShowCheck()
        {
            new CheckForm(this).Show();
        }

        public void ShowOnboarding()
        {
            if (_onboarding == null || _onboarding.IsDisposed)
                _onboarding = new OnboardingForm(this);
            _onboarding.Show();
            _onboarding.Activate();
        }

        /// <summary>The onboarding passed its check: save and start sending.</summary>
        public void FinishOnboarding(List<string> folders, bool notifySent)
        {
            _settings.WatchFolders = folders;
            _settings.NotifySent = notifySent;
            _settings.Paused = false;
            _settings.Onboarded = TraySettings.OnboardingVersion;
            Log.Info("Onboarding finished");
            SettingsChanged();
            Notify(L.T("tray.notify.readyTitle"), L.T("tray.notify.ready", ("folder", folders.FirstOrDefault())), ToolTipIcon.Info, ShowActivity);
        }

        /// <summary>RFM confirmed this user (onboarding sign-in page).</summary>
        public void SignedInAs(string user)
        {
            _serverConfirmed = true;
            _serverError = null;
            SetSignedIn(user, notify: false);
        }

        /// <summary>Browser sign-in; <paramref name="done"/> runs on a worker thread when it ends either way.</summary>
        public void SignInThen(Action done)
        {
            if (_signingIn)
                return;
            _signingIn = true;
            RefreshStatus();
            Task.Run(() => _client.SignIn()).ContinueWith(t => OnUi(() =>
            {
                _signingIn = false;
                Log.Info($"Browser sign-in ended: {(t.IsFaulted ? t.Exception.GetBaseException().Message : t.Result.ToString())}");
                CheckServer(notify: false);
                done?.Invoke();
            }));
        }

        /// <summary>A full check ran (check window or onboarding): take what RFM said as the current state.</summary>
        public void CheckCompleted(List<CheckStep> steps)
        {
            var server = steps.FirstOrDefault();
            if (server != null && server.Status == CheckStatus.Failed)
                OnServerAnswer(server.Detail);
            else
                CheckServer(notify: false);
        }

        private void SettingsChanged()
        {
            _settings.Save();
            Log.Level = _settings.LogLevel;
            Log.Info($"Settings saved: watching {string.Join(", ", _settings.WatchFolders)}; " +
                     $"quiet {_settings.QuietSeconds} s; paused {_settings.Paused}; notify sent {_settings.NotifySent}; log {_settings.LogLevel}");
            _pauseItem.Checked = _settings.Paused;
            _watcher.RestartWatchers();
            RefreshStatus();
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

        private void Resume()
        {
            _pauseItem.Checked = false;
            TogglePause();
        }

        /// <summary>
        /// Ask RFM whether the saved sign-in is valid. A stored token proves
        /// nothing (expired, revoked, or RFM unreachable), so this is what the
        /// status rests on; it runs at start and then periodically.
        /// </summary>
        private void CheckServer(bool notify)
        {
            if (_checking || _signingIn)
                return;
            _checking = true;
            Task.Run(() =>
            {
                try
                {
                    return (User: _client.ConfirmedUser(), Error: (string)null, SignedOut: false);
                }
                catch (SignInRequiredException)
                {
                    return (User: (string)null, Error: (string)null, SignedOut: true);
                }
                catch (Exception ex)
                {
                    return (User: (string)null, Error: RfmClient.Describe(ex), SignedOut: false);
                }
            }).ContinueWith(t => OnUi(() =>
            {
                _checking = false;
                var (user, error, signedOut) = t.Result;
                if (error != null)
                {
                    // Unknown whether signed in; keep what we had
                    OnServerAnswer(error);
                }
                else
                {
                    _serverConfirmed = true;
                    OnServerAnswer(null);
                    SetSignedIn(signedOut ? null : user, notify && signedOut);
                }
                _nextCheckUtc = DateTime.UtcNow + (Status.Health == TrayHealth.Ok ? CheckWhenOk : CheckWhenNot);
            }));
        }

        /// <summary>RFM answered (null) or failed with this error.</summary>
        private void OnServerAnswer(string error)
        {
            if (error == null)
            {
                if (_serverError != null)
                    Log.Info("RFM reachable again");
                _serverError = null;
                _serverConfirmed = true;
            }
            else
            {
                if (_serverError == null)
                    _serverErrorSince = DateTime.Now;
                _serverError = error;
            }
            RefreshStatus();
        }

        private void SetSignedIn(string user, bool notify)
        {
            if (user != _user)
                Log.Info($"RFM user: {user ?? "(none)"}");
            _user = user;
            _watcher.SignedIn = user != null;
            RefreshStatus();
            // The onboarding shows the sign-in itself
            if (user == null && notify && !_signingIn && !(_onboarding?.Visible ?? false))
            {
                _lastReminderUtc = DateTime.UtcNow;
                Notify(L.T("tray.notify.signInTitle"), L.T("tray.notify.signIn"), ToolTipIcon.Warning, SignInOrOut);
            }
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
            SignInThen(null);
        }

        private void OnSent(Catalog catalog)
        {
            _lastSent = catalog;
            OnServerAnswer(null);
            Log.Info($"{catalog.Name}: sent");
            if (!_settings.FirstPushConfirmed)
            {
                // Proof that the whole chain works, once
                _settings.FirstPushConfirmed = true;
                _settings.Save();
                Notify(L.T("tray.notify.firstTitle"), L.T("tray.notify.first", ("name", catalog.Name)), ToolTipIcon.Info, ShowActivity);
                return;
            }
            if (_settings.NotifySent)
                QueueNotification(_pendingSent, catalog);
        }

        private void QueueNotification(List<Catalog> list, Catalog catalog)
        {
            list.Add(catalog);
            _notifyTimer.Stop();
            _notifyTimer.Start();
        }

        private void FlushNotifications()
        {
            _notifyTimer.Stop();
            // Problems first: one balloon at a time, and they need the user
            if (_pendingIssues.Count == 1)
            {
                var catalog = _pendingIssues[0];
                Notify(catalog.Name, ActivityForm.Describe(catalog, this), ToolTipIcon.Warning, () => ShowIssue(catalog));
            }
            else if (_pendingIssues.Count > 1)
            {
                Notify(L.T("tray.notify.manyTitle", ("count", _pendingIssues.Count)),
                    string.Join(", ", _pendingIssues.Select(c => c.Name).Take(5)),
                    ToolTipIcon.Warning, ShowActivity);
            }
            else if (_pendingSent.Count == 1)
            {
                Notify(L.T("tray.notify.sentTitle"), L.T("tray.notify.sent", ("name", _pendingSent[0].Name)), ToolTipIcon.Info, ShowActivity);
            }
            else if (_pendingSent.Count > 1)
            {
                Notify(L.T("tray.notify.sentManyTitle", ("count", _pendingSent.Count)),
                    string.Join(", ", _pendingSent.Select(c => c.Name).Take(5)), ToolTipIcon.Info, ShowActivity);
            }
            _pendingIssues.Clear();
            _pendingSent.Clear();
        }

        private void Notify(string title, string text, ToolTipIcon icon, Action onClick)
        {
            Log.Info($"Notification: {title}: {text}");
            _balloonClick = onClick;
            _icon.ShowBalloonTip(10000, title, string.IsNullOrEmpty(text) ? " " : text, icon);
        }

        private TrayStatus ComputeStatus(List<Catalog> catalogs)
        {
            int attention = catalogs.Count(c => c.State == CatalogState.NeedsAttention);
            var retrying = catalogs.Where(c => c.State == CatalogState.Retrying).OrderBy(c => c.NextAttemptUtc).ToList();
            int waiting = catalogs.Count(c => c.State == CatalogState.Waiting || c.State == CatalogState.Queued
                                              || c.State == CatalogState.Pushing || c.State == CatalogState.Retrying);
            var unreachable = _watcher.UnreachableRoots;

            if (_settings.WatchFolders.Count == 0)
                return new TrayStatus { Health = TrayHealth.NotConfigured, Text = L.T("tray.health.notConfigured"), ActionText = L.T("tray.menu.guide"), Action = ShowOnboarding };
            if (_signingIn)
                return new TrayStatus { Health = TrayHealth.Checking, Text = L.T("tray.status.signingIn") };
            if (_user == null)
                return new TrayStatus
                {
                    Health = TrayHealth.NotSignedIn,
                    Text = waiting > 0 ? L.T("tray.health.notSignedInWaiting", ("count", waiting)) : L.T("tray.health.notSignedIn"),
                    ActionText = L.T("tray.menu.signIn"),
                    Action = SignInOrOut,
                };
            if (_serverError != null)
                return new TrayStatus
                {
                    Health = TrayHealth.ServerProblem,
                    Text = L.T("tray.health.serverProblem", ("time", _serverErrorSince.ToString("HH:mm")), ("error", _serverError)),
                    ActionText = L.T("tray.menu.check"),
                    Action = ShowCheck,
                };
            // RFM answers the check but refuses pushes (e.g. HTTP 500): say so, with RFM's words
            if (retrying.Count > 0)
                return new TrayStatus
                {
                    Health = TrayHealth.ServerProblem,
                    Text = L.T("tray.health.pushFailing", ("count", retrying.Count), ("error", retrying[0].Result?.Message ?? "?"),
                        ("time", retrying[0].NextAttemptUtc.ToLocalTime().ToString("HH:mm"))),
                    ActionText = L.T("tray.menu.activity"),
                    Action = ShowActivity,
                };
            if (unreachable.Count > 0)
                return new TrayStatus
                {
                    Health = TrayHealth.FolderUnreachable,
                    Text = L.T("tray.activity.unreachable", ("folders", string.Join(", ", unreachable))),
                    ActionText = L.T("tray.menu.check"),
                    Action = ShowCheck,
                };
            if (_settings.Paused)
                return new TrayStatus { Health = TrayHealth.Paused, Text = L.T("tray.health.paused", ("count", waiting)), ActionText = L.T("tray.health.resume"), Action = Resume };
            if (attention > 0)
                return new TrayStatus { Health = TrayHealth.Attention, Text = L.T("tray.health.attention", ("count", attention)), ActionText = L.T("tray.menu.activity"), Action = ShowActivity };
            if (!_serverConfirmed)
                return new TrayStatus { Health = TrayHealth.Checking, Text = L.T("tray.health.checking") };

            string text = waiting > 0 ? L.T("tray.health.okBusy", ("count", waiting))
                : _lastSent != null ? L.T("tray.health.okSent", ("name", _lastSent.Name), ("time", _lastSent.StateUtc.ToLocalTime().ToString("HH:mm")))
                : L.T("tray.health.okIdle", ("folder", _settings.WatchFolders[0]));
            return new TrayStatus { Health = TrayHealth.Ok, Text = text };
        }

        private void RefreshStatus()
        {
            var catalogs = _watcher.Snapshot();
            Status = ComputeStatus(catalogs);

            _userItem.Text = _user != null ? L.T("tray.status.signedIn", ("user", _user)) : L.T("tray.status.signedOut");
            _signInItem.Text = _user != null ? L.T("tray.menu.signOut") : L.T("tray.menu.signIn");
            _signInItem.Enabled = !_signingIn;
            _statusItem.Text = Status.ActionText != null ? $"{Status.Text}  →  {Status.ActionText}" : Status.Text;
            _statusItem.Enabled = Status.Action != null;

            // Tooltips are limited to 63 characters
            string tip = "RFM Tray – " + Status.Text;
            _icon.Text = tip.Length > 63 ? tip.Substring(0, 60) + "…" : tip;

            var icon = Status.Good || Status.Health == TrayHealth.Paused ? _appIcon : SystemIcons.Warning;
            if (_icon.Icon != icon)
                _icon.Icon = icon;

            // Folders held for a sign-in nobody noticed: remind now and then
            if (Status.Health == TrayHealth.NotSignedIn && catalogs.Any(c => c.State == CatalogState.Queued)
                && DateTime.UtcNow - _lastReminderUtc > SignInReminder)
            {
                _lastReminderUtc = DateTime.UtcNow;
                Notify(L.T("tray.notify.signInTitle"), Status.Text, ToolTipIcon.Warning, SignInOrOut);
            }

            if (DateTime.UtcNow >= _nextCheckUtc && _nextCheckUtc != default(DateTime))
                CheckServer(notify: _user != null);

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
