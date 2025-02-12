import requests
from bs4 import BeautifulSoup
from typing import List, Tuple
import re
import os
import zipfile
from io import BytesIO

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
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        chapter_table = soup.select_one('div.chapters table tbody')
        if not chapter_table:
            return []

        chapters = []
        for row in chapter_table.find_all('tr'):
            link_elem = row.select_one('td div a')
            if link_elem:
                chapter_url = link_elem['href']
                chapter_text = link_elem.text.strip()

                chapter_match = re.search(r'Chapter (\d+(?:\.\d+)?)', chapter_text)
                if chapter_match:
                    chapter_num = chapter_match.group(1)
                    chapters.append((chapter_num, chapter_text, chapter_url))

        return sorted(chapters, key=lambda x: float(x[0]))
    except Exception as e:
        print(f"Error fetching chapters: {e}")
        return []

def download_chapter(chapter_url: str, chapter_num: str, manga_name: str) -> str:
    """Download a chapter and create a CBZ file"""
    try:
        base_dir = os.path.join(os.getcwd(), manga_name)
        os.makedirs(base_dir, exist_ok=True)
        
        cbz_filename = f"Chapter {chapter_num}.cbz"
        cbz_path = os.path.join(base_dir, cbz_filename)

        if os.path.exists(cbz_path):
            print(f"Chapter {chapter_num} already exists, skipping...")
            return cbz_path

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://mangakatana.com/',
            'Connection': 'keep-alive',
        }

        print(f"Fetching chapter page: {chapter_url}")
        session = requests.Session()
        response = session.get(chapter_url, headers=headers)
        response.raise_for_status()

        image_urls = []

        thzq_match = re.search(r'var\s+thzq\s*=\s*\[(.*?)\];', response.text, re.DOTALL)
        if thzq_match:
            urls_text = thzq_match.group(1)
            raw_urls = urls_text.split(',')
            image_urls = [url.strip().strip("'") for url in raw_urls if 'http' in url]
        
        if not image_urls:
            soup = BeautifulSoup(response.text, 'html.parser')
            imgs_container = soup.select_one('div#imgs div.uk-grid.uk-grid-collapse')
            if imgs_container:
                for img_div in imgs_container.find_all('div', class_='wrap_img'):
                    img = img_div.find('img')
                    if img and img.get('data-src'):
                        image_urls.append(img.get('data-src'))

        if not image_urls:
            with open('debug_page.html', 'w', encoding='utf-8') as f:
                f.write(response.text)
            print("Debug: Saved page source to debug_page.html")
            raise Exception("No images found in chapter")

        image_urls = [url for url in image_urls if url and 'about:blank' not in url and '#' not in url]
        
        print(f"Found {len(image_urls)} images")

        with zipfile.ZipFile(cbz_path, 'w') as cbz:
            for idx, img_url in enumerate(image_urls, 1):
                print(f"Downloading image {idx}/{len(image_urls)}: {img_url}")
                img_response = session.get(img_url, headers=headers)
                img_response.raise_for_status()

                img_filename = f"{idx:03d}.jpg"
                cbz.writestr(img_filename, img_response.content)

        return cbz_path

    except Exception as e:
        print(f"Error downloading chapter {chapter_num}: {e}")
        if os.path.exists(cbz_path):
            os.remove(cbz_path)
        return ""
