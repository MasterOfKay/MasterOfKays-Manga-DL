"""
Shared base for web novel sites (text chapters only).

A novel site lists chapters like a manga site does; a chapter is a list of text
paragraphs that is saved in the novel format from the settings (EPUB by default,
see core.novel_export). Subclasses only say how to read the series page, the
chapter list and one chapter's text.

Chapter numbers are the site's own chapter index (its links count 1, 2, 3, ...),
which stays stable when new chapters are added - the "Chapter 123" in a chapter's
title often differs from it after side stories or merged chapters.
"""

import html
import json
import logging
import os
import re
import threading
import time
from typing import Callable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from .atsumaru import format_number  # noqa: F401  (re-exported for the novel sites)
from .base import ChapterUnavailable, ComicSiteBase, MangaMetadata

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
_HEADING = re.compile(r'^\s*(?:chapter|ch\.?|episode|ep\.?)\s*#?\d+', re.I)
_SCENE_BREAK = re.compile(r'^[\s*~=\-_#•·.]{3,}$')


class NovelSite(ComicSiteBase):
    """A site with text chapters. Subclasses set the class attributes and implement
    _metadata(), _chapters() and _chapter_text()."""

    key = ''                         # site type stored in the library
    name = ''
    base = ''
    pattern: re.Pattern = re.compile(r'^$')
    min_interval = 0.35              # seconds between requests - these sites are small, stay polite
    ad_words: Tuple[str, ...] = ()   # lines with these (lower case) are the site's own notices, not story
    send_referer = True

    def __init__(self):
        super().__init__(self.name, self.base)
        self._session = requests.Session()
        self._session.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.7'})
        if self.send_referer:
            self._session.headers['Referer'] = self.base + '/'
        self._session.mount('https://', HTTPAdapter(pool_connections=4, pool_maxsize=8))
        self._throttle = threading.Lock()
        self._last = 0.0

    # ------------------------------------------------------------- requests
    @classmethod
    def validate_url(cls, url: str) -> bool:
        return bool(cls.pattern.match((url or '').strip()))

    def canonical_url(self, url: str) -> str:
        return (url or '').strip().split('#')[0]

    def _get(self, url: str, **kwargs) -> requests.Response:
        with self._throttle:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        response = self._session.request(kwargs.pop('method', 'GET'), url, timeout=kwargs.pop('timeout', 30),
                                         **kwargs)
        if response.status_code in (403, 429, 503) and 'just a moment' in response.text[:3000].lower():
            raise RuntimeError(f"{self.name} asks for a browser check right now - try again later.")
        response.raise_for_status()
        response.encoding = 'utf-8'
        return response

    def _soup(self, url: str, **kwargs) -> BeautifulSoup:
        return BeautifulSoup(self._get(url, **kwargs).text, 'html.parser')

    def _json(self, url: str, **kwargs):
        return self._get(url, **kwargs).json()

    def _next_data(self, url: str, **kwargs) -> dict:
        """pageProps of a Next.js page."""
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', self._get(url, **kwargs).text, re.S)
        if not match:
            raise RuntimeError(f"Unexpected page from {self.name}: {url}")
        return json.loads(match.group(1)).get('props', {}).get('pageProps', {})

    # ------------------------------------------------------------- to implement
    def _metadata(self, url: str) -> MangaMetadata:
        raise NotImplementedError

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        """[(number, title, chapter url)], oldest first."""
        raise NotImplementedError

    def _chapter_text(self, chapter_url: str) -> Tuple[List[str], str]:
        """(paragraphs, chapter title). Raises ChapterUnavailable when there is no text."""
        raise NotImplementedError

    # ------------------------------------------------------------- ComicSiteBase
    def get_manga_name(self, url: str) -> str:
        try:
            return self._metadata(self.canonical_url(url)).title or 'Unknown'
        except (requests.RequestException, RuntimeError, ValueError) as e:
            logging.warning(f"{self.name} title lookup failed for {url}: {e}")
            return 'Unknown'

    def get_manga_metadata(self, url: str) -> MangaMetadata:
        meta = self._metadata(self.canonical_url(url))
        meta.url = self.canonical_url(url)
        meta.site_type = self.key
        meta.translation_type = 'fan'
        return meta

    def get_chapter_links(self, url: str, language_filter: Optional[str] = None) -> List[Tuple[str, str, str]]:
        seen, result = set(), []
        for number, title, link in self._chapters(self.canonical_url(url)):
            if number not in seen:          # a repeated number would overwrite the earlier chapter
                seen.add(number)
                # 'Chapter 2 Starting over' -> 'Chapter 2: Starting over', so the name is found
                title = re.sub(rf'^(\s*(?:chapter|ch\.?)\s*{re.escape(number)})\s+(?=[^\s:.\-–—])', r'\1: ',
                               html.unescape(title or '').strip(), flags=re.I)
                result.append((number, title, link))
        return result

    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                         base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                         language: str = "en") -> str:
        return self.download_novel_chapter(chapter_url, chapter_num, manga_name, base_path, progress_callback)

    def download_novel_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                               base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                               fmt: str = 'epub', series: str = '', title: str = '', author: str = '',
                               cover_path: str = '', language: str = 'en') -> str:
        """Save a chapter as '<base>/<novel>/Chapter N.<ext>'. Raises on failure."""
        from ..core.novel_export import NovelChapter, extension, write_chapter
        chapter_num = str(chapter_num).strip()
        target_dir = self.get_safe_manga_path(manga_name, base_path)
        if progress_callback:
            progress_callback(0, 2)
        try:
            paragraphs, site_title = self._chapter_text(chapter_url)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (404, 410):
                raise ChapterUnavailable(f"This chapter was removed from {self.name}. "
                                         "Use 'Check for new' to refresh the chapter list.") from e
            raise
        paragraphs = self._clean(paragraphs, site_title or title)
        if not paragraphs:
            raise ChapterUnavailable(f"This chapter has no text on {self.name}.")
        if progress_callback:
            progress_callback(1, 2)
        path = os.path.join(target_dir, f"Chapter {chapter_num}{extension(fmt)}")
        write_chapter(path, fmt, NovelChapter(series=series or manga_name, number=chapter_num,
                                              title=title or chapter_name(site_title, chapter_num),
                                              paragraphs=paragraphs, author=author, language=language or 'en',
                                              cover_path=cover_path))
        if progress_callback:
            progress_callback(2, 2)
        return path

    def _clean(self, paragraphs: List[str], title: str) -> List[str]:
        """Drop empty lines, the site's notices and a first line that only repeats the
        chapter heading (the file gets its own heading)."""
        result = []
        for text in paragraphs:
            text = re.sub(r'[ \t ]+', ' ', text or '').strip()
            if not text:
                continue
            lowered = text.lower()
            if any(word in lowered for word in self.ad_words) and len(text) < 300:
                continue
            result.append('* * *' if _SCENE_BREAK.match(text) else text)
        if result and (_same_heading(result[0], title) or
                       _HEADING.match(result[0]) and len(result[0]) < 160
                       and _same_heading(chapter_name(result[0]), chapter_name(title))):
            result.pop(0)
        return result


