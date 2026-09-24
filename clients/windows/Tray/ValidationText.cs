using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace RFMTray
{
    /// <summary>
    /// Readable text for a PUSH validation rejection: a port of the WebUI's
    /// formatValidationFailure() (frontend/js/app.js), with the same strings.
    /// </summary>
    static class ValidationText
    {
        public static List<string> Suggestions(JObject validation)
        {
            var catalog = validation?["catalog"] as JObject;
            if (catalog == null || (bool?)catalog["valid"] != false)
                return new List<string>();
            return (catalog["suggestions"] as JArray)?.Select(s => (string)s).ToList() ?? new List<string>();
        }

        public static string Format(JObject validation)
        {
            var lines = new List<string>();
            var catalog = validation?["catalog"] as JObject ?? new JObject();
            var content = validation?["content"] as JObject ?? new JObject();

            if ((bool?)catalog["valid"] == false)
            {
                lines.Add(L.T("validation.catalogTitle"));
                string reason = (string)catalog["reason"];
                if (!string.IsNullOrEmpty(reason))
                    lines.Add(L.T("validation." + reason, ("name", (string)catalog["catalog_name"] ?? "")));
                // Suggestions are offered as a list in the dialog, not in this text
                if (reason == "catalogValidation.noMatch" && Suggestions(validation).Count == 0)
                    lines.Add(L.T("validation.noSuggestions"));
            }

            if ((bool?)content["valid"] == false)
            {
                if (lines.Count > 0)
                    lines.Add("");
                lines.Add(L.T("validation.contentTitle"));

                const string nameRule = "contentValidation.invalidFileNames";
                var badNames = Strings(content["invalid_names"]);
                string forms = AcceptedNameForms(content);
                string reason = (string)content["reason"];
                int images = (int?)content["image_count"] ?? 0;
                int required = (int?)content["min_required"] ?? 0;

                if (!string.IsNullOrEmpty(reason))
                {
                    string names = reason == nameRule
                        ? string.Join(", ", badNames)
                        : string.Join(", ", (content["invalid_files"] as JArray ?? new JArray()).Select(f => (string)f["name"]));
                    lines.Add(L.T("validation." + reason,
                        ("images", images), ("required", required), ("names", names), ("forms", forms)));
                }
                if (reason != nameRule && badNames.Count > 0)
                    lines.Add(L.T("validation." + nameRule, ("names", string.Join(", ", badNames)), ("forms", forms)));

                lines.Add("");
                lines.Add(L.T("validation.summary",
                    ("images", images), ("required", required), ("total", (int?)content["total_files"] ?? 0)));
            }

            return string.Join("\r\n", lines);
        }

        /// <summary>The file name forms PIM accepts, from the server's configured suffixes.</summary>
        private static string AcceptedNameForms(JObject content)
        {
            var forms = new List<string> { "3.png" };
            forms.AddRange(Strings(content["allowed_name_suffixes"]).Select(suffix => $"3{suffix}.png"));
            return string.Join(", ", forms);
        }

        private static List<string> Strings(JToken token) =>
            (token as JArray)?.Select(t => (string)t).ToList() ?? new List<string>();
    }
}
