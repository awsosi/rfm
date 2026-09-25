using System;
using System.IdentityModel.Tokens.Jwt;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using RFMLauncher;
using AuthenticationManager = RFMLauncher.AuthenticationManager;

namespace RFMTray
{
    public enum PushOutcome
    {
        Pushed,
        /// <summary>RFM rejected the name or the contents; the user must fix the folder.</summary>
        Rejected,
        /// <summary>The catalog is already published; changing it is an UPDATE.</summary>
        AlreadyPublished,
        /// <summary>The folder is no longer there (pushed from another PC, moved away).</summary>
        Gone,
        /// <summary>Sign-in missing or expired.</summary>
        SignInRequired,
        /// <summary>RFM, PolkaSQL or the worker unavailable; worth retrying later.</summary>
        Transient,
        /// <summary>Any other refusal; retrying will not help until something changes.</summary>
        Failed,
    }

    public class PushResult
    {
        public PushOutcome Outcome;
        /// <summary>The 422 body's { catalog, content } for Rejected.</summary>
        public JObject Validation;
        public string Message;
    }

    class SignInRequiredException : Exception
    {
        public SignInRequiredException() : base(L.T("tray.check.notSignedIn")) { }
    }

    /// <summary>RFM answered, but with an error.</summary>
    class RfmException : Exception
    {
        public RfmException(string message) : base(message) { }
    }

    /// <summary>
    /// The RFM API calls RFM Tray needs, under the user's own sign-in (the
    /// credential RFMLauncher uses). Every push is audited against that user,
    /// with "RFMTray" in the user agent.
    /// </summary>
    public class RfmClient
    {
        // Validation reasons that describe an outage rather than the folder
        private static readonly string[] TransientReasons =
        {
            "catalogValidation.serviceUnavailable",
            "catalogValidation.timeout",
            "contentValidation.workerUnavailable",
        };

        private readonly Config _config;
        private readonly AuthenticationManager _auth;
        private readonly HttpClient _http;
        // Checks must answer quickly; a PUSH may take minutes
        private readonly HttpClient _quick;
        private int? _workerId;

        public RfmClient(Config config)
        {
            _config = config;
            _auth = new AuthenticationManager(config);
            // A PUSH returns when the worker has copied the catalog
            _http = NewHttpClient(TimeSpan.FromMinutes(15));
            _quick = NewHttpClient(TimeSpan.FromSeconds(20));
        }

        private static HttpClient NewHttpClient(TimeSpan timeout)
        {
            var http = new HttpClient { Timeout = timeout };
            http.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue(
                "RFMTray", Assembly.GetExecutingAssembly().GetName().Version.ToString()));
            return http;
        }

        public string ServerUrl => _config.ApiBaseUrl;

        /// <summary>GET /health, which needs no sign-in: null when RFM answers, else what went wrong.</summary>
        public string ServerProblem()
        {
            try
            {
                var response = _quick.GetAsync(_config.ApiBaseUrl.TrimEnd('/') + "/health").Result;
                Log.Info($"GET /health -> {(int)response.StatusCode}");
                return response.IsSuccessStatusCode ? null : $"HTTP {(int)response.StatusCode}";
            }
            catch (Exception ex)
            {
                Log.Info($"GET /health: {ex}");
                return Describe(ex);
            }
        }

        /// <summary>The user RFM itself confirms for the saved sign-in; SignInRequiredException when there is none.</summary>
        public string ConfirmedUser()
        {
            var response = Check(Send(HttpMethod.Get, "/api/auth/me", null, _quick));
            return (string)ReadJson(response)["username"];
        }

        /// <summary>The worker pushes go to (the first active one, as the WebUI): "name (status)".</summary>
        public string WorkerName()
        {
            _workerId = null;
            int id = WorkerId();
            var workers = JArray.Parse(Check(Send(HttpMethod.Get, "/api/workers/list", null, _quick)).Content.ReadAsStringAsync().Result);
            var worker = workers.First(w => (int)w["id"] == id);
            return $"{worker["name"]} ({worker["status"]})";
        }

        /// <summary>
        /// How RFM sees a watched folder: its virtual path and how many entries
        /// the worker lists in it, which proves the server reaches the same folder.
        /// </summary>
        public (string VirtualPath, int Entries) Locate(string windowsPath)
        {
            int workerId = WorkerId();
            var resolve = Check(Send(HttpMethod.Post, "/api/path/resolve", new
            {
                windows_path = PathRules.NormalizeToCanonicalPath(windowsPath, _config),
                worker_id = workerId,
            }, _quick));
            string virtualPath = (string)ReadJson(resolve)["virtual_path"];
            var list = Check(Send(HttpMethod.Get,
                $"/api/files/list?worker_id={workerId}&path={Uri.EscapeDataString(virtualPath)}&limit=1", null, _quick));
            return (virtualPath, (int)ReadJson(list)["total_count"]);
        }

        /// <summary>A failure in words a user can pass on: the innermost cause, not "One or more errors occurred".</summary>
        public static string Describe(Exception ex)
        {
            if (ex is RfmException || ex is SignInRequiredException)
                return ex.Message;
            // GetBaseException stops at the first non-aggregate: HttpRequestException's
            // "An error occurred while sending the request" hides the real cause
            while (ex.InnerException != null)
                ex = ex.InnerException;
            return ex is TaskCanceledException ? L.T("tray.check.timeout") : ex.Message;
        }

        private static HttpResponseMessage Check(HttpResponseMessage response)
        {
            if (response.IsSuccessStatusCode)
                return response;
            var detail = ErrorDetail(response);
            throw new RfmException($"HTTP {(int)response.StatusCode}" + (detail != null ? $": {detail}" : ""));
        }

