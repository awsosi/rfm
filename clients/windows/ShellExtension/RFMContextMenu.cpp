// RFMContextMenu.cpp : Implementation of CRFMContextMenu

#include "pch.h"
#include "RFMContextMenu.h"
#include "Utils.h"

// Menu command IDs
#define IDM_RFM_PREPARE 0
#define IDM_RFM_SEND 1

// IShellExtInit Implementation
STDMETHODIMP CRFMContextMenu::Initialize(
	PCIDLIST_ABSOLUTE pidlFolder,
	IDataObject* pDataObj,
	HKEY hkeyProgID)
{
	if (!pDataObj)
	{
		return E_INVALIDARG;
	}

	// Get selected path from data object
	HRESULT hr = GetPathFromDataObject(pDataObj);
	if (FAILED(hr))
	{
		return hr;
	}

	// Only show menu for single directory selection
	if (!m_isSingleSelection || !m_isDirectory)
	{
		return E_FAIL;
	}

	// Check if path is allowed
	if (!IsPathAllowed(m_selectedPath))
	{
		return E_FAIL;  // Don't show menu items for non-allowed paths
	}

	return S_OK;
}

// IContextMenu Implementation
STDMETHODIMP CRFMContextMenu::QueryContextMenu(
	HMENU hMenu,
	UINT indexMenu,
	UINT idCmdFirst,
	UINT idCmdLast,
	UINT uFlags)
{
	// Don't show menu in special contexts
	if (uFlags & CMF_DEFAULTONLY)
	{
		return MAKE_HRESULT(SEVERITY_SUCCESS, 0, 0);
	}

	// Load localized strings if not already loaded
	if (m_prepareText.empty())
	{
		m_prepareText = Utils::GetLocalizedString(L"contextMenu.prepare");
		m_sendText = Utils::GetLocalizedString(L"contextMenu.send");
		m_prepareHelpText = Utils::GetLocalizedString(L"contextMenu.prepareHelp");
		m_sendHelpText = Utils::GetLocalizedString(L"contextMenu.sendHelp");
	}

	// Load menu icon if not already loaded
	if (!m_hMenuBitmap)
	{
		m_hMenuBitmap = LoadMenuIcon();
	}

	// Add "Prepare selected to be sent with RFM" menu item
	MENUITEMINFO mii = { sizeof(mii) };
	mii.fMask = MIIM_STRING | MIIM_ID | MIIM_BITMAP;
	mii.wID = idCmdFirst + IDM_RFM_PREPARE;
	mii.dwTypeData = const_cast<LPWSTR>(m_prepareText.c_str());
	mii.hbmpItem = m_hMenuBitmap;
	InsertMenuItem(hMenu, indexMenu++, TRUE, &mii);

	// Add "Send selected with RFM" menu item
	mii.wID = idCmdFirst + IDM_RFM_SEND;
	mii.dwTypeData = const_cast<LPWSTR>(m_sendText.c_str());
	mii.hbmpItem = m_hMenuBitmap;
	InsertMenuItem(hMenu, indexMenu++, TRUE, &mii);

	// Return number of items added
	return MAKE_HRESULT(SEVERITY_SUCCESS, 0, 2);
}

STDMETHODIMP CRFMContextMenu::InvokeCommand(CMINVOKECOMMANDINFO* pici)
{
	// Check for verb string invocation (not supported)
	if (HIWORD(pici->lpVerb))
	{
		return E_INVALIDARG;
	}

	// Get command index
	UINT idCmd = LOWORD(pici->lpVerb);

	// Determine action
	std::wstring action;
	switch (idCmd)
	{
	case IDM_RFM_PREPARE:
		action = L"prepare";
		break;

	case IDM_RFM_SEND:
		action = L"push";
		break;

	default:
		return E_INVALIDARG;
	}

	// Launch RFM launcher
	if (!LaunchRFM(action, m_selectedPath))
	{
		return E_FAIL;
	}

	return S_OK;
}

