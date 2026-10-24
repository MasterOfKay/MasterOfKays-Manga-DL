"""
MangaBall downloader (https://mangaball.com).

The site is a web app on top of a public JSON API (api.mangaball.com/api/v1):
    GET  /title/detail/<id>                     details (name, description, cover, authors, tags, ...)
    POST /chapter/chapter-listing-by-title-id   every upload of every chapter, in every language
    GET  /chapter-detail?chapter_id=<id>        the page images of one chapter
Images are only served with the site as referer.

Chapters come in many languages and from several groups per language; the library
keeps all of them (language picker + release group filter in the chapter panel).
"""

import io
import logging
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter

from .atsumaru import _plain_markdown, format_number
from .base import ChapterInfo, ChapterUnavailable, ComicSiteBase, MangaMetadata, save_file

BASE = "https://mangaball.com"
API = "https://api.mangaball.com/api/v1"
COVERS = "https://bulbasaur.poke-black-and-white.net/covers/"
_SERIES = re.compile(r'^https?://(?:www\.)?mangaball\.(?:com|net)/title-detail/([0-9a-f]{24})(?:-[^/?#]*)?/?(?:[?#].*)?$',
                     re.I)
_CHAPTER = re.compile(r'/chapter-detail/([0-9a-f]{24})', re.I)
PARALLEL_IMAGES = 6


def cover_url(image: dict) -> str:
    """The site's own cover copy, else the one it took from MangaDex / MangaUpdates."""
    image = image or {}
    path = ((image.get('cover') or {}).get('path') or '').replace('\\', '/')     # some are 'id\\cover.jpg'
    if path:
        return COVERS + path.lstrip('/')
    return image.get('cdn_mangadex') or image.get('cdn_mangaupdates') or image.get('file') or ''


def chapter_name(name: str) -> str:
    """'The Villainess Duke […] – Chapter 25' -> '', 'Ch.14 - Rain' -> 'Rain', 'OFFICIAL TRANSLATION' -> ''"""
    name = (name or '').strip()
    match = re.search(r'(?:^|\s)(?:chapter|ch\.?|episode|ep\.?)\s*[\d.]+\s*[:\-–—.]?\s*', name, re.I)
    if match:
        name = name[match.end():].strip()
    return '' if name.upper() == 'OFFICIAL TRANSLATION' else name


