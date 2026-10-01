"""
The RFM version, shared by every component: ``<major.minor from VERSION>.<commits in HEAD>``.

The Docker image bakes it into ``/app/RFM_VERSION`` at build time (see
``backend/Dockerfile``); the worker, RFM Launcher, RFM Tray and the installer
get the same number from ``Version.targets``. Run from a checkout, it is
computed the same way.
"""

import subprocess
from pathlib import Path

# /app in the image, the repository root in a checkout
_ROOT = Path(__file__).resolve().parents[2]


def _detect() -> str:
    baked = _ROOT / "RFM_VERSION"
    if baked.is_file():
        return baked.read_text().strip()
    try:
        base = (_ROOT / "VERSION").read_text().strip()
        count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return f"{base}.{count}"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


RFM_VERSION = _detect()
