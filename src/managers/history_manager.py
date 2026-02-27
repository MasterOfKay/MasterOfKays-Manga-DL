"""
History manager for tracking downloaded manga and chapters.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any


class HistoryManager:
    """Manages history of downloaded manga and chapters."""
    
    def __init__(self):
        self.history_file = os.path.join(os.path.expanduser("~"), ".mangadownloader", "history.json")
        self.history = self._load_history()
        
    def _load_history(self) -> Dict[str, Any]:
        """Load history from file."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for manga_name, manga_data in data.items():
                    if 'chapters' not in manga_data:
                        manga_data['chapters'] = {}
                    if 'first_download' not in manga_data:
                        manga_data['first_download'] = datetime.now().isoformat()
                    if 'last_updated' not in manga_data:
                        manga_data['last_updated'] = datetime.now().isoformat()
                    if 'site_type' not in manga_data:
                        manga_data['site_type'] = 'unknown'
                    if manga_data['site_type'] == 'mangadex':
                        logging.info(f"Found mangadex manga in history: {manga_name}")
                    if 'url' not in manga_data:
                        manga_data['url'] = ''
                        
                return data
            else:
                return {}
        except Exception as e:
            logging.error(f"Error loading history: {e}")
            return {}
    
    def _save_history(self) -> None:
        """Save history to file."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Error saving history: {e}")
    
    def add_manga(self, manga_name: str, url: str, site_type: str) -> None:
        """Add a manga to history."""
        if manga_name not in self.history:
            self.history[manga_name] = {
                'url': url,
                'site_type': site_type,
                'first_download': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'chapters': {}
            }
        else:
            self.history[manga_name]['last_updated'] = datetime.now().isoformat()
            
        self._save_history()
    
    def add_downloaded_chapter(self, manga_name: str, chapter_num: str, site_type: str, chapter_url: str) -> None:
        """Record a successfully downloaded chapter."""
        if manga_name not in self.history:
            self.add_manga(manga_name, "", site_type)
            
        self.history[manga_name]['chapters'][chapter_num] = {
            'download_date': datetime.now().isoformat(),
            'url': chapter_url
        }
        self.history[manga_name]['last_updated'] = datetime.now().isoformat()
        
        self._save_history()
    
    def get_manga_list(self) -> List[str]:
        """Get list of all manga in history."""
        return list(self.history.keys())
    
    def get_manga_data(self, manga_name: str) -> Dict[str, Any]:
        """Get data for a specific manga."""
        return self.history.get(manga_name, {})
    
    def get_chapter_data(self, manga_name: str, chapter_num: str) -> Dict[str, Any]:
        """Get data for a specific chapter."""
        manga_data = self.get_manga_data(manga_name)
        chapters = manga_data.get('chapters', {})
        return chapters.get(chapter_num, {})
    
    def get_downloaded_chapters(self, manga_name: str) -> List[str]:
        """Get list of downloaded chapters for a manga."""
        manga_data = self.get_manga_data(manga_name)
        return list(manga_data.get('chapters', {}).keys())
    
    def update_manga_url(self, manga_name: str, url: str, site_type: str) -> None:
        """Update the URL for a manga in history."""
        if manga_name in self.history:
            self.history[manga_name]['url'] = url
            self.history[manga_name]['site_type'] = site_type
            self.history[manga_name]['last_updated'] = datetime.now().isoformat()
            self._save_history()
    
    def delete_manga(self, manga_name: str) -> None:
        """Delete a manga from history."""
        if manga_name in self.history:
            del self.history[manga_name]
            self._save_history()
    
    def get_chapter_count(self, manga_name: str) -> int:
        """Get the number of downloaded chapters for a manga."""
        manga_data = self.get_manga_data(manga_name)
        return len(manga_data.get('chapters', {}))
    
    def get_last_update(self, manga_name: str) -> str:
        """Get the last update date for a manga."""
        manga_data = self.get_manga_data(manga_name)
        return manga_data.get('last_updated', '')
    
    def get_site_type(self, manga_name: str) -> str:
        """Get the site type for a manga."""
        manga_data = self.get_manga_data(manga_name)
        return manga_data.get('site_type', 'unknown')
    
    def get_manga_url(self, manga_name: str) -> str:
        """Get the URL for a manga."""
        manga_data = self.get_manga_data(manga_name)
        return manga_data.get('url', '')