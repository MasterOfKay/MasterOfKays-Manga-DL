"""
MangaDex downloader implementation with full language and metadata support.
"""

import requests
import json
import time
import os
import zipfile
import logging
from typing import List, Tuple, Optional, Callable, Union, Dict
import re
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime

from .base import ComicSiteBase, MangaMetadata, ChapterInfo


class MangaDexDownloader(ComicSiteBase):
    """MangaDex manga downloader wi            # Try to get actual metadata from AP            # Try to get actual metadata from API if            # Create ComicInfo.xml
            if not os.path.exists(comic_info_path):
                status_display = metadata.status.title() if metadata and metadata.status != "unknown" else "Unknown"
                comic_info = f'''<?xml version="1.0"?>
<ComicInfo>
    <Title>{metadata.title if metadata else manga_name}</Title>
    <Series>{metadata.title if metadata else manga_name}</Series>
    <LocalizedSeries>{metadata.title if metadata else manga_name}</LocalizedSeries>
    <Summary>{metadata.description if metadata else ""}</Summary>
    <Writer>{metadata.author if metadata else ""}</Writer>
    <Publisher>MangaDex</Publisher>
    <Genre>{", ".join(metadata.genres) if metadata and metadata.genres else ""}</Genre>
    <LanguageISO>en</LanguageISO>
    <Web>https://mangadex.org</Web>
    <SeriesStatus>{status_display}</SeriesStatus>
</ComicInfo>'''ailable
            metadata = None
            manga_url = url or getattr(self, 'current_url', '')
            if manga_url:
                try:
                    metadata = self.get_manga_metadata(manga_url)
                except Exception as e:
                    logging.warning(f"Could not fetch metadata for {manga_name}: {e}")
            
            if not os.path.exists(series_json_path):
                if metadata:
                    series_data = {
                        "title": metadata.title or manga_name,
                        "description": metadata.description or "",
                        "author": metadata.author or "",
                        "artist": metadata.author or "",  # MangaDex doesn't separate artist
                        "genres": metadata.genres or [],
                        "status": metadata.status or "unknown",
                        "year": metadata.release_date or "",
                        "language": metadata.language or "en",
                        "site": "mangadex"
                    }
                else:
                    series_data = {
                        "title": manga_name,
                        "description": "",
                        "author": "",
                        "artist": "",
                        "genres": [],
                        "status": "unknown",
                        "year": "",
                        "language": "en",
                        "site": "mangadex"
                    } # Create ComicInfo.xml
            if not os.path.exists(comic_info_path):
                status_display = metadata.status.title() if metadata and metadata.status != "unknown" else "Unknown"
                comic_info = f'''<?xml version="1.0"?>
<ComicInfo>
    <Title>{metadata.title if metadata else manga_name}</Title>
    <Series>{metadata.title if metadata else manga_name}</Series>
    <LocalizedSeries>{metadata.title if metadata else manga_name}</LocalizedSeries>
    <Summary>{metadata.description if metadata else ""}</Summary>
    <Writer>{metadata.author if metadata else ""}</Writer>
    <Publisher>MangaDex</Publisher>
    <Genre>{", ".join(metadata.genres) if metadata and metadata.genres else ""}</Genre>
    <LanguageISO>en</LanguageISO>
    <Web>https://mangadex.org</Web>
    <SeriesStatus>{status_display}</SeriesStatus>
</ComicInfo>'''vailable
            metadata = None
            if url and hasattr(self, 'current_url'):
                try:
                    metadata = self.get_manga_metadata(self.current_url)
                except Exception as e:
                    logging.warning(f"Could not fetch metadata for {manga_name}: {e}")
            
            if not os.path.exists(series_json_path):
                if metadata:
                    series_data = {
                        "title": metadata.title or manga_name,
                        "description": metadata.description or "",
                        "author": metadata.author or "",
                        "artist": metadata.author or "",  # MangaDex doesn't separate artist
                        "genres": metadata.genres or [],
                        "status": metadata.status or "unknown",
                        "year": metadata.release_date or "",
                        "language": metadata.language or "en",
                        "site": "mangadex"
                    }
                else:
                    series_data = {
                        "title": manga_name,
                        "description": "",
                        "author": "",
                        "artist": "",
                        "genres": [],
                        "status": "unknown",
                        "year": "",
                        "language": "en",
                        "site": "mangadex"
                    }ve language and metadata support."""
    
    def __init__(self):
        super().__init__("MangaDex", "https://mangadex.org")
        self.api_base = "https://api.mangadex.org"
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'MasterOfKays-Manga-DL/1.0',
            'Accept': 'application/json'
        })
        
        self.current_url = ""
        
        self.language_names = {
            'en': 'English',
            'ja': 'Japanese',
            'ko': 'Korean',
            'zh': 'Chinese (Simplified)',
            'zh-hk': 'Chinese (Traditional)',
            'fr': 'French',
            'es': 'Spanish',
            'es-la': 'Spanish (Latin America)',
            'de': 'German',
            'it': 'Italian',
            'pt': 'Portuguese',
            'pt-br': 'Portuguese (Brazil)',
            'ru': 'Russian',
            'ar': 'Arabic',
            'th': 'Thai',
            'vi': 'Vietnamese',
            'id': 'Indonesian',
            'ms': 'Malay',
            'tl': 'Filipino',
            'tr': 'Turkish',
            'pl': 'Polish',
            'nl': 'Dutch',
            'sv': 'Swedish',
            'da': 'Danish',
            'no': 'Norwegian',
            'fi': 'Finnish',
            'cs': 'Czech',
            'hu': 'Hungarian',
            'ro': 'Romanian',
            'uk': 'Ukrainian',
            'bg': 'Bulgarian',
            'hr': 'Croatian',
            'sr': 'Serbian',
            'sk': 'Slovak',
            'sl': 'Slovenian',
            'et': 'Estonian',
            'lv': 'Latvian',
            'lt': 'Lithuanian',
            'he': 'Hebrew',
            'hi': 'Hindi',
            'bn': 'Bengali',
            'ta': 'Tamil',
            'te': 'Telugu',
            'ml': 'Malayalam',
            'kn': 'Kannada',
            'gu': 'Gujarati',
            'pa': 'Punjabi',
            'ur': 'Urdu',
            'fa': 'Persian',
            'ne': 'Nepali',
            'si': 'Sinhala',
            'my': 'Myanmar',
            'km': 'Khmer',
            'lo': 'Lao',
            'ka': 'Georgian',
            'am': 'Amharic',
            'sw': 'Swahili',
            'zu': 'Zulu',
            'af': 'Afrikaans'
        }
    
    @classmethod
    def validate_url(cls, url: str) -> bool:
        """Check if URL is valid for MangaDex."""
        pattern = r'^https?://mangadex\.org/title/[a-f0-9\-]+/[^/]+.*$'
        return bool(re.match(pattern, url))
    
    def extract_manga_id(self, url: str) -> str:
        """Extract manga ID from MangaDex URL."""
        match = re.search(r'/title/([a-f0-9\-]+)/', url)
        if match:
            return match.group(1)
        raise ValueError("Invalid MangaDex URL format")
    
    def get_manga_name(self, url: str) -> str:
        """Extract manga name from URL or fetch from API."""
        try:
            manga_id = self.extract_manga_id(url)
            api_url = f"{self.api_base}/manga/{manga_id}"
            
            response = self._session.get(api_url, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            if data.get('result') == 'ok':
                title_data = data['data']['attributes']['title']
                if 'en' in title_data:
                    return title_data['en']
                elif title_data:
                    return list(title_data.values())[0]
            
            return "Unknown Manga"
            
        except Exception as e:
            print(f"Error fetching manga name: {e}")
            return "Unknown Manga"
    
    def get_manga_metadata(self, url: str) -> MangaMetadata:
        """Extract comprehensive manga metadata from MangaDex API."""
        metadata = MangaMetadata()
        
        try:
            manga_id = self.extract_manga_id(url)
            
            api_url = f"{self.api_base}/manga/{manga_id}"
            params = {
                'includes[]': ['author', 'artist', 'cover_art']
            }
            
            response = self._session.get(api_url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            if data.get('result') != 'ok':
                return metadata
            
            manga_data = data['data']
            attrs = manga_data['attributes']
            
            title_data = attrs.get('title', {})
            metadata.title = title_data.get('en') or list(title_data.values())[0] if title_data else "Unknown"
            
            desc_data = attrs.get('description', {})
            metadata.description = desc_data.get('en') or list(desc_data.values())[0] if desc_data else ""
            
            alt_titles = attrs.get('altTitles', [])
            for alt_title in alt_titles:
                if isinstance(alt_title, dict):
                    for lang, title in alt_title.items():
                        if title not in metadata.alternative_names:
                            metadata.alternative_names.append(title)
            
            status_map = {
                'ongoing': 'ongoing',
                'completed': 'completed',
                'hiatus': 'hiatus',
                'cancelled': 'cancelled'
            }
            metadata.status = status_map.get(attrs.get('status', 'unknown'), 'unknown')
            
            tags = attrs.get('tags', [])
            for tag in tags:
                if isinstance(tag, dict):
                    tag_attrs = tag.get('attributes', {})
                    tag_name = tag_attrs.get('name', {})
                    if 'en' in tag_name:
                        metadata.genres.append(tag_name['en'])
            
            available_langs = attrs.get('availableTranslatedLanguages', [])
            metadata.available_languages = [lang for lang in available_langs if lang]
            
            year = attrs.get('year')
            if year:
                metadata.release_date = str(year)
            
            rating_data = attrs.get('rating')
            if rating_data and 'average' in rating_data:
                metadata.rating = float(rating_data['average'])
            
            relationships = manga_data.get('relationships', [])
            for rel in relationships:
                rel_type = rel.get('type')
                rel_attrs = rel.get('attributes', {})
                
                if rel_type == 'author':
                    metadata.author = rel_attrs.get('name', '')
                elif rel_type == 'artist':
                    metadata.artist = rel_attrs.get('name', '')
                elif rel_type == 'cover_art':
                    cover_filename = rel_attrs.get('fileName')
                    if cover_filename:
                        metadata.cover_image_url = f"https://uploads.mangadex.org/covers/{manga_id}/{cover_filename}.512.jpg"
            
            return metadata
            
        except Exception as e:
            print(f"Error fetching manga metadata: {e}")
            return metadata
    
    def get_chapter_links(self, url: str, language_filter: Optional[str] = None) -> List[Union[Tuple[str, str, str], ChapterInfo]]:
        """Get all chapter information from MangaDex API with language support."""
        try:
            manga_id = self.extract_manga_id(url)
            chapters_info = []
            
            params = {
                'manga': manga_id,
                'limit': 100,
                'offset': 0
            }
            
            if language_filter:
                params['translatedLanguage[]'] = language_filter
            
            while True:
                api_url = f"{self.api_base}/chapter"
                response = self._session.get(api_url, params=params, timeout=15)
                response.raise_for_status()
                
                data = response.json()
                if data.get('result') != 'ok':
                    break
                
                chapters = data.get('data', [])
                if not chapters:
                    break
                
                for chapter_data in chapters:
                    chapter_info = self._parse_chapter_data(chapter_data)
                    if chapter_info:
                        chapters_info.append(chapter_info)
                
                total = data.get('total', 0)
                offset = params['offset']
                limit = params['limit']
                
                if offset + limit >= total:
                    break
                
                params['offset'] += limit
                time.sleep(0.1)  # Rate limiting
            
            return chapters_info
            
        except Exception as e:
            print(f"Error fetching chapter links: {e}")
            return []
    
    def _parse_chapter_data(self, chapter_data: dict) -> Optional[ChapterInfo]:
        """Parse chapter data from API response."""
        try:
            attrs = chapter_data.get('attributes', {})
            
            chapter_info = ChapterInfo()
            chapter_info.chapter_id = chapter_data.get('id', '')
            chapter_info.chapter_number = attrs.get('chapter', '') or '0'
            chapter_info.volume_number = attrs.get('volume', '') or ''
            chapter_info.title = attrs.get('title', '') or ''
            chapter_info.language = attrs.get('translatedLanguage', 'en')
            chapter_info.pages = attrs.get('pages', 0)
            
            publish_at = attrs.get('publishAt')
            if publish_at:
                try:
                    dt = datetime.fromisoformat(publish_at.replace('Z', '+00:00'))
                    chapter_info.release_date = dt.strftime('%Y-%m-%d')
                except:
                    chapter_info.release_date = publish_at[:10]  # Just date part
            
            relationships = chapter_data.get('relationships', [])
            for rel in relationships:
                rel_type = rel.get('type')
                rel_attrs = rel.get('attributes', {})
                
                if rel_type == 'scanlation_group':
                    chapter_info.scanlation_group = rel_attrs.get('name', '')
                elif rel_type == 'user':
                    chapter_info.translator = rel_attrs.get('username', '')
            
            chapter_info.chapter_url = f"https://mangadex.org/chapter/{chapter_info.chapter_id}"
            
            return chapter_info
            
        except Exception as e:
            print(f"Error parsing chapter data: {e}")
            return None
    
    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str, 
                        base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                        language: str = "en", chapter_info: Optional[ChapterInfo] = None,
                        cancel_check: Optional[Callable] = None,
                        pause_check: Optional[Callable] = None) -> Union[str, Dict]:
        """Download a chapter from MangaDex and create CBZ file."""
        try:
            chapter_id = self._extract_chapter_id(chapter_url)
            if not chapter_id:
                logging.error(f"Failed to extract chapter ID from: {chapter_url}")
                return {"success": False, "error": "Invalid chapter URL"}
            
            logging.info(f"Extracted chapter ID: {chapter_id}")
            
            at_home_url = f"{self.api_base}/at-home/server/{chapter_id}"
            response = self._session.get(at_home_url, timeout=15)
            response.raise_for_status()
            
            at_home_data = response.json()
            if at_home_data.get('result') != 'ok':
                return {"success": False, "error": "Failed to get chapter server info"}
            
            base_url = at_home_data['baseUrl']
            chapter_hash = at_home_data['chapter']['hash']
            data_pages = at_home_data['chapter']['data']  # High quality pages
            
            if not data_pages:
                return {"success": False, "error": "No pages found for this chapter"}
            
            manga_path = self.get_safe_manga_path(manga_name, base_path)
            
            if chapter_info:
                filename_parts = []
                
                lang_code = language.upper() if language else "EN"
                filename_parts.append(f"[{lang_code}]")
                
                if chapter_info.volume_number:
                    filename_parts.append(f"Vol.{chapter_info.volume_number}")
                filename_parts.append(f"Chapter {chapter_num}")
                if chapter_info.title:
                    safe_title = self.sanitize_filename(chapter_info.title)
                    filename_parts.append(f"- {safe_title}")
                
                filename = " ".join(filename_parts)
                
                if chapter_info.scanlation_group:
                    safe_group = self.sanitize_filename(chapter_info.scanlation_group)
                    filename += f" [{safe_group}]"
                    
                filename += ".cbz"
            else:
                lang_code = language.upper() if language else "EN"
                filename = f"[{lang_code}] Chapter {chapter_num}.cbz"
            
            cbz_path = os.path.join(manga_path, filename)
            
            if os.path.exists(cbz_path):
                return {"success": True, "path": cbz_path, "message": "File already exists"}
            
            downloaded_images = []
            total_pages = len(data_pages)
            
            for i, page_filename in enumerate(data_pages):
                if pause_check:
                    while pause_check():
                        if cancel_check and cancel_check():
                            return {"success": False, "error": "Cancelled"}
                        time.sleep(0.3)
                
                if cancel_check and cancel_check():
                    return {"success": False, "error": "Cancelled"}
                
                if progress_callback:
                    progress_callback(i + 1, total_pages, f"Downloading page {i + 1}/{total_pages}")
                
                page_url = f"{base_url}/data/{chapter_hash}/{page_filename}"
                
                try:
                    page_response = self._session.get(page_url, timeout=30)
                    page_response.raise_for_status()
                    
                    downloaded_images.append((page_filename, page_response.content))
                    time.sleep(0.1)  # Rate limiting
                    
                except Exception as e:
                    print(f"Error downloading page {i + 1}: {e}")
                    continue
            
            if not downloaded_images:
                return {"success": False, "error": "Failed to download any pages"}
            
            with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_STORED) as zipf:
                for page_filename, page_content in downloaded_images:
                    zipf.writestr(page_filename, page_content)
            
            self.manga_metadata(manga_path, manga_name, getattr(self, 'current_url', ''))
            
            if progress_callback:
                progress_callback(total_pages, total_pages, f"Created CBZ: {filename}")
            
            return {"success": True, "path": cbz_path}
            
        except Exception as e:
            error_msg = f"Error downloading chapter: {e}"
            print(error_msg)
            return {"success": False, "error": error_msg}
    
    def _extract_chapter_id(self, chapter_url: str) -> Optional[str]:
        """Extract chapter ID from MangaDex chapter URL or return ID if already extracted."""
        if re.match(r'^[a-f0-9\-]{36}$', chapter_url):
            return chapter_url
        
        match = re.search(r'/chapter/([a-f0-9\-]+)', chapter_url)
        return match.group(1) if match else None
    
    def get_available_languages(self, url: str) -> List[Tuple[str, str]]:
        """Get all available languages for a manga."""
        try:
            metadata = self.get_manga_metadata(url)
            languages = []
            
            for lang_code in metadata.available_languages:
                lang_name = self.language_names.get(lang_code, lang_code.upper())
                languages.append((lang_code, lang_name))
            
            languages.sort(key=lambda x: x[1])
            return languages
            
        except Exception as e:
            print(f"Error getting available languages: {e}")
            return [('en', 'English')]
    
    def get_chapters_by_language(self, url: str, language: str) -> List[ChapterInfo]:
        """Get chapters filtered by specific language."""
        chapters = self.get_chapter_links(url, language_filter=language)
        return [chapter for chapter in chapters if isinstance(chapter, ChapterInfo)]
    
    def get_volumes_structure(self, chapters: List[ChapterInfo]) -> Dict[str, List[ChapterInfo]]:
        """Organize chapters by volume."""
        volumes = {}
        
        for chapter in chapters:
            vol_key = chapter.volume_number or "No Volume"
            if vol_key not in volumes:
                volumes[vol_key] = []
            volumes[vol_key].append(chapter)
        
        sorted_volumes = {}
        for vol_key in sorted(volumes.keys(), key=lambda x: (x == "No Volume", x)):
            sorted_volumes[vol_key] = sorted(volumes[vol_key], 
                                           key=lambda c: (float(c.chapter_number) if c.chapter_number.replace('.', '').isdigit() else float('inf')))
        
        return sorted_volumes
    
    def manga_metadata(self, manga_path: str, manga_name: str, url: str = ""):
        """Create series.json, ComicInfo.xml, and download cover if they don't exist."""
        try:
            series_json_path = os.path.join(manga_path, "series.json")
            comic_info_path = os.path.join(manga_path, "ComicInfo.xml")
            cover_path = os.path.join(manga_path, "cover.png")
            
            if all(os.path.exists(p) for p in [series_json_path, comic_info_path, cover_path]):
                return
            
            if not os.path.exists(series_json_path):
                series_data = {
                    "title": manga_name,
                    "description": "",
                    "author": "",
                    "artist": "",
                    "genres": [],
                    "status": "unknown",
                    "year": "",
                    "language": "en",
                    "site": "mangadex"
                }
                
                with open(series_json_path, 'w', encoding='utf-8') as f:
                    json.dump(series_data, f, indent=2, ensure_ascii=False)
            
            if not os.path.exists(comic_info_path):
                comic_info = f'''<?xml version="1.0"?>
<ComicInfo>
    <Title>{manga_name}</Title>
    <Series>{manga_name}</Series>
    <LocalizedSeries>{manga_name}</LocalizedSeries>
    <LanguageISO>en</LanguageISO>
                        <Web>https://mangadex.org</Web>
</ComicInfo>'''
                
                with open(comic_info_path, 'w', encoding='utf-8') as f:
                    f.write(comic_info)
            
            if not os.path.exists(cover_path):
                placeholder_text = "No Cover Available"
                with open(cover_path, 'w') as f:
                    f.write(placeholder_text)
                    
        except Exception as e:
            logging.error(f"Failed to create manga metadata: {e}")