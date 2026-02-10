using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IdentityModel.Tokens.Jwt;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading;
using CredentialManagement;
using Newtonsoft.Json;

namespace RFMLauncher
{
    /// <summary>
    /// Device authorization response model
    /// </summary>
    public class DeviceAuthorizationResponse
    {
        [JsonProperty("device_code")]
        public string DeviceCode { get; set; }

        [JsonProperty("user_code")]
        public string UserCode { get; set; }

        [JsonProperty("verification_uri")]
        public string VerificationUri { get; set; }

        [JsonProperty("expires_in")]
        public int ExpiresIn { get; set; }
    }

    /// <summary>
    /// Login response model
    /// </summary>
    public class LoginResponse
    {
        [JsonProperty("access_token")]
        public string AccessToken { get; set; }

        [JsonProperty("refresh_token")]
        public string RefreshToken { get; set; }

        [JsonProperty("token_type")]
        public string TokenType { get; set; }

        [JsonProperty("expires_in")]
        public int ExpiresIn { get; set; }

        [JsonProperty("user_id")]
        public int UserId { get; set; }

        [JsonProperty("username")]
        public string Username { get; set; }

        [JsonProperty("role")]
        public string Role { get; set; }
    }

    /// <summary>
    /// Error response model
    /// </summary>
    public class ErrorResponse
    {
        [JsonProperty("detail")]
        public string Detail { get; set; }
    }

    /// <summary>
    /// Manages OAuth device flow authentication and token storage
    /// </summary>
    public class AuthenticationManager
    {
        private readonly Config _config;
        private readonly HttpClient _httpClient;

        public AuthenticationManager(Config config)
        {
            _config = config;
            _httpClient = new HttpClient();
            _httpClient.Timeout = TimeSpan.FromSeconds(30);
        }

        /// <summary>
        /// Get valid access token from Windows Credential Manager
        /// Returns null if not authenticated or token expired
        /// </summary>
        public string GetValidToken()
        {
            try
            {
                // Load credential from Windows Credential Manager
                var cred = LoadCredential(_config.CredentialTargetPrefix);
                if (cred == null)
                {
                    Console.WriteLine($"No saved credential found for: {_config.CredentialTargetPrefix}");
                    return null;
                }

                Console.WriteLine($"Credential loaded for user: {cred.Username}");
                string accessToken = cred.Password;

                // Check if token is expired
                if (IsTokenExpired(accessToken))
                {
                    Console.WriteLine("Token expired, attempting refresh...");

                    // Try to refresh using refresh_token stored in Description field
                    string refreshToken = cred.Description;
                    if (!string.IsNullOrEmpty(refreshToken))
                    {
                        Console.WriteLine("Refresh token found, requesting new access token...");
                        string newToken = RefreshToken(refreshToken);
                        if (newToken != null)
                        {
                            Console.WriteLine("Token refreshed successfully!");
                            // Save new token
                            SaveCredential(_config.CredentialTargetPrefix, cred.Username, newToken, refreshToken);
                            return newToken;
                        }
                        else
                        {
                            Console.WriteLine("Token refresh failed, need to re-authenticate");
                        }
                    }
                    else
                    {
                        Console.WriteLine("No refresh token available, need to re-authenticate");
                    }

                    return null;
                }

                Console.WriteLine("Saved token is still valid");
                return accessToken;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to get token: {ex.Message}");
                Console.WriteLine($"Stack trace: {ex.StackTrace}");
                return null;
            }
        }

