import requests
from bs4 import BeautifulSoup
from typing import List, Tuple
import os
import zipfile
from urllib.parse import urlparse
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options

def get_chapter_links(manga_url: str) -> List[Tuple[str, str, str]]:
    """
    Scrapes chapter information from an Asura Comics manga page.
    Returns list of tuples: (chapter_number, chapter_name, chapter_link)
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(manga_url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        chapter_container = soup.select_one('div.pl-4.pr-2.pb-4.overflow-y-auto')
        
        if not chapter_container:
            return []

        chapters = []
        for chapter_div in chapter_container.find_all('div', class_='relative'):
            link = chapter_div.find('a')
            if link and link.get('href'):
                chapter_text = link.get_text(strip=True)
                chapter_text = chapter_text.replace('Chapter', '', 1).strip()
                
                match = re.match(r'(\d+(?:\.\d+)?)\s*(.+)', chapter_text)
                if match:
                    chapter_num = match.group(1).strip()
                    chapter_name = match.group(2).strip()
                else:
                    chapter_num, chapter_name = chapter_text, ''

                chapter_url = link['href']
                if not chapter_url.startswith(('http://', 'https://')):
                    if chapter_url.startswith('/'):
                        chapter_url = f"https://asuracomic.net{chapter_url}"
                    else:
                        chapter_url = f"https://asuracomic.net/series/{chapter_url}"
                
                chapters.append((chapter_num, chapter_name, chapter_url))

        return list(reversed(chapters))

    except requests.RequestException as e:
        print(f"Error fetching manga page: {e}")
        return []

def get_manga_name(url: str) -> str:
    """Extract manga name from URL"""
    path = urlparse(url).path
    manga_name = path.split('/')[-1]
    manga_name = '-'.join(manga_name.split('-')[:-1])
    return manga_name.replace('-', ' ').title()

def get_manga_folder(manga_name: str) -> str:
    """Get or create manga folder"""
    folder_name = manga_name.replace(' ', '-').lower()
    folder_path = os.path.join(os.getcwd(), folder_name)

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"Created new folder: {folder_name}")
    
    return folder_path


def download_chapter(chapter_url: str, chapter_num: str, manga_name: str, base_path: str = None, progress_callback=None) -> str:
    """Download a chapter and create a CBZ file with progress reporting and robust error handling"""
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
                img = div.find('img', class_='object-cover')
                if img and img.get('src'):
                    src = img['src']
                    if ('gg.asuracomic.net' in src and 
                        '/storage/media/' in src and 
                        'chapter page' in img.get('alt', '').lower()):
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
        if 'cbz_path' in locals() and os.path.exists(cbz_path):
            os.remove(cbz_path)
        return ""
