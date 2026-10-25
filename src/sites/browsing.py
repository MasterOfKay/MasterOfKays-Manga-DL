"""
Browsing the sites: latest updates, search and categories.

Each browser returns BrowseItem lists and knows its own category slugs. Combined
"search + category" requests are done server-side where the site supports it and
filtered locally otherwise.
"""

import html
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .base import COMIC_MARKER, fix_text, is_novel_url

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
PAGE_SIZE = 24


@dataclass
class BrowseItem:
    """One manga in a browse/search list."""
    title: str
    url: str
    site: str
    cover_url: str = ''
    latest: str = ''                 # e.g. "Chapter 35 · 48 minutes ago"
    status: str = ''
    genres: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.title = fix_text(self.title)

    @property
    def is_novel(self) -> bool:
        return is_novel_url(self.url)


def genre_key(name: str) -> str:
    """Site-independent key for a category name ("Sci-fi", "SF", "sci_fi" -> "scifi")."""
    key = re.sub(r'[^a-z0-9]', '', (name or '').lower())
    return {'sf': 'scifi', 'sciencefiction': 'scifi', 'superhero': 'superhero', 'superheroes': 'superhero',
            'sliceoflife': 'sliceoflife', 'martialart': 'martialarts', 'reincarnated': 'reincarnation',
            'oneshot': 'oneshot', 'boyslove': 'yaoi', 'girlslove': 'yuri'}.get(key, key)


def _matches(item: BrowseItem, query: str) -> bool:
    return not query or query.lower() in item.title.lower()


