using System;
using System.Collections;
using System.Configuration.Install;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.ServiceProcess;
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace FileManagerWorkerInstaller
{
    /// <summary>
    /// Manages Windows Service installation and uninstallation
    /// Uses Win32 API for service control
    /// </summary>
    public static class ServiceManager
    {
        private const string SERVICE_NAME = "FileManagerWorker";
        private const string SERVICE_DISPLAY_NAME = "File Manager Worker Service";
        private const string SERVICE_DESCRIPTION = "Manages file operations for centralized file manager";
        private const string INSTALL_PATH = @"C:\Program Files\FileManager\Worker";

        #region Win32 API Declarations

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        static extern IntPtr OpenSCManager(string machineName, string databaseName, uint dwAccess);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        static extern IntPtr CreateService(
            IntPtr hSCManager,
            string lpServiceName,
            string lpDisplayName,
            uint dwDesiredAccess,
            uint dwServiceType,
            uint dwStartType,
            uint dwErrorControl,
            string lpBinaryPathName,
            string lpLoadOrderGroup,
            IntPtr lpdwTagId,
            string lpDependencies,
            string lpServiceStartName,
            string lpPassword);

        [DllImport("advapi32.dll", SetLastError = true)]
        static extern bool CloseServiceHandle(IntPtr hSCObject);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        static extern IntPtr OpenService(IntPtr hSCManager, string lpServiceName, uint dwDesiredAccess);

        [DllImport("advapi32.dll", SetLastError = true)]
        static extern bool DeleteService(IntPtr hService);

        [DllImport("advapi32.dll", SetLastError = true)]
        static extern bool ControlService(IntPtr hService, uint dwControl, ref SERVICE_STATUS lpServiceStatus);

        [DllImport("advapi32.dll", SetLastError = true)]
        static extern bool QueryServiceStatus(IntPtr hService, ref SERVICE_STATUS lpServiceStatus);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Auto)]
        static extern bool ChangeServiceConfig2(IntPtr hService, uint dwInfoLevel, ref SERVICE_DESCRIPTION lpInfo);

        // Service access rights
        const uint SC_MANAGER_ALL_ACCESS = 0xF003F;
        const uint SERVICE_ALL_ACCESS = 0xF01FF;
        const uint SERVICE_QUERY_STATUS = 0x0004;
        const uint SERVICE_STOP = 0x0020;

        // Service types
        const uint SERVICE_WIN32_OWN_PROCESS = 0x00000010;

        // Service start types
        const uint SERVICE_DEMAND_START = 0x00000003; // Manual
        const uint SERVICE_AUTO_START = 0x00000002;   // Automatic

        // Service error control
        const uint SERVICE_ERROR_NORMAL = 0x00000001;

        // Service control codes
        const uint SERVICE_CONTROL_STOP = 0x00000001;

        // Service config info levels
        const uint SERVICE_CONFIG_DESCRIPTION = 1;

        [StructLayout(LayoutKind.Sequential)]
        struct SERVICE_STATUS
        {
            public uint dwServiceType;
            public uint dwCurrentState;
            public uint dwControlsAccepted;
            public uint dwWin32ExitCode;
            public uint dwServiceSpecificExitCode;
            public uint dwCheckPoint;
            public uint dwWaitHint;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
        struct SERVICE_DESCRIPTION
        {
            public string lpDescription;
        }

        // Service states
        const uint SERVICE_STOPPED = 0x00000001;
        const uint SERVICE_RUNNING = 0x00000004;

        #endregion

        /// <summary>
        /// Installs the Windows Service
        /// </summary>
        public static void InstallService(string username, string password)
        {
            IntPtr scManager = IntPtr.Zero;
            IntPtr service = IntPtr.Zero;

            try
            {
                // Open Service Control Manager
                scManager = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
                if (scManager == IntPtr.Zero)
                {
                    throw new Exception($"Failed to open Service Control Manager. Error: {Marshal.GetLastWin32Error()}");
                }

                // Check if service already exists
                service = OpenService(scManager, SERVICE_NAME, SERVICE_ALL_ACCESS);
                if (service != IntPtr.Zero)
                {
                    CloseServiceHandle(service);
                    throw new Exception($"Service '{SERVICE_NAME}' already exists. Uninstall it first.");
                }

                // Build binary path
                string binaryPath = Path.Combine(INSTALL_PATH, "FileManagerWorker.exe");
                if (!File.Exists(binaryPath))
                {
                    throw new Exception($"Executable not found at: {binaryPath}");
                }

                // Format username for service
                string serviceUsername = username;
                if (!username.Contains("\\") && !username.Contains("@"))
                {
                    // Add .\ prefix for local machine accounts
                    serviceUsername = ".\\" + username;
                }

                // Create the service
                service = CreateService(
                    scManager,
                    SERVICE_NAME,
                    SERVICE_DISPLAY_NAME,
                    SERVICE_ALL_ACCESS,
                    SERVICE_WIN32_OWN_PROCESS,
                    SERVICE_DEMAND_START, // Manual start
                    SERVICE_ERROR_NORMAL,
                    binaryPath,
                    null,
                    IntPtr.Zero,
                    null,
                    serviceUsername,
                    password);

                if (service == IntPtr.Zero)
                {
                    int error = Marshal.GetLastWin32Error();
                    throw new Exception($"Failed to create service. Win32 Error: {error}");
                }

                // Set service description
                SERVICE_DESCRIPTION desc = new SERVICE_DESCRIPTION
                {
                    lpDescription = SERVICE_DESCRIPTION
                };

                if (!ChangeServiceConfig2(service, SERVICE_CONFIG_DESCRIPTION, ref desc))
                {
                    // Non-fatal, just log
                    Console.WriteLine($"    WARNING: Could not set service description. Error: {Marshal.GetLastWin32Error()}");
                }

                // Set service recovery options via registry (optional)
                SetServiceRecoveryOptions();

                Console.WriteLine($"    Service '{SERVICE_NAME}' created successfully");
            }
            catch (Exception ex)
            {
                throw new Exception($"Service installation failed: {ex.Message}", ex);
            }
            finally
            {
                if (service != IntPtr.Zero)
                    CloseServiceHandle(service);
                if (scManager != IntPtr.Zero)
                    CloseServiceHandle(scManager);
            }
        }

        /// <summary>
        /// Uninstalls the Windows Service
        /// </summary>
        public static void UninstallService()
        {
            IntPtr scManager = IntPtr.Zero;
            IntPtr service = IntPtr.Zero;

            try
            {
                // Open Service Control Manager
                scManager = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
                if (scManager == IntPtr.Zero)
                {
                    throw new Exception($"Failed to open Service Control Manager. Error: {Marshal.GetLastWin32Error()}");
                }

                // Open the service
                service = OpenService(scManager, SERVICE_NAME, SERVICE_ALL_ACCESS);
                if (service == IntPtr.Zero)
                {
                    throw new Exception($"Service '{SERVICE_NAME}' not found.");
                }

                // Delete the service
                if (!DeleteService(service))
                {
                    int error = Marshal.GetLastWin32Error();
                    throw new Exception($"Failed to delete service. Win32 Error: {error}");
                }

                Console.WriteLine($"    Service '{SERVICE_NAME}' deleted successfully");
            }
            catch (Exception ex)
            {
                throw new Exception($"Service uninstallation failed: {ex.Message}", ex);
            }
            finally
            {
                if (service != IntPtr.Zero)
                    CloseServiceHandle(service);
                if (scManager != IntPtr.Zero)
                    CloseServiceHandle(scManager);
            }
        }

        /// <summary>
        /// Stops the Windows Service if running
        /// </summary>
        public static void StopService()
        {
            IntPtr scManager = IntPtr.Zero;
            IntPtr service = IntPtr.Zero;

            try
            {
                // Open Service Control Manager
                scManager = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
                if (scManager == IntPtr.Zero)
                {
                    Console.WriteLine($"    Service not installed or already stopped");
                    return;
                }

                // Open the service
                service = OpenService(scManager, SERVICE_NAME, SERVICE_STOP | SERVICE_QUERY_STATUS);
                if (service == IntPtr.Zero)
                {
                    Console.WriteLine($"    Service not found or already stopped");
                    return;
                }

                // Query service status
                SERVICE_STATUS status = new SERVICE_STATUS();
                if (QueryServiceStatus(service, ref status))
                {
                    if (status.dwCurrentState == SERVICE_STOPPED)
                    {
                        Console.WriteLine($"    Service already stopped");
                        return;
                    }

                    if (status.dwCurrentState == SERVICE_RUNNING)
                    {
                        // Stop the service
                        if (!ControlService(service, SERVICE_CONTROL_STOP, ref status))
                        {
                            Console.WriteLine($"    WARNING: Could not stop service. Error: {Marshal.GetLastWin32Error()}");
                        }
                        else
                        {
                            // Wait for service to stop
                            for (int i = 0; i < 30; i++)
                            {
                                System.Threading.Thread.Sleep(1000);
                                QueryServiceStatus(service, ref status);
                                if (status.dwCurrentState == SERVICE_STOPPED)
                                {
                                    break;
                                }
                            }

                            if (status.dwCurrentState != SERVICE_STOPPED)
                            {
                                Console.WriteLine($"    WARNING: Service did not stop in time");
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    WARNING: Error stopping service: {ex.Message}");
            }
            finally
            {
                if (service != IntPtr.Zero)
                    CloseServiceHandle(service);
                if (scManager != IntPtr.Zero)
                    CloseServiceHandle(scManager);
            }
        }

        /// <summary>
        /// Sets service recovery options via registry
        /// </summary>
        private static void SetServiceRecoveryOptions()
        {
            try
            {
                string keyPath = $@"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}";
                using (RegistryKey key = Registry.LocalMachine.OpenSubKey(keyPath, true))
                {
                    if (key != null)
                    {
                        // Set failure actions: Restart service on failure
                        // This is a simplified version - full implementation would use ChangeServiceConfig2 with SERVICE_FAILURE_ACTIONS
                        key.SetValue("Description", SERVICE_DESCRIPTION);
                        key.SetValue("DelayedAutostart", 0, RegistryValueKind.DWord); // Not delayed
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"    WARNING: Could not set recovery options: {ex.Message}");
            }
        }

        /// <summary>
        /// Checks if the service is installed
        /// </summary>
        public static bool IsServiceInstalled()
        {
            IntPtr scManager = IntPtr.Zero;
            IntPtr service = IntPtr.Zero;

            try
            {
                scManager = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
                if (scManager == IntPtr.Zero)
                    return false;

                service = OpenService(scManager, SERVICE_NAME, SERVICE_QUERY_STATUS);
                return service != IntPtr.Zero;
            }
            finally
            {
                if (service != IntPtr.Zero)
                    CloseServiceHandle(service);
                if (scManager != IntPtr.Zero)
                    CloseServiceHandle(scManager);
            }
        }

        /// <summary>
        /// Gets the current service status
        /// </summary>
        public static string GetServiceStatus()
        {
            IntPtr scManager = IntPtr.Zero;
            IntPtr service = IntPtr.Zero;

            try
            {
                scManager = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
                if (scManager == IntPtr.Zero)
                    return "Unknown";

                service = OpenService(scManager, SERVICE_NAME, SERVICE_QUERY_STATUS);
                if (service == IntPtr.Zero)
                    return "Not Installed";

                SERVICE_STATUS status = new SERVICE_STATUS();
                if (QueryServiceStatus(service, ref status))
                {
                    switch (status.dwCurrentState)
                    {
                        case SERVICE_STOPPED: return "Stopped";
                        case SERVICE_RUNNING: return "Running";
                        case 0x00000002: return "Starting";
                        case 0x00000003: return "Stopping";
                        default: return $"Unknown ({status.dwCurrentState})";
                    }
                }

                return "Unknown";
            }
            finally
            {
                if (service != IntPtr.Zero)
                    CloseServiceHandle(service);
                if (scManager != IntPtr.Zero)
                    CloseServiceHandle(scManager);
            }
        }
    }
}
