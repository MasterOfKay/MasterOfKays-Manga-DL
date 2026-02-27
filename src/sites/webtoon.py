"""
Webtoon downloader implementation - English only.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Tuple, Optional, Callable
import re
import os
import zipfile
from urllib.parse import urljoin

from .base import ComicSiteBase

import logging
logger = logging.getLogger(__name__)


class WebtoonDownloader(ComicSiteBase):
    """Webtoon manga downloader for English content."""
    
    def __init__(self):
        super().__init__("Webtoon", "https://www.webtoons.com")
        self._chapter_cache = {}
    
    @classmethod
    def validate_url(cls, url: str) -> bool:
        """Check if URL is valid for Webtoon."""
        pattern = r'^https?://www\.webtoons\.com/[a-z]{2}/[^/]+/[^/]+/list\?title_no=\d+$'
        return bool(re.match(pattern, url))
    
    def get_manga_name(self, url: str) -> str:
        """Extract manga name from URL."""
        match = re.search(r'/([^/]+)/list', url)
        if match:
            return match.group(1).replace('-', ' ').title()
        return "Unknown Manga"
    
    def get_manga_metadata(self, url: str):
        """Extract comprehensive manga metadata from Webtoon manga page."""
        from .base import MangaMetadata
        
        metadata = MangaMetadata()
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://www.webtoons.com/'
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            metadata.language = 'en'
            
            title_elem = soup.select_one('h1.subj') or soup.select_one('.detail_header h1') or soup.select_one('h1')
            if title_elem:
                metadata.title = title_elem.get_text(strip=True)
            
            cover_img = (soup.select_one('.detail_header .thmb img') or 
                        soup.select_one('.detail_body .thmb img') or 
                        soup.select_one('.info .pic img') or
                        soup.select_one('img[alt*="thumbnail"]'))
            
            if cover_img and hasattr(cover_img, 'get'):
                src = cover_img.get('src')
                if src and isinstance(src, str):
                    if 'type=f' in src:
                        src = src.replace('type=f160_151', 'type=crop600_600')
                    metadata.cover_image_url = src
            
            desc_elem = soup.select_one('.summary') or soup.select_one('.detail_summary') or soup.select_one('.description')
            if desc_elem:
                metadata.description = desc_elem.get_text(strip=True)
            
            page_text = soup.get_text()
            created_by_match = re.search(r'Created by\s*([^\n\r]+)', page_text, re.IGNORECASE)
            if created_by_match:
                author_text = created_by_match.group(1).strip()
                if 'Other Works' in author_text:
                    author_text = author_text.split('Other Works')[0].strip()
                metadata.author = author_text
            
            if not metadata.author:
                author_elem = soup.select_one('.detail_header .author') or soup.select_one('.author a') or soup.select_one('[data-author]')
                if author_elem:
                    metadata.author = author_elem.get_text(strip=True)
            
            genre_elems = soup.select('.genre a, .tag a, [data-genre]')
            for elem in genre_elems:
                genre = elem.get_text(strip=True)
                if genre and genre not in metadata.genres:
                    metadata.genres.append(genre)
            
            url_parts = url.split('/')
            if not metadata.genres and len(url_parts) > 5:
                genre_from_url = url_parts[5].replace('-', ' ').title()
                if genre_from_url:
                    metadata.genres.append(genre_from_url)
            
            if 'official' in page_text.lower():
                metadata.translation_type = 'official'
            elif 'fan' in page_text.lower() and 'translation' in page_text.lower():
                metadata.translation_type = 'fan'
            else:
                metadata.translation_type = 'official'
            
            status_text = soup.get_text().lower()
            if 'completed' in status_text or 'finished' in status_text:
                metadata.status = 'completed'
            elif 'ongoing' in status_text or 'updating' in status_text:
                metadata.status = 'ongoing'
            else:
                metadata.status = 'ongoing'
            
            return metadata
            
        except Exception as e:
            logging.error(f"Error extracting metadata from {url}: {e}")
            return metadata
    
    def get_chapter_links(self, url: str, use_cache: bool = True, db_manager=None, manga_id: Optional[int] = None) -> List[Tuple[str, str, str]]:
        """Get all chapter links from Webtoon manga page with caching and incremental updates.
        
        Returns list of tuples: (chapter_num, chapter_name, chapter_url)
        """
        try:
            if use_cache and db_manager and manga_id:
                cached_chapters = self._get_cached_chapters(db_manager, manga_id)
                if cached_chapters:
                    return self._incremental_chapter_update(url, db_manager, manga_id, cached_chapters)
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.7', 
                'Referer': 'https://www.webtoons.com/',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0'
            }

            logging.info(f"Fetching chapter list from: {url} (full scan)")
            
            if '?' not in url:
                title_match = re.search(r'/([^/]+)/list', url)
                if title_match:
                    title_no_match = re.search(r'title_no=(\d+)', url)
                    if not title_no_match:
                        response = requests.get(url, headers=headers)
                        response.raise_for_status()
                        title_no_match = re.search(r'title_no=(\d+)', response.url)
                    if title_no_match:
                        title_no = title_no_match.group(1)
                        url = f"{url}?title_no={title_no}" if '?' not in url else url

            session = requests.Session()
            all_chapters = []
            page = 1
            max_pages = 100 
            
            while page <= max_pages:
                if '?' in url:
                    separator = '&' if 'page=' not in url else ''
                    if 'page=' in url:
                        current_url = re.sub(r'page=\d+', f'page={page}', url)
                    else:
                        current_url = f"{url}{separator}page={page}" if page > 1 else url
                else:
                    current_url = f"{url}?page={page}" if page > 1 else url
                
                logging.debug(f"Fetching page {page}: {current_url}")
                
                response = session.get(current_url, headers=headers)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')

                chapter_list = soup.select('ul#_listUl > li')
                if not chapter_list:
                    if page == 1:
                        logging.debug("Chapter list not found on first page")
                        with open('debug_webtoon.html', 'w', encoding='utf-8') as f:
                            f.write(response.text)
                    break

                page_chapters = []
                for item in chapter_list:
                    try:
                        link_elem = item.select_one('a')
                        if not link_elem:
                            continue
                            
                        href = link_elem.get('href')
                        if not isinstance(href, str):
                            continue
                            
                        chapter_url = urljoin('https://www.webtoons.com', href)

                        chapter_match = re.search(r'episode_no=(\d+)', chapter_url)
                        if not chapter_match:
                            continue
                            
                        chapter_num = chapter_match.group(1)

                        title_elem = item.select_one('.subj')
                        chapter_name = title_elem.get_text(strip=True) if title_elem else f"Episode {chapter_num}"
                        
                        page_chapters.append((chapter_num, chapter_name, chapter_url))
                        
                    except Exception as e:
                        logging.warning(f"Error parsing chapter: {e}")
                        continue

                if not page_chapters:
                    logging.debug(f"No chapters found on page {page}, stopping pagination")
                    break
                    
                all_chapters.extend(page_chapters)
                logging.debug(f"Found {len(page_chapters)} chapters on page {page} (total: {len(all_chapters)})")
                
                next_page_link = soup.select_one('.paginate a[class*="next"]') or soup.select_one(f'.paginate a[href*="page={page + 1}"]')
                if not next_page_link:
                    logging.debug(f"No next page found after page {page}, stopping pagination")
                    break
                
                page += 1

            seen_episodes = set()
            unique_chapters = []
            for chapter_num, chapter_name, chapter_url in all_chapters:
                if chapter_num not in seen_episodes:
                    seen_episodes.add(chapter_num)
                    unique_chapters.append((chapter_num, chapter_name, chapter_url))

            unique_chapters.sort(key=lambda x: int(x[0]))
            logging.info(f"Found {len(unique_chapters)} total unique chapters across {page - 1} pages")
            
            if unique_chapters and db_manager and manga_id:
                self._update_scan_tracking(db_manager, manga_id, unique_chapters, page - 1)
            
            return unique_chapters

        except Exception as e:
            logging.error(f"Error fetching chapters: {e}")
            return []
    
    def _get_cached_chapters(self, db_manager, manga_id: int) -> List[Tuple[str, str, str]]:
        """Get cached chapters from database."""
        try:
            chapters = db_manager.get_chapters_for_manga(manga_id)
            return [(ch['chapter_number'], ch['chapter_name'], ch['chapter_url']) for ch in chapters]
        except Exception as e:
            logging.error(f"Error getting cached chapters: {e}")
            return []
    
    def _incremental_chapter_update(self, url: str, db_manager, manga_id: int, cached_chapters: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
        """Perform incremental update - check page 1 for new chapters and scan until we find cached ones."""
        try:
            if not cached_chapters:
                logging.debug("No cached chapters, performing full scan")
                return cached_chapters
            
            cached_episode_numbers = [int(ch[0]) for ch in cached_chapters]
            latest_cached_episode = max(cached_episode_numbers)
            
            logging.debug(f"Incremental update: Latest cached episode is {latest_cached_episode}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.7', 
                'Referer': 'https://www.webtoons.com/',
            }
            
            session = requests.Session()
            new_chapters = []
            
            page = 1
            found_cached_episode = False
            max_pages_to_check = 20
            
            while page <= max_pages_to_check and not found_cached_episode:
                if '?' in url:
                    separator = '&' if 'page=' not in url else ''
                    if 'page=' in url:
                        current_url = re.sub(r'page=\d+', f'page={page}', url)
                    else:
                        current_url = f"{url}{separator}page={page}" if page > 1 else url
                else:
                    current_url = f"{url}?page={page}" if page > 1 else url
                
                logging.debug(f"Checking page {page} for new chapters...")
                
                try:
                    response = session.get(current_url, headers=headers, timeout=10)
                    response.raise_for_status()
                except Exception as e:
                    logging.warning(f"Error fetching page {page}: {e}")
                    break
                
                soup = BeautifulSoup(response.text, 'html.parser')
                chapter_list = soup.select('ul#_listUl > li')
                
                if not chapter_list:
                    logging.debug(f"No chapters found on page {page}, ending scan")
                    break
                
                page_has_new_chapters = False
                
                for item in chapter_list:
                    try:
                        link_elem = item.select_one('a')
                        if not link_elem:
                            continue
                            
                        href = link_elem.get('href')
                        if not isinstance(href, str):
                            continue
                            
                        chapter_url = urljoin('https://www.webtoons.com', href)
                        chapter_match = re.search(r'episode_no=(\d+)', chapter_url)
                        if not chapter_match:
                            continue
                            
                        chapter_num = chapter_match.group(1)
                        episode_number = int(chapter_num)
                        
                        title_elem = item.select_one('.subj')
                        chapter_name = title_elem.get_text(strip=True) if title_elem else f"Episode {chapter_num}"
                        
                        if episode_number > latest_cached_episode:
                            new_chapters.append((chapter_num, chapter_name, chapter_url))
                            page_has_new_chapters = True
                            logging.debug(f"Found new chapter: Episode {episode_number}")
                        
                        elif episode_number <= latest_cached_episode:
                            found_cached_episode = True
                            logging.debug(f"Found cached episode {episode_number}, stopping scan")
                            break
                        
                    except Exception as e:
                        logging.warning(f"Error parsing chapter: {e}")
                        continue
                
                if not page_has_new_chapters and page > 1:
                    logging.debug(f"No new chapters on page {page}, scan complete")
                    break
                
                page += 1
            
            if page > max_pages_to_check:
                logging.debug(f"Reached page limit ({max_pages_to_check}), stopping scan")
            
            all_chapters = list(cached_chapters)
            for new_ch in new_chapters:
                if not any(cached_ch[0] == new_ch[0] for cached_ch in cached_chapters):
                    all_chapters.append(new_ch)
            
            all_chapters.sort(key=lambda x: int(x[0]))
            
            logging.info(f"Incremental update complete: {len(new_chapters)} new chapters found, {len(all_chapters)} total")
            
            if new_chapters:
                try:
                    from ..managers.database_manager import ChapterData
                    for chapter_num, chapter_name, chapter_url in new_chapters:
                        chapter_data = ChapterData(
                            chapter_number=chapter_num,
                            chapter_name=chapter_name,
                            chapter_url=chapter_url,
                            language='en',
                            is_downloaded=False
                        )
                        db_manager.add_or_update_chapter(manga_id, chapter_data)
                    logging.info(f"Added {len(new_chapters)} new chapters to database")
                except Exception as e:
                    logging.error(f"Error updating database with new chapters: {e}")
            
            return all_chapters
            
        except Exception as e:
            logging.error(f"Error in incremental update: {e}")
            return cached_chapters
    
    def _update_scan_tracking(self, db_manager, manga_id: int, chapters: List[Tuple[str, str, str]], total_pages: int):
        """Update scan tracking information in database for future incremental updates."""
        try:
            if not chapters:
                return
            
            episode_numbers = [int(ch[0]) for ch in chapters]
            latest_episode = max(episode_numbers)
            
            from datetime import datetime
            current_time = datetime.now().isoformat()
            
            import sqlite3
            with sqlite3.connect(db_manager.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE manga 
                    SET last_page_scanned = ?, 
                        total_pages = ?, 
                        last_chapter_scan = ?,
                        chapters_cached = ?,
                        last_updated = ?
                    WHERE id = ?
                """, (1, total_pages, str(latest_episode), len(chapters), current_time, manga_id))
                conn.commit()
                
            logging.debug(f"Updated scan tracking: latest_episode={latest_episode}, total_pages={total_pages}, chapters_cached={len(chapters)}")
            
        except Exception as e:
            logging.error(f"Error updating scan tracking: {e}")
    
    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str, 
                        base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                        language: str = "en") -> str:
        """Download a Webtoon chapter and create a CBZ file with robust error handling."""
        try:
            chapter_num = str(chapter_num).strip()
            
            base_dir = self.get_safe_manga_path(manga_name, base_path)
            
            cbz_filename = f"Chapter {chapter_num}.cbz"
            cbz_path = os.path.join(base_dir, cbz_filename)
            
            if os.path.exists(cbz_path):
                if os.path.getsize(cbz_path) > 0:
                    logging.debug(f"Chapter {chapter_num} already exists, skipping")
                    return cbz_path
                else:
                    logging.info(f"Found empty file for Chapter {chapter_num}, removing and redownloading")
                    os.remove(cbz_path)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.webtoons.com/'
            }

            response = requests.get(chapter_url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            image_container = soup.select_one('#_imageList')
            if not image_container:
                raise Exception("Could not find image container")

            images = image_container.find_all('img')
            if not images:
                raise Exception("No images found in chapter")

            with zipfile.ZipFile(cbz_path, 'w') as cbz:
                for idx, img in enumerate(images, 1):
                    img_url = img.get('data-url') or img.get('src') if hasattr(img, 'get') else None
                    if not img_url or not isinstance(img_url, str):
                        continue

                    if progress_callback:
                        progress_callback(idx, len(images))
                    img_response = requests.get(img_url, headers=headers)
                    img_response.raise_for_status()
                    
                    img_filename = f"{idx:03d}.jpg"
                    cbz.writestr(img_filename, img_response.content)

            return cbz_path

        except Exception as e:
            logging.error(f"Error downloading chapter {chapter_num}: {e}")
            cbz_path = os.path.join(self.get_safe_manga_path(manga_name, base_path), f"Chapter {chapter_num}.cbz")
            if os.path.exists(cbz_path):
                os.remove(cbz_path)
            return ""

def get_manga_name(url: str) -> str:
    """Backward compatibility function."""
    downloader = WebtoonDownloader()
    return downloader.get_manga_name(url)


def get_chapter_links(url: str) -> List[Tuple[str, str, str]]:
    """Backward compatibility function."""
    downloader = WebtoonDownloader()
    return downloader.get_chapter_links(url)


def download_chapter(chapter_url: str, chapter_num: str, manga_name: str, 
                    base_path: Optional[str] = None, language: str = "en") -> str:
    """Backward compatibility function."""
    downloader = WebtoonDownloader()
    return downloader.download_chapter(chapter_url, chapter_num, manga_name, base_path, language=language)