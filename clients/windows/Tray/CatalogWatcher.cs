using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;

namespace RFMTray
{
    public enum CatalogState
    {
        /// <summary>Still being copied, empty, or inside the quiet period.</summary>
        Waiting,
        Queued,
        Pushing,
        Pushed,
        /// <summary>RFM refused it; waits until the folder changes or the user retries.</summary>
        NeedsAttention,
        /// <summary>RFM unreachable; retried with back-off.</summary>
        Retrying,
    }

    /// <summary>
    /// A folder directly inside a watched folder: one catalog to push.
    /// </summary>
    public class Catalog
    {
        public string Path;
        public string Name => System.IO.Path.GetFileName(Path);
        public string Root;
        public CatalogState State;
        public int Files;
        public bool Partial;
        public string Signature;
        /// <summary>When the contents last changed (the quiet period runs from here).</summary>
        public DateTime ChangedUtc;
        public DateTime StateUtc;
        public PushResult Result;
        public int Attempts;
        public DateTime NextAttemptUtc;
        /// <summary>Send without waiting for the quiet period (renamed or "Send now").</summary>
        public bool SkipQuiet;

        public Catalog Copy() => (Catalog)MemberwiseClone();
    }

    /// <summary>
    /// Finds catalogs that have finished copying into the watched folders and
    /// pushes them one at a time.
    ///
    /// Premature pushes are avoided by requiring, in order: at least one file;
    /// no partial/temporary files; no change in file count, sizes or times for
    /// the quiet period; and every file opening without a sharing violation
    /// (a copy still writing holds its file open). File system notifications
    /// only trigger an early rescan: over SMB they can be lost, so the
    /// periodic rescan is what the decision rests on.
    /// </summary>
    public class CatalogWatcher : IDisposable
    {
        private static readonly TimeSpan ScanInterval = TimeSpan.FromSeconds(10);
        private static readonly TimeSpan KeepPushedFor = TimeSpan.FromHours(12);
        private static readonly string[] PartialSuffixes = { ".tmp", ".part", ".partial", ".crdownload", ".download", ".!ut" };
        private static readonly string[] PartialPrefixes = { "~$", ".~lock" };

        /// <summary>Transient failures before the user is told RFM is unreachable.</summary>
        public const int NotifyAfterAttempts = 3;

        private readonly object _lock = new object();
        private readonly Dictionary<string, Catalog> _catalogs = new Dictionary<string, Catalog>(StringComparer.OrdinalIgnoreCase);
        private readonly List<FileSystemWatcher> _watchers = new List<FileSystemWatcher>();
        private readonly AutoResetEvent _wake = new AutoResetEvent(false);
        private readonly RfmClient _client;
        private readonly TraySettings _settings;
        private Thread _thread;
        private volatile bool _stop;
        private volatile bool _signedIn;

        /// <summary>A catalog needs the user (raised on the watcher thread).</summary>
        public event Action<Catalog> AttentionNeeded;
        public event Action SignInNeeded;

        public CatalogWatcher(RfmClient client, TraySettings settings)
        {
            _client = client;
            _settings = settings;
        }

        public bool SignedIn
        {
            get => _signedIn;
            set
            {
                if (_signedIn != value)
                    Log.Info($"Signed in: {value}");
                _signedIn = value;
                _wake.Set();
            }
        }

        /// <summary>Watched folders that cannot be reached right now.</summary>
        public List<string> UnreachableRoots { get; private set; } = new List<string>();

        public void Start()
        {
            RestartWatchers();
            _thread = new Thread(Run) { IsBackground = true, Name = "RFM catalog watcher" };
            _thread.Start();
        }