# ------------------------------------------------------------------ helpers
def chapter_name(title: str, number: str = '') -> str:
    """'Chapter 12: The Duel' -> 'The Duel'; a title that is only 'Chapter 12' -> ''."""
    title = html.unescape(title or '').strip()
    match = re.match(r'^\s*(?:chapter|ch\.?|episode|ep\.?)\s*#?([\d.]+)\s*[:\-–—.]*\s*', title, flags=re.I)
    if not match:
        return title
    rest = title[match.end():].strip()
    return '' if rest in ('', match.group(1), number) else rest


def _same_heading(line: str, title: str) -> bool:
    norm = lambda s: re.sub(r'[^0-9a-z]+', '', (s or '').lower())   # noqa: E731
    return bool(title) and norm(line) == norm(title)


def html_paragraphs(element) -> List[str]:
    """Text paragraphs of a chapter body: its <p> tags, or its lines when it has none."""
    if element is None:
        return []
    for tag in element.find_all(['script', 'style', 'ins', 'iframe', 'noscript', 'button']):
        tag.decompose()
    paragraphs = [p.get_text(' ', strip=True) for p in element.find_all('p')]
    if any(paragraphs):
        return paragraphs
    for br in element.find_all('br'):
        br.replace_with('\n')
    return text_paragraphs(element.get_text())


def text_paragraphs(text: str) -> List[str]:
    """Plain text chapter -> paragraphs (one per line)."""
    return [line.strip() for line in (text or '').replace('\r\n', '\n').split('\n') if line.strip()]


def plain_status(value) -> str:
    """'OnGoing', 'releasing', 'COMPLETED', 'finished' -> 'ongoing' / 'completed' / ..."""
    status = re.sub(r'[^a-z]', '', str(value or '').lower())
    if status in ('ongoing', 'releasing', 'publishing', 'active'):
        return 'ongoing'
    if status in ('completed', 'complete', 'finished', 'ended', 'end'):
        return 'completed'
    if status in ('hiatus', 'onhold', 'paused'):
        return 'hiatus'
    if status in ('cancelled', 'canceled', 'dropped', 'abandoned', 'discontinued'):
        return 'cancelled'
    return status or 'unknown'


def chapter_index(url: str) -> str:
    """'.../chapter-12' or '..._12.html' -> '12'"""
    match = re.search(r'(?:chapter-|_)(\d+)(?:\.html)?/?$', url or '')
    return match.group(1) if match else ''


def header_metadata(soup: BeautifulSoup, base: str) -> MangaMetadata:
    """Series page of the "novel-header" theme used by Novel Fire and Wuxia Box."""
    meta = MangaMetadata()
    title = soup.select_one('.novel-header h1, h1.novel-title')
    meta.title = title.get_text(' ', strip=True) if title else ''
    alt = soup.select_one('.novel-header .alternative-title')
    if alt and alt.get_text(strip=True):
        meta.alternative_names = [a.strip() for a in alt.get_text(strip=True).split(',') if a.strip()]
    author = soup.select_one('.novel-header .author [itemprop=author]')
    meta.author = author.get_text(' ', strip=True) if author else ''
    meta.genres = [a.get_text(strip=True) for a in soup.select('.categories a.property-item')]
    for strong in soup.select('.header-stats strong'):
        word = strong.get_text(strip=True).lower()
        if word in ('ongoing', 'completed', 'hiatus'):
            meta.status = word
    summary = soup.select_one('.summary .content, #info .summary .content')
    if summary:
        meta.description = '\n\n'.join(p for p in html_paragraphs(summary) if p.lower() not in ('show more', 'less'))
    image = soup.select_one('.novel-header figure.cover img, .novel-header .cover img')
    src = (image.get('data-src') or image.get('src') or '') if image else ''
    og = soup.find('meta', property='og:image')
    if (not src or 'placeholder' in src) and og:
        src = og.get('content', '')
    meta.cover_image_url = absolute(src, base)
    return meta


def absolute(href: str, base: str) -> str:
    if not href:
        return ''
    if href.startswith('//'):
        return 'https:' + href
    return href if href.startswith('http') else base + '/' + href.lstrip('/')
