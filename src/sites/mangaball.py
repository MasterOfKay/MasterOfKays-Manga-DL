"""
MangaBall downloader (https://mangaball.com).

The site is a web app on top of a public JSON API (api.mangaball.com/api/v1):
    GET  /title/detail/<id>                     details (name, description, cover, authors, tags, ...)
    POST /chapter/chapter-listing-by-title-id   every upload of every chapter, in every language
    GET  /chapter-detail?chapter_id=<id>        the page images of one chapter
Images are only served with the site as referer. Pages nobody read recently come
slowly from the image server (~30 KB/s per connection, ~0.4 MB/s in all), so one
set of connections is shared by the chapter being downloaded and the next ones of
the queue: the current chapter always goes first, and spare connections load ahead.

Chapters come in many languages and from several groups per language; the library
keeps all of them (language picker + release group filter in the chapter panel).
"""

import io
import logging
import os
import re
import threading
import time
import zipfile
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
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
# Each connection is slow on its own; about 16 at once use what the server gives
# (a 15 page chapter: ~33 s with 6, ~18 s with 16). More only split the same speed.
PARALLEL_IMAGES = 16
AHEAD_CHAPTERS = 4        # read-ahead chapters kept in memory until they are downloaded
STALL_SECONDS = 180       # no bytes at all for this long: fail the chapter (it is retried)
# Pages come in parts: a broken connection resumes where it stopped, and the parts of a
# big page (some are 10 MB+) load side by side instead of one slow stream for minutes.
PART_BYTES = 512 * 1024
PARALLEL_PARTS = 8


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
        self._session.mount('https://', HTTPAdapter(pool_connections=4,
                                                    pool_maxsize=PARALLEL_IMAGES + PARALLEL_PARTS + 4))
        self._pages = _PageQueue(self._fetch_image, PARALLEL_IMAGES)
        self._parts = ThreadPoolExecutor(max_workers=PARALLEL_PARTS, thread_name_prefix='mangaball-parts')
        self._received: Dict[str, int] = {}       # page url -> bytes so far (progress while pages load)
        self._sizes: Dict[str, int] = {}          # page url -> full size, once the server told it
        self._count_lock = threading.Lock()

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
        chapter_id = match.group(1).lower()
        chapter = self._pages.chapter_data(chapter_id)       # loaded ahead, else None
        if chapter is None:
            chapter = self._chapter(chapter_id)
        urls = self._page_urls(chapter)
        if not urls:
            raise ChapterUnavailable("No pages found for this chapter on MangaBall.")

        lang = (chapter.get('lang') or language or 'en').lower()
        suffix = '' if lang == 'en' else f".{lang}"
        target_dir = self.get_safe_manga_path(manga_name, base_path)
        cbz_path = os.path.join(target_dir, f"Chapter {chapter_num}{suffix}.cbz")

        futures = self._pages.take(chapter_id, urls)
        try:
            images = self._wait_pages(urls, futures, progress_callback)
        finally:
            self._pages.release(chapter_id)
            for url in urls:
                self._received.pop(url, None)
                self._sizes.pop(url, None)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as cbz:    # images are already compressed
            for index, (url, content) in enumerate(zip(urls, images), start=1):
                ext = os.path.splitext(url.split('?')[0])[1].lower() or '.webp'
                cbz.writestr(f"{index:03d}{ext}", content)
        save_file(cbz_path, buffer.getvalue())
        return cbz_path

    def _chapter(self, chapter_id: str) -> dict:
        try:
            data = self._get('chapter-detail', chapter_id=chapter_id).get('data') or {}
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ChapterUnavailable("This chapter was removed from MangaBall. "
                                         "Use 'Check for new' to refresh the chapter list.") from e
            raise
        chapter = data.get('chapter') or {}
        if not chapter:
            raise ChapterUnavailable("This chapter was removed from MangaBall. "
                                     "Use 'Check for new' to refresh the chapter list.")
        return chapter

    @staticmethod
    def _page_urls(chapter: dict) -> List[str]:
        return [p for p in chapter.get('pages') or [] if isinstance(p, str) and p.startswith('http')]

    def _wait_pages(self, urls: List[str], futures: Dict[str, Future],
                    progress_callback: Optional[Callable]) -> List[bytes]:
        """Wait for the pages, reporting progress by bytes so it moves while they load (they
        all come in together near the end). Sizes the server didn't tell yet are guessed."""
        pending = set(futures.values())
        last_got, last_change = -1, time.monotonic()
        while pending:
            _, pending = wait(pending, timeout=0.5)
            for future in futures.values():
                if future.done() and (future.cancelled() or future.exception()):
                    return [futures[url].result() for url in urls]     # raises: the chapter fails at once
            sizes =[len(f.result()) for f in futures.values() if f.done() and not f.cancelled() and not f.exception()]
            got = sum(sizes) + sum(self._received.get(u, 0) for u, f in futures.items() if not f.done())
            if got != last_got:
                last_got, last_change = got, time.monotonic()
            elif time.monotonic() - last_change > STALL_SECONDS:
                raise RuntimeError(f"MangaBall sent nothing for {STALL_SECONDS} s")
            if progress_callback:
                known = [self._sizes[u] for u in urls if u in self._sizes]
                guess = sum(known) / len(known) if known else 600_000
                total = sum(self._sizes.get(u, guess) for u in urls)
                # per mille, never "done" before the last page is in
                progress_callback(min(int(got * 1000 / max(total, 1)), 990) if pending else 1000, 1000)
        return [futures[url].result() for url in urls]     # raises -> the chapter fails and is retried

    # ------------------------------------------------------------- read-ahead
    def prefetch(self, chapter_url: str) -> None:
        """Queue a coming chapter of the download queue: its pages load on connections the
        current chapter doesn't need, so they are (partly) here when its turn comes."""
        match = _CHAPTER.search(chapter_url or '')
        if match:
            self._pages.ahead(match.group(1).lower(), self._chapter, self._page_urls)

    def _fetch_image(self, url: str) -> bytes:
        """One page: the first part tells the size, the rest load in parallel."""
        with self._count_lock:
            self._received[url] = 0
        first, total = self._fetch_part(url, 0, PART_BYTES - 1)
        if total is None or len(first) >= total:          # small page, or no partial requests here
            return first
        self._sizes[url] = total
        parts = [self._parts.submit(self._fetch_part, url, start, min(start + PART_BYTES, total) - 1)
                 for start in range(len(first), total, PART_BYTES)]
        data = first + b''.join(part.result()[0] for part in parts)     # raises -> the page failed
        if len(data) != total:
            raise RuntimeError(f"Page is incomplete ({len(data)} of {total} bytes)")
        return data

    def _fetch_part(self, url: str, start: int, end: int):
        """Bytes start..end of a page, resuming after a broken connection. Returns (bytes,
        full size) - the size is None when the server sent the whole file instead."""
        data = bytearray()
        last: Optional[Exception] = None
        for attempt in range(4):
            try:
                headers = {'Range': f"bytes={start + len(data)}-{end}", 'Accept-Encoding': 'identity'}
                with self._session.get(url, headers=headers, timeout=60, stream=True) as response:
                    response.raise_for_status()
                    if not response.headers.get('content-type', '').startswith('image/'):
                        raise RuntimeError(f"Not an image: {url}")
                    whole = response.status_code != 206
                    if whole:                                 # range ignored: take the full file
                        with self._count_lock:
                            self._received[url] = self._received.get(url, 0) - len(data)
                        data = bytearray()
                    for block in response.iter_content(32 * 1024):
                        data += block
                        with self._count_lock:
                            self._received[url] = self._received.get(url, 0) + len(block)
                    if whole:
                        return bytes(data), None
                    size = response.headers.get('Content-Range', '').rpartition('/')[2]
                    if start + len(data) < end + 1 and (not size.isdigit() or start + len(data) < int(size)):
                        raise RuntimeError("Connection ended early")
                    return bytes(data), int(size) if size.isdigit() else None
            except (requests.RequestException, RuntimeError) as e:
                if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 416:
                    raise RuntimeError(f"Page failed to download: {e}") from e
                logging.warning(f"MangaBall page part failed ({url.rsplit('/', 1)[-1]} from {start + len(data)}, "
                                f"attempt {attempt + 1}): {e}")
                last = e
                time.sleep(1 + attempt)
        raise RuntimeError(f"Page failed to download: {last}")

