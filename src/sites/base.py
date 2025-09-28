"""
Base class for comic site downloaders.
All site-specific downloaders should inherit from this class.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Union, Optional, Callable
import os
import re
import requests
import json
from urllib.parse import urljoin, urlparse


class MangaMetadata:
    """Manga metadata structure for scraped data."""
    def __init__(self):
        self.title: str = ""
        self.description: str = ""
        self.author: str = ""
        self.genres: List[str] = []
        self.status: str = "unknown"  # ongoing, completed, cancelled
        self.release_date: str = ""
        self.alternative_names: List[str] = []
        self.cover_image_url: str = ""
        self.language: str = "en"  # Default to English
        self.translation_type: str = "official" 


class ComicSiteBase(ABC):
    """Base class for comic site downloaders."""
    
    def __init__(self, site_name: str, base_url: str):
        self.site_name = site_name
        self.base_url = base_url
    
    @abstractmethod
    def get_manga_name(self, url: str) -> str:
        """Extract manga name from URL."""
        pass
    
    @abstractmethod
    def get_manga_metadata(self, url: str) -> MangaMetadata:
        """
        Extract comprehensive manga metadata from the manga page.
        Returns MangaMetadata object with all available information.
        """
        pass
    
    @abstractmethod
    def get_chapter_links(self, url: str) -> List[Tuple[str, str, str]]:
        """
        Get all chapter links from manga page.
        Returns list of tuples: (chapter_number, chapter_name, chapter_url)
        """
        pass
    
    @abstractmethod
    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str, 
                        base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                        language: str = "en") -> Union[str, Dict]:
        """
        Download a chapter and create a CBZ file.
        Returns path to CBZ file or result dictionary.
        """
        pass
    
    def get_chapter_filename(self, manga_name: str, chapter_num: str, language: str = "en") -> str:
        """Generate chapter filename with language support."""
        safe_manga_name = self.sanitize_filename(manga_name)
        safe_chapter_num = self.sanitize_filename(str(chapter_num))
        
        if language and language != "en":
            return f"Chapter {safe_chapter_num}.{language}.cbz"
        else:
            return f"Chapter {safe_chapter_num}.cbz"
    
    @classmethod
    @abstractmethod
    def validate_url(cls, url: str) -> bool:
        """Check if URL is valid for this site."""
        pass
    
    def sanitize_filename(self, name: str) -> str:
        """Remove invalid characters from filename."""
        return ''.join(c for c in name if c not in '/:*?"<>|')
    
    def ensure_directory(self, path: str) -> str:
        """Create directory if it doesn't exist."""
        os.makedirs(path, exist_ok=True)
        return path
    
    def get_safe_manga_path(self, manga_name: str, base_path: Optional[str] = None) -> str:
        """Get safe path for manga directory."""
        safe_name = self.sanitize_filename(manga_name)
        if not safe_name:
            safe_name = manga_name
        
        if base_path is None or not os.path.isdir(base_path):
            base_path = os.getcwd()
        
        return self.ensure_directory(os.path.join(base_path, safe_name))
    
    def download_cover_image(self, cover_url: str, manga_path: str) -> str:
        """Download cover image and save as cover.png in manga directory."""
        if not cover_url:
            return ""
            
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(cover_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            cover_path = os.path.join(manga_path, "cover.png")
            with open(cover_path, 'wb') as f:
                f.write(response.content)
            
            return cover_path
            
        except Exception as e:
            print(f"Error downloading cover image: {e}")
            return ""
    
    def create_metadata_file(self, metadata: MangaMetadata, manga_path: str):
        """Create metadata files for external readers (Kavita, Komga)."""
        try:
            comic_info = f"""<?xml version="1.0" encoding="utf-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
    <Title>{self._escape_xml(metadata.title)}</Title>
    <Series>{self._escape_xml(metadata.title)}</Series>
    <Summary>{self._escape_xml(metadata.description)}</Summary>
    <Writer>{self._escape_xml(metadata.author)}</Writer>
    <Genre>{self._escape_xml(', '.join(metadata.genres))}</Genre>
    <PublicationStatus>{self._escape_xml(metadata.status.title())}</PublicationStatus>
    <Year>{metadata.release_date[:4] if metadata.release_date else ''}</Year>
    <AlternateSeries>{self._escape_xml(', '.join(metadata.alternative_names))}</AlternateSeries>
    <Manga>Yes</Manga>
</ComicInfo>"""
            
            comic_info_path = os.path.join(manga_path, "ComicInfo.xml")
            with open(comic_info_path, 'w', encoding='utf-8') as f:
                f.write(comic_info)
            
            metadata_dict = {
                'title': metadata.title,
                'description': metadata.description,
                'author': metadata.author,
                'genres': metadata.genres,
                'status': metadata.status,
                'release_date': metadata.release_date,
                'alternative_names': metadata.alternative_names,
                'cover_image_url': metadata.cover_image_url
            }
            
            metadata_path = os.path.join(manga_path, "metadata.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata_dict, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"Error creating metadata files: {e}")
    
    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters."""
        if not text:
            return ""
        return (text.replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
                   .replace('"', "&quot;")
                   .replace("'", "&apos;"))