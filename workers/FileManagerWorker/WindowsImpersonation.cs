using System;
using System.Runtime.InteropServices;
using System.Security.Principal;
using NLog;

namespace FileManagerWorker
{
    /// <summary>
    /// Provides Windows impersonation for file operations using samba credentials
    /// </summary>
    public class WindowsImpersonation : IDisposable
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();

        private WindowsImpersonationContext _impersonationContext;
        private IntPtr _tokenHandle = IntPtr.Zero;
        private bool _isImpersonating = false;

        // P/Invoke declarations
        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        private static extern bool LogonUser(
            string lpszUsername,
            string lpszDomain,
            string lpszPassword,
            int dwLogonType,
            int dwLogonProvider,
            out IntPtr phToken);

        [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);

        // Logon types
        private const int LOGON32_LOGON_INTERACTIVE = 2;
        private const int LOGON32_LOGON_NETWORK = 3;
        private const int LOGON32_LOGON_NETWORK_CLEARTEXT = 8;

        // Logon providers
        private const int LOGON32_PROVIDER_DEFAULT = 0;
        private const int LOGON32_PROVIDER_WINNT50 = 3;

        /// <summary>
        /// Impersonate using provided credentials
        /// </summary>
        /// <param name="username">Username (can include DOMAIN\\User format)</param>
        /// <param name="password">Password</param>
        /// <returns>True if impersonation succeeded</returns>
        public bool Impersonate(string username, string password)
        {
            if (string.IsNullOrWhiteSpace(username))
            {
                Logger.Debug("No credentials provided, skipping impersonation");
                return false;
            }

            try
            {
                // Parse domain and username
                string domain = null;
                string user = username;

                if (username.Contains("\\"))
                {
                    var parts = username.Split('\\');
                    domain = parts[0];
                    user = parts[1];
                }
                else if (username.Contains("@"))
                {
                    // UPN format (user@domain.com)
                    user = username;
                    domain = null;
                }

                Logger.Debug("Attempting impersonation for user: {0}\\{1}", domain ?? ".", user);

                // Attempt logon
                bool returnValue = LogonUser(
                    user,
                    domain,
                    password,
                    LOGON32_LOGON_NETWORK_CLEARTEXT,
                    LOGON32_PROVIDER_DEFAULT,
                    out _tokenHandle);

                if (!returnValue)
                {
                    int error = Marshal.GetLastWin32Error();
                    Logger.Error("LogonUser failed with error code: {0}", error);
                    return false;
                }

                // Impersonate the logged-on user
                WindowsIdentity identity = new WindowsIdentity(_tokenHandle);
                _impersonationContext = identity.Impersonate();
                _isImpersonating = true;

                Logger.Info("Successfully impersonating user: {0}", identity.Name);
                return true;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to impersonate user: {0}", username);
                return false;
            }
        }

        /// <summary>
        /// Reverts impersonation back to original identity
        /// </summary>
        public void Revert()
        {
            if (_isImpersonating)
            {
                _impersonationContext?.Undo();
                _isImpersonating = false;
                Logger.Debug("Reverted impersonation");
            }
        }

        /// <summary>
        /// Dispose and cleanup
        /// </summary>
        public void Dispose()
        {
            Revert();

            if (_impersonationContext != null)
            {
                _impersonationContext.Dispose();
                _impersonationContext = null;
            }

            if (_tokenHandle != IntPtr.Zero)
            {
                CloseHandle(_tokenHandle);
                _tokenHandle = IntPtr.Zero;
            }
        }

        /// <summary>
        /// Execute action with impersonation
        /// </summary>
        public static T ExecuteWithImpersonation<T>(string username, string password, Func<T> action)
        {
            using (var impersonation = new WindowsImpersonation())
            {
                if (!string.IsNullOrWhiteSpace(username))
                {
                    if (!impersonation.Impersonate(username, password))
                    {
                        throw new InvalidOperationException($"Failed to impersonate user: {username}");
                    }
                }

                return action();
            }
        }

        /// <summary>
        /// Execute action with impersonation (void version)
        /// </summary>
        public static void ExecuteWithImpersonation(string username, string password, Action action)
        {
            using (var impersonation = new WindowsImpersonation())
            {
                if (!string.IsNullOrWhiteSpace(username))
                {
                    if (!impersonation.Impersonate(username, password))
                    {
                        throw new InvalidOperationException($"Failed to impersonate user: {username}");
                    }
                }

                action();
            }
        }
    }
}
