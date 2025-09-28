"""Managers package."""

from .download_manager import DownloadManager, DownloadSignals
from .history_manager import HistoryManager
from .settings_manager import SettingsManager
from .database_manager import DatabaseManager
from .metadata_manager import MetadataManager

__all__ = [
    'DownloadManager',
    'DownloadSignals', 
    'HistoryManager',
    'SettingsManager',
    'DatabaseManager',
    'MetadataManager'
]