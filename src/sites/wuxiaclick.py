"""
wuxia.click downloader (https://wuxia.click), web novels only.

A Next.js site: every page carries its data as JSON. The series page
(/novel/<slug>?page=N) has the metadata and 100 chapters of the list per page,
a chapter page (/chapter/<slug>-<number>) its paragraphs.
"""

import re
from typing import List, Tuple

from .base import MangaMetadata
from .novel_base import NovelSite, format_number, plain_status

BASE = "https://wuxia.click"
COVERS = "https://cdn.wuxiaworld.eu"


def cover_url(novel: dict) -> str:
    """'covers/v1/<hash>' -> the 480 px WebP the site shows."""
    key = novel.get('coverKey') or ''
    return f"{COVERS}/{key}-480.webp" if key else ''


class WuxiaClickDownloader(NovelSite):
    key, name, base = 'wuxiaclick', 'wuxia.click', BASE
    pattern = re.compile(r'^https?://(?:www\.)?wuxia\.click/novel/([a-z0-9\-]+)/?(?:[?#].*)?$', re.I)

    def canonical_url(self, url: str) -> str:
        match = self.pattern.match((url or '').strip())
        return f"{BASE}/novel/{match.group(1).lower()}" if match else url

    def _metadata(self, url: str) -> MangaMetadata:
        novel = self._next_data(url).get('novel') or {}
        meta = MangaMetadata()
        meta.title = novel.get('title') or ''
        meta.description = novel.get('description') or ''
        meta.author = (novel.get('author') or {}).get('name') or ''
        meta.genres = [g['name'] for g in novel.get('genres') or [] if g.get('name')]
        meta.alternative_names = [n for n in novel.get('altTitles') or [] if isinstance(n, str)]
        meta.status = plain_status(novel.get('status'))
        meta.cover_image_url = cover_url(novel)
        return meta

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        slug = self.pattern.match(url).group(1)
        result, page, pages = [], 1, 1
        while page <= pages:
            toc = self._next_data(url, params={'page': page}).get('toc') or {}
            pages = min(len(toc.get('ranges') or []) or 1, 500)
            for item in toc.get('items') or []:
                number = format_number(item.get('number'))
                result.append((number, item.get('title') or '', f"{BASE}/chapter/{slug}-{number}"))
            page += 1
        return result

    def _chapter_text(self, chapter_url: str):
        chapter = (self._next_data(chapter_url).get('data') or {}).get('chapter') or {}
        return list(chapter.get('paragraphs') or []), chapter.get('title') or ''
