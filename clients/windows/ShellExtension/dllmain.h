// dllmain.h : Declaration of module class.

class CRFMShellExtModule : public ATL::CAtlDllModuleT< CRFMShellExtModule >
{
public :
	DECLARE_LIBID(LIBID_RFMShellExtLib)
	DECLARE_REGISTRY_APPID_RESOURCEID(IDR_RFMSHELLEXT, "{B1C2D3E4-F5A6-7890-BCDE-F12345678901}")
};

extern class CRFMShellExtModule _AtlModule;
extern HINSTANCE g_hInstance;
