using System.Collections.Generic;
using Newtonsoft.Json;

namespace FileManagerWorker.Models
{
    /// <summary>
    /// Represents a response to a command execution (matches API CommandResponseRequest schema)
    /// </summary>
    public class CommandResponse
    {
        [JsonProperty("status")]
        public string Status { get; set; } // "success", "failed", "error"

        [JsonProperty("message")]
        public string Message { get; set; }

        [JsonProperty("file_count")]
        public int? FileCount { get; set; }

        [JsonProperty("total_size_bytes")]
        public long? TotalSizeBytes { get; set; }

        [JsonProperty("error_details")]
        public Dictionary<string, object> ErrorDetails { get; set; }

        // Not sent to API, used internally
        [JsonIgnore]
        public int CommandId { get; set; }

        public CommandResponse()
        {
            ErrorDetails = new Dictionary<string, object>();
        }

        public static CommandResponse Success(int commandId, string message = null, int? fileCount = null, long? totalSizeBytes = null)
        {
            return new CommandResponse
            {
                CommandId = commandId,
                Status = "success",
                Message = message ?? "Command completed successfully",
                FileCount = fileCount,
                TotalSizeBytes = totalSizeBytes
            };
        }

        public static CommandResponse Failed(int commandId, string message, Dictionary<string, object> errorDetails = null)
        {
            return new CommandResponse
            {
                CommandId = commandId,
                Status = "failed",
                Message = message,
                ErrorDetails = errorDetails ?? new Dictionary<string, object>()
            };
        }

        public static CommandResponse Error(int commandId, string message, Dictionary<string, object> errorDetails = null)
        {
            return new CommandResponse
            {
                CommandId = commandId,
                Status = "error",
                Message = message,
                ErrorDetails = errorDetails ?? new Dictionary<string, object>()
            };
        }
    }
}
