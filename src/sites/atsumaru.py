"""
Atsumaru downloader (https://atsu.moe).

The site is a web app on top of a public JSON API:
    /api/manga/page?id=<id>                 details (title, synopsis, poster, scanlators, ...)
    /api/manga/allChapters?mangaId=<id>     every chapter of every scanlation group
    /api/read/chapter?mangaId=&chapterId=   the pages of one chapter
    /api/read/novelChapter?mangaId=&chapterId=   the text of a light novel chapter
Images are served from cdn.atsu.moe/static/<path>. Light novels live under /novel/<id>
and are saved as EPUB (or another format from the settings).

A chapter is often uploaded by several groups; every upload is listed, best first
(the site's preferred group, then the users' votes), and the library picks one.
"""

import io
import logging
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter

from .base import ChapterInfo, ChapterUnavailable, ComicSiteBase, MangaMetadata, save_file

BASE = "https://atsu.moe"
CDN = "https://cdn.atsu.moe"
_SERIES = re.compile(r'^https?://(?:www\.)?atsu\.moe/(manga|novel)/([A-Za-z0-9_\-]+)/?(?:[?#].*)?$', re.I)
_CHAPTER = re.compile(r'/(?:read|novel)/([A-Za-z0-9_\-]+)/([A-Za-z0-9_\-]+)')
PARALLEL_IMAGES = 6


def static_url(path: str) -> str:
    """'posters/x.jpg', '/static/posters/x.jpg' -> 'https://cdn.atsu.moe/static/posters/x.jpg'"""
    if not path or path.startswith('http'):
        return path or ''
    path = path.lstrip('/')
    if path.startswith('static/'):
        path = path[len('static/'):]
    return f"{CDN}/static/{path}"