        /// <summary>
        /// Perform OAuth device flow authentication
        /// </summary>
        public string PerformDeviceFlow(Dictionary<string, string> localization)
        {
            try
            {
                // Step 1: Request device code
                var requestUrl = $"{_config.ApiBaseUrl}/api/auth/device/request";
                var response = _httpClient.PostAsync(requestUrl, null).Result;

                if (!response.IsSuccessStatusCode)
                {
                    Console.WriteLine($"Failed to request device code: {response.StatusCode}");
                    return null;
                }

                var content = response.Content.ReadAsStringAsync().Result;
                var deviceResp = JsonConvert.DeserializeObject<DeviceAuthorizationResponse>(content);

                // Step 2: Open browser to verification URI
                string verificationUrl = $"{deviceResp.VerificationUri}?user_code={deviceResp.UserCode}";

                Process.Start(new ProcessStartInfo
                {
                    FileName = verificationUrl,
                    UseShellExecute = true
                });

                // Step 3: Show user code to console
                string waitingMessage = localization["auth.waitingApproval"].Replace("{code}", deviceResp.UserCode);
                Console.WriteLine(waitingMessage);
                Console.WriteLine($"Verification URL: {verificationUrl}");
                Console.WriteLine($"Expires in: {deviceResp.ExpiresIn / 60} minutes");
                Console.WriteLine();

                // Step 4: Poll for approval
                DateTime expiresAt = DateTime.Now.AddSeconds(deviceResp.ExpiresIn);
                int pollCount = 0;

                while (DateTime.Now < expiresAt)
                {
                    Thread.Sleep(5000); // Poll every 5 seconds
                    pollCount++;

                    Console.Write($"\rPolling for approval... ({pollCount * 5}s elapsed)");

                    var pollUrl = $"{_config.ApiBaseUrl}/api/auth/device/poll";
                    var pollPayload = new { device_code = deviceResp.DeviceCode };
                    var pollJson = JsonConvert.SerializeObject(pollPayload);
                    var pollContent = new StringContent(pollJson, Encoding.UTF8, "application/json");

                    var pollResponse = _httpClient.PostAsync(pollUrl, pollContent).Result;

                    if (pollResponse.IsSuccessStatusCode)
                    {
                        // Approved!
                        Console.WriteLine();
                        var pollResponseContent = pollResponse.Content.ReadAsStringAsync().Result;
                        var tokenResponse = JsonConvert.DeserializeObject<LoginResponse>(pollResponseContent);

                        // Save to Windows Credential Manager
                        SaveCredential(
                            _config.CredentialTargetPrefix,
                            tokenResponse.Username,
                            tokenResponse.AccessToken,
                            tokenResponse.RefreshToken
                        );

                        Console.WriteLine(localization["auth.authSuccess"]);
                        return tokenResponse.AccessToken;
                    }

                    // Check error
                    if (pollResponse.StatusCode == System.Net.HttpStatusCode.BadRequest)
                    {
                        var errorContent = pollResponse.Content.ReadAsStringAsync().Result;
                        var errorResp = JsonConvert.DeserializeObject<ErrorResponse>(errorContent);

                        if (errorResp.Detail == "expired_token")
                        {
                            Console.WriteLine();
                            Console.WriteLine("Authorization code expired.");
                            return null;
                        }

                        // authorization_pending is expected, continue polling
                    }
                }

                // Timeout
                Console.WriteLine();
                Console.WriteLine(localization["errors.authTimeout"]);
                return null;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Device flow error: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// Refresh access token using refresh token
        /// </summary>
        private string RefreshToken(string refreshToken)
        {
            try
            {
                var refreshUrl = $"{_config.ApiBaseUrl}/api/auth/refresh";

                var request = new HttpRequestMessage(HttpMethod.Post, refreshUrl);
                request.Headers.Add("Authorization", $"Bearer {refreshToken}");

                var response = _httpClient.SendAsync(request).Result;

                if (response.IsSuccessStatusCode)
                {
                    var content = response.Content.ReadAsStringAsync().Result;
                    var tokenResponse = JsonConvert.DeserializeObject<LoginResponse>(content);
                    return tokenResponse.AccessToken;
                }

                return null;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Token refresh failed: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// Check if JWT token is expired
        /// </summary>
        private bool IsTokenExpired(string token)
        {
            try
            {
                var handler = new JwtSecurityTokenHandler();
                var jwtToken = handler.ReadJwtToken(token);

                // Check expiration claim
                var exp = jwtToken.Claims.FirstOrDefault(c => c.Type == "exp")?.Value;
                if (exp == null)
                {
                    return true; // No expiration claim, consider expired
                }

                long expUnix = long.Parse(exp);
                DateTime expDate = DateTimeOffset.FromUnixTimeSeconds(expUnix).UtcDateTime;

                // Add 1 minute buffer to account for clock skew
                return DateTime.UtcNow.AddMinutes(1) >= expDate;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to parse token: {ex.Message}");
                return true; // Consider expired if we can't parse
            }
        }

        /// <summary>
        /// Save credential to Windows Credential Manager
        /// </summary>
        private void SaveCredential(string target, string username, string accessToken, string refreshToken = null)
        {
            try
            {
                using (var cred = new Credential
                {
                    Target = target,
                    Username = username,
                    Password = accessToken,
                    Type = CredentialType.Generic,
                    PersistanceType = PersistanceType.Enterprise
                })
                {
                    // Store refresh token in description field (not ideal but works)
                    if (!string.IsNullOrEmpty(refreshToken))
                    {
                        cred.Description = refreshToken;
                    }

                    bool saved = cred.Save();
                    if (saved)
                    {
                        Console.WriteLine($"Credential saved successfully to Windows Credential Manager");
                        Console.WriteLine($"  Target: {target}");
                        Console.WriteLine($"  Username: {username}");
                    }
                    else
                    {
                        Console.WriteLine($"WARNING: Failed to save credential (Save() returned false)");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to save credential: {ex.Message}");
                Console.WriteLine($"Stack trace: {ex.StackTrace}");
            }
        }

        /// <summary>
        /// Load credential from Windows Credential Manager
        /// </summary>
        private Credential LoadCredential(string target)
        {
            try
            {
                using (var cred = new Credential { Target = target })
                {
                    if (cred.Load())
                    {
                        // Create a new credential object to return
                        var loadedCred = new Credential
                        {
                            Target = cred.Target,
                            Username = cred.Username,
                            Password = cred.Password,
                            Description = cred.Description
                        };

                        return loadedCred;
                    }
                }

                return null;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to load credential: {ex.Message}");
                return null;
            }
        }
    }
}
