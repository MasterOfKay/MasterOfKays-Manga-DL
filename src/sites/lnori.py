"""
LNORI downloader (https://lnori.com), light novels.

A static site. A series page (/series/<id>/<slug>) carries its volume list as
schema.org JSON-LD, and a volume page (/book/<id>/<slug>) carries that volume's
whole text: every page of the book as a <section class="chapter"> with the table of
contents (.toc-sidebar) pointing at the ones that start something.

A chapter here is one entry of a volume's table of contents, numbered straight
through the series ('Vol 2 Ch 3: ...'), so a new volume only adds numbers at the
end. Reading the chapter list loads every volume page once - they are big, so the
pages a volume is made of stay cached for a while and the downloads that follow
use them. Illustrations are not part of a text chapter and are left out.
"""

import json
import re
import threading
import time
from collections import OrderedDict
from typing import Dict, List, Tuple

from bs4 import BeautifulSoup

from .base import ChapterUnavailable, MangaMetadata
from .novel_base import NovelSite

BASE = "https://lnori.com"
SERIES_TTL = 600                 # seconds a series page is reused
VOLUME_TTL = 1800                # ... and a volume's chapters
VOLUME_CACHE = 3                 # volumes kept in memory (a volume is a whole book)
_VOLUME_NUMBER = re.compile(r'\b(?:volume|vol)\.?\s*(\d+(?:\.\d+)?)', re.I)
_CHAPTER_LABEL = re.compile(r'^\s*(?:chapter|ch\.?|episode|ep\.?)\s*#?([\d.]+)\s*[:.\-–—|]*\s*', re.I)
_TEXT_TAGS = ('h1', 'h2', 'h3', 'h4', 'p')
_DROP_TAGS = ('script', 'style', 'img', 'figure', 'ins', 'iframe', 'noscript', 'button')

Entry = Tuple[str, str, List[str]]          # (page anchor, table of contents label, paragraphs)


class LnoriDownloader(NovelSite):
    key, name, base = 'lnori', 'LNORI', BASE
    pattern = re.compile(r'^https?://(?:www\.)?lnori\.com/series/(\d+)(?:/([^/?#]*))?/?(?:[?#].*)?$', re.I)
    min_interval = 0.5           # the pages are large - don't ask for them back to back

    def __init__(self):
        super().__init__()
        self._series: Dict[str, Tuple[float, dict]] = {}
        self._volumes: 'OrderedDict[str, Tuple[float, List[Entry]]]' = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- links
    def canonical_url(self, url: str) -> str:
        match = self.pattern.match((url or '').strip())
        if not match:
            return url
        slug = match.group(2) or ''
        return f"{BASE}/series/{match.group(1)}" + (f"/{slug}" if slug else '')

    # ------------------------------------------------------------- series page
    def _book(self, url: str) -> dict:
        """The series' schema.org data: name, author, description, image, genre, hasPart."""
        with self._lock:
            hit = self._series.get(url)
            if hit and time.monotonic() - hit[0] < SERIES_TTL:
                return hit[1]
        soup = self._soup(url)
        data = _json_ld(soup)
        if not data.get('name'):
            data['name'] = _text(soup.select_one('h1'))
        if not data.get('hasPart'):
            data['hasPart'] = _volume_cards(soup)
        if not data.get('image'):
            image = soup.find('meta', property='og:image')
            data['image'] = image.get('content', '') if image else ''
        with self._lock:
            self._series[url] = (time.monotonic(), data)
        return data

    def _metadata(self, url: str) -> MangaMetadata:
        data = self._book(url)
        meta = MangaMetadata()
        meta.title = data.get('name') or ''
        meta.description = data.get('description') or ''
        author = data.get('author') or {}
        meta.author = (author.get('name') if isinstance(author, dict) else str(author)) or ''
        meta.genres = [g.strip() for g in (data.get('genre') or '').split(',') if g.strip()]
        meta.cover_image_url = data.get('image') or ''
        return meta

    def _parts(self, url: str) -> List[Tuple[str, str]]:
        """[(volume number, volume page url)] of a series, in reading order."""
        parts = []
        for position, part in enumerate(self._book(url).get('hasPart') or [], start=1):
            link = (part or {}).get('url') or ''
            if not re.match(r'^https?://(?:www\.)?lnori\.com/book/\d+', link):
                continue
            match = _VOLUME_NUMBER.search(part.get('name') or '')
            parts.append((match.group(1) if match else str(part.get('position') or position), link))
        return parts

    # ------------------------------------------------------------- volume pages
    def _entries(self, book_url: str) -> List[Entry]:
        """The chapters of one volume: its table of contents, with the text of each entry
        (the pages from its own anchor up to the next entry's)."""
        book_url = book_url.split('#')[0]
        with self._lock:
            hit = self._volumes.get(book_url)
            if hit and time.monotonic() - hit[0] < VOLUME_TTL:
                self._volumes.move_to_end(book_url)
                return hit[1]
        entries = _parse_volume(self._soup(book_url))
        with self._lock:
            self._volumes[book_url] = (time.monotonic(), entries)
            self._volumes.move_to_end(book_url)
            while len(self._volumes) > VOLUME_CACHE:
                self._volumes.popitem(last=False)
        return entries

    # ------------------------------------------------------------- chapters
    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        result: List[Tuple[str, str, str]] = []
        for volume, book_url in self._parts(url):
            for anchor, label, _ in self._entries(book_url):
                result.append((str(len(result) + 1), _title(volume, label), f"{book_url}#{anchor}"))
        if not result:
            raise ValueError("No volumes with text were found for this LNORI series.")
        return result

    def _chapter_text(self, chapter_url: str) -> Tuple[List[str], str]:
        book_url, _, anchor = chapter_url.partition('#')
        for entry_anchor, label, paragraphs in self._entries(book_url):
            if entry_anchor == anchor:
                return paragraphs, label
        raise ChapterUnavailable("This chapter is no longer part of the volume on LNORI. "
                                 "Use 'Check for new' to refresh the chapter list.")


