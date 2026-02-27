"""
Settings manager for application configuration.
"""

import os
import json
import logging
from typing import Dict, Any, Optional


class SettingsManager:
    """Manages application settings and configuration."""
    
    def __init__(self):
        self.settings_file = os.path.join(os.path.expanduser("~"), ".mangadownloader", "settings.json")
        self.settings = self._load_settings()
        self._configure_logging()
    
    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from file."""
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return self._get_default_settings()
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
            return self._get_default_settings()
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """Get default settings."""
        return {
            'download_path': os.path.join(os.path.expanduser("~"), "Downloads", "Manga"),
            'debug_mode': False,
            'theme': {
                'dark_mode': False,
                'background_color': '#FFFFFF',
                'text_color': '#000000',
                'accent_color': '#0078D4',
                'sidebar_color': '#F3F2F1',
                'button_color': '#0078D4',
                'button_hover_color': '#106EBE',
                'success_color': '#107C10',
                'error_color': '#D13438',
                'warning_color': '#FF8C00',
                'info_color': '#0078D4'
            },
            'download': {
                'max_concurrent_downloads': 1,
                'retry_attempts': 3,
                'timeout': 30,
                'save_cover': True,
                'save_comicinfo': True,
                'save_series_json': True,
                'embed_comicinfo_in_cbz': False,
                'embed_cover_in_cbz': False
            },
            'ui': {
                'window_size': {'width': 1200, 'height': 800},
                'window_position': {'x': 100, 'y': 100}
            }
        }
    
    def _save_settings(self) -> None:
        """Save settings to file."""
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Error saving settings: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        keys = key.split('.')
        value = self.settings
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """Set a setting value."""
        keys = key.split('.')
        setting = self.settings
        
        for k in keys[:-1]:
            if k not in setting or not isinstance(setting[k], dict):
                setting[k] = {}
            setting = setting[k]
        
        setting[keys[-1]] = value
        self._save_settings()
    
    def get_download_path(self) -> str:
        """Get the download path."""
        return self.get('download_path', os.path.join(os.path.expanduser("~"), "Downloads", "Manga"))
    
    def set_download_path(self, path: str) -> None:
        """Set the download path."""
        self.set('download_path', path)
    
    def get_theme_settings(self) -> Dict[str, Any]:
        """Get theme settings."""
        return self.get('theme', {
            'dark_mode': False,
            'background_color': '#FFFFFF',
            'text_color': '#000000'
        })
    
    def set_theme_settings(self, theme_settings: Dict[str, Any]) -> None:
        """Set theme settings."""
        for key, value in theme_settings.items():
            self.set(f'theme.{key}', value)
    
    def is_dark_mode(self) -> bool:
        """Check if dark mode is enabled."""
        return self.get('theme.dark_mode', False)
    
    def set_dark_mode(self, enabled: bool) -> None:
        """Set dark mode."""
        self.set('theme.dark_mode', enabled)
    
    def get_window_size(self) -> Dict[str, int]:
        """Get window size."""
        return self.get('ui.window_size', {'width': 1200, 'height': 800})
    
    def set_window_size(self, width: int, height: int) -> None:
        """Set window size."""
        self.set('ui.window_size', {'width': width, 'height': height})
    
    def get_window_position(self) -> Dict[str, int]:
        """Get window position."""
        return self.get('ui.window_position', {'x': 100, 'y': 100})
    
    def set_window_position(self, x: int, y: int) -> None:
        """Set window position."""
        self.set('ui.window_position', {'x': x, 'y': y})
    
    def get_max_concurrent_downloads(self) -> int:
        """Get maximum concurrent downloads."""
        return self.get('download.max_concurrent_downloads', 1)
    
    def set_max_concurrent_downloads(self, count: int) -> None:
        """Set maximum concurrent downloads."""
        self.set('download.max_concurrent_downloads', count)
    
    def get_retry_attempts(self) -> int:
        """Get retry attempts."""
        return self.get('download.retry_attempts', 3)
    
    def set_retry_attempts(self, attempts: int) -> None:
        """Set retry attempts."""
        self.set('download.retry_attempts', attempts)
    
    def get_timeout(self) -> int:
        """Get download timeout."""
        return self.get('download.timeout', 30)
    
    def set_timeout(self, timeout: int) -> None:
        """Set download timeout."""
        self.set('download.timeout', timeout)
    
    def is_debug_mode(self) -> bool:
        """Check if debug mode is enabled."""
        return self.get('debug_mode', False)
    
    def set_debug_mode(self, enabled: bool) -> None:
        """Set debug mode."""
        self.set('debug_mode', enabled)
        self._configure_logging()
    
    def _configure_logging(self) -> None:
        """Configure logging based on debug mode setting."""
        if self.is_debug_mode():
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                filename='manga_download.log',
                filemode='a',
                force=True
            )
        else:
            logging.basicConfig(
                level=logging.WARNING,
                format='%(levelname)s - %(message)s',
                force=True
            )
    
    def get_color_scheme(self) -> Dict[str, str]:
        """Get current color scheme."""
        default_colors = {
            'background_color': '#FFFFFF',
            'text_color': '#000000', 
            'accent_color': '#0078D4',
            'sidebar_color': '#F3F2F1',
            'button_color': '#0078D4',
            'button_hover_color': '#106EBE',
            'success_color': '#107C10',
            'error_color': '#D13438',
            'warning_color': '#FF8C00',
            'info_color': '#0078D4',
            'history_card_background': '#FFFFFF',
            'history_card_border': '#E0E0E0',
            'history_card_text': '#000000',
            'history_card_subtitle': '#6C757D',
            'history_card_new_background': '#FFF3CD',
            'history_card_new_border': '#FFEAA7',
            'history_card_hover_background': '#F8F9FA',
            'chapter_viewer_background': '#FFFFFF',
            'chapter_viewer_border': '#E0E0E0',
            'chapter_viewer_text': '#000000',
            'chapter_viewer_success': '#28A745',
            'chapter_viewer_error': '#DC3545',
            'chapter_viewer_pending': '#6C757D',
            'chapter_viewer_new': '#007BFF'
        }
        
        theme = self.get('theme', {})
        colors = {}
        for key, default_value in default_colors.items():
            colors[key] = theme.get(key, default_value)
        
        return colors
    
    def set_color_scheme(self, colors: Dict[str, str]) -> None:
        """Set color scheme."""
        for key, value in colors.items():
            self.set(f'theme.{key}', value)
    
    def set_individual_color(self, color_name: str, color_value: str) -> None:
        """Set an individual color in the theme."""
        self.set(f'theme.{color_name}', color_value)
    
    def get_individual_color(self, color_name: str) -> str:
        """Get an individual color from the theme."""
        default_colors = {
            'background_color': '#FFFFFF',
            'text_color': '#000000',
            'accent_color': '#0078D4', 
            'sidebar_color': '#F3F2F1',
            'button_color': '#0078D4',
            'button_hover_color': '#106EBE',
            'success_color': '#107C10',
            'error_color': '#D13438',
            'warning_color': '#FF8C00',
            'info_color': '#0078D4'
        }
        return self.get(f'theme.{color_name}', default_colors.get(color_name, '#000000'))
    
    def reset_color_scheme_to_default(self) -> None:
        """Reset color scheme to default values."""
        default_theme = self._get_default_settings()['theme']
        for key, value in default_theme.items():
            if key != 'dark_mode':
                self.set(f'theme.{key}', value)
    
    def reset_to_defaults(self) -> None:
        """Reset all settings to defaults."""
        self.settings = self._get_default_settings()
        self._save_settings()


    def get_save_cover(self) -> bool:
        """Return True if a cover.png should be saved inside the manga folder."""
        return self.get('download.save_cover', True)

    def set_save_cover(self, enabled: bool) -> None:
        self.set('download.save_cover', enabled)

    def get_save_comicinfo(self) -> bool:
        """Return True if ComicInfo.xml should be saved inside the manga folder."""
        return self.get('download.save_comicinfo', True)

    def set_save_comicinfo(self, enabled: bool) -> None:
        self.set('download.save_comicinfo', enabled)

    def get_save_series_json(self) -> bool:
        """Return True if series.json should be saved inside the manga folder."""
        return self.get('download.save_series_json', True)

    def set_save_series_json(self, enabled: bool) -> None:
        self.set('download.save_series_json', enabled)

    def get_embed_comicinfo_in_cbz(self) -> bool:
        """Return True if ComicInfo.xml should be embedded inside each CBZ."""
        return self.get('download.embed_comicinfo_in_cbz', False)

    def set_embed_comicinfo_in_cbz(self, enabled: bool) -> None:
        self.set('download.embed_comicinfo_in_cbz', enabled)

    def get_embed_cover_in_cbz(self) -> bool:
        """Return True if cover.png should be embedded inside each CBZ."""
        return self.get('download.embed_cover_in_cbz', False)

    def set_embed_cover_in_cbz(self, enabled: bool) -> None:
        self.set('download.embed_cover_in_cbz', enabled)