class _Cached:
    """Tiny TTL cache for lists that come as one big page (Webtoon) and for category lists."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._data: Dict[str, Tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._data.get(key)
            return hit[1] if hit and time.monotonic() - hit[0] < self.ttl else None

    def put(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)


class SiteBrowser:
    key = ''
    label = ''
    kinds = ('manga',)               # what the site has: 'manga' and/or 'novel'

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.8'})
        self.cache = _Cached(ttl=600)

    def _soup(self, url: str, **params) -> Tuple[BeautifulSoup, str]:
        response = self.session.get(url, params=params or None, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return BeautifulSoup(response.text, 'html.parser'), response.url

    def genres(self) -> List[Tuple[str, str]]:
        """[(display name, site slug)]"""
        raise NotImplementedError

    def browse(self, query: str = '', genre_slug: str = '', page: int = 1) -> Tuple[List[BrowseItem], bool]:
        """Returns (items, has_more). Empty query + genre -> latest updates."""
        raise NotImplementedError


# ------------------------------------------------------------------ MangaKatana
class KatanaBrowser(SiteBrowser):
    key, label = 'mangakatana', 'MangaKatana'
    base = 'https://mangakatana.com'

    def genres(self):
        cached = self.cache.get('genres')
        if cached:
            return cached
        soup, _ = self._soup(f'{self.base}/genre/action')
        found = {}
        for a in soup.find_all('a', href=True):
            m = re.match(rf'^{re.escape(self.base)}/genre/([a-z0-9\-]+)/?$', a['href'])
            name = a.get_text(strip=True)
            if m and name and not name.isdigit():
                found.setdefault(m.group(1), name)
        result = sorted(((n, s) for s, n in found.items()), key=lambda x: x[0].lower())
        self.cache.put('genres', result)
        return result

    def browse(self, query='', genre_slug='', page=1):
        if query:
            path = f'{self.base}/page/{page}' if page > 1 else self.base + '/'
            soup, final_url = self._soup(path, search=query, search_by='book_name')
            if '/manga/' in final_url:            # a unique hit redirects straight to the manga
                return [self._single(soup, final_url)], False
        elif genre_slug:
            soup, _ = self._soup(f'{self.base}/genre/{genre_slug}' + (f'/page/{page}' if page > 1 else ''))
        else:
            soup, _ = self._soup(f'{self.base}/latest' + (f'/page/{page}' if page > 1 else ''))
        items = [self._item(it) for it in soup.select('#book_list .item')]
        items = [i for i in items if i]
        if query and genre_slug:
            wanted = genre_key(genre_slug)
            items = [i for i in items if any(genre_key(g) == wanted for g in i.genres)]
        has_more = bool(soup.find('a', href=re.compile(rf'/page/{page + 1}(\?|$|/)')))
        return items, has_more

    def _item(self, it) -> Optional[BrowseItem]:
        link = it.select_one('h3.title a')
        if not link:
            return None
        img = it.select_one('.wrap_img img')
        status = it.select_one('.status')
        span = it.select_one('h3.title span')
        date = it.select_one('.date')
        latest = (span.get_text(strip=True).lstrip('- ').strip() if span else '')
        latest = re.sub(r'^Update chapter', 'Chapter', latest, flags=re.I)
        when = date.get_text(strip=True) if date else ''
        return BrowseItem(
            title=link.get_text(strip=True), url=link['href'].split('?')[0].rstrip('/'), site=self.key,
            cover_url=img.get('src', '') if img else '',
            latest=' · '.join(x for x in (latest, when) if x),
            status=status.get_text(strip=True).lower() if status else '',
            genres=[a.get_text(strip=True) for a in it.select('.genres a')])

    def _single(self, soup, url) -> BrowseItem:
        title = soup.select_one('h1.heading') or soup.find('h1')
        image = soup.find('meta', property='og:image')
        return BrowseItem(title=title.get_text(strip=True) if title else url, url=url.split('?')[0], site=self.key,
                          cover_url=image.get('content', '') if image else '')


# ------------------------------------------------------------------- Asura Scans
class AsuraBrowser(SiteBrowser):
    key, label = 'asura', 'Asura Scans'
    base = 'https://asurascans.com'

    def genres(self):
        cached = self.cache.get('genres')
        if cached:
            return cached
        response = self.session.get(f'{self.base}/browse', timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        raw = html.unescape(response.text)
        found = {}
        for name, slug in re.findall(r'"name":\[0,"([^"]+)"\],"slug":\[0,"([a-z0-9\-]+)"\]', raw):
            found.setdefault(slug, name)
        result = sorted(((n, s) for s, n in found.items()), key=lambda x: x[0].lower())
        self.cache.put('genres', result)
        return result

    def browse(self, query='', genre_slug='', page=1):
        params = {}
        if query:
            params['search'] = query
        if genre_slug:
            params['genres'] = genre_slug
        if page > 1:
            params['page'] = page
        soup, _ = self._soup(f'{self.base}/browse', **params)
        covers = {}
        for a in soup.find_all('a', href=True):
            img = a.find('img')
            if img and re.search(r'/comics/[a-z0-9\-]+', a['href']):
                covers.setdefault(a['href'].rstrip('/'), img.get('src', ''))
        items, seen = [], set()
        for a in soup.find_all('a', href=True):
            title = a.find('h3')
            href = a['href'].rstrip('/')
            if not title or not re.search(r'/comics/[a-z0-9\-]+-[0-9a-f]{8}$', href) or href in seen:
                continue
            seen.add(href)
            # Climb to this card's own container: the largest ancestor that still holds one title.
            card = a
            while card.parent is not None and len(card.parent.find_all('h3')) <= 1:
                card = card.parent
            text = card.get_text(' ', strip=True)
            chapters = re.search(r'(\d+)\s*Chs', text)
            status = re.search(r'\b(ongoing|completed|hiatus|dropped|season end)\b', text, re.I)
            items.append(BrowseItem(
                title=title.get_text(strip=True), url=self.base + href if href.startswith('/') else href,
                site=self.key, cover_url=covers.get(href, ''),
                latest=f"{chapters.group(1)} chapters" if chapters else '',
                status=status.group(1).lower() if status else ''))
        has_more = bool(soup.find('a', href=re.compile(rf'[?&]page={page + 1}\b')))
        return items, has_more


# ---------------------------------------------------------------------- Webtoon
class WebtoonBrowser(SiteBrowser):
    key, label = 'webtoon', 'Webtoon'
    base = 'https://www.webtoons.com/en'

    def genres(self):
        cached = self.cache.get('genres')
        if cached:
            return cached
        soup, _ = self._soup(f'{self.base}/genres')
        codes = sorted({x.get('data-genre') for x in soup.find_all(attrs={'data-genre': True}) if x.get('data-genre')})
        names = {'SF': 'Sci-Fi', 'SUPER_HERO': 'Superhero', 'GRAPHIC_NOVEL': 'Graphic Novel',
                 'SLICE_OF_LIFE': 'Slice of Life', 'TIPTOON': 'Tiptoon'}
        result = [(names.get(c, c.replace('_', ' ').title()), c.lower()) for c in codes]
        self.cache.put('genres', result)
        return result

    def browse(self, query='', genre_slug='', page=1):
        if genre_slug:
            # One page with ~1000 titles sorted by update: cache it and page locally (query filters it).
            items = self._full_list(f'genre:{genre_slug}', f'{self.base}/genres/{genre_slug}', sortOrder='UPDATE')
            items = [i for i in items if _matches(i, query)]
        elif query:
            soup, _ = self._soup(f'{self.base}/search', keyword=query)
            items = self._parse(soup)
        else:
            items = self._full_list('latest', f'{self.base}/originals', sortOrder='UPDATE')
        start = (page - 1) * PAGE_SIZE
        return items[start:start + PAGE_SIZE], len(items) > start + PAGE_SIZE

    def _full_list(self, key, url, **params) -> List[BrowseItem]:
        cached = self.cache.get(key)
        if cached is None:
            soup, _ = self._soup(url, **params)
            cached = self._parse(soup)
            self.cache.put(key, cached)
        return cached

    def _parse(self, soup) -> List[BrowseItem]:
        items, seen = [], set()
        for a in soup.find_all('a', href=True):
            m = re.search(r'title_no=(\d+)', a['href'])
            title = a.select_one('.title')
            if not m or not title or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            img = a.find('img')
            genre = a.select_one('.genre')
            up = a.select_one('[class^=badge_up], .badge_up2, .badge_new2')
            url = a['href'].split('&')[0]
            if url.startswith('/'):
                url = 'https://www.webtoons.com' + url
            items.append(BrowseItem(
                title=title.get_text(strip=True), url=url, site=self.key,
                cover_url=img.get('src', '') if img else '',
                latest='Updated' if up and up.get_text(strip=True) == 'UP' else (up.get_text(strip=True).title() if up else ''),
                genres=[genre.get_text(strip=True)] if genre else []))
        return items


# --------------------------------------------------------------------- MangaDex
class MangaDexBrowser(SiteBrowser):
    key, label = 'mangadex', 'MangaDex'
    api = 'https://api.mangadex.org'

    def __init__(self, language: str = 'en'):
        super().__init__()
        self.language = language

    def genres(self):
        cached = self.cache.get('genres')
        if cached:
            return cached
        response = self.session.get(f'{self.api}/manga/tag', timeout=30)
        response.raise_for_status()
        result = []
        for tag in response.json().get('data', []):
            attrs = tag.get('attributes', {})
            if attrs.get('group') in ('genre', 'theme'):
                result.append((attrs.get('name', {}).get('en', ''), tag['id']))
        result = sorted((r for r in result if r[0]), key=lambda x: x[0].lower())
        self.cache.put('genres', result)
        return result

    def browse(self, query='', genre_slug='', page=1):
        params = {
            'limit': PAGE_SIZE, 'offset': (page - 1) * PAGE_SIZE,
            'includes[]': ['cover_art'], 'contentRating[]': ['safe', 'suggestive'],
            'hasAvailableChapters': 'true',
        }
        if self.language:
            params['availableTranslatedLanguage[]'] = [self.language]
        if query:
            params['title'] = query
            params['order[relevance]'] = 'desc'
        else:
            params['order[latestUploadedChapter]'] = 'desc'
        if genre_slug:
            params['includedTags[]'] = [genre_slug]
        response = self.session.get(f'{self.api}/manga', params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        items = [self._item(m) for m in data.get('data', [])]
        return [i for i in items if i], params['offset'] + PAGE_SIZE < data.get('total', 0)

    def _item(self, manga) -> Optional[BrowseItem]:
        attrs = manga.get('attributes', {})
        titles = attrs.get('title', {})
        title = titles.get('en') or next((t.get('en') for t in attrs.get('altTitles', []) if t.get('en')), None) \
            or next(iter(titles.values()), '')
        if not title:
            return None
        cover = next((r.get('attributes', {}).get('fileName') for r in manga.get('relationships', [])
                      if r.get('type') == 'cover_art'), '')
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') or 'manga'
        last = attrs.get('lastChapter')
        return BrowseItem(
            title=title, url=f"https://mangadex.org/title/{manga['id']}/{slug}", site=self.key,
            cover_url=f"https://uploads.mangadex.org/covers/{manga['id']}/{cover}.256.jpg" if cover else '',
            latest=f"Chapter {last}" if last else '',
            status=attrs.get('status', ''),
            genres=[t.get('attributes', {}).get('name', {}).get('en', '') for t in attrs.get('tags', [])])


# ------------------------------------------------------------------- MangaFreak
class MangaFreakBrowser(SiteBrowser):
    key, label = 'mangafreak', 'MangaFreak'
    base = 'https://ww3.mangafreak.me'
    # Entries of the site's genre menu whose pages are empty (checked Oct 2026), plus duplicates.
    # "Shoujoai"/"Shounenai" are the working ones; "Shoujo Ai"/"Shounen Ai" are (nearly) empty.
    _skip = {'All', 'Add', 'Actions', 'Full Color', 'Isekai', 'Lolicon', 'Manhwa', 'Reincarnation',
             'School Of Life', 'Shotacon', 'Shoujo Ai', 'Shounen Ai', 'Superhero', 'Villainess',
             'Web Comic', 'Webtoon', 'Historica', 'Life'}

    def genres(self):
        cached = self.cache.get('genres')
        if cached:
            return cached
        soup, _ = self._soup(f'{self.base}/Genre')
        found = {}
        for a in soup.find_all('a', href=re.compile(r'^/Genre/[A-Za-z_]+$')):
            name = a.get_text(strip=True)
            if name and name not in self._skip:
                found.setdefault(a['href'].rsplit('/', 1)[1], name)
        result = sorted(((n, s) for s, n in found.items()), key=lambda x: x[0].lower())
        self.cache.put('genres', result)
        return result

    def browse(self, query='', genre_slug='', page=1):
        if query:
            # One page of results, no paging. Spaces must be '+' in the path.
            soup, _ = self._soup(f"{self.base}/Find/{requests.utils.quote(query.strip(), safe='').replace('%20', '+')}")
            items = [self._search_item(it) for it in soup.select('.manga_search_item')]
            items = [i for i in items if i]
            if genre_slug:
                wanted = genre_key(genre_slug)
                items = [i for i in items if any(genre_key(g) == wanted for g in i.genres)]
            return items, False
        if genre_slug:
            soup, _ = self._soup(f'{self.base}/Genre/{genre_slug}/{page}')
            items = [self._ranking_item(it) for it in soup.select('.ranking_item')]
            more = bool(soup.find('a', href=f'/Genre/{genre_slug}/{page + 1}'))
        else:
            soup, _ = self._soup(f'{self.base}/Latest_Releases/{page}')
            items = [self._latest_item(it) for it in soup.select('.latest_releases_item')]
            more = bool(soup.find('a', href=f'/Latest_Releases/{page + 1}'))
        return [i for i in items if i], more

    def _url(self, href: str) -> str:
        return self.base + href if href.startswith('/') else href

    @staticmethod
    def _cover(href: str) -> str:
        """Full-size cover from the series slug ('/Manga/Lost_Man' -> .../manga_images/lost_man.jpg);
        the latest list itself only has 55x85 thumbnails."""
        slug = href.rstrip('/').rsplit('/', 1)[-1].lower()
        return f'https://images.mangafreak.me/manga_images/{slug}.jpg'

    @staticmethod
    def _status(text: str) -> str:
        found = re.search(r'\((ongoing|completed)\)', text, re.I)
        return found.group(1).lower() if found else ''

    def _latest_item(self, it) -> Optional[BrowseItem]:
        link = it.select_one('.latest_releases_info > a[href^="/Manga/"]')
        if not link:
            return None
        chapter = it.select_one('.latest_releases_info div a')
        number = re.search(r'(\d+(?:\.\d+)?[a-z]?)\s*$', chapter.get_text(strip=True)) if chapter else None
        when = it.select_one('.latest_releases_time')
        picture = it.select_one('.latest_releases_image')
        classes = ' '.join(picture.get('class', [])) if picture else ''
        latest = f"Chapter {number.group(1)}" if number else ''
        return BrowseItem(
            title=link.get_text(strip=True), url=self._url(link['href']), site=self.key,
            cover_url=self._cover(link['href']),
            latest=' · '.join(x for x in (latest, when.get_text(strip=True) if when else '') if x),
            status='completed' if 'complete' in classes else 'ongoing' if 'ongoing' in classes else '')

    def _ranking_item(self, it) -> Optional[BrowseItem]:
        link = it.select_one('.ranking_item_info a[href^="/Manga/"]')
        if not link:
            return None
        img = it.select_one('.ranking_item_image img')
        text = it.get_text(' ', strip=True)
        count = re.search(r'(\d+)\w*\s+Published', text)
        return BrowseItem(
            title=link.get_text(strip=True), url=self._url(link['href']), site=self.key,
            cover_url=img.get('src', '') if img else self._cover(link['href']),
            latest=f"{count.group(1)} chapters" if count else '', status=self._status(text))

    def _search_item(self, it) -> Optional[BrowseItem]:
        link = it.select_one('h3 a[href^="/Manga/"]')
        if not link:
            return None
        img = it.select_one('img')
        text = it.get_text(' ', strip=True)
        count = re.search(r'(\d+)\s+Chapters Published', text)
        return BrowseItem(
            title=link.get_text(strip=True), url=self._url(link['href']), site=self.key,
            cover_url=img.get('src', '') if img else self._cover(link['href']),
            latest=f"{count.group(1)} chapters" if count else '', status=self._status(text),
            genres=[a.get_text(strip=True) for a in it.select('a[href^="/Genre/"]')])


# --------------------------------------------------------------------- Atsumaru
class AtsumaruBrowser(SiteBrowser):
    key, label = 'atsumaru', 'Atsumaru'
    base = 'https://atsu.moe'
    kinds = ('manga', 'novel')
    _skip = {'Hentai'}               # adult titles are filtered out anyway

    def genres(self):
        cached = self.cache.get('genres')
        if cached:
            return cached
        response = self.session.get(f'{self.base}/api/explore/availableFilters', timeout=30)
        response.raise_for_status()
        result = sorted(((g['name'], g['id']) for g in response.json().get('genres', [])
                         if g.get('name') and g['name'] not in self._skip), key=lambda x: x[0].lower())
        self.cache.put('genres', result)
        return result

    def browse(self, query='', genre_slug='', page=1, kind=''):
        """kind: 'manga' or 'novel' to show only one of them ('' = both)."""
        if not query and not genre_slug and kind != 'novel':
            response = self.session.get(f'{self.base}/api/home2/recentlyUpdated', timeout=30,
                                        params={'offset': (page - 1) * PAGE_SIZE, 'limit': PAGE_SIZE})
            response.raise_for_status()
            rows = response.json().get('items', [])
            items = [self._latest_item(r) for r in rows if r.get('id') and not (kind and r.get('medium') == 'Novel')]
            return items, len(rows) >= PAGE_SIZE
        # The site's own search index: title search and/or genre, most viewed first. The update feed
        # has hardly any novels, so "novels only" without a search shows the most read ones.
        filters = ['hidden:!=true', 'isAdult:=false']
        if kind:
            filters.append('medium:=Novel' if kind == 'novel' else 'medium:!=Novel')
        if genre_slug:
            filters.append(f'genreIds:={genre_slug}')
        params = {'q': query.strip() or '*', 'query_by': 'title,englishTitle,otherNames',
                  'filter_by': ' && '.join(filters), 'page': page, 'per_page': PAGE_SIZE}
        if not query:
            params['sort_by'] = 'views:desc'
        response = self.session.get(f'{self.base}/collections/manga/documents/search', params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        items = [self._search_item(h.get('document', {})) for h in data.get('hits', [])]
        return [i for i in items if i], data.get('found', 0) > page * PAGE_SIZE

    def _cover(self, path: str) -> str:
        from .atsumaru import static_url
        # Full JPEG: the smaller variants are AVIF, which Qt can't always show.
        return static_url(re.sub(r'-(small|medium|large)\.avif$', '.jpg', path or ''))

    def _url(self, row) -> str:
        """Light novels (text chapters, saved as EPUB) have their own address."""
        kind = 'novel' if row.get('medium') == 'Novel' else 'manga'
        return f"{self.base}/{kind}/{row['id']}"

    def _latest_item(self, row) -> BrowseItem:
        when = ''
        if row.get('updatedAt'):
            minutes = max(0, int((time.time() * 1000 - row['updatedAt']) / 60000))
            when = (f"{minutes} min ago" if minutes < 60 else f"{minutes // 60} h ago" if minutes < 1440
                    else f"{minutes // 1440} d ago")
        return BrowseItem(title=row.get('title', ''), url=self._url(row), site=self.key,
                          cover_url=self._cover(row.get('image', '')),
                          latest=f"Updated {when}" if when else '')

    def _search_item(self, doc) -> Optional[BrowseItem]:
        if not doc.get('id') or not doc.get('title'):
            return None
        count = doc.get('chapterCount')
        return BrowseItem(title=doc['title'], url=self._url(doc), site=self.key,
                          cover_url=self._cover(doc.get('poster', '')),
                          latest=f"{count} chapters" if count else '',
                          status=(doc.get('status') or '').lower(), genres=list(doc.get('tags') or []))


# --------------------------------------------------------------------- MangaBall
class MangaBallBrowser(SiteBrowser):
    key, label = 'mangaball', 'MangaBall'
    api = 'https://api.mangaball.com/api/v1'
    language = 'en'                  # latest updates: titles with new chapters in this language
    _groups = ('genre', 'theme')
    _skip = {'adult', 'hentai', 'smut', 'mature', 'sexual violence'}     # adult titles are filtered out anyway

    def __init__(self):
        super().__init__()
        self.session.headers.update({'Origin': 'https://mangaball.com', 'Referer': 'https://mangaball.com/'})

    def _json(self, method: str, path: str, **kwargs) -> dict:
        response = self.session.request(method, f'{self.api}/{path}', timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()

    def genres(self):
        cached = self.cache.get('genres')
        if cached:
            return cached
        grouped = self._json('GET', 'tag/get-grouped').get('data') or {}
        found = {t['name']: t.get('id') or t.get('_id') for group in self._groups for t in grouped.get(group) or []
                 if t.get('name') and (t.get('id') or t.get('_id')) and t['name'].lower() not in self._skip}
        result = sorted(found.items(), key=lambda x: x[0].lower())
        self.cache.put('genres', result)
        return result

    def browse(self, query='', genre_slug='', page=1):
        params = {'page': page, 'limit': PAGE_SIZE, 'adult_mode': 'no_18'}
        if not query and not genre_slug:
            if self.language:
                params['chapterLanguage'] = self.language
            data = self._json('GET', 'title/recently-updated', params=params)
        else:
            if query:
                params['keyword'] = query.strip()
            if genre_slug:
                params['included_tags'] = genre_slug
            data = self._json('GET', 'title/search-advanced', params=params)
        pages = (data.get('pagination') or {}).get('total_pages') or 0
        items = [self._item(t) for t in data.get('data') or [] if t.get('id') and not t.get('is18plus')]
        return [i for i in items if i], page < pages

    def _item(self, title) -> Optional[BrowseItem]:
        from .mangaball import cover_url
        if not title.get('name'):
            return None
        latest = ''
        recent = [c for c in title.get('recent_chapters') or [] if c.get('lang') == (self.language or c.get('lang'))]
        if recent:
            number = recent[0].get('number')
            when = _ago(recent[0].get('created_at') or '')
            if number is not None:
                latest = f"Chapter {number:g}" if isinstance(number, float) else f"Chapter {number}"
                latest += f" · {when}" if when else ''
        elif title.get('chapters_count'):
            latest = f"{title['chapters_count']} chapters"
        return BrowseItem(title=title['name'], url=f"https://mangaball.com/title-detail/{title['id']}", site=self.key,
                          cover_url=cover_url(title.get('image')), latest=latest,
                          status=(title.get('status') or '').lower(),
                          genres=[t['name'] for t in title.get('tags') or []
                                  if t.get('name') and t.get('group') in self._groups])


def _ago(stamp: str) -> str:
    """'2026-10-23T20:14:15.244000' (UTC) -> '5 h ago'"""
    from datetime import datetime, timezone
    try:
        then = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError:
        return ''
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    minutes = max(0, int((datetime.now(timezone.utc) - then).total_seconds() // 60))
    return (f"{minutes} min ago" if minutes < 60 else f"{minutes // 60} h ago" if minutes < 1440
            else f"{minutes // 1440} d ago")


# ------------------------------------------------------------------ Weeb Central
class WeebCentralBrowser(SiteBrowser):
    key, label = 'weebcentral', 'Weeb Central'
    base = 'https://weebcentral.com'
    _adult = {'Adult', 'Hentai', 'Lolicon', 'Shotacon', 'Smut', 'Mature', 'Ecchi'}

    def genres(self):
        cached = self.cache.get('genres')
        if cached:
            return cached
        soup, _ = self._soup(f'{self.base}/search')
        names = {i['value'] for i in soup.find_all('input', id=re.compile(r'^tag-.+-value$')) if i.get('value')}
        result = sorted(((n, n) for n in names - self._adult), key=lambda x: x[0].lower())
        self.cache.put('genres', result)
        return result

    def browse(self, query='', genre_slug='', page=1):
        if not query and not genre_slug:
            soup, _ = self._soup(f'{self.base}/latest-updates/{page}')
            items = [self._latest_item(a) for a in soup.find_all('article', recursive=False)]
            more = bool(soup.find(attrs={'hx-get': re.compile(rf'/latest-updates/{page + 1}$')}))
            return [i for i in items if i], more
        limit = 32
        params = {'text': query.strip(), 'sort': 'Best Match' if query else 'Popularity', 'order': 'Descending',
                  'official': 'Any', 'anime': 'Any', 'adult': 'False', 'display_mode': 'Full Display',
                  'limit': limit, 'offset': (page - 1) * limit}
        if genre_slug:
            params['included_tag'] = genre_slug
        soup, _ = self._soup(f'{self.base}/search/data', **params)
        items = [self._search_item(a) for a in soup.select('article.bg-base-300')]
        more = bool(soup.find(attrs={'hx-get': re.compile(r'offset=')}))
        return [i for i in items if i], more

    def _latest_item(self, it) -> Optional[BrowseItem]:
        link = it.find('a', href=re.compile(r'^/series/'))
        if not link:
            return None
        chapter = it.select_one('a[href^="/chapters/"] span')
        when = it.find('time')
        img = it.find('img', src=re.compile(r'/cover/'))
        status = it.find('img', src=re.compile(r'icon-(ongoing|complete)'))
        latest = ' · '.join(x for x in (chapter.get_text(strip=True) if chapter else '',
                                         _ago(when['datetime']) if when and when.get('datetime') else '') if x)
        return BrowseItem(title=it.get('data-tip') or (img.get('alt', '').removesuffix(' cover') if img else ''),
                          url=self.base + link['href'], site=self.key, cover_url=img['src'] if img else '',
                          latest=latest,
                          status=('completed' if 'complete' in status['src'] else 'ongoing') if status else '')

    def _search_item(self, it) -> Optional[BrowseItem]:
        link = it.find('a', href=re.compile(r'/series/'))
        if not link:
            return None
        sections = it.find_all('section', recursive=False)
        info = sections[-1] if sections else it
        fields = {}
        for div in info.find_all('div', recursive=False):
            text = div.get_text(' ', strip=True)
            if ':' in text:
                key, value = text.split(':', 1)
                fields[key.strip().lower()] = value.strip()
        title = info.find('div', recursive=False)
        img = it.find('img', src=re.compile(r'/cover/'))
        status = fields.get('status', '').lower()
        href = link['href']
        return BrowseItem(title=title.get_text(' ', strip=True) if title else '',
                          url=href if href.startswith('http') else self.base + href, site=self.key,
                          cover_url=img['src'] if img else '',
                          status={'complete': 'completed', 'canceled': 'cancelled'}.get(status, status),
                          genres=[g.strip() for g in fields.get('tag(s)', '').split(',') if g.strip()])


# ================================================================ novel sites
# Sites with web novels only (text chapters). Explicit titles are left out like on the manga sites;
# "Mature" is kept - on novel sites it marks most cultivation and fantasy stories.
_ADULT = {'adult', 'smut', 'hentai', 'lolicon', 'shotacon'}


def _abs(href: str, base: str) -> str:
    if not href:
        return ''
    if href.startswith('//'):
        return 'https:' + href
    return href if href.startswith('http') else base + '/' + href.lstrip('/')


def _number(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or '')
    return str(int(number)) if number.is_integer() else f"{number:g}"


class _NovelBrowser(SiteBrowser):
    kinds = ('novel',)
    base = ''

    def __init__(self):
        super().__init__()
        self.session.headers['Referer'] = self.base + '/'

    def _json(self, url: str, **params):
        response = self.session.get(url, params=params or None, timeout=30)
        response.raise_for_status()
        return response.json()

    def _next_data(self, url: str, **params) -> dict:
        response = self.session.get(url, params=params or None, timeout=30)
        response.raise_for_status()
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', response.text, re.S)
        return json.loads(match.group(1)).get('props', {}).get('pageProps', {}) if match else {}

    def _cached_genres(self, load) -> List[Tuple[str, str]]:
        cached = self.cache.get('genres')
        if cached:
            return cached
        found = {}
        for name, slug in load():
            if name and slug and genre_key(name) not in _ADULT:
                found.setdefault(name.strip(), slug)
        result = sorted(found.items(), key=lambda x: x[0].lower())
        self.cache.put('genres', result)
        return result


class FreeWebNovelBrowser(_NovelBrowser):
    key, label = 'freewebnovel', 'FreeWebNovel'
    base = 'https://freewebnovel.com'

    def genres(self):
        def load():
            soup, _ = self._soup(f'{self.base}/sort/latest-release')
            for a in soup.find_all('a', href=re.compile(r'^/genre/[^/]+$')):
                yield a.get_text(strip=True), a['href'].split('/genre/', 1)[1]
        return self._cached_genres(load)

    def browse(self, query='', genre_slug='', page=1):
        if query:
            soup, _ = self._soup(f'{self.base}/search', keyword=query, **({'page': page} if page > 1 else {}))
            more = bool(soup.find('a', href=re.compile(rf'[?&]page={page + 1}\b')))
        else:
            path = f'/genre/{genre_slug}' if genre_slug else '/sort/latest-release'
            soup, _ = self._soup(self.base + path + (f'/{page}' if page > 1 else ''))
            more = bool(soup.find('a', href=re.compile(rf'{re.escape(path)}/{page + 1}$')))
        items = [i for i in (self._item(row) for row in soup.select('.li-row')) if i]
        if query and genre_slug:
            wanted = genre_key(genre_slug.replace('+', ' '))
            items = [i for i in items if any(genre_key(g) == wanted for g in i.genres)]
        return items, more

    def _item(self, row) -> Optional[BrowseItem]:
        link = row.select_one('h3.tit a[href]')
        if not link:
            return None
        img = row.select_one('.pic img')
        count = row.select_one('a.chapter .s1')
        return BrowseItem(title=link.get('title') or link.get_text(strip=True), url=_abs(link['href'], self.base),
                          site=self.key, cover_url=_abs(img.get('src', '') if img else '', self.base),
                          latest=count.get_text(strip=True) if count else '',
                          genres=[a.get_text(strip=True) for a in row.select('a[href^="/genre/"]')])


class _HeaderThemeBrowser(_NovelBrowser):
    """Lists of the "novel-header" theme (Novel Fire, Wuxia Box)."""

    def _items(self, soup) -> List[BrowseItem]:
        items = []
        for it in soup.select('li.novel-item'):
            link = it.find('a', href=True)
            title = it.select_one('.novel-title')
            if not link or not title:
                continue
            img = it.find('img')
            src = (img.get('data-src') or img.get('src') or '') if img else ''
            chapter = it.select_one('.chapter-title')
            stats = []
            for span in it.select('.novel-stats span'):
                if 'status' in (span.get('class') or []):
                    continue
                for icon in span.find_all('i'):
                    icon.decompose()             # icon font ligatures ("book", "update")
                text = span.get_text(' ', strip=True)
                if text and 'Rank' not in text:
                    stats.append(text)
            latest = ' · '.join(([chapter.get_text(' ', strip=True)] if chapter else []) + stats[:2])
            status = it.select_one('.status')
            items.append(BrowseItem(title=link.get('title') or title.get_text(' ', strip=True),
                                    url=_abs(link['href'], self.base), site=self.key,
                                    cover_url='' if 'placeholder' in src or src.startswith('data:')
                                    else _abs(src, self.base),
                                    latest=latest, status=status.get_text(strip=True).lower() if status else ''))
        return items


class NovelFireBrowser(_HeaderThemeBrowser):
    key, label = 'novelfire', 'Novel Fire'
    base = 'https://novelfire.net'

    def genres(self):
        def load():
            soup, _ = self._soup(f'{self.base}/genre-all/sort-new/status-all/all-novel')
            for a in soup.find_all('a', href=re.compile(r'/genre-[a-z0-9\-]+/sort-')):
                slug = re.search(r'/genre-([a-z0-9\-]+)/sort-', a['href']).group(1)
                if slug != 'all':
                    yield a.get_text(strip=True), slug
        return self._cached_genres(load)

    def browse(self, query='', genre_slug='', page=1):
        if genre_slug:
            soup, _ = self._soup(f'{self.base}/genre-{genre_slug}/sort-new/status-all/all-novel', page=page)
        elif query:
            soup, _ = self._soup(f'{self.base}/search', keyword=query, page=page)
        else:
            soup, _ = self._soup(f'{self.base}/latest-release-novels', page=page)
        items = [i for i in self._items(soup) if not genre_slug or _matches(i, query)]
        return items, bool(soup.select_one(f'.pagination a[href*="page={page + 1}"]'))


class WuxiaBoxBrowser(_HeaderThemeBrowser):
    key, label = 'wuxiabox', 'Wuxia Box'
    base = 'https://www.wuxiabox.com'

    def __init__(self):
        super().__init__()
        self.session.headers.pop('Referer', None)    # see WuxiaBoxDownloader.send_referer

    def genres(self):
        def load():
            soup, _ = self._soup(f'{self.base}/list/all/all-lastdotime-0.html')
            for a in soup.find_all('a', href=re.compile(r'^/list/[a-z0-9\-]+/all-')):
                slug = a['href'].split('/')[2]
                if slug != 'all':
                    yield a.get_text(strip=True), slug
        return self._cached_genres(load)

    def browse(self, query='', genre_slug='', page=1):
        if query and not genre_slug:
            search_id = self.cache.get(f'search:{query}')
            if not search_id:
                response = self.session.post(f'{self.base}/e/search/index.php', timeout=30,
                                             data={'show': 'title', 'tempid': '1', 'tbname': 'news', 'keyboard': query})
                response.raise_for_status()
                match = re.search(r'searchid=(\d+)', response.url)
                if not match:
                    return [], False
                search_id = match.group(1)
                self.cache.put(f'search:{query}', search_id)
            soup, _ = self._soup(f'{self.base}/e/search/result/index.php', page=page - 1, searchid=search_id)
            return self._items(soup), bool(soup.select_one(f'.pagination a[href*="page={page}&"]'))
        slug = genre_slug or 'all'
        soup, _ = self._soup(f'{self.base}/list/{slug}/all-lastdotime-{page - 1}.html')
        items = [i for i in self._items(soup) if _matches(i, query)]
        return items, bool(soup.select_one(f'.pagination a[href$="all-lastdotime-{page}.html"]'))


class WuxiaClickBrowser(_NovelBrowser):
    key, label = 'wuxiaclick', 'wuxia.click'
    base = 'https://wuxia.click'

    def genres(self):
        return self._cached_genres(lambda: ((g.get('name'), g.get('slug'))
                                            for g in self._next_data(f'{self.base}/browse').get('genres') or []))

    def browse(self, query='', genre_slug='', page=1):
        if query and not genre_slug:
            result = self._next_data(f'{self.base}/search', q=query).get('result') or {}
            return self._items(result), False          # the search has one page
        if genre_slug:
            listing = self._next_data(f'{self.base}/category/{genre_slug}', page=page).get('listing') or {}
        else:
            listing = self._next_data(f'{self.base}/browse', order_by='latest', page=page).get('listing') or {}
        items = [i for i in self._items(listing) if _matches(i, query)]
        return items, page < (listing.get('totalPages') or 0)

    def _items(self, listing) -> List[BrowseItem]:
        from .wuxiaclick import cover_url
        items = []
        for novel in listing.get('items') or []:
            if not novel.get('slug') or novel.get('isAdult'):
                continue
            latest = ''
            if novel.get('latestChapterNumber') is not None:
                when = _ago(novel.get('latestChapterAt') or '')
                latest = f"Chapter {_number(novel['latestChapterNumber'])}" + (f" · {when}" if when else '')
            items.append(BrowseItem(title=novel.get('title', ''), url=f"{self.base}/novel/{novel['slug']}",
                                    site=self.key, cover_url=cover_url(novel), latest=latest,
                                    status=(novel.get('status') or '').lower()))
        return items


class NovelBuddyBrowser(_NovelBrowser):
    key, label = 'novelbuddy', 'NovelBuddy'
    base = 'https://novelbuddy.me'

    def genres(self):
        return self._cached_genres(lambda: ((g.get('name'), g.get('slug'))
                                            for g in self._next_data(f'{self.base}/latest').get('genres') or []))

    def browse(self, query='', genre_slug='', page=1):
        if query and not genre_slug:
            data = self._next_data(f'{self.base}/search', q=query, page=page)
            items, pagination = data.get('ssrItems') or [], data.get('ssrPagination') or {}
        else:
            data = self._next_data(f'{self.base}/genres/{genre_slug}' if genre_slug else f'{self.base}/latest',
                                   page=page)
            items, pagination = data.get('items') or [], data.get('pagination') or {}
        result = [i for i in (self._item(m) for m in items) if i and _matches(i, query)]
        return result, bool(pagination.get('has_next'))

    def _item(self, manga) -> Optional[BrowseItem]:
        if not manga.get('url') or manga.get('isAdult'):
            return None
        chapters = manga.get('latestChapters') or []
        newest = (chapters[0].get('name') or '') if chapters else manga.get('displayChapters', '')
        latest = ' · '.join(x for x in (newest, manga.get('displayUpdatedShort') or '') if x)
        return BrowseItem(title=manga.get('name', ''), url=_abs(manga['url'], self.base), site=self.key,
                          cover_url=manga.get('cover') or '', latest=latest, status=(manga.get('status') or '').lower(),
                          genres=[g['name'] for g in manga.get('genres') or [] if isinstance(g, dict) and g.get('name')])


class NovelArchiveBrowser(_NovelBrowser):
    key, label = 'novelarchive', 'Novel Archive'
    base = 'https://novelarchive.cc'
    # The site has hundreds of fine-grained tags; only the usual genres go into the category list.
    _main = {'action', 'adventure', 'comedy', 'drama', 'fantasy', 'harem', 'historical', 'horror', 'josei',
             'martialarts', 'mecha', 'mystery', 'psychological', 'romance', 'schoollife', 'scifi', 'seinen', 'shoujo',
             'shounen', 'sliceoflife', 'sports', 'supernatural', 'tragedy', 'wuxia', 'xianxia', 'xuanhuan', 'urban',
             'isekai', 'reincarnation', 'system', 'videogames', 'military', 'gamelit', 'litrpg', 'genderbender'}

    def genres(self):
        def load():
            for g in self._json(f'{self.base}/api/novels/genres').get('genres') or []:
                if genre_key(g.get('label', '')) in self._main:
                    yield g['label'], g['value']
        return self._cached_genres(load)

    def browse(self, query='', genre_slug='', page=1):
        params = {'page': page, 'perPage': PAGE_SIZE}
        if query:
            params.update(search=query, fuzzy=1)
        if genre_slug:
            params['genre'] = genre_slug
        data = self._json(f'{self.base}/api/novels', **params)
        items = []
        for novel in data.get('novels') or []:
            genres = [g.strip() for g in (novel.get('genres') or '').split(',') if g.strip()]
            if not novel.get('id') or any(genre_key(g) in _ADULT for g in genres):
                continue
            count, when = novel.get('total_chapters'), novel.get('latest_release') or ''
            latest = ' · '.join(x for x in (f"{count} chapters" if count else '',
                                             '' if when == 'Unknown' else when) if x)
            items.append(BrowseItem(title=html.unescape(novel.get('title', '')),
                                    url=f"{self.base}/novel?id={novel['id']}", site=self.key,
                                    cover_url=_abs(novel.get('cover_url') or '', self.base), latest=latest,
                                    status=(novel.get('release_status') or '').lower(), genres=genres))
        return items, bool((data.get('pagination') or {}).get('has_next'))


class ChikariBrowser(_NovelBrowser):
    key, label = 'chikari', 'chikari.moe'
    base = 'https://chikari.moe'

    def genres(self):
        return self._cached_genres(lambda: ((g.get('name'), g.get('slug'))
                                            for g in self._json(f'{self.base}/api/novels/genres') or []))

    def browse(self, query='', genre_slug='', page=1):
        if query and not genre_slug:
            rows = self._json(f'{self.base}/api/novels/search', q=query)
            return self._items(rows if isinstance(rows, list) else rows.get('items') or []), False
        params = {'limit': PAGE_SIZE, 'offset': (page - 1) * PAGE_SIZE}
        if genre_slug:
            params['genre'] = genre_slug
        data = self._json(f'{self.base}/api/novels', **params)
        items = [i for i in self._items(data.get('items') or []) if _matches(i, query)]
        return items, page * PAGE_SIZE < (data.get('total') or 0)

    def _items(self, rows) -> List[BrowseItem]:
        items = []
        for novel in rows:
            if not novel.get('slug') or novel.get('is_nsfw') or (novel.get('medium') or 'novel') != 'novel':
                continue
            latest = ''
            if novel.get('latest_chapter') is not None:
                when = _ago(novel.get('last_chapter_at') or '')
                latest = f"Chapter {_number(novel['latest_chapter'])}" + (f" · {when}" if when else '')
            status = (novel.get('status') or '').lower()
            items.append(BrowseItem(title=novel.get('title', ''), url=f"{self.base}/novels/{novel['slug']}",
                                    site=self.key, cover_url=novel.get('cover_url') or '', latest=latest,
                                    status='ongoing' if status == 'releasing' else status))
        return items


class CyrisiaBrowser(_NovelBrowser):
    """Everything on Cyrisia: web novels and light novels ('novel') and comics ('manga').

    The site has no categories and no search of its own - it loads its whole shelf
    (/api/bookshelf: name, kind, chapter count, last update) and filters it in the
    browser, which is what a search here does too. Only the names and kinds are kept
    from those ~54,000 rows.
    """
    key, label = 'cyrisia', 'Cyrisia'
    base = 'https://cyrisia.com'
    kinds = ('manga', 'novel')
    _SHELF_TTL = 1800              # the shelf is a big list - reused for half an hour

    def __init__(self):
        super().__init__()
        self.shelf_cache = _Cached(ttl=self._SHELF_TTL)

    def genres(self):
        return []          # the site has no category lists

    def browse(self, query='', genre_slug='', page=1, kind=''):
        """kind: 'manga' (comics) or 'novel' (web and light novels), '' = both."""
        if query:
            wanted = query.lower()
            rows = [r for r in self._shelf() if _of_kind(r[1], kind) and wanted in r[0].lower()]
            chunk = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
            return [self._row_item(r) for r in chunk], len(rows) > page * PAGE_SIZE
        try:
            # The feed of all kinds; 'type=comic' is answered with a proxy error at times.
            data = self._json(f'{self.base}/api/account/catalog/recent', days=60, limit=PAGE_SIZE,
                              offset=(page - 1) * PAGE_SIZE)
            rows = data.get('series') or []
        except (requests.HTTPError, ValueError):
            # The update feed is down now and then; the shelf's own update times stand in.
            shelf = [r for r in self._shelf() if _of_kind(r[1], kind)]
            chunk = shelf[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
            return [self._row_item(r) for r in chunk], len(shelf) > page * PAGE_SIZE
        items = []
        for row in rows:
            if not row.get('name') or not _of_kind(row.get('content_type') or '', kind):
                continue
            when = _ago(row.get('added_at') or '')
            added = row.get('added_volumes') or 0
            items.append(self._item(row['name'], row.get('content_type') or '',
                                    ' · '.join(x for x in (f"+{added} chapters" if added else '', when) if x),
                                    row.get('cover_volume') or ''))
        return items, len(rows) >= PAGE_SIZE

    def _shelf(self) -> List[Tuple[str, str, int]]:
        """[(name, kind, chapter count)] of the whole site, the newest update first."""
        cached = self.shelf_cache.get('shelf')
        if cached is not None:
            return cached
        response = self.session.get(f'{self.base}/api/bookshelf', timeout=120)
        response.raise_for_status()
        rows = sorted((row for row in response.json() if isinstance(row, dict) and row.get('name')),
                      key=lambda row: row.get('updated') or 0, reverse=True)
        result = [(row['name'], row.get('kind') or '', row.get('count') or 0) for row in rows]
        self.shelf_cache.put('shelf', result)
        return result

    def _row_item(self, row: Tuple[str, str, int]) -> BrowseItem:
        name, kind, count = row
        return self._item(name, kind, f"{count} chapters" if count else '')

    def _item(self, name: str, kind: str = '', latest: str = '', cover_file: str = '') -> BrowseItem:
        name_q = quote(name, safe='')
        cover = f"{self.base}/api/cover?series={name_q}" + (f"&v={quote(cover_file, safe='')}" if cover_file else '')
        url = f"{self.base}/series/{name_q}" + (f"?{COMIC_MARKER}" if kind == 'comic' else '')
        return BrowseItem(title=name, url=url, site=self.key, cover_url=cover, latest=latest)


def _of_kind(content_type: str, kind: str) -> bool:
    """Cyrisia's 'comic' is a manga here, its 'webnovel' and 'ln' are novels."""
    if not kind:
        return True
    return (content_type == 'comic') if kind == 'manga' else (content_type != 'comic')


