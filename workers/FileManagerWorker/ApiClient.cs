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
using Newtonsoft.Json;
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
        private readonly CertificateManager _certManager;
        private readonly ServiceConfiguration _config;
        private X509Certificate2 _clientCertificate;
        private bool _isRegistered = false;private static bool IsNetworkFailure(HttpRequestException ex) =>
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

            // Create HttpClientHandler with mTLS support
            var handler = new WebRequestHandler();
            handler.ClientCertificates.Add(_clientCertificate);
            handler.ClientCertificateOptions = ClientCertificateOption.Manual;

            // Accept self-signed certificates (for testing - remove in production)
            handler.ServerCertificateValidationCallback = (sender, cert, chain, sslPolicyErrors) => true;

            _httpClient = new HttpClient(handler)
            {
                Timeout = TimeSpan.FromSeconds(30)
            };

            _httpClient.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        }

        /// <summary>
        /// Registers the worker with the Central API by sending public key
        /// </summary>
        public async Task<bool> RegisterWorkerAsync()
        {
            try
            {
                Logger.Info("========================================================================");
                Logger.Info("Attempting worker registration with Central API...");
                Logger.Info("  API URL: {0}", _apiUrl);
                Logger.Info("  Hostname: {0}", Environment.MachineName);
                Logger.Info("========================================================================");

                var publicKeyPem = _certManager.ExportPublicKeyAsPem(_clientCertificate);
                var workerName = Environment.MachineName;

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

                Logger.Debug("Sending registration request...");
                var response = await _httpClient.PostAsync($"{_apiUrl}/api/workers/register", content);

                if (response.IsSuccessStatusCode)
                {
                    var responseContent = await response.Content.ReadAsStringAsync();
                    Logger.Info("========================================================================");
                    Logger.Info("✓ Worker registered successfully!");
                    Logger.Info("========================================================================");
                    Logger.Info("Response: {0}", responseContent);
                    Logger.Info("");
                    Logger.Info("IMPORTANT: Worker status is PENDING - awaiting admin approval");
                    Logger.Info("Admin must approve this worker at: /pages/admin.html -> Workers tab");
                    Logger.Info("========================================================================");
                    _isRegistered = true;
                    return true;
                }
                else
                {
                    var errorContent = await response.Content.ReadAsStringAsync();
                    Logger.Error("========================================================================");
                    Logger.Error("✗ Worker registration FAILED");
                    Logger.Error("========================================================================");
                    Logger.Error("  Status Code: {0}", response.StatusCode);
                    Logger.Error("  Response: {0}", errorContent);
                    Logger.Error("  API URL: {0}", _apiUrl);
                    Logger.Error("");
                    Logger.Error("DIAGNOSIS:");
                    if (response.StatusCode == HttpStatusCode.Forbidden)
                    {
                        Logger.Error("  - 403 Forbidden: Worker may be blocked or certificate rejected");
                    }
                    else if (response.StatusCode == HttpStatusCode.Unauthorized)
                    {
                        Logger.Error("  - 401 Unauthorized: Authentication failed");
                    }
                    else if (response.StatusCode == HttpStatusCode.BadRequest)
                    {
                        Logger.Error("  - 400 Bad Request: Invalid registration data format");
                    }
                    else
                    {
                        Logger.Error("  - HTTP error occurred during registration");
                    }
                    Logger.Error("");
                    Logger.Error("POSSIBLE CAUSES:");
                    Logger.Error("  1. Wrong API URL configured");
                    Logger.Error("  2. API server is rejecting the request");
                    Logger.Error("  3. Network connectivity issues");
                    Logger.Error("  4. Certificate validation problems");
                    Logger.Error("========================================================================");
                    return false;
                }
            }
			catch (HttpRequestException ex) when (ex.InnerException is SocketException sockEx && sockEx.SocketErrorCode == SocketError.ConnectionRefused)
			{
                Logger.Warn("========================================================================");
                Logger.Warn("Central API is offline or unreachable");
                Logger.Warn("========================================================================");
                Logger.Warn("  API URL: {0}", _apiUrl);
                Logger.Warn("  Error: Connection refused");
                Logger.Warn("  Detail: {0}", ex.Message);
                Logger.Warn("");
                Logger.Warn("The worker will retry registration during next poll cycle.");
                Logger.Warn("========================================================================");
				return false;
			}
            catch (Exception ex)
            {
                Logger.Error("========================================================================");
                Logger.Error("✗ Worker registration exception");
                Logger.Error("========================================================================");
                Logger.Error(ex, "Unexpected error during registration");
                Logger.Error("  API URL: {0}", _apiUrl);
                Logger.Error("========================================================================");
                return false;
            }
		}

        /// <summary>
        /// Long-polls for commands from Central API
        /// </summary>
        public async Task<CommandRequest> PollForCommandAsync(CancellationToken cancellationToken)
        {
            try
            {
                // Ensure worker is registered
                if (!_isRegistered)
                {
                    await RegisterWorkerAsync();
                }

                var workerId = Environment.MachineName;
                var requestUri = $"{_apiUrl}/api/workers/{workerId}/commands/poll?timeout=30";

                var response = await _httpClient.GetAsync(requestUri, cancellationToken);

                if (response.StatusCode == HttpStatusCode.NoContent)
                {
                    // No commands available
                    return null;
                }

                if (response.IsSuccessStatusCode)
                {
                    var json = await response.Content.ReadAsStringAsync();
                    var command = JsonConvert.DeserializeObject<CommandRequest>(json);
                    Logger.Info("Received command: {0} (ID: {1})", command.Command, command.CommandId);
                    return command;
                }
                else if (response.StatusCode == HttpStatusCode.Forbidden)
                {
                    Logger.Warn("Worker certificate has been revoked or is not authorized");
                    _isRegistered = false;
                    return null;
                }
                else
                {
                    Logger.Warn("Poll request failed: {0}", response.StatusCode);
                    return null;
                }
            }
			catch (HttpRequestException ex) when (IsNetworkFailure(ex))
			{
				Logger.Debug("API unreachable during poll ({APIUrl}): {Message}", _apiUrl, ex.Message);
				return null;
			}
			catch (TaskCanceledException)
            {
                // Normal cancellation, don't log as error
                return null;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Error polling for commands");
                return null;
            }
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

        public void Dispose()
        {
            _httpClient?.Dispose();
        }
    }
}
