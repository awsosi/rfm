namespace FileManagerWorker.Models
{
    /// <summary>
    /// Configuration for the worker service
    /// </summary>
    public class ServiceConfiguration
    {
        public string ApiUrl { get; set; }
        public string ServiceUser { get; set; }
        public string ServicePassword { get; set; }
        public string PathAPrefix { get; set; }
        public string PathBPrefix { get; set; }
        public string PathCPrefix { get; set; }
        public int PollingIntervalSeconds { get; set; } = 5;
        public string CertificateThumbprint { get; set; }
        public bool UseMtls { get; set; } = true;
    }
}
