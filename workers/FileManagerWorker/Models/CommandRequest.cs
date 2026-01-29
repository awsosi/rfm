using System.Collections.Generic;
using Newtonsoft.Json;

namespace FileManagerWorker.Models
{
    /// <summary>
    /// Represents a command request from the Central API (pull-based)
    /// </summary>
    public class CommandRequest
    {
        [JsonProperty("command_id")]
        public int? CommandId { get; set; }

        [JsonProperty("command")]
        public string Command { get; set; }

        [JsonProperty("source_path")]
        public string SourcePath { get; set; }

        [JsonProperty("dest_path")]
        public string DestPath { get; set; }

        [JsonProperty("parameters")]
        public Dictionary<string, object> Parameters { get; set; }
    }
}
