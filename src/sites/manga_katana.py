"""
MangaKatana downloader implementation.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Tuple, Dict, Union, Optional, Callable
import os
import re
import time
import zipfile
import json
import logging

from .base import ComicSiteBase

logger = logging.getLogger(__name__)


class MangaKatanaDownloader(ComicSiteBase):
    """MangaKatana manga downloader."""
    
    def __init__(self):
        super().__init__("MangaKatana", "https://mangakatana.com")
    
    @classmethod
    def validate_url(cls, url: str) -> bool:
        """Check if URL is valid for MangaKatana."""
        pattern = r'^https?://mangakatana\.com/manga/[a-zA-Z0-9-_.]+/?$'
        return bool(re.match(pattern, url))
    
    def get_manga_name(self, url: str) -> str:
        """Extract manga name from URL."""
        match = re.search(r'/manga/([^/]+)', url)
        if match:
            name = match.group(1).replace('-', ' ').title()
            return re.sub(r'\.\d+$', '', name)
        return "Unknown Manga"
    
    def get_manga_metadata(self, url: str):
        """Extract comprehensive manga metadata from MangaKatana manga page."""
        from .base import MangaMetadata
        
        metadata = MangaMetadata()
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title_elem = soup.select_one('h1.heading') or soup.select_one('h1') or soup.select_one('.manga-title')
            if title_elem:
                metadata.title = title_elem.get_text(strip=True)
            
            cover_img = soup.select_one('div.cover img') or soup.select_one('.manga-cover img') or soup.select_one('img[src*="cover"]')
            if cover_img and hasattr(cover_img, 'get'):
                src = cover_img.get('src')
                if src and isinstance(src, str):
                    if src.startswith('/'):
                        metadata.cover_image_url = f"https://mangakatana.com{src}"
                    else:
                        metadata.cover_image_url = src
            
            info_section = soup.select_one('.info')
            if info_section:
                info_text = info_section.get_text()
                
                alt_match = re.search(r'Alt name\(s\):\s*([^\n]+)', info_text, re.IGNORECASE)
                if alt_match:
                    alt_names = [name.strip() for name in alt_match.group(1).split(';') if name.strip()]
                    metadata.alternative_names = alt_names
                
                author_match = re.search(r'Author\(s\)\s*/\s*Artist\(s\):\s*([^\n]+)', info_text, re.IGNORECASE)
                if author_match:
                    metadata.author = author_match.group(1).strip()
                
                genres_match = re.search(r'Genres:\s*([^\n]+)', info_text, re.IGNORECASE)
                if genres_match:
                    genres_text = genres_match.group(1).strip()
                    genres = []
                    genre_parts = re.findall(r'[A-Z][a-z]*(?:\s+[A-Z][a-z]*)*', genres_text)
                    for part in genre_parts:
                        if part.strip() and part.strip() not in genres:
                            genres.append(part.strip())
                    metadata.genres = genres
                
                status_match = re.search(r'Status:\s*([^\n]+)', info_text, re.IGNORECASE)
                if status_match:
                    status_text = status_match.group(1).strip().lower()
                    status_map = {
                        'ongoing': 'ongoing',
                        'completed': 'completed',
                        'finished': 'completed',
                        'discontinued': 'cancelled',
                        'cancelled': 'cancelled'
                    }
                    metadata.status = status_map.get(status_text, 'unknown')
                
                latest_match = re.search(r'Latest chapter\(s\):\s*([^\n]+)', info_text, re.IGNORECASE)
                if latest_match:
                    latest_text = latest_match.group(1).strip()
                    metadata.release_date = latest_text
                
                update_match = re.search(r'Update at:\s*([^\n]+)', info_text, re.IGNORECASE)
                if update_match:
                    update_text = update_match.group(1).strip()
                    if not metadata.release_date:
                        metadata.release_date = update_text
            
            desc_elem = soup.select_one('.summary p') or soup.select_one('.description') or soup.select_one('.manga-summary')
            if desc_elem:
                metadata.description = desc_elem.get_text(strip=True)
            
            if not metadata.genres:
                genre_links = soup.select('a[href*="/genre/"]')
                for link in genre_links:
                    genre = link.get_text(strip=True)
                    if genre and genre not in metadata.genres:
                        metadata.genres.append(genre)
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting metadata from {url}: {e}")
            return metadata
    
    def get_chapter_links(self, url: str) -> List[Tuple[str, str, str]]:
        """Get all chapter links from MangaKatana manga page."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            
            max_retries = 3
            response = None
            for attempt in range(max_retries):
                try:
                    response = requests.get(url, headers=headers, timeout=10)
                    response.raise_for_status()
                    break
                except (requests.RequestException, ConnectionError) as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Error fetching manga page (attempt {attempt+1}/{max_retries}): {e}")
                        time.sleep(2)
                    else:
                        logger.error(f"Failed to fetch manga page after {max_retries} attempts: {e}")
                        raise

            if not response:
                raise Exception("Failed to fetch page")

            soup = BeautifulSoup(response.text, 'html.parser')

            chapter_table = soup.select_one('div.chapters table tbody')
            if not chapter_table:
                logger.warning("Couldn't find chapters table, trying alternative selectors")
                chapter_table = soup.select_one('table.uk-table tbody')
                if not chapter_table:
                    chapter_table = soup.select_one('div.chapters')
                    if not chapter_table:
                        logger.error("No chapter table found with any selector")
                        return []

            chapters = []
            
            rows = chapter_table.find_all('tr')
            if not rows:
                links = chapter_table.find_all('a', href=re.compile(r'/manga/.*?/chapter-\d+'))
                if not links:
                    logger.error("No chapter rows or links found")
                    return []
                    
                for link in links:
                    chapter_url = link['href']
                    chapter_text = link.text.strip()
                    
                    chapter_match = re.search(r'Chapter (\d+(?:\.\d+)?)', chapter_text)
                    if chapter_match:
                        chapter_num = chapter_match.group(1)
                        chapters.append((chapter_num, chapter_text, chapter_url))
            else:
                for row in rows:
                    link_elem = row.select_one('td div a') or row.select_one('td a')
                    if link_elem and link_elem.has_attr('href'):
                        chapter_url = link_elem['href']
                        if not chapter_url.startswith('http'):
                            chapter_url = f"https://mangakatana.com{chapter_url}"
                            
                        chapter_text = link_elem.text.strip()
                        chapter_match = re.search(r'Chapter (\d+(?:\.\d+)?)', chapter_text)
                        if chapter_match:
                            chapter_num = chapter_match.group(1)
                            chapters.append((chapter_num, chapter_text, chapter_url))

            chapters.sort(key=lambda x: float(x[0]) if x[0].replace('.', '', 1).isdigit() else 0)
            logger.info(f"Found {len(chapters)} chapters")
            return chapters
            
        except Exception as e:
            logger.exception(f"Error fetching chapters: {e}")
            return []
    
    def download_chapter_with_name(self, chapter_url: str, chapter_num: str, chapter_name: str, manga_name: str, 
                                  base_path: Optional[str] = None, progress_callback: Optional[Callable] = None) -> Dict[str, Union[str, bool]]:
        """Download a MangaKatana chapter with full chapter name and create a CBZ file."""
        try:
            chapter_num = str(chapter_num).strip()
            
            base_dir = self.get_safe_manga_path(manga_name, base_path)
            
            if chapter_name and chapter_name.strip() and chapter_name.strip() != f"Chapter {chapter_num}":
                clean_chapter_name = chapter_name.strip().replace(':', ' -')
                clean_chapter_name = re.sub(r'[<>"/\\|?*]', '', clean_chapter_name)
                cbz_filename = f"{clean_chapter_name}.cbz"
            else:
                cbz_filename = f"Chapter {chapter_num}.cbz"
            
            cbz_path = os.path.join(base_dir, cbz_filename)
            
            return self._download_chapter_internal(chapter_url, chapter_num, manga_name, base_path, progress_callback, cbz_filename)
            
        except Exception as e:
            logging.error(f"Error in download_chapter_with_name: {e}")
            return {"success": False, "error": str(e)}

    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str, 
                        base_path: Optional[str] = None, progress_callback: Optional[Callable] = None, 
                        language: str = "en") -> Dict[str, Union[str, bool]]:
        """Download a MangaKatana chapter and create a CBZ file with robust error handling."""
        return self._download_chapter_internal(chapter_url, chapter_num, manga_name, base_path, progress_callback)
    
    def _download_chapter_internal(self, chapter_url: str, chapter_num: str, manga_name: str, 
                                  base_path: Optional[str] = None, progress_callback: Optional[Callable] = None, 
                                  cbz_filename: Optional[str] = None) -> Dict[str, Union[str, bool]]:
        """Internal method to download a MangaKatana chapter."""
        try:
            chapter_num = str(chapter_num).strip()
            
            base_dir = self.get_safe_manga_path(manga_name, base_path)
            
            if not cbz_filename:
                cbz_filename = f"Chapter {chapter_num}.cbz"
            cbz_path = os.path.join(base_dir, cbz_filename)
            
            if os.path.exists(cbz_path):
                if os.path.getsize(cbz_path) > 0:
                    logger.debug(f"Chapter {chapter_num} already exists, skipping")
                    return {"path": cbz_path, "url": chapter_url, "success": True}
                else:
                    logger.info(f"Found empty file for Chapter {chapter_num}, removing and redownloading")
                    os.remove(cbz_path)
            
            logger.info(f"Starting download of {manga_name} chapter {chapter_num}")
        
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
                'Cache-Control': 'max-age=0',
                'Referer': 'https://mangakatana.com/',
            })

            max_retries = 3
            response = None
            for attempt in range(max_retries):
                try:
                    response = session.get(chapter_url, timeout=15)
                    response.raise_for_status()
                    logger.info(f"Successfully loaded chapter page: {chapter_url}")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Error loading chapter page (attempt {attempt+1}/{max_retries}): {e}")
                        time.sleep(2)
                    else:
                        logger.error(f"Failed to load chapter page after {max_retries} attempts: {e}")
                        raise

            if not response:
                raise Exception("Failed to load chapter page")

            image_urls = []
            
            js_patterns = [
                r'var\s+thzq\s*=\s*\[(.*?)\];',
                r'var\s+chapImages\s*=\s*\[(.*?)\];',
                r'var\s+images\s*=\s*\[(.*?)\];',
                r'var\s+pages\s*=\s*\[(.*?)\];',
                r'"images"\s*:\s*\[(.*?)\]',
            ]
            
            for pattern in js_patterns:
                matches = re.search(pattern, response.text, re.DOTALL)
                if matches:
                    urls_text = matches.group(1)
                    raw_urls = re.findall(r'["\'](https?://[^"\']+)["\']', urls_text)
                    for url in raw_urls:
                        if url and 'about:blank' not in url and '#' not in url:
                            image_urls.append(url)
                    
                    if image_urls:
                        logger.info(f"Method 1: Found {len(image_urls)} image URLs using pattern: {pattern}")
                        break
            
            if not image_urls:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                selectors = [
                    'div#imgs div.uk-grid.uk-grid-collapse', 
                    'div.img-content div.reading-content',
                    'div#imgs',
                    'div.chapter-content',
                    'div.reading-content',
                    'div.read-container',
                    'div.viewer-container',
                    'div.chapter-images',
                    'div.manga-reading-box',
                ]
                
                for selector in selectors:
                    imgs_container = soup.select_one(selector)
                    if imgs_container:
                        for img in imgs_container.find_all('img'):
                            for attr in ['data-src', 'src', 'data-lazy-src', 'data-original', 'data-lazy', 'data-url']:
                                src = img.get(attr)
                                if src and 'http' in src and 'about:blank' not in src and '#' not in src:
                                    image_urls.append(src)
                                    break
                        
                        if image_urls:
                            logger.info(f"Method 2: Found {len(image_urls)} image URLs using selector: {selector}")
                            break

            cleaned_urls = []
            seen_urls = set()
            for url in image_urls:
                url = url.strip()
                bg_match = re.search(r'url\([\'"]?(.*?)[\'"]?\)', url)
                if bg_match:
                    url = bg_match.group(1)
                
                if 'icon' in url.lower() or 'logo' in url.lower():
                    continue
                    
                if url not in seen_urls:
                    seen_urls.add(url)
                    cleaned_urls.append(url)
            
            image_urls = cleaned_urls
            
            if not image_urls:
                logger.error("No images found in chapter.")
                raise Exception("No images found in chapter.")

            logger.info(f"Found {len(image_urls)} images for chapter {chapter_num}")
            
            try:
                def get_url_number(url):
                    name_match = re.search(r'(\d+)\.(jpg|jpeg|png|webp|gif)', url.lower())
                    if name_match:
                        return int(name_match.group(1))
                    return 0
                
                if all(get_url_number(url) > 0 for url in image_urls):
                    image_urls.sort(key=get_url_number)
            except Exception as sort_error:
                logger.warning(f"Could not sort image URLs naturally: {sort_error}")
            
            successful_downloads = 0
            total_images = len(image_urls)
            if progress_callback:
                progress_callback(0, total_images)
            with zipfile.ZipFile(cbz_path, 'w') as cbz:
                for idx, img_url in enumerate(image_urls, 1):
                    try:
                        img_downloaded = False
                        for img_attempt in range(3):
                            try:
                                img_response = session.get(img_url, timeout=15)
                                img_response.raise_for_status()
                                
                                if len(img_response.content) < 1000:  # Skip very small images
                                    logger.warning(f"Image {idx} too small ({len(img_response.content)} bytes), skipping")
                                    break
                                
                                img_filename = f"{idx:03d}.jpg"
                                cbz.writestr(img_filename, img_response.content)
                                successful_downloads += 1
                                img_downloaded = True
                                logger.debug(f"Downloaded image {idx}/{total_images} ({len(img_response.content)} bytes)")
                                if progress_callback:
                                    progress_callback(idx, total_images)
                                break
                            except Exception as e:
                                if img_attempt < 2:
                                    logger.warning(f"Error downloading image {idx}, attempt {img_attempt+1}: {e}")
                                    time.sleep(2)
                                else:
                                    logger.error(f"Failed to download image {idx} after 3 attempts: {e}")
                        
                        if not img_downloaded:
                            logger.warning(f"Could not download image {idx}, continuing with next")
                    except Exception as img_error:
                        logger.error(f"Error processing image {idx}: {img_error}")
            
            if not os.path.exists(cbz_path) or os.path.getsize(cbz_path) < 1000:
                logger.error(f"CBZ file is too small or missing (size: {os.path.getsize(cbz_path) if os.path.exists(cbz_path) else 0} bytes)")
                if os.path.exists(cbz_path):
                    os.remove(cbz_path)
                return {"path": "", "url": chapter_url, "success": False}
            
            if successful_downloads == 0:
                logger.error("No images were successfully downloaded")
                if os.path.exists(cbz_path):
                    os.remove(cbz_path)
                return {"path": "", "url": chapter_url, "success": False}
            
            logger.info(f"Successfully downloaded {successful_downloads}/{len(image_urls)} images")
                
            logger.info(f"Successfully created CBZ for chapter {chapter_num}")
            return {"path": cbz_path, "url": chapter_url, "success": True}

        except Exception as e:
            logger.exception(f"Error downloading chapter {chapter_num}: {e}")
            cbz_path = os.path.join(self.get_safe_manga_path(manga_name, base_path), f"Chapter {chapter_num}.cbz")
            if os.path.exists(cbz_path):
                os.remove(cbz_path)
            return {"path": "", "url": chapter_url, "success": False}
    
    def check_for_updates(self, manga_url: str, current_chapters: List[str]) -> List[Tuple[str, str, str]]:
        """Check if there are new chapters available."""
        try:
            all_chapters = self.get_chapter_links(manga_url)
            if not all_chapters:
                logger.warning(f"No chapters found for {manga_url}")
                return []
                
            current_chapters_set = {str(ch) for ch in current_chapters}
            
            new_chapters = [ch for ch in all_chapters if str(ch[0]) not in current_chapters_set]
            
            if new_chapters:
                logger.info(f"Found {len(new_chapters)} new chapters")
            else:
                logger.info("No new chapters found")
                
            return new_chapters
        except Exception as e:
            logger.exception(f"Error checking for updates: {e}")
            return []


def get_manga_name(url: str) -> str:
    """Backward compatibility function."""
    downloader = MangaKatanaDownloader()
    return downloader.get_manga_name(url)


def get_chapter_links(url: str) -> List[Tuple[str, str, str]]:
    """Backward compatibility function."""
    downloader = MangaKatanaDownloader()
    return downloader.get_chapter_links(url)


def download_chapter(chapter_url: str, chapter_num: str, manga_name: str, 
                    base_path: Optional[str] = None) -> Dict[str, Union[str, bool]]:
    """Backward compatibility function."""
    downloader = MangaKatanaDownloader()
    return downloader.download_chapter(chapter_url, chapter_num, manga_name, base_path)


def check_for_updates(manga_url: str, current_chapters: List[str]) -> List[Tuple[str, str, str]]:
    """Backward compatibility function."""
    downloader = MangaKatanaDownloader()
    return downloader.check_for_updates(manga_url, current_chapters)