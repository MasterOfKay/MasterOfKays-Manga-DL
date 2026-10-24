"""
MangaFreak downloader (https://ww3.mangafreak.me).

Series pages (/Manga/<Slug>) list every chapter in a table with its name; a
reader page (/Read1_<Slug>_<number>) holds all images of the chapter. The site
moves between mirror hosts (ww1, ww2, w15, ...), so any mangafreak host is
accepted and rewritten to the current one.
"""

import io
import logging
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from .base import ChapterUnavailable, ComicSiteBase, MangaMetadata, save_file

BASE = "https://ww3.mangafreak.me"
_HOST = r'https?://(?:[a-z0-9]+\.)?mangafreak\.[a-z]+'
_SERIES = re.compile(rf'^{_HOST}/Manga/([A-Za-z0-9_\-]+)/?(?:[?#].*)?$', re.I)
_ANY = re.compile(rf'^{_HOST}(/.*)?$', re.I)
# "/Read1_Kingdom_891", "/Read1_..._97b" (b = second part), "/Read1_..._9e" (extra)
_CHAPTER_HREF = re.compile(r'_(\d+(?:\.\d+)?)([a-z]?)/?$', re.I)
PARALLEL_IMAGES = 6


def chapter_number(href: str) -> str:
    """'..._60' -> '60', '..._60b' -> '60.2', '..._9e' -> '9.5' (letters become decimals so they sort)."""
    match = _CHAPTER_HREF.search(href or '')
    if not match:
        return ''
    number, part = match.groups()
    if part and '.' not in number:
        return f"{number}.{ord(part.lower()) - ord('a') + 1}"
    return number


