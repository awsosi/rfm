using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using FileManagerWorker.Models;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NLog;

namespace FileManagerWorker
{
    /// <summary>
    /// Handles HTTPS and mTLS communication with Central API
    /// </summary>
    public class ApiClient : IDisposable
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();
        private readonly string _apiUrl;
        private readonly HttpClient _httpClient;
        private readonly HttpClient _downloadClient;
        private readonly CertificateManager _certManager;
        private readonly ServiceConfiguration _config;
        private X509Certificate2 _clientCertificate;
        private bool _isRegistered = false;

        // Seconds the server may hold a poll open. Kept below HttpClient.Timeout (30s)
        // so an idle poll ends with the server's empty answer rather than a client-side
        // timeout that is indistinguishable from the API hanging.
        private const int LongPollSeconds = 25;

        // Upper bound for a single file download (see DownloadToFileAsync).
        private static readonly TimeSpan DownloadTimeout = TimeSpan.FromMinutes(30);

        // Connection state as last observed. Each is only logged when it changes, so a
        // worker left waiting for hours produces one warning and one recovery entry,
        // not one per retry.
        private string _serverStatus;          // ACTIVE / PENDING / SUSPENDED ..., null = not yet known
        private string _unreachableReason;     // null = API reachable
        private string _lastRegistrationError; // null = last registration attempt succeeded

        /// <summary>
        /// True while the API refuses this worker's polls because it is not ACTIVE
        /// (PENDING approval, SUSPENDED, ...). Nothing changes until the server-side
        /// status does, so the polling loop backs off much further than usual.
        /// </summary>
        public bool IsRejected => _serverStatus != null && _serverStatus != "ACTIVE";

        private static bool IsNetworkFailure(HttpRequestException ex) =>
        	ex.InnerException is SocketException sock &&
	        (sock.SocketErrorCode == SocketError.ConnectionRefused ||
	         sock.SocketErrorCode == SocketError.TimedOut ||
	         sock.SocketErrorCode == SocketError.HostUnreachable);

