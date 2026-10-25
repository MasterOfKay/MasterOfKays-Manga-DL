"""
Cyrisia downloader (https://cyrisia.com) - everything the site has.

The library holds three kinds of series, all under /series/<name>: web novels (text
chapters), light novels (the publishers' EPUB volumes) and comics (CBZ chapters,
saved as this app's own CBZ of the page images).

    /api/account/catalog/series/<name>   the kind ('webnovel' | 'ln' | 'comic'),
                                         metadata and every file of the series
    /read/<name>/<file>                  the reader page of one file
    /bibi-bookshelf/<name>/<file>        a light novel volume (EPUB)
    /api/comic/pages?series=&v=          the page images of a comic chapter
    /api/cover?series=&v=                a series cover

The file endpoints answer 'auth_required' unless the request comes from the file's
own reader page, so they are asked for with that page as the Referer - no account
is needed. A comic series' link carries '?kind=comic' (base.COMIC_MARKER) so the
app knows from the link alone that it is a comic and not a novel.
"""

import html
import io
import logging
import os
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

import requests

from .base import COMIC_MARKER, ChapterUnavailable, MangaMetadata, save_file
from .novel_base import NovelSite, format_number, html_paragraphs, plain_status

BASE = "https://cyrisia.com"
PARALLEL_IMAGES = 6
CATALOG_TTL = 300                # seconds a series' file list is reused
_INDEX = re.compile(r'^(\d+)')                                            # '00001 - Chapter 1.txt'
_CHAPTER = re.compile(r'\b(?:chapter|ch|episode|ep)\.?\s*(\d+(?:\.\d+)?)', re.I)
_VOLUME = re.compile(r'\b(?:volume|vol|v)\.?\s*(\d+(?:\.\d+)?)', re.I)       # 'Volume 03', 'Vol 3', 'v03'
_NUMBER = re.compile(r'(\d+(?:\.\d+)?)')
_TAGS = re.compile(r'\s*[\[{(][^\])}]*[\])}]')                            # '[Yen Press]', '{v2}'


