"""
Novel Fire (https://novelfire.net) and Wuxia Box (https://www.wuxiabox.com) downloaders,
web novels only. Both use the same site theme.

Novel Fire: series /book/<slug>, chapter list /book/<slug>/chapters?page=N (100 per
page), chapters /book/<slug>/chapter-N. A chapter page sends the reader on to the
site's mirror (novelphoenix.com right now); the redirect is followed, the text is
in #content.

Wuxia Box: series /novel/<slug>.html, chapter list fragments from
/e/extend/fy.php?page=N&wjm=<slug> (from 0, 100 per page), chapters
/novel/<slug>_N.html with the text in .chapter-content.
"""

import re
from typing import List, Tuple

from .base import MangaMetadata
from .novel_base import NovelSite, absolute, chapter_index, header_metadata, html_paragraphs

_REDIRECT = re.compile(r'location\.href\s*=\s*"([^"]+)"')


class NovelFireDownloader(NovelSite):
    key, name, base = 'novelfire', 'Novel Fire', 'https://novelfire.net'
    pattern = re.compile(r'^https?://(?:www\.)?novelfire\.net/book/([a-z0-9\-]+)/?(?:[?#].*)?$', re.I)
    ad_words = ('novelfire', 'novel fire', 'novelphoenix')

    def canonical_url(self, url: str) -> str:
        match = self.pattern.match((url or '').strip())
        return f"{self.base}/book/{match.group(1).lower()}" if match else url

    def _metadata(self, url: str) -> MangaMetadata:
        return header_metadata(self._soup(url), self.base)

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        result, page = [], 1
        while True:
            soup = self._soup(f"{url}/chapters", params={'page': page})
            for link in soup.select('ul.chapter-list li a[href]'):
                number = chapter_index(link['href'])
                title = link.select_one('.chapter-title')
                if number:
                    result.append((number, title.get_text(' ', strip=True) if title else link.get('title', ''),
                                   absolute(link['href'], self.base)))
            if not soup.select_one(f'.pagination a[href*="page={page + 1}"]') or page >= 300:
                return result
            page += 1

    def _chapter_text(self, chapter_url: str):
        soup = self._soup(chapter_url)
        content = soup.select_one('#content')
        if content is None:
            mirror = _REDIRECT.search(str(soup))
            if not mirror:
                return [], ''
            soup = self._soup(mirror.group(1).replace('\\/', '/').split('?')[0])
            content = soup.select_one('#content')
        heading = content.find('h4') if content else None
        title = heading.get_text(' ', strip=True) if heading else ''
        if heading:
            heading.decompose()
        return html_paragraphs(content), title


class WuxiaBoxDownloader(NovelSite):
    key, name, base = 'wuxiabox', 'Wuxia Box', 'https://www.wuxiabox.com'
    pattern = re.compile(r'^https?://(?:www\.)?wuxiabox\.com/novel/([a-z0-9\-]+)\.html(?:[?#].*)?$', re.I)
    ad_words = ('wuxiabox', 'wuxia box')
    send_referer = False             # its chapter pages answer requests with a Referer with a browser check

    def canonical_url(self, url: str) -> str:
        match = self.pattern.match((url or '').strip())
        return f"{self.base}/novel/{match.group(1).lower()}.html" if match else url

    def _metadata(self, url: str) -> MangaMetadata:
        return header_metadata(self._soup(url), self.base)

    def _chapters(self, url: str) -> List[Tuple[str, str, str]]:
        slug = self.pattern.match(url).group(1)
        result, page = [], 0
        while True:
            soup = self._soup(f"{self.base}/e/extend/fy.php", params={'page': page, 'wjm': slug})
            links = soup.select('ul.chapter-list li a[href]')
            for link in links:
                number = chapter_index(link['href'])
                title = link.select_one('.chapter-title')
                if number:
                    result.append((number, title.get_text(' ', strip=True) if title else '',
                                   absolute(link['href'], self.base)))
            if not links or not soup.select_one(f'.pagination a[href*="page={page + 1}&"]') or page >= 300:
                return result
            page += 1

    def _chapter_text(self, chapter_url: str):
        soup = self._soup(chapter_url)
        title = soup.select_one('.chapter-title, h1 .chapter-title, .titles h2')
        return html_paragraphs(soup.select_one('.chapter-content')), title.get_text(' ', strip=True) if title else ''