		public ApiClient(string apiUrl, CertificateManager certManager, ServiceConfiguration config = null)
        {
            _apiUrl = apiUrl?.TrimEnd('/');
            _certManager = certManager;
            _config = config;

            // Get client certificate (read-only - must exist from /config setup)
            _clientCertificate = _certManager.GetCertificateReadOnly();
            if (_clientCertificate == null)
            {
                throw new InvalidOperationException("mTLS certificate not found. Run /config as Administrator first.");
            }

            _httpClient = new HttpClient(CreateHandler())
            {
                Timeout = TimeSpan.FromSeconds(30)
            };

            _httpClient.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));

            // Downloads get their own client: a large file over a slow link outlasts the
            // 30s timeout above, so DownloadToFileAsync enforces its own limit instead.
            // Redirects are not followed, so the client certificate only ever goes to _apiUrl.
            var downloadHandler = CreateHandler();
            downloadHandler.AllowAutoRedirect = false;
            _downloadClient = new HttpClient(downloadHandler)
            {
                Timeout = System.Threading.Timeout.InfiniteTimeSpan
            };
        }

        /// <summary>
        /// HTTP handler with the mTLS client certificate and TLS settings shared by all requests
        /// </summary>
        private WebRequestHandler CreateHandler()
        {
            var handler = new WebRequestHandler();
            handler.ClientCertificates.Add(_clientCertificate);
            handler.ClientCertificateOptions = ClientCertificateOption.Manual;

            // Accept self-signed certificates (for testing - remove in production)
            handler.ServerCertificateValidationCallback = (sender, cert, chain, sslPolicyErrors) => true;

            return handler;
        }

        /// <summary>
        /// Registers the worker with the Central API by sending public key.
        /// For a hostname the server already knows this only refreshes the record;
        /// the server keeps the existing status, which is reported as-is.
        /// </summary>
        public async Task<bool> RegisterWorkerAsync()
        {
            var workerName = Environment.MachineName;
            try
            {
                Logger.Debug("Registering worker {0} with {1}", workerName, _apiUrl);

                var publicKeyPem = _certManager.ExportPublicKeyAsPem(_clientCertificate);

                // Build registration data matching API WorkerRegister schema
                var registrationData = new
                {
                    name = workerName,
                    hostname = workerName,
                    public_key = publicKeyPem,
                    path_a_prefix = _config?.PathAPrefix ?? @"C:\PathA",
                    path_b_prefix = _config?.PathBPrefix ?? @"C:\PathB",
                    path_c_prefix = _config?.PathCPrefix ?? @"C:\PathC",
                    version = "1.0.0"
                };

                var json = JsonConvert.SerializeObject(registrationData);
                var content = new StringContent(json, Encoding.UTF8, "application/json");

                var response = await _httpClient.PostAsync($"{_apiUrl}/api/workers/register", content);
                var responseContent = await response.Content.ReadAsStringAsync();

                if (!response.IsSuccessStatusCode)
                {
                    ReportReachable();
                    ReportRegistrationFailure($"HTTP {(int)response.StatusCode} {response.StatusCode}: {responseContent}");
                    return false;
                }

                _isRegistered = true;
                _lastRegistrationError = null;
                ReportReachable();

                string status = null;
                try { status = (string)JObject.Parse(responseContent)["status"]; }
                catch (JsonException) { }

                Logger.Info("Registered worker {0} with {1} (server status: {2})", workerName, _apiUrl, status ?? "unknown");
                ReportServerStatus(status);
                return true;
            }
            catch (HttpRequestException ex) when (IsNetworkFailure(ex))
            {
                ReportUnreachable(ex.InnerException?.Message ?? ex.Message);
                return false;
            }
            catch (TaskCanceledException)
            {
                ReportUnreachable("registration request timed out");
                return false;
            }
            catch (Exception ex)
            {
                ReportRegistrationFailure(ex.GetBaseException().Message);
                return false;
            }
        }

        /// <summary>
        /// Long-polls for commands from Central API. Returns null when there is nothing
        /// to run, including while the API is unreachable or refusing this worker.
        /// </summary>
        public async Task<CommandRequest> PollForCommandAsync(CancellationToken cancellationToken)
        {
            try
            {
                if (!_isRegistered && !await RegisterWorkerAsync())
                {
                    return null;
                }

                var workerId = Environment.MachineName;
                var requestUri = $"{_apiUrl}/api/workers/{workerId}/commands/poll?timeout={LongPollSeconds}";

                var response = await _httpClient.GetAsync(requestUri, cancellationToken);
                var body = await response.Content.ReadAsStringAsync();

                if (response.StatusCode == HttpStatusCode.Forbidden)
                {
                    // The API answers 403 "Worker is not active (status: X)" for any worker
                    // that is not ACTIVE. The registration itself is fine - re-registering
                    // would only rewrite the stored key and prefixes on every retry - so
                    // keep it and wait for the server-side status to change.
                    ReportReachable();
                    ReportServerStatus(ParseRejectedStatus(body));
                    return null;
                }

                if (response.StatusCode == HttpStatusCode.NotFound)
                {
                    // The worker record is gone (e.g. deleted by an administrator).
                    ReportReachable();
                    Logger.Warn("Worker {0} is no longer known to {1}; registering again", workerId, _apiUrl);
                    _isRegistered = false;
                    _serverStatus = null;
                    return null;
                }

                if (!response.IsSuccessStatusCode)
                {
                    // Typically 502/503/504 from the reverse proxy while the API restarts.
                    ReportUnreachable($"HTTP {(int)response.StatusCode} {response.StatusCode}");
                    return null;
                }

                ReportReachable();
                ReportServerStatus("ACTIVE");

                // No command waiting: the API answers 200 with every field null.
                var command = JsonConvert.DeserializeObject<CommandRequest>(body);
                if (command?.CommandId == null)
                {
                    return null;
                }

                Logger.Info("Received command: {0} (ID: {1})", command.Command, command.CommandId);
                return command;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                // Service is stopping
                return null;
            }
            catch (TaskCanceledException)
            {
                // HttpClient.Timeout elapsed although the server should answer within LongPollSeconds
                ReportUnreachable("poll request timed out");
                return null;
            }
            catch (HttpRequestException ex)
            {
                ReportUnreachable(ex.GetBaseException().Message);
                return null;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Error polling for commands");
                return null;
            }
        }

        /// <summary>
        /// Records the server-side status of this worker and logs only when it changes.
        /// </summary>
        private void ReportServerStatus(string status)
        {
            if (string.IsNullOrEmpty(status) || status == _serverStatus)
            {
                return;
            }

            var previous = _serverStatus;
            _serverStatus = status;
            var workerId = Environment.MachineName;

            switch (status)
            {
                case "ACTIVE":
                    if (previous == null)
                        Logger.Info("Worker {0} is ACTIVE on {1}", workerId, _apiUrl);
                    else
                        WorkerService.Lifecycle.Info("Worker {0} is ACTIVE again on {1} (was {2}) and is receiving commands", workerId, _apiUrl, previous);
                    break;

                case "PENDING":
                    Logger.Warn("Worker {0} is registered on {1} but awaiting administrator approval. " +
                                "It receives no commands until approved and checks again every {2}s.",
                                workerId, _apiUrl, WorkerService.UnauthorizedRetrySeconds);
                    break;

                case "SUSPENDED":
                    Logger.Warn("Worker {0} is SUSPENDED on {1} and receives no commands. " +
                                "It keeps sending heartbeats, checks again every {2}s, and resumes on its own once the server reactivates it.",
                                workerId, _apiUrl, WorkerService.UnauthorizedRetrySeconds);
                    break;

                default:
                    Logger.Warn("Worker {0} is not active on {1} (status: {2}) and receives no commands; checking again every {3}s",
                                workerId, _apiUrl, status, WorkerService.UnauthorizedRetrySeconds);
                    break;
            }
        }

        private static string ParseRejectedStatus(string body)
        {
            var match = Regex.Match(body ?? string.Empty, @"status:\s*([A-Za-z_]+)");
            return match.Success ? match.Groups[1].Value.ToUpperInvariant() : "NOT_ACTIVE";
        }

        private void ReportUnreachable(string reason)
        {
            if (_unreachableReason == null)
                Logger.Warn("Central API {0} is unreachable ({1}); will keep retrying", _apiUrl, reason);
            else
                Logger.Debug("Central API {0} still unreachable ({1})", _apiUrl, reason);

            _unreachableReason = reason;
        }

        private void ReportReachable()
        {
            if (_unreachableReason == null)
            {
                return;
            }

            WorkerService.Lifecycle.Info("Central API {0} is reachable again (was: {1})", _apiUrl, _unreachableReason);
            _unreachableReason = null;
        }

        private void ReportRegistrationFailure(string reason)
        {
            if (reason == _lastRegistrationError)
            {
                Logger.Debug("Registration still failing: {0}", reason);
                return;
            }

            _lastRegistrationError = reason;
            Logger.Error("Registration of worker {0} with {1} failed: {2}. Retrying on every poll; logged again only if the error changes.",
                         Environment.MachineName, _apiUrl, reason);
        }

        /// <summary>
        /// Sends command response back to Central API
        /// </summary>
        public async Task<bool> SendResponseAsync(CommandResponse response)
        {
            try
            {
                var workerId = Environment.MachineName;
                var json = JsonConvert.SerializeObject(response);
                var content = new StringContent(json, Encoding.UTF8, "application/json");

                var httpResponse = await _httpClient.PostAsync(
                    $"{_apiUrl}/api/workers/{workerId}/commands/{response.CommandId}/response",
                    content);

                if (httpResponse.IsSuccessStatusCode)
                {
                    Logger.Info("Response sent for command {0}: {1}", response.CommandId, response.Status);
                    return true;
                }
                else
                {
                    Logger.Error("Failed to send response: {0}", httpResponse.StatusCode);
                    return false;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Error sending response");
                return false;
            }
        }

        /// <summary>
        /// Sends progress update for long-running commands (optional feature)
        /// </summary>
        public async Task SendProgressAsync(int commandId, int progressPercent, string message = null)
        {
            try
            {
                // Note: Progress updates are optional in pull-based architecture
                // The command is updated with final response only
                Logger.Debug("Progress update: Command {0} at {1}%", commandId, progressPercent);
            }
            catch (Exception ex)
            {
                Logger.Warn(ex, "Error logging progress update");
            }
        }

        /// <summary>
        /// Gets configuration from Central API
        /// </summary>
        public async Task<ServiceConfiguration> GetConfigurationAsync()
        {
            try
            {
                var workerId = Environment.MachineName;
                var response = await _httpClient.GetAsync($"{_apiUrl}/api/workers/{workerId}/config");

                if (response.IsSuccessStatusCode)
                {
                    var json = await response.Content.ReadAsStringAsync();
                    var config = JsonConvert.DeserializeObject<ServiceConfiguration>(json);
                    Logger.Info("Configuration retrieved from API");
                    return config;
                }
                else
                {
                    Logger.Warn("Failed to get configuration: {0}", response.StatusCode);
                    return null;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Error getting configuration");
                return null;
            }
        }

        /// <summary>
        /// Sends heartbeat to Central API
        /// </summary>
        public async Task<bool> SendHeartbeatAsync()
        {
            try
            {
                var workerId = Environment.MachineName;
                var heartbeatData = new
                {
                    Timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                    Status = "online"
                };

                var json = JsonConvert.SerializeObject(heartbeatData);
                var content = new StringContent(json, Encoding.UTF8, "application/json");

                var response = await _httpClient.PostAsync($"{_apiUrl}/api/workers/{workerId}/heartbeat", content);

                return response.IsSuccessStatusCode;
            }
			catch (HttpRequestException ex) when (IsNetworkFailure(ex))
			{
				Logger.Debug("API unreachable during poll: {Message}", ex.Message);
				return false;
			}
			catch (Exception ex)
            {
                Logger.Debug(ex, "Heartbeat failed");
                return false;
            }
        }

        /// <summary>
        /// Streams a file served by the Central API to a new local file, hashing it on the way.
        /// relativeUrl must be a path on the API ("/api/..."); it may carry a signed query
        /// string, which is a credential and is never logged. Returns the byte count and the
        /// lowercase hex SHA-256 of what was written.
        /// </summary>
        public async Task<(long Bytes, string Sha256)> DownloadToFileAsync(
            string relativeUrl, string localPath, CancellationToken cancellationToken)
        {
            if (string.IsNullOrEmpty(relativeUrl) || !relativeUrl.StartsWith("/api/", StringComparison.Ordinal))
            {
                throw new ArgumentException("Download URL must be a relative path starting with /api/");
            }

            var uri = new Uri(_apiUrl + relativeUrl);
            if (!string.Equals(uri.Authority, new Uri(_apiUrl).Authority, StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException("Download URL must stay on the configured API host");
            }

            var urlPath = uri.AbsolutePath;

            using (var cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken))
            {
                cts.CancelAfter(DownloadTimeout);
                try
                {
                    using (var response = await _downloadClient.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, cts.Token))
                    {
                        if (!response.IsSuccessStatusCode)
                        {
                            var body = await response.Content.ReadAsStringAsync();
                            if (body.Length > 300)
                            {
                                body = body.Substring(0, 300) + "...";
                            }

                            string hint = "";
                            if (response.StatusCode == HttpStatusCode.Forbidden)
                                hint = " (link invalid or expired, or worker not ACTIVE)";
                            else if (response.StatusCode == HttpStatusCode.NotFound)
                                hint = " (upload no longer exists)";

                            throw new HttpRequestException(
                                $"Download of {urlPath} failed: HTTP {(int)response.StatusCode} {response.StatusCode}{hint}: {body}");
                        }

                        long bytes = 0;
                        using (var sha = System.Security.Cryptography.SHA256.Create())
                        using (var source = await response.Content.ReadAsStreamAsync())
                        using (var target = new System.IO.FileStream(localPath, System.IO.FileMode.CreateNew,
                            System.IO.FileAccess.Write, System.IO.FileShare.None, 81920, useAsync: true))
                        {
                            var buffer = new byte[81920];
                            int read;
                            while ((read = await source.ReadAsync(buffer, 0, buffer.Length, cts.Token)) > 0)
                            {
                                await target.WriteAsync(buffer, 0, read, cts.Token);
                                sha.TransformBlock(buffer, 0, read, null, 0);
                                bytes += read;
                            }

                            sha.TransformFinalBlock(buffer, 0, 0);
                            var hash = BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
                            return (bytes, hash);
                        }
                    }
                }
                catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
                {
                    throw new TimeoutException($"Download of {urlPath} did not finish within {DownloadTimeout.TotalMinutes} minutes");
                }
            }
        }

        public void Dispose()
        {
            _httpClient?.Dispose();
            _downloadClient?.Dispose();
        }
    }
}