class CyrisiaDownloader(NovelSite):
    key, name, base = 'cyrisia', 'Cyrisia', BASE
    pattern = re.compile(r'^https?://(?:www\.)?cyrisia\.com/series/([^/?#]+)/?(?:[?#].*)?$', re.I)
    ad_words = ('cyrisia',)

    def __init__(self):
        super().__init__()
        self._catalog: Dict[str, Tuple[float, dict]] = {}      # series name -> (fetched at, series)
        self._catalog_lock = threading.Lock()

    # ------------------------------------------------------------- links
    def series_url(self, name: str, kind: str = '') -> str:
        url = f"{BASE}/series/{quote(name, safe='')}"
        return f"{url}?{COMIC_MARKER}" if kind == 'comic' else url

    def canonical_url(self, url: str) -> str:
        if not self.pattern.match((url or '').strip()):
            return url
        name = self._name(url)
        kind = 'comic' if COMIC_MARKER in url else self._kind(name)
        return self.series_url(name, kind)

    def _name(self, url: str) -> str:
        return unquote(self.pattern.match(url.strip()).group(1))

    def _read_url(self, name: str, file: str) -> str:
        return f"{BASE}/read/{quote(name, safe='')}/{quote(file, safe='')}"

    # ------------------------------------------------------------- catalog
    def _series(self, name: str) -> dict:
        """{'name', 'content_type', 'metadata', 'volumes': [{'filename', ...}]} of a series."""
        with self._catalog_lock:
            hit = self._catalog.get(name)
            if hit and time.monotonic() - hit[0] < CATALOG_TTL:
                return hit[1]
        data = self._json(f"{BASE}/api/account/catalog/series/{quote(name, safe='')}",
                          headers={'Referer': self.series_url(name)})
        series = data.get('series') or {}
        if not series.get('name'):
            raise ValueError(f"Cyrisia doesn't have a series called '{name}'.")
        with self._catalog_lock:
            self._catalog[name] = (time.monotonic(), series)
        return series

    def _kind(self, name: str) -> str:
        """'webnovel' | 'ln' | 'comic', '' when the site can't be reached (the link then
        counts as a novel - a download still goes by the file's own type)."""
        try:
            return self._series(name).get('content_type') or ''
        except (requests.RequestException, RuntimeError, ValueError) as e:
            logging.warning(f"Cyrisia kind lookup failed for {name}: {e}")
            return ''

    # ------------------------------------------------------------- series
    def _metadata(self, url: str) -> MangaMetadata:
        name = self._name(url)
        series = self._series(name)
        data = series.get('metadata') or {}
        files = _file_names(series)
        meta = MangaMetadata()
        meta.title = data.get('title_en') or series.get('name') or name
        meta.description = data.get('synopsis') or ''
        meta.genres = [g for g in (data.get('genres') or data.get('tags') or []) if isinstance(g, str)]
        meta.author = data.get('author') or ''
        meta.status = plain_status(data.get('publication_status'))
        # The site has no cover of its own - it renders one from a file of the series.
        meta.cover_image_url = data.get('cover_url') or (
            f"{BASE}/api/cover?series={quote(name, safe='')}" +
            (f"&v={quote(files[0], safe='')}" if files else ''))
        return meta

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        name = self._name(url)
        series = self._series(name)
        kind = series.get('content_type') or ''
        files = _file_names(series)
        rows = [(float(number), -_edition(file), number, self._label(name, file, kind), self._read_url(name, file))
                for file, number in zip(files, _numbers(files, kind))]
        if not rows:
            raise ValueError(f"This Cyrisia series has no files to download ({kind or 'unknown kind'}).")
        # The site keeps its re-uploads of a volume next to the first one ('{v2}'); sorting the
        # newest edition first makes it the one the library takes for that volume.
        return [(number, label, url) for _, _, number, label, url in sorted(rows)]

    def _label(self, name: str, file: str, kind: str) -> str:
        """'00001 - Chapter 1: Nightmare Begins.txt' -> 'Chapter 1: Nightmare Begins',
        'Mushoku Tensei - Volume 01 [Seven Seas][Kobo].epub' -> 'Volume 01'."""
        label = re.sub(r'^\d+\s*-\s*', '', os.path.splitext(file)[0])
        if kind == 'ln':
            label = _TAGS.sub('', label).strip()
            # The volumes are named after the series - sometimes without the '(Light Novel)'
            # kind of suffix the series itself carries.
            for prefix in (name, re.sub(r'\s*\([^)]*\)\s*$', '', name)):
                if prefix and label.lower().startswith(prefix.lower()):
                    label = label[len(prefix):].lstrip(' -–—')
                    break
            label = re.sub(r'^v\.?\s*0*(\d+)$', r'Volume \1', label, flags=re.I)
        return html.unescape(label).strip()

    # ------------------------------------------------------------- download
    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                         base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                         language: str = "en") -> str:
        if _file_of(chapter_url).lower().endswith('.txt'):
            return self.download_novel_chapter(chapter_url, chapter_num, manga_name, base_path, progress_callback)
        return self._download_file(chapter_url, chapter_num, manga_name, base_path, progress_callback)

    def download_novel_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                               base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                               fmt: str = 'epub', series: str = '', title: str = '', author: str = '',
                               cover_path: str = '', language: str = 'en') -> str:
        """A text chapter in the format from the settings; a light novel volume or a comic
        chapter as the file the site has."""
        if not _file_of(chapter_url).lower().endswith('.txt'):
            return self._download_file(chapter_url, chapter_num, manga_name, base_path, progress_callback)
        return super().download_novel_chapter(chapter_url, chapter_num, manga_name, base_path, progress_callback,
                                              fmt=fmt, series=series, title=title, author=author,
                                              cover_path=cover_path, language=language)

    def _chapter_text(self, chapter_url: str):
        soup = self._soup(chapter_url)
        title = soup.select_one('.ch-title, h1')
        return html_paragraphs(soup.select_one('article.ch-text')), title.get_text(' ', strip=True) if title else ''

    def _download_file(self, chapter_url: str, chapter_num: str, manga_name: str, base_path: Optional[str],
                       progress_callback: Optional[Callable]) -> str:
        """A comic chapter ('<base>/<manga>/Chapter N.cbz') or a light novel volume
        ('<base>/<novel>/Chapter N.epub'). Raises on failure."""
        name, file = _series_of(chapter_url), _file_of(chapter_url)
        suffix = os.path.splitext(file)[1].lower()
        if not name or suffix not in ('.cbz', '.epub'):
            raise ChapterUnavailable(f"Not a Cyrisia chapter link: {chapter_url}")
        path = os.path.join(self.get_safe_manga_path(manga_name, base_path),
                            f"Chapter {str(chapter_num).strip()}{suffix}")
        if suffix == '.epub':
            return self._download_volume(name, file, chapter_url, path, progress_callback)
        return self._download_comic(name, file, chapter_url, path, progress_callback)

    def _download_volume(self, name: str, file: str, chapter_url: str, path: str,
                         progress_callback: Optional[Callable]) -> str:
        """The site's own EPUB of a light novel volume, byte for byte - it is never rebuilt
        in the format from the settings, only named the way the app names a chapter."""
        response = self._file_request(f"{BASE}/bibi-bookshelf/{quote(name, safe='')}/{quote(file, safe='')}",
                                      chapter_url, stream=True, timeout=180)
        total = int(response.headers.get('Content-Length') or 0)
        buffer, done = io.BytesIO(), 0
        if progress_callback:
            progress_callback(0, total or 1)
        for block in response.iter_content(chunk_size=256 * 1024):
            if not block:
                continue
            buffer.write(block)
            done += len(block)
            if progress_callback and total:
                progress_callback(min(done, total), total)
        data = buffer.getvalue()
        if not data.startswith(b'PK'):
            raise ChapterUnavailable(f"Cyrisia didn't send the EPUB of '{file}'.")
        save_file(path, data)
        if progress_callback:
            progress_callback(total or 1, total or 1)
        return path

    def _download_comic(self, name: str, file: str, chapter_url: str, path: str,
                        progress_callback: Optional[Callable]) -> str:
        """The page images of a .cbz chapter, zipped again as this app's CBZ."""
        data = self._file_request(f"{BASE}/api/comic/pages", chapter_url,
                                  params={'series': name, 'v': file}).json()
        urls = [u for u in (data.get('urls') or []) if u]
        if not data.get('ok') or not urls:
            raise ChapterUnavailable(f"Cyrisia has no pages for '{file}' right now.")

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
                suffix = os.path.splitext(url.split('?')[0])[1].lower() or '.jpg'
                cbz.writestr(f"{index:03d}{suffix}", content)
        save_file(path, buffer.getvalue())
        return path

    def _file_request(self, url: str, chapter_url: str, **kwargs) -> requests.Response:
        """A file endpoint, asked for from the file's own reader page (its hotlink check)."""
        try:
            return self._get(url, headers={'Referer': chapter_url}, **kwargs)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in (401, 403):
                raise ChapterUnavailable("Cyrisia turned this download down. Open the chapter in a browser "
                                         "once and try again.") from e
            if status in (404, 410):
                raise ChapterUnavailable("This chapter was removed from Cyrisia. "
                                         "Use 'Check for new' to refresh the chapter list.") from e
            raise

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