class MangaBallDownloader(ComicSiteBase):
    """MangaBall (mangaball.com) downloader."""

    def __init__(self):
        super().__init__("MangaBall", BASE)
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/124.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.7',
            'Origin': BASE,
            'Referer': BASE + '/',
        })
        self._session.mount('https://', HTTPAdapter(pool_connections=4, pool_maxsize=PARALLEL_IMAGES * 2))

    # ------------------------------------------------------------- urls
    @classmethod
    def validate_url(cls, url: str) -> bool:
        return bool(_SERIES.match((url or '').strip()))

    def canonical_url(self, url: str) -> str:
        match = _SERIES.match((url or '').strip())
        return f"{BASE}/title-detail/{match.group(1).lower()}" if match else url

    @staticmethod
    def _title_id(url: str) -> str:
        match = _SERIES.match((url or '').strip())
        if not match:
            raise ValueError(f"Not a MangaBall manga link: {url}")
        return match.group(1).lower()

    def _get(self, path: str, **params) -> dict:
        response = self._session.get(f"{API}/{path}", params=params or None, timeout=30)
        response.raise_for_status()
        return response.json()

    def _detail(self, url: str) -> dict:
        return self._get(f"title/detail/{self._title_id(url)}").get('data') or {}

    # ------------------------------------------------------------- series
    def get_manga_name(self, url: str) -> str:
        try:
            return self._detail(url).get('name') or 'Unknown'
        except (requests.RequestException, ValueError) as e:
            logging.warning(f"MangaBall title lookup failed for {url}: {e}")
            return 'Unknown'

    def get_manga_metadata(self, url: str) -> MangaMetadata:
        data = self._detail(url)
        meta = MangaMetadata()
        meta.url = self.canonical_url(url)
        meta.site_type = 'mangaball'
        meta.title = data.get('name') or ''
        description = data.get('description') or ''
        if isinstance(description, list):
            description = '\n\n'.join(d for d in description if isinstance(d, str))
        meta.description = _plain_markdown(description)
        people = data.get('authors') or []
        meta.author = ', '.join(dict.fromkeys(a['name'] for a in people
                                              if a.get('name') and 'artist' not in (a.get('roles') or [])))
        meta.artist = ', '.join(dict.fromkeys(a['name'] for a in people
                                              if a.get('name') and 'artist' in (a.get('roles') or [])))
        meta.genres = [t['name'] for t in data.get('tags') or []
                       if t.get('name') and t.get('group') in ('genre', 'theme')]
        meta.alternative_names = [n for n in dict.fromkeys(data.get('alternateName') or []) if n and n != meta.title]
        status = (data.get('status') or '').lower()
        meta.status = status if status in ('ongoing', 'completed', 'hiatus', 'cancelled') else status or 'unknown'
        if data.get('date_published'):
            meta.release_date = str(data['date_published'])
        meta.cover_image_url = cover_url(data.get('image'))
        return meta

    def get_chapter_links(self, url: str, language_filter: Optional[str] = None) -> List[ChapterInfo]:
        """Every upload of every chapter in every language, oldest first. Within a chapter the group
        with the most chapters in that language comes first (fewest switches between groups)."""
        title_id = self._title_id(url)
        if language_filter:
            languages = [language_filter]
        else:
            try:
                languages = [l for l in self._detail(url).get('availableTranslatedLanguages') or [] if l]
            except (requests.RequestException, ValueError) as e:
                logging.warning(f"MangaBall language lookup failed for {url}: {e}")
                languages = []
        if languages:
            # One request per language, side by side: the full list takes the server ~30-45 s on
            # big series, a single language a few seconds.
            with ThreadPoolExecutor(max_workers=min(6, len(languages))) as pool:
                lists = list(pool.map(lambda lang: self._listing(title_id, lang), languages))
            uploads = [c for chapters in lists for c in chapters]
        else:
            uploads = self._listing(title_id)
        uploads = [c for c in uploads if c.get('id') and c.get('status', 'published') == 'published']
        uploads = list({c['id']: c for c in uploads}.values())

        counts: Dict[tuple, int] = {}
        for chapter in uploads:
            key = (chapter.get('lang') or 'en', chapter.get('group_name') or '')
            counts[key] = counts.get(key, 0) + 1

        def number(chapter) -> float:
            try:
                return float(chapter.get('number', chapter.get('chapter_number')) or 0)
            except (TypeError, ValueError):
                return 0.0

        uploads.sort(key=lambda c: (number(c), -counts[(c.get('lang') or 'en', c.get('group_name') or '')],
                                    c.get('created_at') or ''))
        result = []
        for chapter in uploads:
            info = ChapterInfo()
            info.chapter_number = format_number(number(chapter))
            info.title = chapter_name(chapter.get('name', ''))
            info.volume_number = format_number(chapter['volume']) if chapter.get('volume') else ''
            info.language = (chapter.get('lang') or 'en').lower()
            info.chapter_id = chapter['id']
            info.chapter_url = f"{BASE}/chapter-detail/{chapter['id']}?chapter={info.chapter_number}"
            info.scanlation_group = chapter.get('group_name') or (chapter.get('group') or {}).get('name') or ''
            info.release_date = (chapter.get('created_at') or '')[:10]
            result.append(info)
        return result

    def _listing(self, title_id: str, lang: str = '') -> List[dict]:
        body = {'title_id': title_id}
        if lang:
            body['lang'] = lang
        response = self._session.post(f"{API}/chapter/chapter-listing-by-title-id", json=body, timeout=90)
        response.raise_for_status()
        data = response.json()
        if data.get('status') != 'success':
            # Never return a partial list: the library drops chapters that are missing from it.
            raise RuntimeError(f"MangaBall returned an error: {data.get('message') or data.get('status')}")
        return data.get('data') or []

    # ------------------------------------------------------------- download
    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                         base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                         language: str = "en") -> str:
        """Download a chapter into '<base>/<manga>/Chapter N.cbz' ('Chapter N.es.cbz' for other
        languages, so they don't overwrite each other). Raises on failure."""
        match = _CHAPTER.search(chapter_url or '')
        if not match:
            raise ChapterUnavailable(f"Not a MangaBall chapter link: {chapter_url}")
        chapter_num = str(chapter_num).strip()
        try:
            data = self._get('chapter-detail', chapter_id=match.group(1)).get('data') or {}
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ChapterUnavailable("This chapter was removed from MangaBall. "
                                         "Use 'Check for new' to refresh the chapter list.") from e
            raise
        chapter = data.get('chapter') or {}
        if not chapter:
            raise ChapterUnavailable("This chapter was removed from MangaBall. "
                                     "Use 'Check for new' to refresh the chapter list.")
        urls = [p for p in chapter.get('pages') or [] if isinstance(p, str) and p.startswith('http')]
        if not urls:
            raise ChapterUnavailable("No pages found for this chapter on MangaBall.")

        lang = (chapter.get('lang') or language or 'en').lower()
        suffix = '' if lang == 'en' else f".{lang}"
        target_dir = self.get_safe_manga_path(manga_name, base_path)
        cbz_path = os.path.join(target_dir, f"Chapter {chapter_num}{suffix}.cbz")

        images: List[Optional[bytes]] = [None] * len(urls)
        done = 0
        if progress_callback:
            progress_callback(0, len(urls))
        with ThreadPoolExecutor(max_workers=PARALLEL_IMAGES) as pool:
            futures = {pool.submit(self._fetch_image, url): i for i, url in enumerate(urls)}
            for future in as_completed(futures):
                images[futures[future]] = future.result()    # raises -> the chapter fails and is retried
                done += 1
                if progress_callback:
                    progress_callback(done, len(urls))

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as cbz:    # images are already compressed
            for index, (url, content) in enumerate(zip(urls, images), start=1):
                ext = os.path.splitext(url.split('?')[0])[1].lower() or '.webp'
                cbz.writestr(f"{index:03d}{ext}", content)
        save_file(cbz_path, buffer.getvalue())
        return cbz_path

    def _fetch_image(self, url: str) -> bytes:
        last: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = self._session.get(url, timeout=60)
                response.raise_for_status()
                if not response.headers.get('content-type', '').startswith('image/'):
                    raise RuntimeError(f"Not an image: {url}")
                return response.content
            except (requests.RequestException, RuntimeError) as e:
                last = e
                time.sleep(1 + attempt)
        raise RuntimeError(f"Page failed to download: {last}")
