"""
FreeWebNovel downloader (https://freewebnovel.com), web novels only.

The series page (/novel/<slug>) holds the metadata and says how many chapter list
pages there are; each list page comes from '?ajax=chapters&page=N' as JSON with an
HTML fragment. A chapter (/novel/<slug>/chapter-N) has its text in #article.
"""

import re
from typing import List, Tuple

from bs4 import BeautifulSoup

from .base import MangaMetadata
from .novel_base import NovelSite, absolute, chapter_index, html_paragraphs

BASE = "https://freewebnovel.com"
LIST_PAGE = 200


class FreeWebNovelDownloader(NovelSite):
    key, name, base = 'freewebnovel', 'FreeWebNovel', BASE
    pattern = re.compile(r'^https?://(?:www\.)?freewebnovel\.com/novel/([a-z0-9\-]+)/?(?:[?#].*)?$', re.I)
    ad_words = ('freewebnovel', 'free web novel')

    def canonical_url(self, url: str) -> str:
        match = self.pattern.match((url or '').strip())
        return f"{BASE}/novel/{match.group(1).lower()}" if match else url

    def _metadata(self, url: str) -> MangaMetadata:
        soup = self._soup(url)
        meta = MangaMetadata()
        title = soup.select_one('.m-desc h1.tit, h1.tit')
        meta.title = title.get_text(' ', strip=True) if title else ''
        for item in soup.select('.m-info .txt .item'):
            icon = item.find('span', title=True)
            value = item.select_one('.right')
            if not icon or not value:
                continue
            kind = icon['title'].lower()
            if kind == 'author':
                meta.author = ', '.join(a.get_text(strip=True) for a in value.find_all('a')) or \
                    value.get_text(' ', strip=True)
            elif kind == 'genre':
                meta.genres = [a.get_text(strip=True) for a in value.find_all('a')]
            elif kind == 'status':
                status = value.get_text(strip=True).lower()
                meta.status = 'completed' if 'complete' in status else 'ongoing' if 'going' in status else status
            elif kind == 'alternative names':
                meta.alternative_names = [n.strip() for n in value.get_text(' ', strip=True).split(',') if n.strip()]
        summary = soup.select_one('.m-desc .inner')
        meta.description = '\n\n'.join(html_paragraphs(summary)) if summary else ''
        cover = soup.find('meta', property='og:image')
        meta.cover_image_url = absolute(cover.get('content', '') if cover else '', BASE)
        return meta

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        result, page = [], 1
        while True:
            data = self._json(url, params={'ajax': 'chapters', 'page': page, 'pageSize': LIST_PAGE})
            links = BeautifulSoup(data.get('html') or '', 'html.parser').find_all('a', href=True)
            for link in links:
                number = chapter_index(link['href'])
                if number:
                    result.append((number, link.get('title') or link.get_text(' ', strip=True),
                                   absolute(link['href'], BASE)))
            if len(links) < LIST_PAGE or page >= 200:
                return result
            page += 1

    def _chapter_text(self, chapter_url: str):
        soup = self._soup(chapter_url)
        title = soup.select_one('span.chapter') or soup.select_one('h1.tit')
        return html_paragraphs(soup.select_one('#article')), title.get_text(' ', strip=True) if title else ''