class MangaFreakDownloader(ComicSiteBase):
    """MangaFreak downloader."""

    def __init__(self):
        super().__init__("MangaFreak", BASE)
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/124.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.7',
            'Referer': BASE + '/',
        })
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=PARALLEL_IMAGES * 2)
        self._session.mount('https://', adapter)

    # ------------------------------------------------------------- urls
    @classmethod
    def validate_url(cls, url: str) -> bool:
        return bool(_SERIES.match((url or '').strip()))

    def canonical_url(self, url: str) -> str:
        """Current host, no trailing slash/query: https://ww3.mangafreak.me/Manga/Lost_Man"""
        match = _SERIES.match((url or '').strip())
        return f"{BASE}/Manga/{match.group(1)}" if match else url

    @staticmethod
    def _current_host(url: str) -> str:
        """Rewrite links stored from an older mirror host onto the current one."""
        match = _ANY.match(url or '')
        return BASE + (match.group(1) or '/') if match else url

    def _soup(self, url: str) -> BeautifulSoup:
        response = self._session.get(self._current_host(url), timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return BeautifulSoup(response.text, 'html.parser')

    # ------------------------------------------------------------- series
    def get_manga_name(self, url: str) -> str:
        try:
            title = self._soup(url).select_one('.manga_series_data h1')
            if title and title.get_text(strip=True):
                return title.get_text(strip=True)
        except requests.RequestException as e:
            logging.warning(f"MangaFreak title lookup failed for {url}: {e}")
        match = _SERIES.match(url or '')
        return match.group(1).replace('_', ' ') if match else 'Unknown'

    def get_manga_metadata(self, url: str) -> MangaMetadata:
        meta = MangaMetadata()
        meta.url = self.canonical_url(url)
        meta.site_type = 'mangafreak'
        soup = self._soup(url)
        data = soup.select_one('.manga_series_data')
        title = data.find('h1') if data else None
        meta.title = title.get_text(strip=True) if title else self.get_manga_name(url)
        for line in (data.find_all('div', recursive=False) if data else []):
            text = line.get_text(' ', strip=True)
            if text.startswith('Alternative Title:'):
                names = text.split(':', 1)[1]
                meta.alternative_names = [n.strip() for n in re.split(r'[,;]', names) if n.strip()]
            elif text.startswith('Written By:'):
                meta.author = text.split(':', 1)[1].strip()
            elif text.startswith('Illustrated By:'):
                meta.artist = text.split(':', 1)[1].strip()
            elif text.startswith('Year Published:'):
                meta.release_date = text.split(':', 1)[1].strip()
            elif 'series' in text.lower() and text.lower().startswith('this is'):
                meta.status = 'completed' if 'complete' in text.lower() else 'ongoing'
        meta.genres = [a.get_text(strip=True) for a in soup.select('.series_sub_genre_list a')]
        description = soup.select_one('.manga_series_description p')
        meta.description = description.get_text('\n', strip=True) if description else ''
        image = soup.select_one('.manga_series_image img') or soup.find('meta', property='og:image')
        meta.cover_image_url = (image.get('src') or image.get('content') or '') if image else ''
        return meta

    def get_chapter_links(self, url: str, language_filter: Optional[str] = None) -> List[Tuple[str, str, str]]:
        """[(number, name, url)] oldest first. Raises when the page can't be read."""
        soup = self._soup(url)
        chapters, seen = [], set()
        for link in soup.select('table a.chapter-link[href]'):
            href = link['href']
            number = chapter_number(href)
            if not number or number in seen:
                continue
            seen.add(number)
            # The site serves U+FFFD where it lost a non-breaking space ("1st Punch:<?>One Punch").
            text = re.sub(r'\s+', ' ', link.get_text(' ', strip=True).replace('�', ' '))
            # "Chapter 2 - Demonstration" -> "Demonstration"; "Chapter 119" -> ""
            name = re.sub(r'^chapter\s*[\w.]+\s*(?:[-:–]\s*)?', '', text, flags=re.I).strip()
            chapters.append((number, name, BASE + href if href.startswith('/') else self._current_host(href)))
        chapters.sort(key=lambda c: float(c[0]))
        return chapters

    # ------------------------------------------------------------- download
    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                         base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                         language: str = "en") -> str:
        """Download a chapter into '<base>/<manga>/Chapter N.cbz'. Raises on failure."""
        chapter_num = str(chapter_num).strip()
        target_dir = self.get_safe_manga_path(manga_name, base_path)
        cbz_path = os.path.join(target_dir, f"Chapter {chapter_num}.cbz")

        soup = self._soup(chapter_url)
        urls = [img.get('src') for img in soup.find_all('img')
                if '/mangas/' in (img.get('src') or '')]
        urls = list(dict.fromkeys(urls))
        if not urls:
            raise ChapterUnavailable("No pages found for this chapter on MangaFreak.")

        # Fetch several pages at once over kept-alive connections.
        pages: List[Optional[bytes]] = [None] * len(urls)
        done = 0
        if progress_callback:
            progress_callback(0, len(urls))
        with ThreadPoolExecutor(max_workers=PARALLEL_IMAGES) as pool:
            futures = {pool.submit(self._fetch_image, url): i for i, url in enumerate(urls)}
            for future in as_completed(futures):
                pages[futures[future]] = future.result()     # raises -> the chapter fails and is retried
                done += 1
                if progress_callback:
                    progress_callback(done, len(urls))

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as cbz:    # images are already compressed
            for index, (url, data) in enumerate(zip(urls, pages), start=1):
                ext = os.path.splitext(url.split('?')[0])[1].lower() or '.jpg'
                cbz.writestr(f"{index:03d}{ext}", data)
        save_file(cbz_path, buffer.getvalue())
        return cbz_path

    def _fetch_image(self, url: str) -> bytes:
        last: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = self._session.get(url, timeout=30)
                response.raise_for_status()
                if not response.headers.get('content-type', '').startswith('image/'):
                    raise RuntimeError(f"Not an image: {url}")
                return response.content
            except (requests.RequestException, RuntimeError) as e:
                last = e
                time.sleep(1 + attempt)
        raise RuntimeError(f"Page failed to download: {last}")
