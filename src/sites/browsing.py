"""
Browsing the sites: latest updates, search and categories.

Each browser returns BrowseItem lists and knows its own category slugs. Combined
"search + category" requests are done server-side where the site supports it and
filtered locally otherwise.
"""

import html
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from .base import fix_text

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


BROWSERS = [KatanaBrowser, AsuraBrowser, MangaDexBrowser, WebtoonBrowser, MangaFreakBrowser]

REFERERS = {
    'mangakatana': 'https://mangakatana.com/',
    'asura': 'https://asurascans.com/',
    'webtoon': 'https://www.webtoons.com/',
    'mangadex': 'https://mangadex.org/',
    'mangafreak': 'https://ww3.mangafreak.me/',
}