STDMETHODIMP CRFMContextMenu::GetCommandString(
	UINT_PTR idCmd,
	UINT uType,
	UINT* pReserved,
	LPSTR pszName,
	UINT cchMax)
{
	if (uType != GCS_HELPTEXTW)
	{
		return E_NOTIMPL;
	}

	LPCWSTR helpText = nullptr;

	switch (idCmd)
	{
	case IDM_RFM_PREPARE:
		helpText = m_prepareHelpText.c_str();
		break;

	case IDM_RFM_SEND:
		helpText = m_sendHelpText.c_str();
		break;

	default:
		return E_INVALIDARG;
	}

	if (helpText && *helpText)
	{
		wcsncpy_s(reinterpret_cast<LPWSTR>(pszName), cchMax, helpText, _TRUNCATE);
		return S_OK;
	}

	return E_INVALIDARG;
}

// Helper Methods
HRESULT CRFMContextMenu::GetPathFromDataObject(IDataObject* pDataObj)
{
	FORMATETC fmt = { CF_HDROP, NULL, DVASPECT_CONTENT, -1, TYMED_HGLOBAL };
	STGMEDIUM stg = { TYMED_HGLOBAL };

	// Get HDROP from data object
	HRESULT hr = pDataObj->GetData(&fmt, &stg);
	if (FAILED(hr))
	{
		return hr;
	}

	// Get selected file count
	HDROP hDrop = static_cast<HDROP>(GlobalLock(stg.hGlobal));
	if (!hDrop)
	{
		ReleaseStgMedium(&stg);
		return E_FAIL;
	}

	UINT fileCount = DragQueryFile(hDrop, 0xFFFFFFFF, NULL, 0);
	m_isSingleSelection = (fileCount == 1);

	if (fileCount > 0)
	{
		// Get first selected file path
		WCHAR szPath[MAX_PATH];
		if (DragQueryFile(hDrop, 0, szPath, MAX_PATH))
		{
			m_selectedPath = szPath;

			// Check if it's a directory
			DWORD attrs = GetFileAttributes(szPath);
			m_isDirectory = (attrs != INVALID_FILE_ATTRIBUTES) &&
				(attrs & FILE_ATTRIBUTE_DIRECTORY);
		}
	}

	GlobalUnlock(stg.hGlobal);
	ReleaseStgMedium(&stg);

	return m_selectedPath.empty() ? E_FAIL : S_OK;
}

bool CRFMContextMenu::IsPathAllowed(const std::wstring& path)
{
	return Utils::IsPathAllowed(path);
}

std::wstring CRFMContextMenu::GetLauncherPath()
{
	return Utils::GetLauncherPath();
}

bool CRFMContextMenu::LaunchRFM(const std::wstring& action, const std::wstring& path)
{
	std::wstring launcherPath = GetLauncherPath();
	if (launcherPath.empty())
	{
		return false;
	}

	// Build command line: RFMLauncher.exe --action "path"
	std::wstring cmdLine = L"\"" + launcherPath + L"\" --" + action + L" \"" + path + L"\"";

	// Launch process
	STARTUPINFO si = { sizeof(si) };
	PROCESS_INFORMATION pi = { 0 };

	BOOL success = CreateProcess(
		NULL,
		const_cast<LPWSTR>(cmdLine.c_str()),
		NULL,
		NULL,
		FALSE,
		0,
		NULL,
		NULL,
		&si,
		&pi
	);

	if (success)
	{
		CloseHandle(pi.hProcess);
		CloseHandle(pi.hThread);
		return true;
	}

	return false;
}

HBITMAP CRFMContextMenu::LoadMenuIcon()
{
	// Load icon from resources
	HICON hIcon = (HICON)LoadImage(
		_AtlBaseModule.GetModuleInstance(),
		MAKEINTRESOURCE(IDI_RFM_ICON),
		IMAGE_ICON,
		GetSystemMetrics(SM_CXSMICON),
		GetSystemMetrics(SM_CYSMICON),
		LR_DEFAULTCOLOR
	);

	if (!hIcon)
	{
		return NULL;
	}

	// Convert icon to bitmap
	ICONINFO iconInfo = { 0 };
	if (!GetIconInfo(hIcon, &iconInfo))
	{
		DestroyIcon(hIcon);
		return NULL;
	}

	// Clean up temporary bitmaps from ICONINFO
	HBITMAP hBitmap = iconInfo.hbmColor;
	if (iconInfo.hbmMask)
	{
		DeleteObject(iconInfo.hbmMask);
	}

	DestroyIcon(hIcon);
	return hBitmap;
}