class LnoriBrowser(_NovelBrowser):
    """LNORI keeps its whole library on one page (/library), every series with its title,
    author, year, volume count and tags, and has no search or category page of its own -
    so that page is read once and filtered here. Its order is the site's own ranking."""
    key, label = 'lnori', 'LNORI'
    base = 'https://lnori.com'
    _LIBRARY_TTL = 1800
    _main = NovelArchiveBrowser._main      # the site has 148 tags - only the usual genres

    def __init__(self):
        super().__init__()
        self.library_cache = _Cached(ttl=self._LIBRARY_TTL)

    def genres(self):
        def load():
            soup, _ = self._soup(f'{self.base}/genre')
            for link in soup.select('a[href^="/genre/"]'):
                slug = link['href'].split('/genre/', 1)[1].strip('/')
                name = re.sub(r'^[^\w(]+', '', link.get_text(' ', strip=True))     # '💥 action' -> 'action'
                if slug and genre_key(name) in self._main:
                    yield name.title(), slug
        return self._cached_genres(load)

    def browse(self, query='', genre_slug='', page=1):
        items = self._library()
        if genre_slug:
            wanted = genre_key(genre_slug)
            items = [i for i in items if any(genre_key(g) == wanted for g in i.genres)]
        if query:
            lowered = query.lower()      # title or author, like the site's own search box
            items = [i for i in items if lowered in i.title.lower() or lowered in i.latest.lower()]
        return items[(page - 1) * PAGE_SIZE:page * PAGE_SIZE], len(items) > page * PAGE_SIZE

    def _library(self) -> List[BrowseItem]:
        cached = self.library_cache.get('library')
        if cached is not None:
            return cached
        soup, _ = self._soup(f'{self.base}/library')
        items = []
        for card in soup.select('article.card[data-t]'):
            link = card.select_one('a[href^="/series/"]')
            image = card.find('img')
            if not link:
                continue
            # The site says nothing about a series being finished, so the subtitle carries
            # the author, the volume count and the year - and a search looks through it.
            about = (card.get('data-a') or '', f"{card.get('data-v')} volumes" if card.get('data-v') else '',
                     card.get('data-d') or '')
            items.append(BrowseItem(
                title=card['data-t'], url=_abs(link['href'], self.base), site=self.key,
                cover_url=image.get('src', '') if image else '',
                latest=' · '.join(x for x in about if x),
                genres=[t.strip() for t in (card.get('data-tags') or '').split(',') if t.strip()]))
        self.library_cache.put('library', items)
        return items


