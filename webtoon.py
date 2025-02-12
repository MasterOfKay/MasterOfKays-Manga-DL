import requests
from bs4 import BeautifulSoup
from typing import List, Tuple
import re
import os
import zipfile
from urllib.parse import urljoin

def get_manga_name(url: str) -> str:
    """Extract manga name from URL"""
    match = re.search(r'/([^/]+)/list', url)
    if match:
        return match.group(1).replace('-', ' ').title()
    return "Unknown Manga"

def get_chapter_links(url: str) -> List[Tuple[str, str, str]]:
    """Get all chapter links from Webtoon manga page"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'de,en-US;q=0.7,en;q=0.3', 
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

        print(f"Fetching chapter list from: {url}")
        session = requests.Session()
        response = session.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')

        chapter_list = soup.select('ul#_listUl > li')
        if not chapter_list:
            print("Debug: Chapter list not found")
            with open('debug_webtoon.html', 'w', encoding='utf-8') as f:
                f.write(response.text)
            return []

        chapters = []
        for item in chapter_list:
            try:
                link_elem = item.select_one('a')
                if not link_elem:
                    continue
                    
                chapter_url = urljoin('https://www.webtoons.com', link_elem['href'])

                chapter_match = re.search(r'episode_no=(\d+)', chapter_url)
                if not chapter_match:
                    continue
                    
                chapter_num = chapter_match.group(1)

                title_elem = item.select_one('.subj')
                chapter_name = title_elem.text.strip() if title_elem else f"Episode {chapter_num}"
                
                chapters.append((chapter_num, chapter_name, chapter_url))
                
            except Exception as e:
                print(f"Error parsing chapter: {e}")
                continue

        chapters.sort(key=lambda x: int(x[0]))
        print(f"Found {len(chapters)} chapters")
        return chapters

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
                img_url = img.get('data-url') or img.get('src')
                if not img_url:
                    continue

                print(f"Downloading image {idx}/{len(images)}")
                img_response = requests.get(img_url, headers=headers)
                img_response.raise_for_status()
                
                img_filename = f"{idx:03d}.jpg"
                cbz.writestr(img_filename, img_response.content)

        return cbz_path

    except Exception as e:
        print(f"Error downloading chapter {chapter_num}: {e}")
        if os.path.exists(cbz_path):
            os.remove(cbz_path)
        return ""