        /// <summary>Call after the watched folders change.</summary>
        public void RestartWatchers()
        {
            lock (_watchers)
            {
                foreach (var watcher in _watchers)
                    watcher.Dispose();
                _watchers.Clear();

                foreach (var root in _settings.WatchFolders)
                {
                    try
                    {
                        var watcher = new FileSystemWatcher(root) { IncludeSubdirectories = true };
                        watcher.Created += (s, e) => _wake.Set();
                        watcher.Changed += (s, e) => _wake.Set();
                        watcher.Renamed += (s, e) => _wake.Set();
                        watcher.Deleted += (s, e) => _wake.Set();
                        watcher.Error += (s, e) => _wake.Set();
                        watcher.EnableRaisingEvents = true;
                        _watchers.Add(watcher);
                    }
                    catch (Exception ex)
                    {
                        // Share offline: the periodic rescan still covers it
                        Log.Info($"No change notifications for {root}: {ex.Message}");
                    }
                }
            }
            _wake.Set();
        }

        public List<Catalog> Snapshot()
        {
            lock (_lock)
                return _catalogs.Values.Select(c => c.Copy()).OrderBy(c => c.ChangedUtc).ToList();
        }

        /// <summary>Skip the quiet period, or retry after a refusal or outage.</summary>
        public void SendNow(string path)
        {
            lock (_lock)
            {
                if (!_catalogs.TryGetValue(path, out var catalog) || catalog.State == CatalogState.Pushing)
                    return;
                catalog.SkipQuiet = true;
                catalog.Attempts = 0;
                if (catalog.State != CatalogState.Queued)
                    SetState(catalog, CatalogState.Waiting);
            }
            _wake.Set();
        }

        /// <summary>Rename the folder (e.g. to a suggested product name) and send it straight away.</summary>
        public void Rename(string path, string newName)
        {
            string newPath = System.IO.Path.Combine(System.IO.Path.GetDirectoryName(path), newName);
            Directory.Move(path, newPath);

            lock (_lock)
            {
                if (_catalogs.TryGetValue(path, out var old))
                {
                    _catalogs.Remove(path);
                    var renamed = old.Copy();
                    renamed.Path = newPath;
                    renamed.Result = null;
                    renamed.Attempts = 0;
                    // Same contents, already settled
                    renamed.SkipQuiet = true;
                    SetState(renamed, CatalogState.Waiting);
                    _catalogs[newPath] = renamed;
                }
            }
            _wake.Set();
        }

        public void Wake() => _wake.Set();

        private void Run()
        {
            while (!_stop)
            {
                try
                {
                    ScanAll();
                    var next = NextToPush();
                    if (next != null)
                    {
                        Push(next);
                        continue;
                    }
                }
                catch (Exception ex)
                {
                    // Never let one bad folder stop the watcher
                    Log.Error("Watcher loop", ex);
                }

                if (_wake.WaitOne(ScanInterval))
                {
                    // Woken by a file event: let a burst of copy events settle
                    Thread.Sleep(2000);
                }
            }
        }

