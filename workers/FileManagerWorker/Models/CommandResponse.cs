using System.Collections.Generic;

namespace FileManagerWorker.Models
{
    /// <summary>
    /// Represents a response to a command execution
    /// </summary>
    public class CommandResponse
    {
        public string CommandId { get; set; }
        public string Status { get; set; } // "success", "failed", "in_progress"
        public string Error { get; set; }
        public string RollbackStatus { get; set; }
        public Dictionary<string, object> Details { get; set; }
        public int ProgressPercent { get; set; }

        public CommandResponse()
        {
            Details = new Dictionary<string, object>();
        }

        public static CommandResponse Success(string commandId, Dictionary<string, object> details = null)
        {
            return new CommandResponse
            {
                CommandId = commandId,
                Status = "success",
                Details = details ?? new Dictionary<string, object>()
            };
        }

        public static CommandResponse Failed(string commandId, string error, string rollbackStatus = null)
        {
            return new CommandResponse
            {
                CommandId = commandId,
                Status = "failed",
                Error = error,
                RollbackStatus = rollbackStatus
            };
        }

        public static CommandResponse InProgress(string commandId, int progressPercent, Dictionary<string, object> details = null)
        {
            return new CommandResponse
            {
                CommandId = commandId,
                Status = "in_progress",
                ProgressPercent = progressPercent,
                Details = details ?? new Dictionary<string, object>()
            };
        }
    }
}
