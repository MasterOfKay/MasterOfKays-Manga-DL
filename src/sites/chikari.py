"""
chikari.moe downloader (https://chikari.moe), web novels only.

A web app on top of a public JSON API:
    /api/novels/<slug>                          details
    /api/novels/<slug>/chapters                 every chapter, newest first
    /api/novels/<slug>/chapters/<number>/read   one chapter's text
Series links look like /novels/<slug>. Reading too fast makes the site ask for a
human check, so requests are spaced out a little more than on other sites.
"""

import re
from typing import List, Tuple

import requests

from .base import ChapterUnavailable, MangaMetadata
from .novel_base import NovelSite, format_number, plain_status, text_paragraphs

BASE = "https://chikari.moe"


class ChikariDownloader(NovelSite):
    key, name, base = 'chikari', 'chikari.moe', BASE
    pattern = re.compile(r'^https?://(?:www\.)?chikari\.moe/novels/([a-z0-9\-]+)/?(?:[?#].*)?$', re.I)
    min_interval = 0.8

    def canonical_url(self, url: str) -> str:
        match = self.pattern.match((url or '').strip())
        return f"{BASE}/novels/{match.group(1).lower()}" if match else url

    def _slug(self, url: str) -> str:
        return self.pattern.match(url).group(1)

    def _metadata(self, url: str) -> MangaMetadata:
        novel = self._json(f"{BASE}/api/novels/{self._slug(url)}")
        meta = MangaMetadata()
        meta.title = novel.get('title') or ''
        meta.description = novel.get('description') or ''
        meta.author = ', '.join(a.get('name', '') for a in novel.get('authors') or [] if isinstance(a, dict)) or \
            (novel.get('author') or '')
        meta.genres = [g['name'] for g in novel.get('genres') or [] if isinstance(g, dict) and g.get('name')]
        meta.alternative_names = [n for n in novel.get('alt_titles') or [] if isinstance(n, str)]
        meta.status = plain_status(novel.get('status'))
        meta.release_date = str(novel.get('year') or '')
        meta.cover_image_url = novel.get('cover_url') or ''
        return meta

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        slug = self._slug(url)
        items, offset = [], 0
        while True:
            data = self._json(f"{BASE}/api/novels/{slug}/chapters", params={'limit': 500, 'offset': offset})
            batch = data.get('items') or []
            items += batch
            offset += len(batch)
            if not batch or offset >= (data.get('total') or 0) or offset > 50_000:
                break
        rows = [(format_number(c['number']), c.get('title') or '', f"{BASE}/novels/{slug}/{format_number(c['number'])}")
                for c in items if c.get('number') is not None and (c.get('lang') or 'en') == 'en']
        return sorted(rows, key=lambda r: float(r[0]))

    def _chapter_text(self, chapter_url: str):
        match = re.search(r'/novels/([a-z0-9\-]+)/([\d.]+)', chapter_url)
        if not match:
            return [], ''
        try:
            data = self._json(f"{BASE}/api/novels/{match.group(1)}/chapters/{match.group(2)}/read")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 402, 403):
                raise ChapterUnavailable("chikari.moe wants a sign-in or a human check for this chapter.") from e
            raise
        return text_paragraphs(data.get('body') or ''), data.get('title') or ''