# ------------------------------------------------------------------ helpers
def _file_names(series: dict) -> List[str]:
    return [v['filename'] for v in series.get('volumes') or []
            if isinstance(v, dict) and v.get('filename')]


def _series_of(chapter_url: str) -> str:
    match = re.search(r'/read/([^/]+)/[^/?#]+$', chapter_url or '')
    return unquote(match.group(1)) if match else ''


def _file_of(chapter_url: str) -> str:
    match = re.search(r'/read/[^/]+/([^/?#]+)$', chapter_url or '')
    return unquote(match.group(1)) if match else ''


def _edition(file: str) -> int:
    """2 for a '{v2}' re-upload of a volume, 1 for a file the site uploaded once."""
    match = re.search(r'\{v(\d+)\}', file or '', re.I)
    return int(match.group(1)) if match else 1


def _numbers(files: List[str], kind: str) -> List[str]:
    """The chapter (or volume) number of every file of a series, in the site's order.

    '00042 - Chapter 42.txt' and 'Chapter 042.cbz' -> '42', '... - Volume 03 [Yen
    Press].epub' -> '3'. A light novel file without a volume number of its own (a side
    story, an omnibus, 'Complete') goes behind the volume before it as '3.1', so it can
    never take a numbered volume's place; a series whose files are all unnumbered is
    simply counted off.
    """
    numbers = [_number(file, kind) for file in files]
    if not any(numbers):
        return [str(index) for index, _ in enumerate(files, start=1)]
    result, last, extra = [], '0', 0
    for number in numbers:
        if number:
            last, extra = number, 0
        else:
            extra += 1
            number = f"{last}.{extra}"
        result.append(number)
    return result


def _number(file: str, kind: str) -> str:
    """The number a file name carries, '' when it has none."""
    stem = os.path.splitext(file)[0]
    if kind == 'ln':
        match = _VOLUME.search(stem)
    else:
        match = _INDEX.match(stem) or _CHAPTER.search(stem) or _NUMBER.search(stem)
    return format_number(match.group(1)) if match else ''
