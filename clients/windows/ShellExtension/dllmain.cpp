// dllmain.cpp : Implementation of DllMain.

#include "pch.h"
#include "framework.h"
#include "resource.h"
#include "RFMShellExt_i.h"
#include "dllmain.h"

CRFMShellExtModule _AtlModule;
HINSTANCE g_hInstance = NULL;

// DLL Entry Point
extern "C" BOOL WINAPI DllMain(HINSTANCE hInstance, DWORD dwReason, LPVOID lpReserved)
{
	if (dwReason == DLL_PROCESS_ATTACH)
	{
		g_hInstance = hInstance;
	}

	return _AtlModule.DllMain(dwReason, lpReserved);
}
