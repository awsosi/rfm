// Utils.h : Helper functions for RFM Shell Extension

#pragma once

#include <string>
#include <vector>

class Utils
{
public:
	// Check if path is in allowed paths list
	static bool IsPathAllowed(const std::wstring& path);

	// Get launcher executable path
	static std::wstring GetLauncherPath();

	// Load configuration from config.json
	static bool LoadConfig(std::vector<std::wstring>& allowedPaths);

	// Get module directory (where DLL is located)
	static std::wstring GetModuleDirectory();

	// Case-insensitive string comparison
	static bool StartsWithIgnoreCase(const std::wstring& str, const std::wstring& prefix);

	// Load language setting from config.json
	static std::wstring GetLanguage();

	// Load localized string from localization file
	static std::wstring GetLocalizedString(const std::wstring& key);
};
