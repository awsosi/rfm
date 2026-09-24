using System;
using System.Diagnostics;
using System.IO;
using System.Security;
using System.Text;

namespace RFMTray
{
    /// <summary>
    /// The Windows scheduled task that starts RFM Tray when any user signs in.
    /// Registered by the installer (elevated) with --install-task; it runs in
    /// the user's own session with the user's own rights.
    /// </summary>
    static class ScheduledTask
    {
        public const string Name = @"RFM\RFM Tray";

        public static int Install(string exePath)
        {
            // Any user's logon, the Users group (S-1-5-32-545), least privilege.
            // Parallel: on a shared machine every signed-in user gets their own tray.
            string xml = $@"<?xml version=""1.0"" encoding=""UTF-16""?>
<Task version=""1.2"" xmlns=""http://schemas.microsoft.com/windows/2004/02/mit/task"">
  <RegistrationInfo>
    <Description>Starts RFM Tray, which sends finished catalog folders to RFM.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id=""Users"">
      <GroupId>S-1-5-32-545</GroupId>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context=""Users"">
    <Exec>
      <Command>{SecurityElement.Escape(exePath)}</Command>
      <Arguments>--autostart</Arguments>
    </Exec>
  </Actions>
</Task>";

            string file = Path.Combine(Path.GetTempPath(), "RFMTray.task.xml");
            File.WriteAllText(file, xml, Encoding.Unicode);
            try
            {
                return Schtasks($"/Create /TN \"{Name}\" /XML \"{file}\" /F");
            }
            finally
            {
                File.Delete(file);
            }
        }

        public static int Uninstall() => Schtasks($"/Delete /TN \"{Name}\" /F");

        private static int Schtasks(string arguments)
        {
            var info = new ProcessStartInfo("schtasks.exe", arguments)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using (var process = Process.Start(info))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
    }
}
