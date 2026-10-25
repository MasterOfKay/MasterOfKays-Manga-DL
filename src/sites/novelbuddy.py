"""
NovelBuddy downloader (https://novelbuddy.me), web novels only.

The series page (/<slug>) carries its data as Next.js JSON, including the title id;
the whole chapter list comes from the public API (api.novelbuddy.me/titles/<id>/chapters)
and a chapter page (/<slug>/<chapter-slug>) has the chapter's HTML text.
"""

import re
from typing import List, Tuple

from bs4 import BeautifulSoup

from .base import MangaMetadata
from .novel_base import NovelSite, absolute, format_number, html_paragraphs, plain_status

BASE = "https://novelbuddy.me"
API = "https://api.novelbuddy.me"
# Site pages that look like a series link but aren't one.
_RESERVED = {'home', 'latest', 'search', 'genres', 'genre', 'authors', 'author', 'popular', 'ranking', 'login',
             'register', 'library', 'bookmarks', 'history', 'user', 'users', 'settings', 'privacy', 'terms', 'dmca',
             'contact', 'sitemap', 'novel', 'titles', 'trending', 'completed', 'top', 'lists'}


class NovelBuddyDownloader(NovelSite):
    key, name, base = 'novelbuddy', 'NovelBuddy', BASE
    pattern = re.compile(r'^https?://(?:www\.)?novelbuddy\.(?:me|com)/([a-z0-9][a-z0-9\-]*)/?(?:[?#].*)?$', re.I)

    @classmethod
    def validate_url(cls, url: str) -> bool:
        match = cls.pattern.match((url or '').strip())
        return bool(match) and match.group(1).lower() not in _RESERVED

    def canonical_url(self, url: str) -> str:
        match = self.pattern.match((url or '').strip())
        return f"{BASE}/{match.group(1).lower()}" if match else url

    def _manga(self, url: str) -> dict:
        manga = self._next_data(url).get('initialManga') or {}
        if not manga.get('id'):
            raise ValueError(f"Not a NovelBuddy novel: {url}")
        return manga

    def _metadata(self, url: str) -> MangaMetadata:
        manga = self._manga(url)
        meta = MangaMetadata()
        meta.title = manga.get('name') or ''
        meta.description = BeautifulSoup(manga.get('summary') or '', 'html.parser').get_text('\n').strip()
        meta.author = ', '.join(a['name'] for a in manga.get('authors') or [] if a.get('name'))
        meta.genres = [g['name'] for g in manga.get('genres') or [] if g.get('name')]
        meta.alternative_names = [n for n in manga.get('altNames') or [] if isinstance(n, str)]
        meta.status = plain_status(manga.get('status'))
        meta.cover_image_url = manga.get('cover') or ''
        return meta

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        manga = self._manga(url)
        data = self._json(f"{API}/titles/{manga['id']}/chapters", params={'cv': manga.get('cv') or ''})
        chapters = (data.get('data') or {}).get('chapters') or []
        rows = [(format_number(c['number']), c.get('name') or '', absolute(c.get('url', ''), BASE))
                for c in chapters if c.get('number') is not None and c.get('url')]
        return sorted(rows, key=lambda r: float(r[0]))

    def _chapter_text(self, chapter_url: str):
        chapter = self._next_data(chapter_url).get('initialChapter') or {}
        body = BeautifulSoup(chapter.get('content') or '', 'html.parser')
        return html_paragraphs(body), chapter.get('name') or ''
