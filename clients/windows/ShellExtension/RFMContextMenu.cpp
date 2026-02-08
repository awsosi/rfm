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

	// Get localized strings
	std::wstring prepareText = Utils::GetLocalizedString(L"contextMenu.prepare");
	std::wstring sendText = Utils::GetLocalizedString(L"contextMenu.send");

	// Add "Prepare selected to be sent with RFM" menu item
	MENUITEMINFO mii = { sizeof(mii) };
	mii.fMask = MIIM_STRING | MIIM_ID;
	mii.wID = idCmdFirst + IDM_RFM_PREPARE;
	mii.dwTypeData = const_cast<LPWSTR>(prepareText.c_str());
	InsertMenuItem(hMenu, indexMenu++, TRUE, &mii);

	UINT itemsAdded = 1;

	// Add "Send selected with RFM" menu item (only for single selection)
	if (m_isSingleSelection)
	{
		mii.wID = idCmdFirst + IDM_RFM_SEND;
		mii.dwTypeData = const_cast<LPWSTR>(sendText.c_str());
		InsertMenuItem(hMenu, indexMenu++, TRUE, &mii);
		itemsAdded++;
	}

	// Return number of items added
	return MAKE_HRESULT(SEVERITY_SUCCESS, 0, itemsAdded);
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

	std::wstring helpText;

	switch (idCmd)
	{
	case IDM_RFM_PREPARE:
		helpText = Utils::GetLocalizedString(L"contextMenu.prepareHelp");
		break;

	case IDM_RFM_SEND:
		helpText = Utils::GetLocalizedString(L"contextMenu.sendHelp");
		break;

	default:
		return E_INVALIDARG;
	}

	if (!helpText.empty())
	{
		wcsncpy_s(reinterpret_cast<LPWSTR>(pszName), cchMax, helpText.c_str(), _TRUNCATE);
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
