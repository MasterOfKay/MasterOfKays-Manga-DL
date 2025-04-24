import requests
from bs4 import BeautifulSoup
from typing import List, Tuple, Dict, Union
import re
import os
import zipfile
from io import BytesIO
import time
import logging
import json

logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(message)s',
                   filename='manga_download.log',
                   filemode='a')
logger = logging.getLogger(__name__)

def get_manga_name(url: str) -> str:
    """Extract manga name from URL"""
    match = re.search(r'/manga/([^/]+)', url)
    if match:
        name = match.group(1).replace('-', ' ').title()
        return re.sub(r'\.\d+$', '', name)
    return "Unknown Manga"

def get_chapter_links(url: str) -> List[Tuple[str, str, str]]:
    """Get all chapter links from MangaKatana manga page"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        max_retries = 3
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

def download_chapter(chapter_url: str, chapter_num: str, manga_name: str, base_path: str = None) -> Dict[str, Union[str, bool]]:
    """Download a MangaKatana chapter and create a CBZ file with robust error handling.
    Returns a dictionary with the path to the CBZ file and the chapter URL for history tracking.
    """
    try:
        chapter_num = str(chapter_num).strip()
        
        safe_manga_name = ''.join(c for c in manga_name if c not in '/:*?"<>|')
        if not safe_manga_name:
            safe_manga_name = manga_name
        
        if base_path is None or not os.path.isdir(base_path):
            base_path = os.getcwd()
        
        base_dir = os.path.join(base_path, safe_manga_name)
        os.makedirs(base_dir, exist_ok=True)
        
        cbz_filename = f"Chapter {chapter_num}.cbz"
        cbz_path = os.path.join(base_dir, cbz_filename)
        
        if os.path.exists(cbz_path):
            if os.path.getsize(cbz_path) > 0:
                print(f"Chapter {chapter_num} already exists, skipping...")
                return {"path": cbz_path, "url": chapter_url, "success": True}
            else:
                print(f"Found empty file for Chapter {chapter_num}, removing and redownloading...")
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

        if not image_urls:
            all_img_tags = soup.find_all('img')
            for img in all_img_tags:
                for attr in ['data-src', 'src', 'data-lazy-src', 'data-original', 'data-lazy', 'data-url']:
                    src = img.get(attr)
                    if src and 'http' in src and 'about:blank' not in src and '#' not in src:
                        if any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                            image_urls.append(src)
                            break
            
            logger.info(f"Method 3: Found {len(image_urls)} image URLs")

        if not image_urls:
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string:
                    json_matches = re.findall(r'({[^}]+images[^}]+})', script.string)
                    for json_str in json_matches:
                        try:
                            json_str = re.sub(r'([{,])\s*(\w+):', r'\1"\2":', json_str)
                            data = json.loads(json_str)
                            if 'images' in data and isinstance(data['images'], list):
                                for img in data['images']:
                                    if isinstance(img, str) and 'http' in img:
                                        image_urls.append(img)
                                    elif isinstance(img, dict) and 'url' in img and 'http' in img['url']:
                                        image_urls.append(img['url'])
                        except (json.JSONDecodeError, TypeError):
                            continue
            
            if image_urls:
                logger.info(f"Method 4: Found {len(image_urls)} image URLs from JSON in scripts")

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
        
        with zipfile.ZipFile(cbz_path, 'w') as cbz:
            for idx, img_url in enumerate(image_urls, 1):
                try:
                    for img_attempt in range(3):
                        try:
                            img_response = session.get(img_url, timeout=10)
                            img_response.raise_for_status()
                            
                            img_filename = f"{idx:03d}.jpg"
                            
                            cbz.writestr(img_filename, img_response.content)
                            logger.debug(f"Downloaded image {idx}/{len(image_urls)}")
                            break
                        except Exception as e:
                            if img_attempt < 2:
                                logger.warning(f"Error downloading image {idx} (attempt {img_attempt+1}/3): {e}")
                                time.sleep(1)
                            else:
                                logger.error(f"Failed to download image {idx} after 3 attempts: {e}")
                                raise
                except Exception as img_error:
                    logger.error(f"Error processing image {idx}: {img_error}")
        
        if os.path.getsize(cbz_path) < 1000:
            logger.error("CBZ file is too small, likely empty")
            os.remove(cbz_path)
            return {"path": "", "url": chapter_url, "success": False}
            
        logger.info(f"Successfully created CBZ for chapter {chapter_num}")
        return {"path": cbz_path, "url": chapter_url, "success": True}

    except Exception as e:
        logger.exception(f"Error downloading chapter {chapter_num}: {e}")
        if 'cbz_path' in locals() and os.path.exists(cbz_path):
            os.remove(cbz_path)
        return {"path": "", "url": chapter_url, "success": False}

def check_for_updates(manga_url: str, current_chapters: List[str]) -> List[Tuple[str, str, str]]:
    """Check if there are new chapters available
    Returns a list of new chapters that are not in current_chapters
    """
    try:
        all_chapters = get_chapter_links(manga_url)
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