        private void ScanAll()
        {
            var now = DateTime.UtcNow;
            var started = System.Diagnostics.Stopwatch.StartNew();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var unreachable = new List<string>();
            var quiet = TimeSpan.FromSeconds(_settings.QuietSeconds);

            foreach (var root in _settings.WatchFolders.ToList())
            {
                List<DirectoryInfo> folders;
                try
                {
                    folders = new DirectoryInfo(root).EnumerateDirectories()
                        .Where(d => (d.Attributes & (FileAttributes.Hidden | FileAttributes.System)) == 0
                                    && !d.Name.StartsWith(".") && !d.Name.StartsWith("~"))
                        .ToList();
                }
                catch (Exception ex)
                {
                    if (!UnreachableRoots.Contains(root))
                        Log.Info($"Watched folder unreachable: {root}: {ex.Message}");
                    unreachable.Add(root);
                    continue;
                }

                foreach (var folder in folders)
                {
                    FolderScan snapshot;
                    try
                    {
                        snapshot = ScanFolder(folder);
                    }
                    catch (Exception ex)
                    {
                        Log.Info($"{folder.Name}: cannot be read: {ex.Message}");
                        continue; // Being moved or deleted right now
                    }
                    seen.Add(folder.FullName);

                    bool check;
                    lock (_lock)
                        check = Observe(folder.FullName, root, snapshot, now, quiet);

                    // The lock test opens every file, so only once the folder looks settled
                    if (check && FilesUnlocked(folder))
                    {
                        lock (_lock)
                        {
                            if (_catalogs.TryGetValue(folder.FullName, out var catalog) && catalog.State == CatalogState.Waiting)
                                SetState(catalog, CatalogState.Queued);
                        }
                    }
                }
            }

            lock (_lock)
            {
                foreach (var catalog in _catalogs.Values.ToList())
                {
                    if (seen.Contains(catalog.Path) || catalog.State == CatalogState.Pushing)
                        continue;
                    // Pushed catalogs leave the folder; keep them a while as history
                    if (catalog.State != CatalogState.Pushed || now - catalog.StateUtc > KeepPushedFor)
                    {
                        if (catalog.State != CatalogState.Pushed)
                            Log.Info($"{catalog.Name}: no longer in the watched folder ({catalog.State})");
                        _catalogs.Remove(catalog.Path);
                    }
                }
                Log.Debug($"Scan: {seen.Count} folders in {started.ElapsedMilliseconds} ms; " +
                          string.Join(", ", _catalogs.Values.GroupBy(c => c.State).Select(g => $"{g.Key} {g.Count()}")));
            }
            foreach (var root in UnreachableRoots.Except(unreachable))
                Log.Info($"Watched folder reachable again: {root}");
            UnreachableRoots = unreachable;
        }

        /// <summary>Record a scan of one folder; true when it looks ready to send.</summary>
        private bool Observe(string path, string root, FolderScan snapshot, DateTime now, TimeSpan quiet)
        {
            if (!_catalogs.TryGetValue(path, out var catalog))
            {
                catalog = new Catalog { Path = path, Signature = snapshot.Signature, ChangedUtc = now };
                Log.Info($"{catalog.Name}: found in {root} ({snapshot.Signature})");
                SetState(catalog, CatalogState.Waiting);
                _catalogs[path] = catalog;
            }
            else if (catalog.Signature != snapshot.Signature)
            {
                // New or changed files: whatever was decided before no longer holds
                Log.Debug($"{catalog.Name}: changed {catalog.Signature} -> {snapshot.Signature}");
                catalog.Signature = snapshot.Signature;
                catalog.ChangedUtc = now;
                catalog.SkipQuiet = false;
                catalog.Attempts = 0;
                if (catalog.State != CatalogState.Pushing)
                    SetState(catalog, CatalogState.Waiting);
            }

            catalog.Root = root;
            catalog.Files = snapshot.Files;
            catalog.Partial = snapshot.Partial;

            return catalog.State == CatalogState.Waiting
                && snapshot.Files > 0
                && !snapshot.Partial
                && (catalog.SkipQuiet || now - catalog.ChangedUtc >= quiet);
        }

        private Catalog NextToPush()
        {
            var now = DateTime.UtcNow;
            lock (_lock)
            {
                if (_settings.Paused || !_signedIn)
                {
                    int held = _catalogs.Values.Count(c => c.State == CatalogState.Queued || c.State == CatalogState.Retrying);
                    if (held > 0)
                        Log.Debug($"{held} ready, held: {(_settings.Paused ? "paused" : "not signed in")}");
                    return null;
                }
                return _catalogs.Values
                    .Where(c => c.State == CatalogState.Queued
                                || (c.State == CatalogState.Retrying && now >= c.NextAttemptUtc))
                    .OrderBy(c => c.ChangedUtc)
                    .FirstOrDefault();
            }
        }

