// RFMContextMenu.h : Declaration of the CRFMContextMenu

#pragma once
#include "resource.h"       // main symbols
#include "RFMShellExt_i.h"

#if defined(_WIN32_WCE) && !defined(_CE_DCOM) && !defined(_CE_ALLOW_SINGLE_THREADED_OBJECTS_IN_MTA)
#error "Single-threaded COM objects are not properly supported on Windows CE platform, such as the Windows Mobile platforms that do not include full DCOM support. Define _CE_ALLOW_SINGLE_THREADED_OBJECTS_IN_MTA to force ATL to support creating single-thread COM object's and allow use of it's single-threaded COM object implementations. The threading model in your rgs file was set to 'Free' as that is the only threading model supported in non DCOM Windows CE platforms."
#endif

using namespace ATL;

// CRFMContextMenu

class ATL_NO_VTABLE CRFMContextMenu :
	public CComObjectRootEx<CComSingleThreadModel>,
	public CComCoClass<CRFMContextMenu, &CLSID_RFMContextMenu>,
	public IShellExtInit,
	public IContextMenu
{
private:
	std::wstring m_selectedPath;
	bool m_isSingleSelection;
	bool m_isDirectory;

	// Localized menu strings (cached)
	std::wstring m_prepareText;
	std::wstring m_sendText;
	std::wstring m_prepareHelpText;
	std::wstring m_sendHelpText;

	// Helper methods
	HRESULT GetPathFromDataObject(IDataObject* pDataObj);
	bool IsPathAllowed(const std::wstring& path);
	std::wstring GetLauncherPath();
	bool LaunchRFM(const std::wstring& action, const std::wstring& path);

public:
	CRFMContextMenu()
		: m_isSingleSelection(false)
		, m_isDirectory(false)
	{
	}

DECLARE_REGISTRY_RESOURCEID(IDR_RFMCONTEXTMENU)

DECLARE_NOT_AGGREGATABLE(CRFMContextMenu)

BEGIN_COM_MAP(CRFMContextMenu)
	COM_INTERFACE_ENTRY(IShellExtInit)
	COM_INTERFACE_ENTRY(IContextMenu)
END_COM_MAP()

	DECLARE_PROTECT_FINAL_CONSTRUCT()

	HRESULT FinalConstruct()
	{
		return S_OK;
	}

	void FinalRelease()
	{
	}

public:
	// IShellExtInit
	STDMETHOD(Initialize)(
		_In_opt_ PCIDLIST_ABSOLUTE pidlFolder,
		_In_opt_ IDataObject* pDataObj,
		_In_opt_ HKEY hkeyProgID);

	// IContextMenu
	STDMETHOD(QueryContextMenu)(
		HMENU hMenu,
		UINT indexMenu,
		UINT idCmdFirst,
		UINT idCmdLast,
		UINT uFlags);

	STDMETHOD(InvokeCommand)(
		_In_ CMINVOKECOMMANDINFO* pici);

	STDMETHOD(GetCommandString)(
		UINT_PTR idCmd,
		UINT uType,
		_Reserved_ UINT* pReserved,
		_Out_writes_bytes_((uType & GCS_UNICODE) ? (cchMax * sizeof(wchar_t)) : cchMax) LPSTR pszName,
		UINT cchMax);
};

OBJECT_ENTRY_AUTO(__uuidof(RFMContextMenu), CRFMContextMenu)
