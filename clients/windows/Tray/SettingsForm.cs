using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;
using RFMLauncher;

namespace RFMTray
{
    /// <summary>
    /// Which folders to watch, how long to wait after the last change, pause.
    /// </summary>
    public class SettingsForm : Form
    {
        private readonly Config _config;
        private readonly TraySettings _settings;
        private readonly ListBox _folders;
        private readonly NumericUpDown _quiet;
        private readonly CheckBox _paused;
        private readonly ComboBox _logLevel;

        public SettingsForm(Config config, TraySettings settings)
        {
            _config = config;
            _settings = settings;

            Text = L.T("tray.settings.title");
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            StartPosition = FormStartPosition.CenterScreen;
            Font = SystemFonts.MessageBoxFont;
            Size = new Size(620, 480);
            MinimumSize = new Size(480, 420);
            MinimizeBox = false;
            MaximizeBox = false;

            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 7, Padding = new Padding(12) };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            var intro = new Label { Text = L.T("tray.settings.foldersHelp"), AutoSize = true, MaximumSize = new Size(560, 0), Margin = new Padding(3, 0, 3, 8) };
            layout.Controls.Add(intro, 0, 0);
            layout.SetColumnSpan(intro, 2);

            _folders = new ListBox { Dock = DockStyle.Fill, IntegralHeight = false, HorizontalScrollbar = true };
            _folders.Items.AddRange(settings.WatchFolders.Cast<object>().ToArray());
            layout.Controls.Add(_folders, 0, 1);

            var folderButtons = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, Dock = DockStyle.Fill };
            var add = new Button { Text = L.T("tray.settings.add"), AutoSize = true };
            var remove = new Button { Text = L.T("tray.settings.remove"), AutoSize = true };
            add.Click += (s, e) => AddFolder();
            remove.Click += (s, e) => { if (_folders.SelectedIndex >= 0) _folders.Items.RemoveAt(_folders.SelectedIndex); };
            folderButtons.Controls.Add(add);
            folderButtons.Controls.Add(remove);
            layout.Controls.Add(folderButtons, 1, 1);

            var quietRow = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, Margin = new Padding(0, 12, 0, 0) };
            _quiet = new NumericUpDown
            {
                Minimum = TraySettings.MinQuietSeconds,
                Maximum = 3600,
                Increment = 15,
                Value = settings.QuietSeconds,
                Width = 80,
            };
            quietRow.Controls.Add(new Label { Text = L.T("tray.settings.quiet"), AutoSize = true, Margin = new Padding(3, 6, 3, 0) });
            quietRow.Controls.Add(_quiet);
            layout.Controls.Add(quietRow, 0, 2);
            layout.SetColumnSpan(quietRow, 2);

            var quietHelp = new Label { Text = L.T("tray.settings.quietHelp"), AutoSize = true, MaximumSize = new Size(560, 0), ForeColor = SystemColors.GrayText };
            layout.Controls.Add(quietHelp, 0, 3);
            layout.SetColumnSpan(quietHelp, 2);

            _paused = new CheckBox { Text = L.T("tray.menu.pause"), AutoSize = true, Checked = settings.Paused, Margin = new Padding(3, 12, 3, 0) };
            layout.Controls.Add(_paused, 0, 4);
            layout.SetColumnSpan(_paused, 2);

            // Diagnostics for support: off unless someone asks for it
            var logRow = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, Margin = new Padding(0, 12, 0, 0) };
            _logLevel = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 160 };
            _logLevel.Items.AddRange(new object[] { L.T("tray.settings.logOff"), L.T("tray.settings.logInfo"), L.T("tray.settings.logDebug") });
            _logLevel.SelectedIndex = (int)settings.LogLevel;
            var openLog = new Button { Text = L.T("tray.settings.openLog"), AutoSize = true };
            openLog.Click += (s, e) => { Directory.CreateDirectory(Log.FolderPath); Process.Start("explorer.exe", $"\"{Log.FolderPath}\""); };
            logRow.Controls.Add(new Label { Text = L.T("tray.settings.log"), AutoSize = true, Margin = new Padding(3, 6, 3, 0) });
            logRow.Controls.Add(_logLevel);
            logRow.Controls.Add(openLog);
            layout.Controls.Add(logRow, 0, 5);
            layout.SetColumnSpan(logRow, 2);

            var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.RightToLeft, AutoSize = true, Dock = DockStyle.Fill };
            var cancel = new Button { Text = L.T("tray.settings.cancel"), AutoSize = true, DialogResult = DialogResult.Cancel };
            var save = new Button { Text = L.T("tray.settings.save"), AutoSize = true };
            save.Click += (s, e) => Save();
            buttons.Controls.Add(cancel);
            buttons.Controls.Add(save);
            layout.Controls.Add(buttons, 0, 6);
            layout.SetColumnSpan(buttons, 2);

            AcceptButton = save;
            CancelButton = cancel;
            Controls.Add(layout);
        }

        private void AddFolder()
        {
            using (var dialog = new FolderBrowserDialog { Description = L.T("tray.settings.pick"), ShowNewFolderButton = false })
            {
                if (_folders.Items.Count == 0 && _config.AllowedPaths.Count > 0)
                    dialog.SelectedPath = _config.AllowedPaths[0];
                if (dialog.ShowDialog(this) != DialogResult.OK)
                    return;

                string path = dialog.SelectedPath.TrimEnd('\\');
                if (!PathRules.IsPathAllowed(path, _config))
                {
                    MessageBox.Show(this,
                        L.T("tray.settings.notAllowed", ("paths", string.Join("\n", _config.AllowedPaths))),
                        Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                if (!_folders.Items.Cast<string>().Contains(path, StringComparer.OrdinalIgnoreCase))
                    _folders.Items.Add(path);
            }
        }

        private void Save()
        {
            // A new list, so the watcher thread never sees one being edited
            _settings.WatchFolders = _folders.Items.Cast<string>().ToList();
            _settings.QuietSeconds = (int)_quiet.Value;
            _settings.Paused = _paused.Checked;
            _settings.LogLevel = (LogLevel)_logLevel.SelectedIndex;
            DialogResult = DialogResult.OK;
        }
    }
}
