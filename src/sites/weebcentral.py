"""
Weeb Central downloader (https://weebcentral.com).

A series page (/series/<ULID>/<slug>) holds the metadata; its whole chapter list
comes from /series/<ULID>/full-chapter-list and the pages of a chapter from
/chapters/<ULID>/images. The slug in links is only decoration.
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

from .atsumaru import format_number
from .base import ChapterUnavailable, ComicSiteBase, MangaMetadata, save_file

BASE = "https://weebcentral.com"
_SERIES = re.compile(r'^https?://(?:www\.)?weebcentral\.com/series/([0-9A-HJKMNP-TV-Z]{26})(?:/[^?#]*)?(?:[?#].*)?$', re.I)
# "Chapter 271.5", "Episode 165", "Punch 175", "Official Scans 239"
_LABEL = re.compile(r'^(.*?)\s*(\d+(?:\.\d+)?)\s*$')
PARALLEL_IMAGES = 6


class WeebCentralDownloader(ComicSiteBase):
    """Weeb Central downloader."""

    def __init__(self):
        super().__init__("Weeb Central", BASE)
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
        """https://weebcentral.com/series/<ULID> (the slug may change, the id doesn't)."""
        match = _SERIES.match((url or '').strip())
        return f"{BASE}/series/{match.group(1).upper()}" if match else url

    def _soup(self, url: str, **params) -> BeautifulSoup:
        response = self._session.get(url, params=params or None, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return BeautifulSoup(response.text, 'html.parser')

    # ------------------------------------------------------------- series
    def get_manga_name(self, url: str) -> str:
        try:
            title = self._soup(self.canonical_url(url)).find('h1')
            if title and title.get_text(strip=True):
                return title.get_text(strip=True)
        except requests.RequestException as e:
            logging.warning(f"Weeb Central title lookup failed for {url}: {e}")
        return 'Unknown'

    def get_manga_metadata(self, url: str) -> MangaMetadata:
        meta = MangaMetadata()
        meta.url = self.canonical_url(url)
        meta.site_type = 'weebcentral'
        soup = self._soup(meta.url)
        title = soup.find('h1')
        meta.title = title.get_text(strip=True) if title else 'Unknown'
        for item in soup.select('section ul li'):
            label = item.find('strong')
            if not label:
                continue
            key = label.get_text(strip=True).rstrip(':').lower()
            links = [a.get_text(strip=True) for a in item.find_all('a')]
            value = item.get_text(' ', strip=True)[len(label.get_text(' ', strip=True)):].strip()
            if key == 'author(s)':
                meta.author = ', '.join(links)
            elif key == 'tags(s)':
                meta.genres = links
            elif key == 'status':
                status = value.lower()
                meta.status = {'complete': 'completed', 'canceled': 'cancelled'}.get(status, status or 'unknown')
            elif key == 'released':
                meta.release_date = value
            elif key == 'associated name(s)':
                meta.alternative_names = [li.get_text(strip=True) for li in item.select('ul li')]
            elif key == 'official translation':
                meta.translation_type = 'official' if value.lower() == 'yes' else 'scanlation'
            elif key == 'description':
                text = item.find('p')
                meta.description = text.get_text('\n', strip=True) if text else value
        image = soup.find('meta', property='og:image')
        meta.cover_image_url = image.get('content', '') if image else ''
        return meta

    def get_chapter_links(self, url: str, language_filter: Optional[str] = None) -> List[Tuple[str, str, str]]:
        """[(number, name, url)] oldest first. Raises when the list can't be read."""
        soup = self._soup(self.canonical_url(url) + '/full-chapter-list')
        chapters, seen = [], set()
        for link in soup.find_all('a', href=re.compile(r'/chapters/[0-9A-Z]{26}$')):
            label = link.find('span', class_='')
            match = _LABEL.match(label.get_text(' ', strip=True) if label else '')
            if not match:
                continue
            number = format_number(match.group(2))
            # The list is newest first; a number that appears twice (One-Punch Man has
            # "Punch N" next to "Official Scans N") keeps the newest upload.
            if number in seen:
                continue
            seen.add(number)
            href = link['href']
            chapters.append((number, '', BASE + href if href.startswith('/') else href))
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

        try:
            soup = self._soup(chapter_url.rstrip('/') + '/images',
                              is_prev='False', current_page=1, reading_style='long_strip')
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ChapterUnavailable("This chapter was removed from Weeb Central. "
                                         "Use 'Check for new' to refresh the chapter list.")
            raise
        urls = list(dict.fromkeys(img.get('src') for img in soup.find_all('img')
                                  if (img.get('src') or '').startswith('http')))
        if not urls:
            raise ChapterUnavailable("No pages found for this chapter on Weeb Central.")

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
