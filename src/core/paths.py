"""
Filesystem locations used by the app.
"""

import os
import sys


def data_dir() -> str:
    """Folder holding the database, settings, covers and logs."""
    path = os.path.join(os.path.expanduser("~"), ".mangadownloader")
    os.makedirs(path, exist_ok=True)
    return path


def covers_dir() -> str:
    path = os.path.join(data_dir(), "covers")
    os.makedirs(path, exist_ok=True)
    return path


def resource_path(*parts: str) -> str:
    """Path to a bundled resource (works from source and from a PyInstaller build)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def sanitize_folder_name(name: str) -> str:
    """Must match ComicSiteBase.sanitize_filename - that is where the CBZs end up."""
    safe = ''.join(c for c in name if c not in '/:*?"<>|')
    return safe or name