class _PageQueue:
    """A fixed set of download threads shared by the chapter being downloaded and the
    read-ahead of the next ones. Workers always take a page of the current chapter first,
    then the read-ahead chapters in the order they were queued."""

    def __init__(self, fetch: Callable[[str], bytes], workers: int):
        self._fetch = fetch
        self._cond = threading.Condition()
        self._current = ''
        # chapter id -> {'data': chapter dict or None, 'futures': {url: Future}, 'todo': deque of urls}
        self._chapters: 'OrderedDict[str, dict]' = OrderedDict()
        for i in range(workers):
            threading.Thread(target=self._work, name=f'mangaball-pages-{i}', daemon=True).start()

    def ahead(self, chapter_id: str, load: Callable[[str], dict], page_urls: Callable[[dict], List[str]]) -> None:
        with self._cond:
            if chapter_id in self._chapters or chapter_id == self._current:
                return
            self._chapters[chapter_id] = {'data': None, 'futures': {}, 'todo': deque()}
            ahead = [c for c in self._chapters if c != self._current]
            for old in ahead[:max(0, len(ahead) - AHEAD_CHAPTERS)]:   # never downloaded (cancelled, ...)
                self._drop(old)

        def resolve():
            try:
                data = load(chapter_id)
            except Exception as e:
                logging.debug(f"MangaBall read-ahead of {chapter_id} failed: {e}")
                return
            with self._cond:
                entry = self._chapters.get(chapter_id)
                if entry is None or entry['data'] is not None:
                    return
                entry['data'] = data
                for url in page_urls(data):
                    # Its download may have started meanwhile and queued the pages itself.
                    if url not in entry['futures']:
                        entry['futures'][url] = Future()
                        entry['todo'].append(url)
                self._cond.notify_all()
        threading.Thread(target=resolve, name='mangaball-ahead', daemon=True).start()

    def chapter_data(self, chapter_id: str) -> Optional[dict]:
        with self._cond:
            entry = self._chapters.get(chapter_id)
            return entry['data'] if entry else None

    def take(self, chapter_id: str, urls: List[str]) -> Dict[str, Future]:
        """Make this the current chapter: its pages go first. Returns a future per page
        (finished ones from the read-ahead, the others queued)."""
        with self._cond:
            if self._current and self._current != chapter_id:
                # The previous chapter is done (or failed): forget whatever of it is left.
                self._drop(self._current)
            entry = self._chapters.pop(chapter_id, None) or {'data': None, 'futures': {}, 'todo': deque()}
            futures = entry['futures']
            todo = deque(u for u in entry['todo'] if u in urls)
            for url in urls:
                if url not in futures:
                    futures[url] = Future()
                    todo.append(url)
            entry.update(futures=futures, todo=todo)
            self._chapters[chapter_id] = entry
            self._chapters.move_to_end(chapter_id, last=False)
            self._current = chapter_id
            self._cond.notify_all()
            return {url: futures[url] for url in urls}

    def release(self, chapter_id: str) -> None:
        """The chapter is saved (or failed): free its pages, stop what is left of it."""
        with self._cond:
            self._drop(chapter_id)

    def _drop(self, chapter_id: str) -> None:
        entry = self._chapters.pop(chapter_id, None)
        if entry:
            for url in entry['todo']:
                entry['futures'][url].cancel()
        if chapter_id == self._current:
            self._current = ''

    def _next(self):
        for entry in self._chapters.values():          # current chapter first, then queue order
            while entry['todo']:
                url = entry['todo'].popleft()
                future = entry['futures'][url]
                if future.set_running_or_notify_cancel():
                    return url, future
        return None

    def _work(self) -> None:
        while True:
            with self._cond:
                task = self._next()
                while task is None:
                    self._cond.wait()
                    task = self._next()
            url, future = task
            try:
                future.set_result(self._fetch(url))
            except Exception as e:
                future.set_exception(e)