# ------------------------------------------------------------------ parsing
def _json_ld(soup: BeautifulSoup) -> dict:
    """The page's schema.org Book, {} when it has none."""
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '{}')
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get('@type') == 'Book':
                return item
    return {}


def _volume_cards(soup: BeautifulSoup) -> List[dict]:
    """The volume list read off the series page itself, for a page without JSON-LD."""
    parts, seen = [], set()
    for link in soup.select('.vol-grid a[href^="/book/"], a[href^="/book/"]'):
        href = link['href'].split('#')[0]
        if href in seen:
            continue
        seen.add(href)
        parts.append({'name': link.get('aria-label') or _text(link), 'url': BASE + href})
    return parts


def _parse_volume(soup: BeautifulSoup) -> List[Entry]:
    """A volume page -> its table of contents with the text of every entry. Entries with
    no text of their own (cover, inserts, the title page) are left out."""
    body = soup.select_one('article.content-body')
    sections = body.find_all('section', class_='chapter', recursive=False) if body else []
    if not sections:
        return []
    place = {section.get('id'): index for index, section in enumerate(sections) if section.get('id')}
    contents, seen = [], set()
    for link in soup.select('.toc-sidebar a[href^="#"], nav.toc-view a[href^="#"]'):
        anchor = link['href'][1:]
        if anchor in place and anchor not in seen:
            seen.add(anchor)
            contents.append((anchor, _text(link)))
    contents.sort(key=lambda entry: place[entry[0]])

    entries: List[Entry] = []
    for position, (anchor, label) in enumerate(contents):
        start = place[anchor]
        end = place[contents[position + 1][0]] if position + 1 < len(contents) else len(sections)
        paragraphs = [p for section in sections[start:end] for p in _paragraphs(section)]
        if paragraphs and not _only_heading(paragraphs, label):
            entries.append((anchor, label, paragraphs))
    if entries:
        return entries
    # A volume without a usable table of contents: every page that has text is an entry.
    for index, section in enumerate(sections, start=1):
        paragraphs = _paragraphs(section)
        if paragraphs:
            entries.append((section.get('id') or f'page{index:02d}', paragraphs[0][:120], paragraphs))
    return entries


def _only_heading(paragraphs: List[str], label: str) -> bool:
    """True for an entry that is just its own heading - a gallery of illustrations, say,
    which has no text to save."""
    fold = lambda text: re.sub(r'[^0-9a-z]+', '', (text or '').lower())   # noqa: E731
    return not [p for p in paragraphs if fold(p) != fold(label)]


def _paragraphs(section) -> List[str]:
    """The text of one page of the book: its paragraphs and the headings between them."""
    for tag in section.find_all(_DROP_TAGS):
        tag.decompose()
    return [text for text in (_text(tag) for tag in section.find_all(_TEXT_TAGS)) if text]


def _text(element) -> str:
    return element.get_text(' ', strip=True) if element is not None else ''


def _title(volume: str, label: str) -> str:
    """'Chapter 1 The End and the Beginning' in volume 2 -> 'Vol 2 Ch 1: The End and the
    Beginning'; 'Prologue' -> 'Vol 2: Prologue'."""
    match = _CHAPTER_LABEL.match(label or '')
    if match:
        rest = label[match.end():].strip()
        return f"Vol {volume} Ch {match.group(1)}" + (f": {rest}" if rest else '')
    return f"Vol {volume}: {label}".rstrip(': ') if label else f"Vol {volume}"
