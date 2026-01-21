@echo off
REM ============================================================================
REM FileManagerWorker Installer Build Script
REM
REM Compiles the installer into a single standalone .exe file
REM Uses csc.exe (C# Compiler) from .NET Framework
REM ============================================================================

setlocal enabledelayedexpansion

echo.
echo ============================================================================
echo  Building FileManagerWorker Installer
echo ============================================================================
echo.

REM Find csc.exe (C# compiler)
echo [1/5] Locating C# compiler...

set CSC_PATH=
set FRAMEWORK_PATHS=^
    "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" ^
    "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe" ^
    "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\MSBuild\Current\Bin\Roslyn\csc.exe" ^
    "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\Roslyn\csc.exe" ^
    "C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\Roslyn\csc.exe" ^
    "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\Roslyn\csc.exe"

for %%P in (%FRAMEWORK_PATHS%) do (
    if exist %%P (
        set CSC_PATH=%%~P
        echo Found: !CSC_PATH!
        goto :found_compiler
    )
)

echo ERROR: Could not find csc.exe
echo Please ensure .NET Framework 4.x or Visual Studio is installed
pause
exit /b 1

:found_compiler

REM Verify source files exist
echo.
echo [2/5] Verifying source files...

if not exist "Installer.cs" (
    echo ERROR: Installer.cs not found
    pause
    exit /b 1
)

if not exist "ServiceInstaller.cs" (
    echo ERROR: ServiceInstaller.cs not found
    pause
    exit /b 1
)

echo OK - All source files found

REM Create output directory
echo.
echo [3/5] Creating output directory...
if not exist "bin" mkdir bin
echo OK - Output directory ready

REM Compile the installer
echo.
echo [4/5] Compiling installer...
echo.

"%CSC_PATH%" /nologo ^
    /target:exe ^
    /out:bin\FileManagerWorker.exe ^
    /platform:anycpu ^
    /optimize+ ^
    /reference:System.dll ^
    /reference:System.Core.dll ^
    /reference:System.Configuration.dll ^
    /reference:System.Configuration.Install.dll ^
    /reference:System.DirectoryServices.dll ^
    /reference:System.DirectoryServices.AccountManagement.dll ^
    /reference:System.ServiceProcess.dll ^
    /reference:System.Xml.dll ^
    /win32icon:icon.ico ^
    Installer.cs ^
    ServiceInstaller.cs

if errorlevel 1 (
    echo.
    echo ERROR: Compilation failed
    pause
    exit /b 1
)

echo.
echo OK - Compilation successful

REM Verify output
echo.
echo [5/5] Verifying output...

if not exist "bin\FileManagerWorker.exe" (
    echo ERROR: Output file not found
    pause
    exit /b 1
)

REM Get file size
for %%F in (bin\FileManagerWorker.exe) do set FILE_SIZE=%%~zF
set /a FILE_SIZE_KB=!FILE_SIZE! / 1024

echo OK - Executable created successfully
echo.

REM Show summary
echo ============================================================================
echo  BUILD COMPLETE
echo ============================================================================
echo.
echo Output: bin\FileManagerWorker.exe
echo Size:   !FILE_SIZE_KB! KB
echo.
echo The installer is ready for distribution!
echo.
echo USAGE:
echo   bin\FileManagerWorker.exe /install /url https://api.example.com /user ServiceUser /pass Password123
echo   bin\FileManagerWorker.exe /uninstall
echo   bin\FileManagerWorker.exe /debug
echo   bin\FileManagerWorker.exe /?
echo.
echo NOTES:
echo   - Must be run as Administrator on target machine
echo   - No external dependencies required
echo   - Single file deployment
echo.

REM Optional: Create installer package
set /p CREATE_ZIP="Create ZIP package? (Y/N): "
if /i "%CREATE_ZIP%"=="Y" (
    echo.
    echo Creating ZIP package...

    if exist "bin\FileManagerWorker.zip" del "bin\FileManagerWorker.zip"

    REM Check if 7-Zip is available
    if exist "C:\Program Files\7-Zip\7z.exe" (
        "C:\Program Files\7-Zip\7z.exe" a -tzip "bin\FileManagerWorker.zip" "bin\FileManagerWorker.exe" "README-INSTALLER.md" > nul
        echo OK - Package created: bin\FileManagerWorker.zip
    ) else if exist "C:\Program Files (x86)\7-Zip\7z.exe" (
        "C:\Program Files (x86)\7-Zip\7z.exe" a -tzip "bin\FileManagerWorker.zip" "bin\FileManagerWorker.exe" "README-INSTALLER.md" > nul
        echo OK - Package created: bin\FileManagerWorker.zip
    ) else (
        echo WARNING: 7-Zip not found, skipping ZIP creation
        echo You can manually create a ZIP file with the executable
    )
)

echo.
echo Build script completed successfully.
echo.
pause
