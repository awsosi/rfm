using System.Collections.Generic;

namespace FileManagerWorker.Models
{
    /// <summary>
    /// Represents a command request from the Central API
    /// </summary>
    public class CommandRequest
    {
        public string CommandId { get; set; }
        public string Command { get; set; }
        public Dictionary<string, string> Parameters { get; set; }
        public long Timestamp { get; set; }
    }
}
