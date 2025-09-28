"""
AsuraComics downloader implementation.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Tuple, Optional, Callable
import os
import zipfile
from urllib.parse import urlparse
import re
import logging
import time
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options

from .base import ComicSiteBase, MangaMetadata


class AsuraComicsDownloader(ComicSiteBase):
    """AsuraComics manga downloader with enhanced error handling."""
    
    def __init__(self):
        super().__init__("AsuraComics", "https://asuracomic.net")
        self._session = requests.Session()
        self._session.headers.update(self._get_enhanced_headers())
    
    def _get_enhanced_headers(self):
        """Get enhanced headers to avoid bot detection."""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
            'Referer': self.base_url
        }
    
    def _make_request(self, url: str, timeout: int = 10) -> requests.Response:
        """Make HTTP request with proper error handling."""
        try:
            response = self._session.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to access {url}: {e}"
            if "503" in str(e):
                error_msg = "AsuraComics is experiencing server issues (503 Service Unavailable)."
            elif "403" in str(e):
                error_msg = "AsuraComics is blocking requests (403 Forbidden)."
            elif "timeout" in str(e).lower():
                error_msg = "AsuraComics is not responding (timeout)."
            
            logging.error(error_msg)
            raise requests.exceptions.RequestException(error_msg)
    
    @classmethod
    def validate_url(cls, url: str) -> bool:
        """Check if URL is valid for AsuraComics."""
        pattern = r'^https?://asuracomic\.net/series/[a-zA-Z0-9-_]+/?$'
        return bool(re.match(pattern, url))
    
    def get_manga_name(self, url: str) -> str:
        """Extract manga name from URL."""
        path = urlparse(url).path
        manga_name = path.split('/')[-1]
        
        if '-' in manga_name:
            parts = manga_name.split('-')
            if len(parts[-1]) >= 8 and parts[-1].isalnum():
                manga_name = '-'.join(parts[:-1])
        
        readable_name = manga_name.replace('-', ' ').title()
        
        if readable_name.endswith(' Asura Scans'):
            readable_name = readable_name[:-len(' Asura Scans')].strip()
        
        return readable_name
    
    def get_manga_metadata(self, url: str) -> MangaMetadata:
        """Extract comprehensive manga metadata from AsuraComics manga page."""
        metadata = MangaMetadata()
        
        try:
            response = self._make_request(url)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title_elem = (soup.find('h1', class_='text-xl font-bold text-white') or 
                         soup.find('h1') or 
                         soup.find('title'))
            if title_elem:
                title_text = title_elem.get_text(strip=True)
                if title_text and title_text != "Asura Scans":
                    if title_text.endswith('- Asura Scans'):
                        title_text = title_text[:-len('- Asura Scans')].strip()
                    elif title_text.endswith('Asura Scans'):
                        title_text = title_text[:-len('Asura Scans')].strip()
                    
                    url_based_name = self.get_manga_name(url)
                    clean_title = title_text.replace(',', '').replace(':', '').replace(';', '')
                    clean_url = url_based_name.replace(',', '').replace(':', '').replace(';', '')
                    
                    if clean_title.lower().replace(' ', '') == clean_url.lower().replace(' ', ''):
                        metadata.title = url_based_name
                    else:
                        metadata.title = title_text
            
            if not metadata.title:
                metadata.title = self.get_manga_name(url)
            
            cover_img = None
            cover_selectors = [
                'img[alt="poster"]',
                'img.w-full.object-cover',
                'img[src*="conversions"]',
            ]
            
            for selector in cover_selectors:
                cover_img = soup.select_one(selector)
                if cover_img:
                    break
            
            if cover_img and cover_img.get('src'):
                src = cover_img.get('src')
                if isinstance(src, str):
                    metadata.cover_image_url = src
                    if not metadata.cover_image_url.startswith('http'):
                        metadata.cover_image_url = f"{self.base_url.rstrip('/')}{src}"
            
            page_text = soup.get_text()
            
            title_clean = re.escape(metadata.title.replace(' - Asura Scans', '') if metadata.title else "")
            synopsis_patterns = [
                rf'Synopsis\s+{title_clean}(.+?)(?=Serialization|Author|Artist|Status|Type|Updated On|Genres)',
                r'Synopsis\s+[^[]*\[(.+?)\].*?(?=Serialization|Author|Artist|Status|Type|Updated On|Genres)',
                r'Synopsis\s+[^[]*(.+?)(?=Serialization|Author|Artist|Status|Type|Updated On|Genres)',
            ]
            
            for pattern in synopsis_patterns:
                synopsis_match = re.search(pattern, page_text, re.DOTALL | re.IGNORECASE)
                if synopsis_match:
                    desc_text = synopsis_match.group(1).strip()
                    desc_text = re.sub(r'\s+', ' ', desc_text)
                    desc_text = re.sub(r'(Facebook|Twitter|WhatsApp|Pinterest)+', '', desc_text)
                    desc_text = re.sub(r'^[^\w\[\]]*', '', desc_text)
                    
                    if desc_text.startswith('[') and ']' in desc_text:
                        bracket_end = desc_text.find(']')
                        if bracket_end != -1 and bracket_end < len(desc_text) - 1:
                            desc_text = desc_text
                        else:
                            desc_text = re.sub(r'^\[', '', desc_text)
                            desc_text = re.sub(r'\]$', '', desc_text)
                    
                    desc_text = desc_text.strip()
                    
                    if len(desc_text) > 20:
                        metadata.description = desc_text
                        break
            
            if not metadata.description:
                desc_selectors = [
                    'div.text-sm.text-gray-300',
                    '[class*="description"]',
                    'p[class*="text"]',
                    'div[class*="summary"]'
                ]
                
                for selector in desc_selectors:
                    desc_elem = soup.select_one(selector)
                    if desc_elem:
                        desc_text = desc_elem.get_text(strip=True)
                        if len(desc_text) > 50:
                            metadata.description = desc_text
                            break
            
            if 'page_text' not in locals():
                page_text = soup.get_text()
            
            author_patterns = [
                r'Author\s*([^\n\r]+?)(?:\s*Artist|\n)',
                r'Author[:\s]+([^\n\r]+)',
                r'Creator[:\s]+([^\n\r]+)',
                r'by\s+([A-Za-z\s\(\)/]+)',
            ]
            
            for pattern in author_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    author = match.group(1).strip()
                    author = re.sub(r'\s+', ' ', author)
                    
                    if (author and len(author) < 100 and
                        not any(word in author.lower() for word in ['studio that brought', 'mobile gacha', 'synopsis', 'description', 'story of'])):
                        metadata.author = author
                        break
            
            if not metadata.author:
                artist_patterns = [
                    r'Artist\s*([^\n\r]+?)(?:\s*Updated|\n)',
                    r'Artist[:\s]+([^\n\r]+)',
                ]
                
                for pattern in artist_patterns:
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        artist = match.group(1).strip()
                        artist = re.sub(r'\s+', ' ', artist)
                        
                        if (artist and len(artist) < 100 and
                            not any(word in artist.lower() for word in ['studio that brought', 'mobile gacha', 'synopsis', 'description', 'story of'])):
                            metadata.author = f"Artist: {artist}"
                            break
            
            status_patterns = [
                r'Status([A-Za-z]+)Type',
                r'Status\s+([^\s]+)\s+Type',
                r'Status[:\s]+([^\n\r]+)',
                r'Publication[:\s]*Status[:\s]+([^\n\r]+)'
            ]
            
            for pattern in status_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    status_text = match.group(1).strip().lower()
                    status_text = re.sub(r'\s+', ' ', status_text)
                    
                    status_map = {
                        'ongoing': 'ongoing',
                        'completed': 'completed',
                        'finished': 'completed',
                        'complete': 'completed',
                        'hiatus': 'cancelled',
                        'cancelled': 'cancelled',
                        'dropped': 'cancelled',
                        'discontinued': 'cancelled'
                    }
                    
                    for key, value in status_map.items():
                        if key in status_text:
                            metadata.status = value
                            break
                    
                    if metadata.status:
                        break
            
            genre_patterns = [
                r'Genres([A-Za-z\s]+?)(?:Keywords|Updated|Status|Type|$)',
                r'Genre[s]?[:\s]+([^\n\r]+)',
                r'Tag[s]?[:\s]+([^\n\r]+)',
                r'Categories[:\s]+([^\n\r]+)'
            ]
            
            genres_found = set()
            
            for pattern in genre_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    genres_text = match.group(1).strip()
                    
                    if (',' not in genres_text and ';' not in genres_text and 
                        len(genres_text) > 10 and not genres_text.count(' ') > 2):
                        known_genres = ['Genius MC', 'MC', 'Drama', 'Shounen', 'Shoujo', 'Seinen', 'Josei', 'Action', 'Adventure', 'Comedy', 'Fantasy', 'Romance', 'Horror', 'Mystery', 'SciFi', 'Sci-Fi', 'Sports', 'Supernatural', 'Thriller', 'Mecha', 'School', 'Life', 'System', 'Magic', 'Reincarnation', 'Isekai', 'Gaming', 'VR', 'Martial Arts', 'Cultivation', 'Xianxia', 'Manhwa', 'Manhua', 'Webtoon']
                        
                        genre_list = []
                        remaining_text = genres_text
                        
                        for genre in sorted(known_genres, key=len, reverse=True):
                            if genre in remaining_text:
                                genre_list.append(genre)
                                remaining_text = remaining_text.replace(genre, '', 1)
                        
                        if not genre_list:
                            genre_list = re.findall(r'[A-Z][a-z]*', genres_text)
                    else:
                        genre_list = re.split(r'[,;|/\s]+', genres_text)
                    
                    for genre in genre_list:
                        genre = genre.strip()
                        if (genre and len(genre) > 1 and len(genre) < 30 and
                            genre not in genres_found and
                            not any(word in genre.lower() for word in ['keywords', 'read', 'chapter', 'updated', 'genres', 'status', 'type'])):
                            genres_found.add(genre)
                            metadata.genres.append(genre)
                    
                    if genres_found:
                        break
            
            if not metadata.genres:
                tag_selectors = [
                    'span[class*="badge"]',
                    'span[class*="tag"]',
                    'div[class*="genre"]',
                    'a[class*="genre"]'
                ]
                
                for selector in tag_selectors:
                    tags = soup.select(selector)
                    for tag in tags:
                        tag_text = tag.get_text(strip=True)
                        if (tag_text and len(tag_text) < 25 and tag_text not in genres_found and
                            not any(word in tag_text.lower() for word in ['chapter', 'read', 'view', 'more', 'less', 'show', 'hide'])):
                            genres_found.add(tag_text)
                            metadata.genres.append(tag_text)
            
            alt_name_patterns = [
                r'Alternative[:\s]+([^\n\r]+)',
                r'Also known as[:\s]+([^\n\r]+)',
                r'AKA[:\s]+([^\n\r]+)',
                r'Other names[:\s]+([^\n\r]+)'
            ]
            
            for pattern in alt_name_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    alt_names_text = match.group(1).strip()
                    alt_names = [name.strip() for name in alt_names_text.split(',')]
                    metadata.alternative_names.extend([name for name in alt_names if name])
                    break
            
        except Exception as e:
            logging.error(f"Error extracting metadata from {url}: {e}")
            try:
                metadata.title = self.get_manga_name(url)
            except:
                pass
        
        return metadata
    
    def _clean_chapter_name(self, chapter_name: str, chapter_num: str) -> str:
        """Clean chapter name by removing upload dates and unwanted patterns."""
        if not chapter_name:
            return ""
        
        # Remove date patterns (upload dates)
        date_patterns = [
            r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?\s+\d{4}',
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}(?:st|nd|rd|th)?\s+\d{4}',
            r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',  # 12/30/2022 or 30-12-2022
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',   # 2022-12-30
        ]
        
        cleaned = chapter_name
        for pattern in date_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r'\s*[-–—|:;,]\s*$', '', cleaned)
        cleaned = re.sub(r'^\s*[-–—|:;,]\s*', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()
        
        if not cleaned or cleaned.lower() in ['chapter', 'ch', f'chapter {chapter_num}', f'ch {chapter_num}']:
            return ""
        
        chapter_prefix_pattern = rf'chapter\s+{re.escape(str(chapter_num))}\s*[-–—|:;,]*\s*'
        cleaned = re.sub(chapter_prefix_pattern, '', cleaned, flags=re.IGNORECASE).strip()
        
        return cleaned

    def get_chapter_links(self, url: str) -> List[Tuple[str, str, str]]:
        """
        Scrapes chapter information from an Asura Comics manga page.
        Returns list of tuples: (chapter_number, chapter_name, chapter_link)
        """
        try: 
            response = self._make_request(url)

            soup = BeautifulSoup(response.text, 'html.parser')
            
            base_chapter_url = url.rstrip('/') + '/chapter/'
            
            chapters = []
            all_links = soup.find_all('a')
            
            for link in all_links:
                if not hasattr(link, 'get') or not hasattr(link, 'get_text'):
                    continue
                    
                href = link.get('href')
                if not href or not isinstance(href, str):
                    continue
                    
                text = link.get_text(strip=True)
                
                if (href and 'chapter/' in href and 
                    ('chapter' in text.lower() or text.isdigit() or 
                     re.search(r'chapter\s*\d+', text, re.IGNORECASE))):
                    
                    chapter_num = ""
                    chapter_name = ""
                    
                    chapter_match = re.search(r'/chapter/(\d+(?:\.\d+)?)', href)
                    if chapter_match:
                        chapter_num = chapter_match.group(1)
                        
                        clean_text = text.replace('Chapter', '').replace('chapter', '').strip()
                        
                        name_match = re.search(rf'{re.escape(chapter_num)}\s*(.+)', clean_text)
                        if name_match:
                            raw_chapter_name = name_match.group(1).strip()
                        elif clean_text and not clean_text.isdigit():
                            raw_chapter_name = clean_text
                        else:
                            raw_chapter_name = ""
                        
                        chapter_name = self._clean_chapter_name(raw_chapter_name, chapter_num)
                        
                        if not chapter_name:
                            chapter_name = f"Chapter {chapter_num}"
                    else:
                        num_match = re.search(r'(\d+(?:\.\d+)?)', text)
                        if num_match:
                            chapter_num = num_match.group(1)
                            raw_name = text.strip()
                            cleaned_name = self._clean_chapter_name(raw_name, chapter_num)
                            chapter_name = cleaned_name or f"Chapter {chapter_num}"
                        else:
                            continue
                    
                    chapter_url = f"{base_chapter_url}{chapter_num}"
                    
                    chapters.append((chapter_num, chapter_name, chapter_url))
            
            seen = set()
            unique_chapters = []
            for chapter_num, chapter_name, chapter_url in chapters:
                if chapter_num not in seen:
                    seen.add(chapter_num)
                    unique_chapters.append((chapter_num, chapter_name, chapter_url))
            
            try:
                unique_chapters.sort(key=lambda x: float(x[0]))
            except ValueError:
                pass
            
            return unique_chapters

        except Exception as e:
            logging.error(f"Error fetching chapters from {url}: {e}")
            return []
    
    def download_chapter_with_name(self, chapter_url: str, chapter_num: str, chapter_name: str, manga_name: str, 
                                  base_path: Optional[str] = None, progress_callback: Optional[Callable] = None) -> str:
        """Download a chapter with full chapter name and create a CBZ file."""
        try:
            chapter_num = str(chapter_num).strip()
            
            base_dir = self.get_safe_manga_path(manga_name, base_path)
            
            if chapter_name and chapter_name.strip() and chapter_name.strip() != f"Chapter {chapter_num}":
                clean_chapter_name = self._clean_chapter_name(chapter_name.strip(), chapter_num)
                if clean_chapter_name:
                    safe_chapter_name = re.sub(r'[<>:"/\\|?*]', '', clean_chapter_name)
                    cbz_filename = f"Chapter {chapter_num} - {safe_chapter_name}.cbz"
                else:
                    cbz_filename = f"Chapter {chapter_num}.cbz"
            else:
                cbz_filename = f"Chapter {chapter_num}.cbz"
            
            return self._download_chapter_internal(chapter_url, chapter_num, manga_name, base_path, progress_callback, cbz_filename)
            
        except Exception as e:
            logging.error(f"Error in download_chapter_with_name: {e}")
            return ""

    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str, 
                        base_path: Optional[str] = None, progress_callback: Optional[Callable] = None, 
                        language: str = "en") -> str:
        """Download a chapter and create a CBZ file with progress reporting and robust error handling."""
        return self._download_chapter_internal(chapter_url, chapter_num, manga_name, base_path, progress_callback)
    
    def _download_chapter_internal(self, chapter_url: str, chapter_num: str, manga_name: str, 
                                  base_path: Optional[str] = None, progress_callback: Optional[Callable] = None, 
                                  cbz_filename: Optional[str] = None) -> str:
        """Internal method to download a chapter."""
        try:
            chapter_num = str(chapter_num).strip()
            
            base_dir = self.get_safe_manga_path(manga_name, base_path)
            
            if not cbz_filename:
                cbz_filename = f"Chapter {chapter_num}.cbz"
            cbz_path = os.path.join(base_dir, cbz_filename)
            
            if os.path.exists(cbz_path):
                if os.path.getsize(cbz_path) > 0:
                    print(f"Chapter {chapter_num} already exists, skipping...")
                    return cbz_path
                else:
                    print(f"Found empty file for Chapter {chapter_num}, removing and redownloading...")
                    os.remove(cbz_path)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://asuracomic.net/'
            }

            options = Options()
            options.add_argument('--headless')
            
            try:
                driver = webdriver.Firefox(options=options)
            except Exception as e:
                print(f"Failed to create Firefox driver: {e}")
                try:
                    from selenium.webdriver.chrome.options import Options as ChromeOptions
                    chrome_options = ChromeOptions()
                    chrome_options.add_argument('--headless')
                    driver = webdriver.Chrome(options=chrome_options)
                except Exception as chrome_err:
                    print(f"Failed to create Chrome driver as well: {chrome_err}")
                    return ""
            
            try:
                driver.set_page_load_timeout(30)
                
                try:
                    driver.get(chapter_url)
                except Exception as page_error:
                    print(f"Error loading page {chapter_url}: {page_error}")
                    return ""

                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "w-full.mx-auto.center"))
                    )
                except Exception as wait_error:
                    print(f"Timeout waiting for chapter images: {wait_error}")
                    print("Attempting to parse page despite timeout...")

                soup = BeautifulSoup(driver.page_source, 'html.parser')

                images = []
                for div in soup.find_all('div', class_='w-full mx-auto center'):
                    if not hasattr(div, 'find'):
                        continue
                    img = div.find('img', class_='object-cover')
                    if img and hasattr(img, 'get'):
                        src = img.get('src')
                        if isinstance(src, str) and src:
                            alt_text = img.get('alt', '') if hasattr(img, 'get') else ''
                            alt_str = str(alt_text).lower() if alt_text else ''
                            if ('gg.asuracomic.net' in src and 
                                '/storage/media/' in src and 
                                'chapter page' in alt_str):
                                images.append(src)
                
                if not images:
                    print(f"No images found for chapter {chapter_num}, URL: {chapter_url}")
                    print("Page source contains limited HTML for debugging:", driver.page_source[:500])
                    return ""

                total_images = len(images)
                print(f"Found {total_images} pages for chapter {chapter_num}")

                import uuid
                temp_dir = f"temp_chapter_{chapter_num}_{uuid.uuid4().hex[:8]}"
                os.makedirs(temp_dir, exist_ok=True)

                image_paths = []
                
                if progress_callback:
                    progress_callback(0, total_images)
                
                for i, img_url in enumerate(images, 1):
                    img_response = None
                    try:
                        max_retries = 3
                        for retry in range(max_retries):
                            try:
                                img_response = requests.get(img_url, headers=headers, timeout=15)
                                img_response.raise_for_status()
                                break
                            except Exception as img_error:
                                if retry < max_retries - 1:
                                    print(f"Retry {retry+1}/{max_retries} for image {i}")
                                    import time
                                    time.sleep(1)
                                else:
                                    print(f"Failed to download image {i} after {max_retries} attempts: {img_error}")
                                    raise
                        
                        if img_response:
                            img_ext = os.path.splitext(img_url.split('?')[0])[1]
                            if not img_ext or img_ext.lower() not in ['.jpg', '.jpeg', '.png', '.webp']:
                                img_ext = '.webp'
                            
                            img_path = os.path.join(temp_dir, f"{i:03d}{img_ext}")
                            print(f"Downloading page {i}/{len(images)}")
                            
                            with open(img_path, 'wb') as f:
                                f.write(img_response.content)
                            image_paths.append(img_path)
                            
                            if progress_callback:
                                progress_callback(i, total_images)
                            
                    except Exception as e:
                        print(f"Error downloading page {i}: {e}")
                        continue

                if not image_paths:
                    print("Failed to download any images")
                    if os.path.exists(temp_dir):
                        import shutil
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    return ""

                try:
                    with zipfile.ZipFile(cbz_path, 'w') as cbz:
                        for idx, img_path in enumerate(image_paths, 1):
                            img_filename = f"{idx:03d}.jpg"
                            with open(img_path, 'rb') as img_file:
                                cbz.writestr(img_filename, img_file.read())
                except Exception as zip_error:
                    print(f"Error creating CBZ file: {zip_error}")
                    if os.path.exists(cbz_path):
                        os.remove(cbz_path)
                    return ""

                for img_path in image_paths:
                    try:
                        if os.path.exists(img_path):
                            os.remove(img_path)
                    except Exception as rm_error:
                        print(f"Error removing temp file {img_path}: {rm_error}")
                
                try:
                    if os.path.exists(temp_dir):
                        import shutil
                        shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as rm_dir_error:
                    print(f"Error removing temp directory: {rm_dir_error}")

                return cbz_path
                
            finally:
                try:
                    driver.quit()
                except:
                    pass
                
        except Exception as e:
            print(f"Error downloading chapter {chapter_num}: {e}")
            cbz_path = os.path.join(self.get_safe_manga_path(manga_name, base_path), f"Chapter {chapter_num}.cbz")
            if os.path.exists(cbz_path):
                os.remove(cbz_path)
            return ""


# Backward compatibility functions
def get_manga_name(url: str) -> str:
    """Backward compatibility function."""
    downloader = AsuraComicsDownloader()
    return downloader.get_manga_name(url)


def get_chapter_links(manga_url: str) -> List[Tuple[str, str, str]]:
    """Backward compatibility function."""
    downloader = AsuraComicsDownloader()
    return downloader.get_chapter_links(manga_url)


def download_chapter(chapter_url: str, chapter_num: str, manga_name: str, 
                    base_path: Optional[str] = None, progress_callback=None) -> str:
    """Backward compatibility function."""
    downloader = AsuraComicsDownloader()
    return downloader.download_chapter(chapter_url, chapter_num, manga_name, base_path, progress_callback)