BROWSERS = [KatanaBrowser, AsuraBrowser, MangaDexBrowser, WebtoonBrowser, MangaFreakBrowser, AtsumaruBrowser,
            MangaBallBrowser, WeebCentralBrowser,
            FreeWebNovelBrowser, NovelFireBrowser, WuxiaBoxBrowser, WuxiaClickBrowser, NovelBuddyBrowser,
            NovelArchiveBrowser, ChikariBrowser, CyrisiaBrowser, LnoriBrowser]

REFERERS = {
    'mangakatana': 'https://mangakatana.com/',
    'asura': 'https://asurascans.com/',
    'webtoon': 'https://www.webtoons.com/',
    'mangadex': 'https://mangadex.org/',
    'mangafreak': 'https://ww3.mangafreak.me/',
    'atsumaru': 'https://atsu.moe/',
    'mangaball': 'https://mangaball.com/',
    'weebcentral': 'https://weebcentral.com/',
    'freewebnovel': 'https://freewebnovel.com/',
    'novelfire': 'https://novelfire.net/',
    'wuxiabox': '',
    'wuxiaclick': 'https://wuxia.click/',
    'novelbuddy': 'https://novelbuddy.me/',
    'novelarchive': 'https://novelarchive.cc/',
    'chikari': 'https://chikari.moe/',
    'cyrisia': 'https://cyrisia.com/',
    'lnori': 'https://lnori.com/',
}

