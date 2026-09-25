using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace RFMTray
{
    /// <summary>
    /// First-run guide: what RFM Tray does and what the user will see, then
    /// sign-in, folder and a check against the real server. It can only be
    /// finished once RFM has confirmed the sign-in and sees the folder, so a
    /// user who got through it has a Tray that can send.
    /// </summary>
    public class OnboardingForm : Form
    {
        private readonly TrayContext _context;
        private readonly Label _title, _step;
        private readonly Panel _body;
        private readonly Button _back, _next, _cancel;
        private readonly List<Control> _pages = new List<Control>();
        private int _page;

        // Sign-in page
        private Label _signInStatus;
        private Button _signInButton;
        private string _confirmedUser;
        private bool _signingIn;

        // Folder page
        private ListBox _folders;

        // Check page
        private CheckPanel _check;
        private Label _whatNext;
        private CheckBox _notifySent;

        public OnboardingForm(TrayContext context)
        {
            _context = context;

            Text = L.T("tray.onboarding.windowTitle");
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            StartPosition = FormStartPosition.CenterScreen;
            Font = SystemFonts.MessageBoxFont;
            Size = new Size(760, 580);
            MinimumSize = new Size(600, 480);
            MaximizeBox = false;

            var header = new Panel { Dock = DockStyle.Top, Height = 72, BackColor = SystemColors.Window, Padding = new Padding(16, 12, 16, 8) };
            _step = new Label { Dock = DockStyle.Top, AutoSize = false, Height = 18, ForeColor = SystemColors.GrayText };
            _title = new Label { Dock = DockStyle.Top, AutoSize = false, Height = 30, Font = new Font(Font.FontFamily, Font.Size + 5, FontStyle.Bold) };
            header.Controls.Add(_title);
            header.Controls.Add(_step);

            _body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(16, 12, 16, 8) };

            var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
            _cancel = new Button { Text = L.T("tray.onboarding.later"), AutoSize = true };
            _next = new Button { Text = L.T("tray.onboarding.next"), AutoSize = true };
            _back = new Button { Text = L.T("tray.onboarding.back"), AutoSize = true };
            _cancel.Click += (s, e) => Close();
            _next.Click += (s, e) => Next();
            _back.Click += (s, e) => ShowPage(_page - 1);
            buttons.Controls.AddRange(new Control[] { _cancel, _next, _back });

            Controls.Add(_body);
            Controls.Add(new Label { Dock = DockStyle.Top, Height = 1, BackColor = SystemColors.ControlDark });
            Controls.Add(header);
            Controls.Add(buttons);

            _pages.Add(WelcomePage());
            _pages.Add(SignInPage());
            _pages.Add(FolderPage());
            _pages.Add(CheckPage());
            ShowPage(0);
            AcceptButton = _next;
        }

        private static Label Para(string text) =>
            new Label { Text = text, Dock = DockStyle.Top, AutoSize = true, MaximumSize = new Size(700, 0), Padding = new Padding(0, 0, 0, 10) };

        /// <summary>Stack controls top to bottom (DockStyle.Top docks in reverse order).</summary>
        private static Panel Stack(params Control[] controls)
        {
            var panel = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
            foreach (var control in controls.Reverse())
                panel.Controls.Add(control);
            return panel;
        }

        private Control WelcomePage()
        {
            string folder = _context.Settings.WatchFolders.FirstOrDefault() ?? L.T("tray.onboarding.yourFolder");
            return Stack(
                Para(L.T("tray.onboarding.welcomeIntro")),
                Para(L.T("tray.onboarding.welcomeHow", ("folder", folder), ("seconds", _context.Settings.QuietSeconds))),
                Para(L.T("tray.onboarding.welcomeProblems")),
                Para(L.T("tray.onboarding.welcomeIcon")),
                Para(L.T("tray.onboarding.welcomeSteps")));
        }

        private Control SignInPage()
        {
            _signInStatus = new Label { Dock = DockStyle.Top, AutoSize = true, MaximumSize = new Size(700, 0), Padding = new Padding(0, 6, 0, 10), Font = new Font(Font, FontStyle.Bold) };
            _signInButton = new Button { Text = L.T("tray.onboarding.signInButton"), AutoSize = true, Padding = new Padding(10, 3, 10, 3) };
            _signInButton.Click += (s, e) => SignIn();
            var buttonRow = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(0, 0, 0, 12) };
            buttonRow.Controls.Add(_signInButton);
            return Stack(Para(L.T("tray.onboarding.signInText")), _signInStatus, buttonRow, Para(L.T("tray.onboarding.signInHint")));
        }

        private Control FolderPage()
        {
            _folders = new ListBox { Dock = DockStyle.Fill, IntegralHeight = false, HorizontalScrollbar = true };
            _folders.Items.AddRange(_context.Settings.WatchFolders.Cast<object>().ToArray());

            var add = new Button { Text = L.T("tray.settings.add"), AutoSize = true };
            var remove = new Button { Text = L.T("tray.settings.remove"), AutoSize = true };
            add.Click += (s, e) =>
            {
                string path = FolderPicker.Pick(this, _context.Config, this.Text);
                if (path != null && !_folders.Items.Cast<string>().Contains(path, StringComparer.OrdinalIgnoreCase))
                    _folders.Items.Add(path);
                UpdateButtons();
            };
            remove.Click += (s, e) =>
            {
                if (_folders.SelectedIndex >= 0)
                    _folders.Items.RemoveAt(_folders.SelectedIndex);
                UpdateButtons();
            };
            var side = new FlowLayoutPanel { Dock = DockStyle.Right, FlowDirection = FlowDirection.TopDown, AutoSize = true };
            side.Controls.Add(add);
            side.Controls.Add(remove);

            var listArea = new Panel { Dock = DockStyle.Fill };
            listArea.Controls.Add(_folders);
            listArea.Controls.Add(side);

            var page = new Panel { Dock = DockStyle.Fill };
            page.Controls.Add(listArea);
            page.Controls.Add(Para(L.T("tray.onboarding.folderWarning")));
            page.Controls.Add(Para(L.T("tray.onboarding.folderText")));
            return page;
        }

        private Control CheckPage()
        {
            _check = new CheckPanel(_context, () => _folders.Items.Cast<string>()) { Dock = DockStyle.Fill };
            _check.Finished += passed =>
            {
                _whatNext.Visible = passed;
                UpdateButtons();
            };
            _whatNext = new Label { Dock = DockStyle.Bottom, AutoSize = true, MaximumSize = new Size(700, 0), Padding = new Padding(0, 8, 0, 4), Visible = false };
            _notifySent = new CheckBox { Text = L.T("tray.settings.notifySent"), Checked = _context.Settings.NotifySent, AutoSize = true, Dock = DockStyle.Bottom };

            var page = new Panel { Dock = DockStyle.Fill };
            page.Controls.Add(_check);
            page.Controls.Add(Para(L.T("tray.onboarding.checkText")));
            page.Controls.Add(_whatNext);
            page.Controls.Add(_notifySent);
            return page;
        }

        private void ShowPage(int index)
        {
            _page = Math.Max(0, Math.Min(index, _pages.Count - 1));
            _body.Controls.Clear();
            _body.Controls.Add(_pages[_page]);

            string[] titles = { "welcomeTitle", "signInTitle", "folderTitle", "checkTitle" };
            _title.Text = L.T("tray.onboarding." + titles[_page]);
            _step.Text = _page == 0 ? "RFM Tray" : L.T("tray.onboarding.stepOf", ("step", _page), ("steps", _pages.Count - 1));

            if (_page == 1)
                RefreshSignIn();
            if (_page == 3)
            {
                string folder = _folders.Items.Cast<string>().FirstOrDefault() ?? "";
                _whatNext.Text = L.T("tray.onboarding.whatNext", ("folder", folder), ("seconds", _context.Settings.QuietSeconds));
                _whatNext.Visible = false;
                _check.Run();
            }
            UpdateButtons();
        }

        private void UpdateButtons()
        {
            _back.Visible = _page > 0;
            bool last = _page == _pages.Count - 1;
            _next.Text = L.T(last ? "tray.onboarding.finish" : "tray.onboarding.next");
            switch (_page)
            {
                case 1:
                    _next.Enabled = _confirmedUser != null;
                    break;
                case 2:
                    _next.Enabled = _folders.Items.Count > 0;
                    break;
                case 3:
                    _next.Enabled = !_check.Running && _check.Passed;
                    break;
                default:
                    _next.Enabled = true;
                    break;
            }
        }

        private void Next()
        {
            if (_page < _pages.Count - 1)
            {
                ShowPage(_page + 1);
                return;
            }
            _context.FinishOnboarding(_folders.Items.Cast<string>().ToList(), _notifySent.Checked);
            Close();
        }

        /// <summary>Ask RFM who the saved sign-in belongs to (not just whether a token is stored).</summary>
        private void RefreshSignIn()
        {
            if (_signingIn)
                return;
            _confirmedUser = null;
            _signInStatus.ForeColor = SystemColors.WindowText;
            _signInStatus.Text = L.T("tray.onboarding.signInChecking");
            _signInButton.Enabled = false;
            UpdateButtons();

            Task.Run(() =>
            {
                try
                {
                    return (User: _context.Client.ConfirmedUser(), Error: (string)null);
                }
                catch (SignInRequiredException)
                {
                    return (User: (string)null, Error: (string)null);
                }
                catch (Exception ex)
                {
                    return (User: (string)null, Error: RfmClient.Describe(ex));
                }
            }).ContinueWith(t => BeginInvokeSafe(() =>
            {
                var (user, error) = t.Result;
                _confirmedUser = user;
                _signInButton.Enabled = true;
                _signInButton.Text = L.T(user != null ? "tray.onboarding.signInOther" : "tray.onboarding.signInButton");
                _signInStatus.ForeColor = user != null ? Color.DarkGreen : error != null ? Color.DarkRed : SystemColors.WindowText;
                _signInStatus.Text = user != null ? L.T("tray.onboarding.signedIn", ("user", user))
                    : error != null ? L.T("tray.onboarding.signInError", ("url", _context.Client.ServerUrl), ("error", error))
                    : L.T("tray.onboarding.notSignedIn");
                if (user != null)
                    _context.SignedInAs(user);
                UpdateButtons();
            }));
        }

        private void SignIn()
        {
            _signingIn = true;
            _confirmedUser = null;
            _signInButton.Enabled = false;
            _signInStatus.ForeColor = SystemColors.WindowText;
            _signInStatus.Text = L.T("tray.onboarding.signInWaiting");
            UpdateButtons();

            _context.SignInThen(() => BeginInvokeSafe(() =>
            {
                _signingIn = false;
                RefreshSignIn();
                Activate();
            }));
        }

        private void BeginInvokeSafe(Action action)
        {
            if (!IsDisposed && IsHandleCreated)
                BeginInvoke(action);
        }
    }
}
