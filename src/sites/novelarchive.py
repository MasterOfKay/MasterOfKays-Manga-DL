"""
Novel Archive downloader (https://novelarchive.cc), web novels only.

A web app on top of a public JSON API:
    /api/novels/<id>                          details, incl. every chapter name
    /api/novels/<id>/chapters/<n>             one chapter's text (n counts from 1)
Series links look like /novel?id=<id>, the reader is /reader?novel=<id>&chapter=<n>.
"""

import html
import re
from typing import List, Tuple

from .base import MangaMetadata
from .novel_base import NovelSite, absolute, plain_status, text_paragraphs

BASE = "https://novelarchive.cc"


class NovelArchiveDownloader(NovelSite):
    key, name, base = 'novelarchive', 'Novel Archive', BASE
    pattern = re.compile(r'^https?://(?:www\.)?novelarchive\.cc/(?:novel|reader)/?\?(?:.*&)?(?:id|novel)=([0-9a-f]{24})\b',
                         re.I)

    def canonical_url(self, url: str) -> str:
        match = self.pattern.match((url or '').strip())
        return f"{BASE}/novel?id={match.group(1).lower()}" if match else url

    def _novel(self, url: str) -> dict:
        novel_id = self.pattern.match(url).group(1)
        return self._json(f"{BASE}/api/novels/{novel_id}").get('novel') or {}

    def _metadata(self, url: str) -> MangaMetadata:
        novel = self._novel(url)
        meta = MangaMetadata()
        meta.title = html.unescape(novel.get('title') or '')
        meta.description = novel.get('description') or ''
        author = (novel.get('author') or '').strip()
        meta.author = '' if author.lower() == 'unknown' else author
        meta.genres = [g.strip() for g in (novel.get('genres') or '').split(',') if g.strip()]
        names = novel.get('associated_names') or []
        meta.alternative_names = [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
        meta.status = plain_status(novel.get('release_status') or novel.get('ongoing'))
        meta.cover_image_url = absolute(novel.get('cover_url') or novel.get('image_url') or '', BASE)
        return meta

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        novel = self._novel(url)
        names = novel.get('chapter_names') or []
        return [(str(i), html.unescape(name or ''), f"{BASE}/reader?novel={novel['id']}&chapter={i}")
                for i, name in enumerate(names, start=1)]

    def _chapter_text(self, chapter_url: str):
        match = re.search(r'novel=([0-9a-f]{24}).*?chapter=(\d+)', chapter_url)
        if not match:
            return [], ''
        data = self._json(f"{BASE}/api/novels/{match.group(1)}/chapters/{match.group(2)}", params={'prefetch': 1})
        chapter = data.get('chapter') or {}
        return text_paragraphs(chapter.get('content') or ''), html.unescape(chapter.get('name') or '')
