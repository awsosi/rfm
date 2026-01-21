#!/usr/bin/env python3
"""
Entry point for Modular File Manager API.

Run with:
    python -m api.main
    OR
    uvicorn api.main:app --reload
"""

import uvicorn

from api.config import get_settings


def main():
    """Start the API server."""
    settings = get_settings()

    uvicorn.run(
        "api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        workers=1 if settings.api_reload else settings.api_workers,
        log_level=settings.log_level.lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()
