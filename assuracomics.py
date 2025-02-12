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

def download_chapter(chapter_url: str, chapter_num: str, manga_name: str) -> str:
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://asuracomic.net/'
        }

        options = Options()
        options.add_argument('--headless')
        driver = webdriver.Firefox(options=options)
        
        try:
            driver.get(chapter_url)

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "w-full.mx-auto.center"))
            )

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
                print("No chapter images found")
                return ""

            print(f"Found {len(images)} pages")

            temp_dir = f"temp_chapter_{chapter_num}"
            os.makedirs(temp_dir, exist_ok=True)

            image_paths = []
            for i, img_url in enumerate(images, 1):
                try:
                    img_response = requests.get(img_url, headers=headers)
                    img_response.raise_for_status()
                    
                    img_ext = os.path.splitext(img_url.split('?')[0])[1]
                    if not img_ext or img_ext.lower() not in ['.jpg', '.jpeg', '.png', '.webp']:
                        img_ext = '.webp'
                    
                    img_path = os.path.join(temp_dir, f"{i:03d}{img_ext}")
                    print(f"Downloading page {i}/{len(images)}")
                    
                    with open(img_path, 'wb') as f:
                        f.write(img_response.content)
                    image_paths.append(img_path)
                except Exception as e:
                    print(f"Error downloading page {i}")
                    continue

            if not image_paths:
                print("Failed to download any images")
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
                return ""

            manga_folder = get_manga_folder(manga_name)

            cbz_filename = os.path.join(manga_folder, f"{manga_name}-Chapter{chapter_num}.cbz")
            with zipfile.ZipFile(cbz_filename, 'w') as zf:
                for img_path in image_paths:
                    zf.write(img_path, os.path.basename(img_path))

            for img_path in image_paths:
                os.remove(img_path)
            os.rmdir(temp_dir)

            return cbz_filename
            
        finally:
            driver.quit()
            
    except Exception as e:
        print(f"Error downloading chapter {chapter_num}")
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, file))
            os.rmdir(temp_dir)
        return ""
