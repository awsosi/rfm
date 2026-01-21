#!/bin/bash
# ============================================================================
# Build Check Script for FileManagerWorker Installer
#
# This script verifies that all required source files are present
# Run this on non-Windows systems to check the installer is ready to build
# ============================================================================

echo ""
echo "============================================================================"
echo "  FileManagerWorker Installer - Build Check"
echo "============================================================================"
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

all_good=true

# Check for required source files
echo "[1/4] Checking source files..."
if [ -f "Installer.cs" ]; then
    echo -e "  ${GREEN}✓${NC} Installer.cs found"
else
    echo -e "  ${RED}✗${NC} Installer.cs missing"
    all_good=false
fi

if [ -f "ServiceInstaller.cs" ]; then
    echo -e "  ${GREEN}✓${NC} ServiceInstaller.cs found"
else
    echo -e "  ${RED}✗${NC} ServiceInstaller.cs missing"
    all_good=false
fi

if [ -f "build.bat" ]; then
    echo -e "  ${GREEN}✓${NC} build.bat found"
else
    echo -e "  ${RED}✗${NC} build.bat missing"
    all_good=false
fi

# Check for documentation
echo ""
echo "[2/4] Checking documentation..."
if [ -f "../README-INSTALLER.md" ]; then
    echo -e "  ${GREEN}✓${NC} README-INSTALLER.md found"
else
    echo -e "  ${YELLOW}!${NC} README-INSTALLER.md missing (recommended)"
fi

if [ -f "README.md" ]; then
    echo -e "  ${GREEN}✓${NC} README.md found"
else
    echo -e "  ${YELLOW}!${NC} README.md missing (recommended)"
fi

# Check directory structure
echo ""
echo "[3/4] Checking directory structure..."
if [ -d "." ]; then
    echo -e "  ${GREEN}✓${NC} Installer directory exists"
else
    echo -e "  ${RED}✗${NC} Installer directory missing"
    all_good=false
fi

# Verify file content (basic checks)
echo ""
echo "[4/4] Verifying file content..."

if grep -q "class Installer" "Installer.cs" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Installer.cs contains Installer class"
else
    echo -e "  ${RED}✗${NC} Installer.cs missing Installer class"
    all_good=false
fi

if grep -q "class ServiceManager\|static class ServiceManager" "ServiceInstaller.cs" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} ServiceInstaller.cs contains ServiceManager class"
else
    echo -e "  ${RED}✗${NC} ServiceInstaller.cs missing ServiceManager class"
    all_good=false
fi

if grep -q "csc.exe" "build.bat" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} build.bat contains compiler reference"
else
    echo -e "  ${RED}✗${NC} build.bat missing compiler reference"
    all_good=false
fi

# Summary
echo ""
echo "============================================================================"
if [ "$all_good" = true ]; then
    echo -e "  ${GREEN}✓ ALL CHECKS PASSED${NC}"
    echo "============================================================================"
    echo ""
    echo "The installer source is ready to build!"
    echo ""
    echo "To build on Windows:"
    echo "  1. Copy the Installer directory to a Windows machine"
    echo "  2. Run build.bat"
    echo "  3. The output will be in bin\\FileManagerWorker.exe"
    echo ""
    exit 0
else
    echo -e "  ${RED}✗ SOME CHECKS FAILED${NC}"
    echo "============================================================================"
    echo ""
    echo "Please fix the issues above before building."
    echo ""
    exit 1
fi
