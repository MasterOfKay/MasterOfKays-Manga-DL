"""
Settings manager for application configuration.
"""

import copy
import os
import json
import logging
from typing import Dict, Any

from ..core.paths import data_dir


DEFAULT_SETTINGS: Dict[str, Any] = {
    'download_path': os.path.join(os.path.expanduser("~"), "Downloads", "Manga"),
    'debug_mode': False,
    'appearance': {
        'theme': 'system',          # system | light | dark
        'accent': '#6366F1',
    },
    'download': {
        'retry_attempts': 2,
        'save_cover': True,
        'save_comicinfo': True,
        'save_series_json': True,
        'embed_comicinfo_in_cbz': True,
        'embed_cover_in_cbz': False,
    },
    'metadata': {
        'chapter_title': 'name',     # name -> "Returning from the Immortal Realm", full -> "Chapter 1 - ..."
        'chapter_summary': 'first',  # first | all | none - where the series description goes
        'reading_direction': 'ltr',  # ltr | rtl (ComicInfo Manga=YesAndRightToLeft)
        'publisher_from_site': True, # source site as <Publisher> (handy for filtering in Komga)
    },
    'notifications': {
        'in_app': True,             # toasts inside the window
        'desktop': True,            # system notifications while the window is in the background
        'events': {
            'download_started': False,
            'download_finished': True,
            'chapter_finished': False,
            'new_chapters': True,
            'errors': True,
            'app_update': True,
        },
    },
    'updates': {
        'auto_check': True,
        'interval_minutes': 60,
        'check_on_startup': True,
        'auto_download': False,
        'last_check': '',
    },
    'app_updates': {
        'interval': 'daily',         # hourly | daily | weekly | never
        'beta': False,               # also offer GitHub pre-releases
        'last_check': '',
        'notified': '',              # tag we already told the user about
    },
    'ui': {
        'geometry': '',
    },
}

_MISSING = object()


class SettingsManager:
    """Manages application settings stored as JSON in the app data folder."""

    def __init__(self):
        self.settings_file = os.path.join(data_dir(), "settings.json")
        self.settings = self._load_settings()
        self._configure_logging()

    def _load_settings(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
        return copy.deepcopy(DEFAULT_SETTINGS)

    def _save_settings(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            tmp = self.settings_file + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.settings_file)
        except Exception as e:
            logging.error(f"Error saving settings: {e}")

    @staticmethod
    def _lookup(tree: Dict[str, Any], key: str) -> Any:
        value: Any = tree
        for k in key.split('.'):
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return _MISSING
        return value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a dotted setting; falls back to the built-in default, then `default`."""
        value = self._lookup(self.settings, key)
        if value is _MISSING:
            value = self._lookup(DEFAULT_SETTINGS, key)
        if value is _MISSING:
            return default
        return copy.deepcopy(value) if isinstance(value, (dict, list)) else value

    def set(self, key: str, value: Any) -> None:
        keys = key.split('.')
        node = self.settings
        for k in keys[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[keys[-1]] = value
        self._save_settings()

    # --- download -------------------------------------------------------
    def get_download_path(self) -> str:
        return self.get('download_path')

    def set_download_path(self, path: str) -> None:
        self.set('download_path', path)

    def get_retry_attempts(self) -> int:
        return int(self.get('download.retry_attempts', 2))

    def get_save_cover(self) -> bool:
        return bool(self.get('download.save_cover'))

    def get_save_comicinfo(self) -> bool:
        return bool(self.get('download.save_comicinfo'))

    def get_save_series_json(self) -> bool:
        return bool(self.get('download.save_series_json'))

    def get_embed_comicinfo_in_cbz(self) -> bool:
        return bool(self.get('download.embed_comicinfo_in_cbz'))

    def get_embed_cover_in_cbz(self) -> bool:
        return bool(self.get('download.embed_cover_in_cbz'))

    # --- notifications --------------------------------------------------
    def notification_enabled(self, event: str) -> bool:
        return bool(self.get(f'notifications.events.{event}', True))

    # --- logging --------------------------------------------------------
    def is_debug_mode(self) -> bool:
        return bool(self.get('debug_mode'))

    def set_debug_mode(self, enabled: bool) -> None:
        self.set('debug_mode', enabled)
        self._configure_logging()

    def log_file(self) -> str:
        return os.path.join(data_dir(), "manga_downloader.log")

    def _configure_logging(self) -> None:
        if self.is_debug_mode():
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
                filename=self.log_file(),
                filemode='a',
                encoding='utf-8',
                force=True,
            )
        else:
            logging.basicConfig(
                level=logging.WARNING,
                format='%(levelname)s - %(message)s',
                force=True,
            )

    def reset_to_defaults(self) -> None:
        keep_path = self.get_download_path()
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.settings['download_path'] = keep_path
        self._save_settings()