def format_number(value) -> str:
    """19.0 -> '19', 10.5 -> '10.5'"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def chapter_name(title: str) -> str:
    """'Chapter 180 Side Story 1' -> 'Side Story 1', 'Chapter 19' -> '', 'Chapter 1 - 1' -> ''"""
    match = re.match(r'^\s*(?:chapter|ch\.?|episode|ep\.?)\s*([\d.]+)\s*[:\-–—.]?\s*', title or '', flags=re.I)
    if not match:
        return (title or '').strip()
    rest = title[match.end():].strip()
    return '' if rest == match.group(1) else rest


class AtsumaruDownloader(ComicSiteBase):
    """Atsumaru (atsu.moe) downloader."""

    def __init__(self):
        super().__init__("Atsumaru", BASE)
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/124.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.7',
            'Referer': BASE + '/',
        })
        self._session.mount('https://', HTTPAdapter(pool_connections=4, pool_maxsize=PARALLEL_IMAGES * 2))

    # ------------------------------------------------------------- urls
    @classmethod
    def validate_url(cls, url: str) -> bool:
        return bool(_SERIES.match((url or '').strip()))

    def canonical_url(self, url: str) -> str:
        match = _SERIES.match((url or '').strip())
        return f"{BASE}/{match.group(1).lower()}/{match.group(2)}" if match else url

    @staticmethod
    def _manga_id(url: str) -> str:
        match = _SERIES.match((url or '').strip())
        if not match:
            raise ValueError(f"Not an Atsumaru manga link: {url}")
        return match.group(2)

    def _api(self, path: str, **params) -> dict:
        response = self._session.get(f"{BASE}/api/{path}", params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _page(self, url: str) -> dict:
        return self._api('manga/page', id=self._manga_id(url)).get('mangaPage') or {}

    # ------------------------------------------------------------- series
    def get_manga_name(self, url: str) -> str:
        try:
            return self._page(url).get('title') or 'Unknown'
        except (requests.RequestException, ValueError) as e:
            logging.warning(f"Atsumaru title lookup failed for {url}: {e}")
            return 'Unknown'

    def get_manga_metadata(self, url: str) -> MangaMetadata:
        page = self._page(url)
        meta = MangaMetadata()
        meta.url = self.canonical_url(url)
        meta.site_type = 'atsumaru'
        meta.title = page.get('englishTitle') or page.get('title') or ''
        meta.description = _plain_markdown(page.get('synopsis') or '')
        people = page.get('authors') or []
        meta.author = ', '.join(dict.fromkeys(a['name'] for a in people if a.get('type') != 'Artist' and a.get('name')))
        meta.artist = ', '.join(dict.fromkeys(a['name'] for a in people if a.get('type') == 'Artist' and a.get('name')))
        meta.genres = [g['name'] for g in page.get('genres') or [] if g.get('name')]
        meta.alternative_names = [n for n in page.get('otherNames') or [] if n and n != meta.title]
        status = (page.get('status') or '').lower()
        meta.status = 'completed' if 'complete' in status else status or 'unknown'
        if page.get('released'):
            meta.release_date = str(datetime.fromtimestamp(page['released'] / 1000, timezone.utc).year)
        poster = page.get('poster') or {}
        meta.cover_image_url = static_url(poster.get('image') or poster.get('id') or '')
        return meta

    def get_chapter_links(self, url: str, language_filter: Optional[str] = None) -> List[ChapterInfo]:
        """Every upload of every chapter, oldest chapter first and the best group first within a
        chapter. Raises on errors."""
        manga_id = self._manga_id(url)
        kind = 'novel' if '/novel/' in url else 'read'
        chapters = self._api('manga/allChapters', mangaId=manga_id).get('chapters') or []
        if not chapters:
            return []
        rank, names = self._group_rank(manga_id, chapters)
        chapters.sort(key=lambda ch: (float(ch.get('number') or 0), rank(ch)))
        result = []
        for chapter in chapters:
            info = ChapterInfo()
            info.chapter_number = format_number(chapter.get('number'))
            info.title = chapter_name(chapter.get('title', ''))
            info.chapter_url = f"{BASE}/{kind}/{manga_id}/{chapter['id']}"
            info.chapter_id = chapter['id']
            info.language = 'en'
            info.scanlation_group = names.get(chapter.get('scanlationMangaId') or '', '')
            result.append(info)
        return result

    def _group_rank(self, manga_id: str, chapters: List[dict]) -> Tuple[Callable[[dict], tuple], Dict[str, str]]:
        """Sort key for uploads - the site's preferred group, then the best voted, then the one with the
        most chapters (so a series isn't mixed across groups more than needed) - and group id -> name."""
        counts: Dict[str, int] = {}
        for chapter in chapters:
            group = chapter.get('scanlationMangaId') or ''
            counts[group] = counts.get(group, 0) + 1
        scores: Dict[str, float] = {}
        names: Dict[str, str] = {}
        preferred = ''
        try:
            page = self._api('manga/page', id=manga_id).get('mangaPage') or {}
            scanlators = page.get('scanlators') or []
            scores = {g.get('id'): g.get('score') or 0 for g in scanlators}
            names = {g.get('id'): (g.get('name') or '').strip() for g in scanlators}
            preferred = page.get('sourcePreference') or ''
        except requests.RequestException as e:
            logging.warning(f"Atsumaru scanlator lookup failed: {e}")

        def key(chapter: dict) -> tuple:
            group = chapter.get('scanlationMangaId') or ''
            return (group != preferred, -scores.get(group, 0), -counts.get(group, 0), group)
        return key, names

    # ------------------------------------------------------------- download
    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                         base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                         language: str = "en") -> str:
        """Download a chapter into '<base>/<manga>/Chapter N.cbz'. Raises on failure."""
        match = _CHAPTER.search(chapter_url or '')
        if not match:
            raise ChapterUnavailable(f"Not an Atsumaru chapter link: {chapter_url}")
        chapter_num = str(chapter_num).strip()
        target_dir = self.get_safe_manga_path(manga_name, base_path)
        cbz_path = os.path.join(target_dir, f"Chapter {chapter_num}.cbz")

        try:
            data = self._api('read/chapter', mangaId=match.group(1), chapterId=match.group(2))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ChapterUnavailable("This chapter was removed from Atsumaru. "
                                         "Use 'Check for new' to refresh the chapter list.") from e
            raise
        pages = sorted((data.get('readChapter') or {}).get('pages') or [], key=lambda p: p.get('number', 0))
        urls = [static_url(p.get('image', '')) for p in pages if p.get('image')]
        if not urls:
            raise ChapterUnavailable("No pages found for this chapter on Atsumaru.")

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

    def download_novel_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                               base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                               fmt: str = 'epub', series: str = '', title: str = '', author: str = '',
                               cover_path: str = '', language: str = 'en') -> str:
        """Save a light novel chapter as '<base>/<manga>/Chapter N.<ext>'. Raises on failure."""
        from ..core.novel_export import NovelChapter, extension, write_chapter
        match = _CHAPTER.search(chapter_url or '')
        if not match:
            raise ChapterUnavailable(f"Not an Atsumaru chapter link: {chapter_url}")
        chapter_num = str(chapter_num).strip()
        target_dir = self.get_safe_manga_path(manga_name, base_path)
        if progress_callback:
            progress_callback(0, 2)
        try:
            data = self._api('read/novelChapter', mangaId=match.group(1), chapterId=match.group(2))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ChapterUnavailable("This chapter was removed from Atsumaru. "
                                         "Use 'Check for new' to refresh the chapter list.") from e
            raise
        chapter = data.get('readNovelChapter') or {}
        paragraphs = [p.strip() for p in chapter.get('paragraphs') or [] if p and p.strip()]
        if not paragraphs:
            raise ChapterUnavailable("This chapter has no text on Atsumaru.")
        if progress_callback:
            progress_callback(1, 2)
        title = title or chapter_name(chapter.get('title', ''))
        path = os.path.join(target_dir, f"Chapter {chapter_num}{extension(fmt)}")
        write_chapter(path, fmt, NovelChapter(series=series or manga_name, number=chapter_num, title=title,
                                              paragraphs=paragraphs, author=author, language=language or 'en',
                                              cover_path=cover_path))
        if progress_callback:
            progress_callback(2, 2)
        return path

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


def _plain_markdown(text: str) -> str:
    """The synopsis is Markdown: drop link targets and emphasis markers, keep the text."""
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'(\*\*|__|\*|_)(\S.*?\S|\S)\1', r'\2', text)
    text = text.replace('\xad', '')
    return re.sub(r'\n{3,}', '\n\n', text).strip()
