// Utils.cpp : Implementation of utility functions

#include "pch.h"
#include "Utils.h"
#include <shlwapi.h>
#include <atlbase.h>
#include <fstream>
#include <algorithm>

extern HINSTANCE g_hInstance;

std::wstring Utils::GetModuleDirectory()
{
	WCHAR modulePath[MAX_PATH];
	GetModuleFileName(g_hInstance, modulePath, MAX_PATH);

	// Remove filename to get directory
	PathRemoveFileSpec(modulePath);

	return modulePath;
}

std::wstring Utils::GetLauncherPath()
{
	// Launcher is in the same directory as the shell extension DLL
	// or in the parent directory (Program Files\RFM)
	std::wstring moduleDir = GetModuleDirectory();
	std::wstring launcherPath = moduleDir + L"\\RFMLauncher.exe";

	// Check if launcher exists
	if (PathFileExists(launcherPath.c_str()))
	{
		return launcherPath;
	}

	// Try parent directory
	std::wstring parentDir = moduleDir;
	PathRemoveFileSpec(const_cast<LPWSTR>(parentDir.c_str()));
	launcherPath = parentDir + L"\\RFMLauncher.exe";

	if (PathFileExists(launcherPath.c_str()))
	{
		return launcherPath;
	}

	// Try standard installation path
	launcherPath = L"C:\\Program Files\\RFM\\RFMLauncher.exe";
	if (PathFileExists(launcherPath.c_str()))
	{
		return launcherPath;
	}

	return L"";
}

bool Utils::LoadConfig(std::vector<std::wstring>& allowedPaths)
{
	allowedPaths.clear();

	// Get config.json path (same directory as launcher)
	std::wstring moduleDir = GetModuleDirectory();
	std::wstring configPath = moduleDir + L"\\config.json";

	// Try parent directory if not found
	if (!PathFileExists(configPath.c_str()))
	{
		std::wstring parentDir = moduleDir;
		PathRemoveFileSpec(const_cast<LPWSTR>(parentDir.c_str()));
		configPath = parentDir + L"\\config.json";
	}

	// Try standard installation path
	if (!PathFileExists(configPath.c_str()))
	{
		configPath = L"C:\\Program Files\\RFM\\config.json";
	}

	if (!PathFileExists(configPath.c_str()))
	{
		return false;
	}

	// Read config file
	std::wifstream file(configPath);
	if (!file.is_open())
	{
		return false;
	}

	std::wstring content((std::istreambuf_iterator<wchar_t>(file)),
		std::istreambuf_iterator<wchar_t>());
	file.close();

	// Simple JSON parsing for "allowed_paths" array
	// Look for "allowed_paths": [...] pattern
	size_t pathsStart = content.find(L"\"allowed_paths\"");
	if (pathsStart == std::wstring::npos)
	{
		return false;
	}

	// Find opening bracket
	size_t bracketStart = content.find(L'[', pathsStart);
	if (bracketStart == std::wstring::npos)
	{
		return false;
	}

	// Find closing bracket
	size_t bracketEnd = content.find(L']', bracketStart);
	if (bracketEnd == std::wstring::npos)
	{
		return false;
	}

	// Extract paths from array
	std::wstring pathsJson = content.substr(bracketStart + 1, bracketEnd - bracketStart - 1);

	// Parse each quoted string
	size_t pos = 0;
	while (pos < pathsJson.length())
	{
		// Find opening quote
		size_t quoteStart = pathsJson.find(L'"', pos);
		if (quoteStart == std::wstring::npos)
		{
			break;
		}

		// Find closing quote
		size_t quoteEnd = pathsJson.find(L'"', quoteStart + 1);
		if (quoteEnd == std::wstring::npos)
		{
			break;
		}

		// Extract path
		std::wstring path = pathsJson.substr(quoteStart + 1, quoteEnd - quoteStart - 1);

		// Unescape backslashes (JSON uses \\ for single \)
		std::wstring unescaped;
		for (size_t i = 0; i < path.length(); i++)
		{
			if (path[i] == L'\\' && i + 1 < path.length() && path[i + 1] == L'\\')
			{
				unescaped += L'\\';
				i++;  // Skip next backslash
			}
			else
			{
				unescaped += path[i];
			}
		}

		if (!unescaped.empty())
		{
			allowedPaths.push_back(unescaped);
		}

		pos = quoteEnd + 1;
	}

	return !allowedPaths.empty();
}

bool Utils::StartsWithIgnoreCase(const std::wstring& str, const std::wstring& prefix)
{
	if (str.length() < prefix.length())
	{
		return false;
	}

	return _wcsnicmp(str.c_str(), prefix.c_str(), prefix.length()) == 0;
}

bool Utils::IsPathAllowed(const std::wstring& path)
{
	std::vector<std::wstring> allowedPaths;
	if (!LoadConfig(allowedPaths))
	{
		return false;
	}

	// Normalize path separators
	std::wstring normalizedPath = path;
	std::replace(normalizedPath.begin(), normalizedPath.end(), L'/', L'\\');

	// Check if path starts with any allowed path
	for (const auto& allowedPath : allowedPaths)
	{
		std::wstring normalizedAllowed = allowedPath;
		std::replace(normalizedAllowed.begin(), normalizedAllowed.end(), L'/', L'\\');

		if (StartsWithIgnoreCase(normalizedPath, normalizedAllowed))
		{
			return true;
		}
	}

	return false;
}
