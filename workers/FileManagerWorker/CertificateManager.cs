using System;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using NLog;

namespace FileManagerWorker
{
    /// <summary>
    /// Manages certificate generation and storage in Windows Certificate Store
    /// </summary>
    public class CertificateManager
    {
        private static readonly Logger Logger = LogManager.GetCurrentClassLogger();
        private const string CertificateSubject = "CN=FileManagerWorker";
        private const string CertificateFriendlyName = "FileManagerWorker Client Certificate";

		public enum CertStoreMode { CurrentUser, LocalMachine }
		public CertStoreMode StoreMode { get; set; } = CertStoreMode.LocalMachine;  // Domy�lnie LocalMachine dla service

		private X509Store GetStore(StoreName name, OpenFlags flags) =>
			new(name, StoreMode == CertStoreMode.CurrentUser ? StoreLocation.CurrentUser : StoreLocation.LocalMachine);
		/// <summary>
		/// Gets or creates a client certificate for mTLS
		/// </summary>
		public X509Certificate2 GetOrCreateCertificate()
        {
            try
            {
                // Try to find existing certificate
                var existingCert = FindCertificate();
                if (existingCert != null)
                {
                    Logger.Info("Found existing certificate with thumbprint: {0}", existingCert.Thumbprint);
                    return existingCert;
                }

                // Generate new certificate
                Logger.Info("No existing certificate found. Generating new self-signed certificate...");
                var newCert = GenerateSelfSignedCertificate();

                // Store in Windows Certificate Store
                StoreCertificate(newCert);

                Logger.Info("Certificate generated and stored with thumbprint: {0}", newCert.Thumbprint);
                return newCert;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to get or create certificate");
                throw;
            }
        }

        /// <summary>
        /// Finds an existing certificate in the Windows Certificate Store
        /// </summary>
        private X509Certificate2 FindCertificate()
        {
            try
            {
                using (var store = GetStore(StoreName.My, OpenFlags.ReadOnly))
                {
                    store.Open(OpenFlags.ReadOnly);

                    var certificates = store.Certificates.Find(
                        X509FindType.FindBySubjectDistinguishedName,
                        CertificateSubject,
                        false);

                    if (certificates.Count > 0)
                    {
                        // Return the most recent certificate
                        X509Certificate2 mostRecent = null;
                        foreach (X509Certificate2 cert in certificates)
                        {
                            if (mostRecent == null || cert.NotBefore > mostRecent.NotBefore)
                            {
                                mostRecent = cert;
                            }
                        }
                        return mostRecent;
                    }

                    return null;
                }
            }
            catch (Exception ex)
            {
                Logger.Warn(ex, "Error finding certificate");
                return null;
            }
        }

        /// <summary>
        /// Generates a self-signed certificate
        /// </summary>
        private X509Certificate2 GenerateSelfSignedCertificate()
        {
            try
            {
                // Create RSA key pair
                using (RSA rsa = RSA.Create(2048))
                {
                    // Create certificate request
                    var request = new CertificateRequest(
                        CertificateSubject,
                        rsa,
                        HashAlgorithmName.SHA256,
                        RSASignaturePadding.Pkcs1);

                    // Add extensions
                    request.CertificateExtensions.Add(
                        new X509KeyUsageExtension(
                            X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment,
                            true));

                    request.CertificateExtensions.Add(
                        new X509EnhancedKeyUsageExtension(
                            new OidCollection
                            {
                                new Oid("1.3.6.1.5.5.7.3.2") // Client Authentication
                            },
                            false));

                    request.CertificateExtensions.Add(
                        new X509SubjectKeyIdentifierExtension(request.PublicKey, false));

                    // Create self-signed certificate valid for 10 years
                    var certificate = request.CreateSelfSigned(
                        DateTimeOffset.UtcNow.AddDays(-1),
                        DateTimeOffset.UtcNow.AddYears(10));

                    // Set friendly name
                    certificate.FriendlyName = CertificateFriendlyName;

					// Export PFX z kluczem prywatnym i zaimportuj z flagami
					var pfxBytes = certificate.Export(X509ContentType.Pfx);

					// Use appropriate key storage based on StoreMode
					var keyStorageFlags = X509KeyStorageFlags.Exportable | X509KeyStorageFlags.PersistKeySet;
					if (StoreMode == CertStoreMode.LocalMachine)
					{
						keyStorageFlags |= X509KeyStorageFlags.MachineKeySet;
					}
					else
					{
						keyStorageFlags |= X509KeyStorageFlags.UserKeySet;
					}

					return new X509Certificate2(pfxBytes, (string)null, keyStorageFlags);
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to generate self-signed certificate");
                throw;
            }
        }

        /// <summary>
        /// Stores certificate in Windows Certificate Store
        /// </summary>
        private void StoreCertificate(X509Certificate2 certificate)
        {
            try
            {
                using (var store = GetStore(StoreName.My, OpenFlags.ReadWrite))
				{
                    store.Open(OpenFlags.ReadWrite);
                    store.Add(certificate);
					Logger.Info("Certificate stored in {0}\\My store",
	                    StoreMode == CertStoreMode.CurrentUser ? "CurrentUser" : "LocalMachine");
				}
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to store certificate");
                throw;
            }
        }

        /// <summary>
        /// Exports the public key (certificate without private key) as PEM
        /// </summary>
        public string ExportPublicKeyAsPem(X509Certificate2 certificate)
        {
            try
            {
                var publicKeyBytes = certificate.Export(X509ContentType.Cert);
                var base64 = Convert.ToBase64String(publicKeyBytes);

                // Format as PEM
                var pem = "-----BEGIN CERTIFICATE-----\n";
                for (int i = 0; i < base64.Length; i += 64)
                {
                    pem += base64.Substring(i, Math.Min(64, base64.Length - i)) + "\n";
                }
                pem += "-----END CERTIFICATE-----";

                return pem;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to export public key as PEM");
                throw;
            }
        }

        /// <summary>
        /// Gets certificate by thumbprint
        /// </summary>
        public X509Certificate2 GetCertificateByThumbprint(string thumbprint)
        {
            try
            {
				using (var store = GetStore(StoreName.My, OpenFlags.ReadOnly))
				{
                    store.Open(OpenFlags.ReadOnly);

                    var certificates = store.Certificates.Find(
                        X509FindType.FindByThumbprint,
                        thumbprint,
                        false);

                    if (certificates.Count > 0)
                    {
                        return certificates[0];
                    }

                    Logger.Warn("Certificate with thumbprint {0} not found", thumbprint);
                    return null;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Error getting certificate by thumbprint");
                return null;
            }
        }

        /// <summary>
        /// Deletes certificate from store
        /// </summary>
        public void DeleteCertificate(string thumbprint)
        {
            try
            {
                using (var store = GetStore(StoreName.My, OpenFlags.ReadWrite))
				{
                    store.Open(OpenFlags.ReadWrite);

                    var certificates = store.Certificates.Find(
                        X509FindType.FindByThumbprint,
                        thumbprint,
                        false);

                    if (certificates.Count > 0)
                    {
                        store.Remove(certificates[0]);
                        Logger.Info("Certificate with thumbprint {0} removed", thumbprint);
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "Failed to delete certificate");
                throw;
            }
        }
    }
}