        /// <summary>Browser device flow, as RFMLauncher; blocks until approved or expired.</summary>
        public bool SignIn() => _auth.PerformDeviceFlow(LocalizationManager.Load(_config.Language)) != null;

        public void SignOut()
        {
            _auth.SignOut();
            _workerId = null;
        }

        /// <summary>
        /// The signed-in user's name, from the saved token (no network: RFM may
        /// be unreachable at logon). A revoked session shows up as 401 on the next push.
        /// </summary>
        public string CurrentUser()
        {
            string token = _auth.GetValidToken();
            if (token == null)
                return null;
            return new JwtSecurityTokenHandler().ReadJwtToken(token).Claims
                .FirstOrDefault(c => c.Type == "username")?.Value ?? "?";
        }

        public PushResult Push(string windowsPath)
        {
            try
            {
                int workerId = WorkerId();

                string canonicalPath = PathRules.NormalizeToCanonicalPath(windowsPath, _config);
                var resolve = Send(HttpMethod.Post, "/api/path/resolve", new
                {
                    windows_path = canonicalPath,
                    worker_id = workerId,
                });
                if (resolve.StatusCode != HttpStatusCode.OK)
                    return Failure(resolve);
                string virtualPath = (string)ReadJson(resolve)["virtual_path"];
                Log.Info($"PUSH {windowsPath} as {canonicalPath} -> {virtualPath} (worker {workerId})");

                var push = Send(HttpMethod.Post, "/api/operations/push", new
                {
                    source_path = virtualPath,
                    worker_id = workerId,
                    refuse_existing = true,
                });
                if (push.StatusCode == HttpStatusCode.OK)
                {
                    var operation = ReadJson(push);
                    Log.Info($"PUSH operation {operation["id"]}: {operation["status"]}");
                    return (string)operation["status"] == "failed"
                        ? new PushResult { Outcome = PushOutcome.Failed, Message = (string)operation["error_msg"] }
                        : new PushResult { Outcome = PushOutcome.Pushed };
                }

                var detail = ErrorDetail(push) as JObject;
                string error = (string)detail?["error"];
                if ((int)push.StatusCode == 422 && error == "validation_failed")
                {
                    var reasons = new[] { (string)detail["catalog"]?["reason"], (string)detail["content"]?["reason"] };
                    return new PushResult
                    {
                        Outcome = reasons.Any(r => TransientReasons.Contains(r)) ? PushOutcome.Transient : PushOutcome.Rejected,
                        Validation = detail,
                        Message = ValidationText.Format(detail),
                    };
                }
                if (push.StatusCode == HttpStatusCode.Conflict && error == "catalog_exists")
                    return new PushResult { Outcome = PushOutcome.AlreadyPublished, Message = (string)detail["catalog_path"] };

                return Failure(push);
            }
            catch (SignInRequiredException)
            {
                return new PushResult { Outcome = PushOutcome.SignInRequired };
            }
            catch (Exception ex) when (ex is HttpRequestException || ex is TaskCanceledException || ex is AggregateException)
            {
                Log.Debug($"PUSH {windowsPath}: {ex}");
                return new PushResult { Outcome = PushOutcome.Transient, Message = (ex.InnerException ?? ex).Message };
            }
        }

        private int WorkerId()
        {
            if (_workerId == null)
            {
                var response = Send(HttpMethod.Get, "/api/workers/list", null);
                var workers = response.StatusCode == HttpStatusCode.OK ? JArray.Parse(response.Content.ReadAsStringAsync().Result) : null;
                if (workers == null || workers.Count == 0)
                    throw new HttpRequestException(L.T("tray.noWorker"));
                // The WebUI uses the first active worker too
                _workerId = (int)workers[0]["id"];
            }
            return _workerId.Value;
        }

        private PushResult Failure(HttpResponseMessage response)
        {
            int status = (int)response.StatusCode;
            // Worker/API trouble is retried; anything else waits for the user
            if (status >= 500)
                _workerId = null;
            return new PushResult
            {
                Outcome = status >= 500 || status == 429 ? PushOutcome.Transient : PushOutcome.Failed,
                Message = $"HTTP {status}" + (ErrorDetail(response) is JToken detail ? $": {detail}" : ""),
            };
        }

        private HttpResponseMessage Send(HttpMethod method, string path, object body, HttpClient http = null)
        {
            string token = _auth.GetValidToken();
            if (token == null)
            {
                Log.Info($"{method} {path}: no valid saved sign-in (missing, or expired and not refreshed)");
                throw new SignInRequiredException();
            }
            var request = new HttpRequestMessage(method, _config.ApiBaseUrl.TrimEnd('/') + path);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            if (body != null)
                request.Content = new StringContent(JsonConvert.SerializeObject(body), Encoding.UTF8, "application/json");

            var started = System.Diagnostics.Stopwatch.StartNew();
            var response = (http ?? _http).SendAsync(request).Result;
            Log.Info($"{method} {path} -> {(int)response.StatusCode} in {started.ElapsedMilliseconds} ms");
            if (response.StatusCode == HttpStatusCode.Unauthorized)
                throw new SignInRequiredException();
            return response;
        }

        private static JObject ReadJson(HttpResponseMessage response) =>
            JObject.Parse(response.Content.ReadAsStringAsync().Result);

        /// <summary>The API wraps HTTPException details as {"error": detail}.</summary>
        private static JToken ErrorDetail(HttpResponseMessage response)
        {
            try
            {
                return ReadJson(response)["error"];
            }
            catch (JsonException)
            {
                return null;
            }
        }
    }
}
