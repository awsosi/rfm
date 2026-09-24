using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace RFMTray
{
    /// <summary>
    /// Why RFM refused a folder and what to do about it. For an unrecognised
    /// name it lists RFM's suggestions and renames the folder in one click,
    /// after which it is sent again - the same choice the WebUI offers.
    /// </summary>
    public class IssueForm : Form
    {
        private readonly TrayContext _context;
        private readonly Catalog _catalog;
        private readonly TextBox _newName;
        private readonly ListBox _suggestions;

        public IssueForm(TrayContext context, Catalog catalog)
        {
            _context = context;
            _catalog = catalog;

            Text = "RFM – " + catalog.Name;
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            StartPosition = FormStartPosition.CenterScreen;
            Font = SystemFonts.MessageBoxFont;
            Size = new Size(640, 520);
            MinimumSize = new Size(480, 360);
            TopMost = true;

            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 6, Padding = new Padding(12) };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            layout.Controls.Add(new Label
            {
                Text = catalog.Name,
                Font = new Font(Font.FontFamily, Font.Size + 3, FontStyle.Bold),
                AutoSize = true,
            });
            layout.Controls.Add(new Label { Text = catalog.Path, Dock = DockStyle.Fill, Height = 22, AutoEllipsis = true, ForeColor = SystemColors.GrayText, Margin = new Padding(3, 0, 3, 8) });

            layout.Controls.Add(new TextBox
            {
                Text = Message(catalog),
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                Dock = DockStyle.Fill,
                BackColor = SystemColors.Window,
                TabStop = false,
            });

            // Renaming fixes a name RFM does not recognise; offered whenever the name was the problem
            var suggestions = ValidationText.Suggestions(catalog.Result?.Validation);
            bool nameProblem = (bool?)catalog.Result?.Validation?["catalog"]?["valid"] == false;
            var renameBox = new GroupBox { Text = L.T("tray.issue.rename"), Dock = DockStyle.Fill };
            _suggestions = new ListBox { Dock = DockStyle.Fill, IntegralHeight = false };
            _suggestions.Items.AddRange(suggestions.Cast<object>().ToArray());
            _suggestions.SelectedIndexChanged += (s, e) => { if (_suggestions.SelectedItem != null) _newName.Text = (string)_suggestions.SelectedItem; };
            _suggestions.DoubleClick += (s, e) => RenameAndSend();

            var nameRow = new TableLayoutPanel { Dock = DockStyle.Bottom, ColumnCount = 2, AutoSize = true };
            nameRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            nameRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            _newName = new TextBox { Dock = DockStyle.Fill, Text = suggestions.FirstOrDefault() ?? catalog.Name };
            var renameButton = new Button { Text = L.T("tray.issue.renameAndSend"), AutoSize = true };
            renameButton.Click += (s, e) => RenameAndSend();
            nameRow.Controls.Add(_newName, 0, 0);
            nameRow.Controls.Add(renameButton, 1, 0);

            var hint = new Label
            {
                Text = suggestions.Count > 0 ? L.T("validation.suggestionsHeader") : L.T("validation.noSuggestions"),
                Dock = DockStyle.Top,
                AutoSize = true,
                Padding = new Padding(0, 2, 0, 4),
            };
            renameBox.Controls.Add(_suggestions);
            renameBox.Controls.Add(hint);
            renameBox.Controls.Add(nameRow);
            if (suggestions.Count > 0)
                _suggestions.SelectedIndex = 0;
            // Hidden controls take no table cell, so leave it out rather than hide it
            if (nameProblem)
                layout.Controls.Add(renameBox);
            else
                layout.RowStyles[3] = new RowStyle(SizeType.AutoSize);

            layout.Controls.Add(new Label
            {
                Text = L.T("tray.issue.footer"),
                AutoSize = true,
                MaximumSize = new Size(590, 0),
                ForeColor = SystemColors.GrayText,
                Margin = new Padding(3, 8, 3, 0),
            });

            var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill, AutoSize = true };
            var close = new Button { Text = L.T("tray.issue.close"), AutoSize = true, DialogResult = DialogResult.Cancel };
            var retry = new Button { Text = L.T("tray.issue.retry"), AutoSize = true };
            var openRfm = new Button { Text = L.T("tray.activity.openRfm"), AutoSize = true };
            var openFolder = new Button { Text = L.T("tray.activity.openFolder"), AutoSize = true };
            retry.Click += (s, e) => { _context.Watcher.SendNow(_catalog.Path); Close(); };
            openRfm.Click += (s, e) => _context.OpenInRfm(_catalog.Path);
            openFolder.Click += (s, e) => _context.OpenFolder(_catalog.Path);
            // Sending a published catalog again gets the same refusal
            retry.Visible = catalog.Result?.Outcome != PushOutcome.AlreadyPublished;
            buttons.Controls.AddRange(new Control[] { close, retry, openRfm, openFolder });
            layout.Controls.Add(buttons);

            CancelButton = close;
            Controls.Add(layout);
            ActiveControl = nameProblem ? (Control)_suggestions : close;
        }

        private static string Message(Catalog catalog)
        {
            var result = catalog.Result;
            switch (result?.Outcome)
            {
                case PushOutcome.Rejected:
                    return result.Message;
                case PushOutcome.AlreadyPublished:
                    return L.T("tray.issue.alreadyPublished", ("name", catalog.Name), ("catalog", result.Message));
                case PushOutcome.Transient:
                    return L.T("tray.issue.unavailable", ("error", result.Message ?? ""), ("attempts", catalog.Attempts));
                default:
                    return L.T("tray.issue.failed", ("error", result?.Message ?? ""));
            }
        }

        private void RenameAndSend()
        {
            string name = _newName.Text.Trim();
            if (name.Length == 0 || name == _catalog.Name)
                return;
            if (name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            {
                MessageBox.Show(this, L.T("tray.issue.invalidName"), Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            try
            {
                _context.Watcher.Rename(_catalog.Path, name);
                Close();
            }
            catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException)
            {
                MessageBox.Show(this, L.T("tray.issue.renameFailed", ("error", ex.Message)), Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }
    }
}
