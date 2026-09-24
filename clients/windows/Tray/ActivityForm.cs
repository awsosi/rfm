using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;

namespace RFMTray
{
    /// <summary>
    /// Every folder RFM Tray knows about and what is happening to it.
    /// </summary>
    public class ActivityForm : Form
    {
        private readonly TrayContext _context;
        private readonly ListView _list;
        private readonly Label _footer;
        private readonly Button _details, _sendNow, _openFolder, _openRfm;

        public ActivityForm(TrayContext context)
        {
            _context = context;
            Text = L.T("tray.activity.title");
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(820, 440);
            MinimumSize = new Size(560, 300);
            Font = SystemFonts.MessageBoxFont;

            _list = new ListView
            {
                Dock = DockStyle.Fill,
                View = View.Details,
                FullRowSelect = true,
                MultiSelect = false,
                HideSelection = false,
                ShowItemToolTips = true,
            };
            _list.Columns.Add(L.T("tray.activity.folder"), 280);
            _list.Columns.Add(L.T("tray.activity.status"), 420);
            _list.Columns.Add(L.T("tray.activity.files"), 70, HorizontalAlignment.Right);
            _list.SelectedIndexChanged += (s, e) => UpdateButtons();
            _list.DoubleClick += (s, e) => OpenSelected();

            _details = MakeButton(L.T("tray.activity.details"), (s, e) => { var c = Selected(); if (c != null) _context.ShowIssue(c); });
            _sendNow = MakeButton(L.T("tray.activity.sendNow"), (s, e) => { var c = Selected(); if (c != null) _context.Watcher.SendNow(c.Path); });
            _openFolder = MakeButton(L.T("tray.activity.openFolder"), (s, e) => { var c = Selected(); if (c != null) _context.OpenFolder(c.Path); });
            _openRfm = MakeButton(L.T("tray.activity.openRfm"), (s, e) => { var c = Selected(); if (c != null) _context.OpenInRfm(c.Path); });
            var settings = MakeButton(L.T("tray.menu.settings"), (s, e) => _context.ShowSettings());

            var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, AutoSize = true, Padding = new Padding(6) };
            buttons.Controls.AddRange(new Control[] { _details, _sendNow, _openFolder, _openRfm, settings });

            _footer = new Label { Dock = DockStyle.Bottom, AutoSize = false, Height = 24, Padding = new Padding(8, 4, 8, 0), ForeColor = SystemColors.GrayText };

            Controls.Add(_list);
            Controls.Add(buttons);
            Controls.Add(_footer);

            RefreshList(context.Watcher.Snapshot());
        }

        /// <summary>What is happening to a folder, in the user's words.</summary>
        public static string Describe(Catalog c, TraySettings settings)
        {
            switch (c.State)
            {
                case CatalogState.Waiting:
                    if (c.Files == 0)
                        return L.T("tray.state.empty");
                    if (c.Partial)
                        return L.T("tray.state.copying");
                    int left = c.SkipQuiet ? 0 : (int)Math.Ceiling(settings.QuietSeconds - (DateTime.UtcNow - c.ChangedUtc).TotalSeconds);
                    return left > 0 ? L.T("tray.state.waiting", ("seconds", left)) : L.T("tray.state.checking");
                case CatalogState.Queued:
                    return settings.Paused ? L.T("tray.state.paused") : L.T("tray.state.queued");
                case CatalogState.Pushing:
                    return L.T("tray.state.pushing");
                case CatalogState.Pushed:
                    return L.T("tray.state.pushed", ("time", c.StateUtc.ToLocalTime().ToString("HH:mm")));
                case CatalogState.Retrying:
                    return L.T("tray.state.retrying", ("time", c.NextAttemptUtc.ToLocalTime().ToString("HH:mm")));
                default:
                    switch (c.Result?.Outcome)
                    {
                        case PushOutcome.Rejected:
                            return L.T("tray.state.rejected");
                        case PushOutcome.AlreadyPublished:
                            return L.T("tray.state.alreadyPublished");
                        default:
                            return L.T("tray.state.failed");
                    }
            }
        }

        public void RefreshList(List<Catalog> catalogs)
        {
            if (IsDisposed || !Visible)
                return;

            var byPath = catalogs.ToDictionary(c => c.Path, StringComparer.OrdinalIgnoreCase);
            _list.BeginUpdate();
            foreach (ListViewItem item in _list.Items.Cast<ListViewItem>().ToList())
            {
                if (!byPath.ContainsKey(item.Name))
                    item.Remove();
            }
            foreach (var c in catalogs)
            {
                var item = _list.Items[c.Path] ?? _list.Items.Add(new ListViewItem(new[] { "", "", "" }) { Name = c.Path });
                item.Tag = c;
                item.SubItems[0].Text = c.Name;
                item.SubItems[1].Text = Describe(c, _context.Settings);
                item.SubItems[2].Text = c.Files.ToString();
                item.ToolTipText = c.Path;
                item.ForeColor = c.State == CatalogState.NeedsAttention || c.State == CatalogState.Retrying ? Color.DarkRed
                    : c.State == CatalogState.Pushed ? SystemColors.GrayText
                    : SystemColors.WindowText;
            }
            _list.EndUpdate();

            var unreachable = _context.Watcher.UnreachableRoots;
            _footer.Text = unreachable.Count > 0
                ? L.T("tray.activity.unreachable", ("folders", string.Join(", ", unreachable)))
                : _context.Settings.WatchFolders.Count == 0
                    ? L.T("tray.status.notConfigured")
                    : L.T("tray.activity.watching", ("folders", string.Join(", ", _context.Settings.WatchFolders)));
            _footer.ForeColor = unreachable.Count > 0 ? Color.DarkRed : SystemColors.GrayText;
            UpdateButtons();
        }

        private Catalog Selected() => _list.SelectedItems.Count > 0 ? (Catalog)_list.SelectedItems[0].Tag : null;

        private void UpdateButtons()
        {
            var c = Selected();
            bool present = c != null && c.State != CatalogState.Pushed;
            _details.Enabled = c?.Result != null;
            _sendNow.Enabled = present && c.State != CatalogState.Pushing && c.Files > 0;
            _openFolder.Enabled = present;
            _openRfm.Enabled = present;
        }

        private void OpenSelected()
        {
            var c = Selected();
            if (c == null)
                return;
            if (c.Result != null)
                _context.ShowIssue(c);
            else if (c.State != CatalogState.Pushed)
                _context.OpenFolder(c.Path);
        }

        private static Button MakeButton(string text, EventHandler onClick)
        {
            var button = new Button { Text = text, AutoSize = true, Padding = new Padding(6, 2, 6, 2) };
            button.Click += onClick;
            return button;
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            // Closing only hides; the tray keeps running
            if (e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                Hide();
            }
            base.OnFormClosing(e);
        }
    }
}