        private void Push(Catalog catalog)
        {
            lock (_lock)
                SetState(catalog, CatalogState.Pushing);

            var started = System.Diagnostics.Stopwatch.StartNew();
            var result = Directory.Exists(catalog.Path)
                ? _client.Push(catalog.Path)
                : new PushResult { Outcome = PushOutcome.Gone };
            if (result.Outcome != PushOutcome.Pushed && !Directory.Exists(catalog.Path))
                result = new PushResult { Outcome = PushOutcome.Gone };
            Log.Info($"{catalog.Name}: {result.Outcome} after {started.Elapsed.TotalSeconds:0.0} s" +
                     (result.Message != null ? $": {result.Message}" : ""));

            bool notify = false;
            lock (_lock)
            {
                catalog.SkipQuiet = false;
                catalog.Result = result.Outcome == PushOutcome.Pushed ? null : result;
                switch (result.Outcome)
                {
                    case PushOutcome.Pushed:
                        catalog.Attempts = 0;
                        SetState(catalog, CatalogState.Pushed);
                        break;
                    case PushOutcome.Gone:
                        _catalogs.Remove(catalog.Path);
                        break;
                    case PushOutcome.SignInRequired:
                        _signedIn = false;
                        SetState(catalog, CatalogState.Queued);
                        break;
                    case PushOutcome.Transient:
                        catalog.Attempts++;
                        catalog.NextAttemptUtc = DateTime.UtcNow + Backoff(catalog.Attempts);
                        SetState(catalog, CatalogState.Retrying);
                        notify = catalog.Attempts == NotifyAfterAttempts;
                        break;
                    default:
                        SetState(catalog, CatalogState.NeedsAttention);
                        notify = true;
                        break;
                }
            }

            if (result.Outcome == PushOutcome.SignInRequired)
                SignInNeeded?.Invoke();
            if (notify)
                AttentionNeeded?.Invoke(catalog.Copy());
        }

        private static TimeSpan Backoff(int attempts)
        {
            int[] minutes = { 1, 2, 5, 10, 15 };
            return TimeSpan.FromMinutes(minutes[Math.Min(attempts, minutes.Length) - 1]);
        }

        private static void SetState(Catalog catalog, CatalogState state)
        {
            if (catalog.State != state)
                Log.Info($"{catalog.Name}: {catalog.State} -> {state}");
            catalog.State = state;
            catalog.StateUtc = DateTime.UtcNow;
        }

        private struct FolderScan
        {
            public int Files;
            public bool Partial;
            public string Signature;
        }

        private static FolderScan ScanFolder(DirectoryInfo folder)
        {
            int files = 0, dirs = 0;
            long bytes = 0;
            long newest = 0;
            bool partial = false;
            foreach (var entry in folder.EnumerateFileSystemInfos("*", SearchOption.AllDirectories))
            {
                newest = Math.Max(newest, entry.LastWriteTimeUtc.Ticks);
                if (entry is FileInfo file)
                {
                    files++;
                    bytes += file.Length;
                    partial |= PartialSuffixes.Any(s => file.Name.EndsWith(s, StringComparison.OrdinalIgnoreCase))
                               || PartialPrefixes.Any(p => file.Name.StartsWith(p, StringComparison.OrdinalIgnoreCase));
                }
                else
                {
                    dirs++;
                }
            }
            return new FolderScan { Files = files, Partial = partial, Signature = $"{files}|{dirs}|{bytes}|{newest}" };
        }

        /// <summary>False while any file is still open for writing (sharing violation).</summary>
        private static bool FilesUnlocked(DirectoryInfo folder)
        {
            try
            {
                foreach (var file in folder.EnumerateFiles("*", SearchOption.AllDirectories))
                {
                    try
                    {
                        using (new FileStream(file.FullName, FileMode.Open, FileAccess.Read, FileShare.Read)) { }
                    }
                    catch (UnauthorizedAccessException)
                    {
                        // Not readable by this user; the worker reads it under its own account
                    }
                    catch (IOException ex)
                    {
                        Log.Debug($"{folder.Name}: {file.Name} still open: {ex.Message}");
                        return false;
                    }
                }
                return true;
            }
            catch (IOException ex)
            {
                Log.Debug($"{folder.Name}: lock check failed: {ex.Message}");
                return false;
            }
        }

        public void Dispose()
        {
            _stop = true;
            _wake.Set();
            lock (_watchers)
            {
                foreach (var watcher in _watchers)
                    watcher.Dispose();
                _watchers.Clear();
            }
        }
    }
}
