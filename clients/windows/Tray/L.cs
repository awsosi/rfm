using System.Collections.Generic;
using RFMLauncher;

namespace RFMTray
{
    /// <summary>
    /// Localized strings from the launcher's locales/*.json ({name} placeholders).
    /// </summary>
    static class L
    {
        private static Dictionary<string, string> _strings = new Dictionary<string, string>();

        public static void Load(string language)
        {
            _strings = LocalizationManager.Load(language) ?? _strings;
        }

        public static string T(string key, params (string Name, object Value)[] args)
        {
            string text = _strings.TryGetValue(key, out var value) ? value : key;
            foreach (var (name, val) in args)
                text = text.Replace("{" + name + "}", val?.ToString() ?? "");
            return text;
        }
    }
}
