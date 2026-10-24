"""
Asura Scans downloader (asurascans.com/comics/...).

The site moved from asuracomic.net/series/<slug> to asurascans.com/comics/<slug>.
Old links are still accepted: asurascans.com redirects old slugs to the current
page, so `canonical_url()` maps them to the new address.

Series and chapter pages are server rendered (Astro); the data lives in
HTML-escaped JSON props, so no browser automation is needed.
"""

import html
import io
import json
import logging
import os
import re
import threading
import time
import zipfile
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import ChapterUnavailable, ComicSiteBase, MangaMetadata, save_file

BASE = "https://asurascans.com"
_NEW_SERIES = re.compile(r'^https?://(?:www\.)?asurascans\.com/comics/([a-z0-9][a-z0-9\-_]*)/?(?:[?#].*)?$', re.I)
_OLD_SERIES = re.compile(r'^https?://(?:www\.)?(?:asuracomic\.net|asuracomics\.com|asuratoon\.com|asura\.gg|asurascans\.com)'
                         r'/(?:series|manga|comics)/([a-z0-9][a-z0-9\-_]*)/?(?:[?#].*)?$', re.I)
_CHAPTER = re.compile(r'^(https?://[^/]+/(?:series|comics|manga)/[a-z0-9\-_]+)/chapter/([\d.]+)', re.I)
_SITE_SUFFIX = re.compile(r'[\s\-–—|]+asura\s*(scans?|comics?|toon|scan)?\s*$', re.I)


def _prop(text: str, name: str) -> str:
    """Read a string field from Astro's serialized props: "name":[0,"value"]."""
    match = re.search(rf'"{name}":\[0,("(?:[^"\\]|\\.)*")\]', text)
    if not match:
        return ''
    try:
        return json.loads(match.group(1)).strip()
    except ValueError:
        return ''


class AsuraComicsDownloader(ComicSiteBase):
    """Asura Scans downloader."""

    def __init__(self):
        super().__init__("AsuraComics", BASE)
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/124.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.7',
            'Referer': BASE + '/',
        })
        self._canonical: Dict[str, str] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- urls
    @classmethod
    def validate_url(cls, url: str) -> bool:
        url = (url or '').strip()
        return bool(_NEW_SERIES.match(url) or _OLD_SERIES.match(url))

    @staticmethod
    def is_legacy_url(url: str) -> bool:
        return bool(_OLD_SERIES.match(url or '')) and not _NEW_SERIES.match(url or '')

    def canonical_url(self, url: str) -> str:
        """Current asurascans.com/comics/... address for any (old or new) series link."""
        url = (url or '').strip()
        if _NEW_SERIES.match(url):
            return url.split('?')[0].split('#')[0].rstrip('/')
        match = _OLD_SERIES.match(url)
        if not match:
            return url
        with self._lock:
            if url in self._canonical:
                return self._canonical[url]
        slug = match.group(1)
        new_url = ''
        try:
            response = self._session.get(f"{BASE}/comics/{slug}", timeout=20, allow_redirects=True)
            if response.ok and _NEW_SERIES.match(response.url):
                new_url = response.url.split('?')[0].rstrip('/')
        except requests.RequestException as e:
            logging.warning(f"Asura redirect lookup failed for {slug}: {e}")
        if not new_url:
            new_url = self._search(self.get_manga_name(url))
        if new_url:
            with self._lock:
                self._canonical[url] = new_url
            logging.info(f"Asura link mapped: {url} -> {new_url}")
            return new_url
        return url

    def _search(self, title: str) -> str:
        """Find a series by title via the browse page (fallback when no redirect exists)."""
        if not title:
            return ''
        try:
            response = self._session.get(f"{BASE}/browse?search={quote_plus(title)}", timeout=20)
            response.raise_for_status()
        except requests.RequestException:
            return ''
        wanted = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        for slug in dict.fromkeys(re.findall(r'/comics/([a-z0-9\-]+)(?=["/?])', response.text)):
            base = re.sub(r'-[0-9a-f]{8}$', '', slug)
            if base == wanted:
                return f"{BASE}/comics/{slug}"
        return ''

    def _chapter_url(self, chapter_url: str) -> str:
        """Rewrite old chapter links onto the current series address."""
        match = _CHAPTER.match(chapter_url or '')
        if not match:
            return chapter_url
        series, number = match.group(1), match.group(2)
        return f"{self.canonical_url(series)}/chapter/{number}"

    def _get(self, url: str, timeout: int = 30) -> requests.Response:
        try:
            response = self._session.get(url, timeout=timeout)
            response.raise_for_status()
            # The site sends no charset, so requests would guess Latin-1 and turn
            # "Mercenary's" into "Mercenaryâs".
            response.encoding = 'utf-8'
            return response
        except requests.RequestException as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            message = {403: "Asura Scans is blocking requests (403).",
                       404: "Asura Scans page not found (404) - the link may have changed.",
                       503: "Asura Scans is having server issues (503)."}.get(status, f"Couldn't reach Asura Scans: {e}")
            raise requests.RequestException(message) from e

    # --------------------------------------------------------- metadata
    def get_manga_name(self, url: str) -> str:
        match = _NEW_SERIES.match(url or '') or _OLD_SERIES.match(url or '')
        slug = match.group(1) if match else urlparse(url).path.rstrip('/').split('/')[-1]
        slug = re.sub(r'-[0-9a-f]{8}$', '', slug)
        return _SITE_SUFFIX.sub('', slug.replace('-', ' ').title()).strip()

    def get_manga_metadata(self, url: str) -> MangaMetadata:
        metadata = MangaMetadata()
        metadata.site_type = 'asura'
        try:
            url = self.canonical_url(url)
            metadata.url = url
            response = self._get(url)
            raw = html.unescape(response.text)
            soup = BeautifulSoup(response.text, 'html.parser')

            h1 = soup.find('h1')
            title = h1.get_text(strip=True) if h1 else ''
            if not title:
                og = soup.find('meta', property='og:title')
                title = og.get('content', '') if og else ''
            metadata.title = _SITE_SUFFIX.sub('', title).strip() or self.get_manga_name(url)

            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                metadata.cover_image_url = urljoin(BASE, og_image['content'])

            metadata.description = _prop(raw, 'description')
            if not metadata.description:
                og_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
                metadata.description = (og_desc.get('content', '') if og_desc else '').strip()
            metadata.description = re.sub(r'\s+', ' ', metadata.description)

            author, artist = _prop(raw, 'author'), _prop(raw, 'artist')
            if author and artist and artist.lower() != author.lower():
                metadata.author = f"{author} / {artist}"
            else:
                metadata.author = author or artist

            status = _prop(raw, 'status').lower()
            metadata.status = {'ongoing': 'ongoing', 'completed': 'completed', 'complete': 'completed',
                               'hiatus': 'hiatus', 'dropped': 'cancelled', 'cancelled': 'cancelled',
                               'season end': 'ongoing'}.get(status, status or 'unknown')

            genres = [a.get_text(strip=True) for a in soup.find_all('a', href=True) if 'genres=' in a['href']]
            metadata.genres = list(dict.fromkeys(g for g in genres if g))
        except Exception as e:
            logging.error(f"Error extracting Asura metadata from {url}: {e}")
            if not metadata.title:
                metadata.title = self.get_manga_name(url)
        return metadata

    # ---------------------------------------------------------- chapters
    def _clean_chapter_name(self, chapter_name: str, chapter_num: str) -> str:
        """Strip 'Chapter N', upload dates and relative times from a chapter label."""
        if not chapter_name:
            return ''
        cleaned = chapter_name
        cleaned = re.sub(rf'^\s*chapter\s*{re.escape(str(chapter_num))}\b', '', cleaned, flags=re.I)
        cleaned = re.sub(r'\b\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago\b', '', cleaned, flags=re.I)
        cleaned = re.sub(r'\b(an?|one)\s+(second|minute|hour|day|week|month|year)\s+ago\b|\blast\s+(week|month|year)\b'
                         r'|\b(yesterday|today|just now)\b', '', cleaned, flags=re.I)
        cleaned = re.sub(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}',
                         '', cleaned, flags=re.I)
        cleaned = re.sub(r'\d{1,4}[/-]\d{1,2}[/-]\d{1,4}', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -–—|:;,')
        if cleaned.lower() in ('', 'chapter', 'ch', 'new', 'first chapter', 'latest chapter'):
            return ''
        return cleaned

    def get_chapter_links(self, url: str) -> List[Tuple[str, str, str]]:
        """Returns (chapter_number, chapter_name, chapter_url) sorted by number."""
        try:
            url = self.canonical_url(url)
            response = self._get(url)
            soup = BeautifulSoup(response.text, 'html.parser')
            series_path = urlparse(url).path.rstrip('/')
            chapters: Dict[str, Tuple[str, str, str]] = {}
            for link in soup.find_all('a', href=True):
                href = link['href']
                match = re.search(r'/chapter/(\d+(?:\.\d+)?)/?$', href)
                if not match or series_path not in urljoin(BASE, href):
                    continue
                number = match.group(1)
                text = link.get_text(' ', strip=True)
                # "First Chapter" / "Latest" shortcut buttons point at real chapters too - skip them
                if not re.match(r'^\s*chapter\s*[\d.]+', text, re.I) and number in chapters:
                    continue
                name = self._clean_chapter_name(text, number)
                if number not in chapters or (name and chapters[number][1] == f"Chapter {number}"):
                    chapters[number] = (number, name or f"Chapter {number}", f"{url}/chapter/{number}")
            free_at = self._early_access_times(response.text)
            return sorted(((n, name, link, free_at.get(n, '')) for n, name, link in chapters.values()),
                          key=lambda c: float(c[0]))
        except Exception as e:
            logging.error(f"Error fetching Asura chapters from {url}: {e}")
            return []

    @staticmethod
    def _early_access_times(page: str) -> Dict[str, str]:
        """Chapter number -> 'early_access_until' from the chapter list props.
        A chapter in the future of that time is still paywalled; is_premium alone isn't
        reliable (it stays true after the chapter became free)."""
        raw = html.unescape(page)
        times: Dict[str, str] = {}
        for match in re.finditer(r'"number":\[0,(\d+(?:\.\d+)?)\](.{0,600}?)"early_access_until":\[0,(?:"([^"]+)"|null)\]',
                                 raw):
            if '"number":[' in match.group(2):
                continue                    # belongs to another chapter object
            number = match.group(1)
            number = str(int(float(number))) if float(number).is_integer() else number
            times.setdefault(number, match.group(3) or '')
        return times

    # ---------------------------------------------------------- download
    def download_chapter_with_name(self, chapter_url: str, chapter_num: str, chapter_name: str, manga_name: str,
                                   base_path: Optional[str] = None, progress_callback: Optional[Callable] = None) -> str:
        chapter_num = str(chapter_num).strip()
        clean = self._clean_chapter_name(chapter_name or '', chapter_num)
        if clean:
            safe = re.sub(r'[<>:"/\\|?*]', '', clean)
            filename = f"Chapter {chapter_num} - {safe}.cbz"
        else:
            filename = f"Chapter {chapter_num}.cbz"
        return self._download(chapter_url, chapter_num, manga_name, base_path, progress_callback, filename)

    def download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str,
                         base_path: Optional[str] = None, progress_callback: Optional[Callable] = None,
                         language: str = "en") -> str:
        return self._download(chapter_url, str(chapter_num).strip(), manga_name, base_path, progress_callback,
                              f"Chapter {str(chapter_num).strip()}.cbz")

    def _page_urls(self, chapter_url: str, chapter_num: str) -> List[str]:
        response = self._get(chapter_url)
        raw = html.unescape(response.text)
        # Only isLocked counts: chapters keep isPremium=true after their early-access period ends.
        if re.search(r'"isLocked":\[0,true\]', raw):
            unlock = re.search(r'"unlockTime":\[0,"([^"]+)"\]', raw)
            when = ''
            if unlock:
                try:
                    stamp = datetime.fromisoformat(unlock.group(1).replace('Z', '+00:00')).astimezone()
                    when = f" It becomes free on {stamp:%d %b %Y at %H:%M}."
                except ValueError:
                    pass
            raise ChapterUnavailable("This chapter is still early access on Asura Scans." + (
                when or " Try again once it is free."))
        # Images live under /chapters/ or, for older re-uploaded chapters, /chapters-restored/
        urls = re.findall(r'"url":\[0,"(https?://[^"]+/chapters[\w-]*/[^"]+)"\]', raw)
        if not urls:
            urls = re.findall(r'(https?://cdn\.asurascans\.com/asura-images/chapters[\w-]*/[^"\'\s<>]+)', raw)
        # Image folders are named after the chapter number (/chapters/x/12/, /chapters-restored/x/12/)
        # or after the chapter's internal id (/chapters-merged/x/152387/).
        keys = [re.escape(str(chapter_num))]
        chapter_id = re.search(r'"chapterId":\[0,(\d+)\]', raw)
        if chapter_id:
            keys.append(chapter_id.group(1))
        key = '|'.join(keys)
        own = [u for u in urls if re.search(rf'/chapters[\w-]*/[^/]+/(?:{key})/', u)]
        if not own:
            own = self._pages_prop(raw)
        # Never fall back to arbitrary pictures on the page (that once produced
        # 1-page "chapters" made of a random image).
        return list(dict.fromkeys(own))

    @staticmethod
    def _pages_prop(raw: str) -> List[str]:
        """URLs from the chapter's own "pages":[1,[...]] prop (bracket-matched)."""
        start = raw.find('"pages":[1,[')
        if start < 0:
            return []
        i, depth = start + len('"pages":'), 0
        for j in range(i, min(len(raw), i + 200_000)):
            if raw[j] == '[':
                depth += 1
            elif raw[j] == ']':
                depth -= 1
                if depth == 0:
                    return re.findall(r'"url":\[0,"(https?://[^"]+)"\]', raw[i:j + 1])
        return []

    @staticmethod
    def _image_count(path: str) -> int:
        try:
            with zipfile.ZipFile(path) as zf:
                return sum(1 for n in zf.namelist()
                           if n.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.avif', '.gif'))
                           and not n.startswith('000_cover'))
        except (OSError, zipfile.BadZipFile):
            return 0

    def _download(self, chapter_url: str, chapter_num: str, manga_name: str, base_path: Optional[str],
                  progress_callback: Optional[Callable], filename: str) -> str:
        chapter_url = self._chapter_url(chapter_url)
        target_dir = self.get_safe_manga_path(manga_name, base_path)
        cbz_path = os.path.join(target_dir, filename)

        pages = self._page_urls(chapter_url, chapter_num)
        if not pages:
            raise ChapterUnavailable("No pages found for this chapter - the site layout may have changed.")

        # Reuse an existing file only if it is complete; broken/partial ones get replaced.
        for name in os.listdir(target_dir):
            if not re.match(rf'^Chapter {re.escape(chapter_num)}(\.cbz$| - )', name):
                continue
            path = os.path.join(target_dir, name)
            if self._image_count(path) >= len(pages):
                return path
            logging.info(f"{path} has fewer pages than the site lists - downloading it again")
            cbz_path = path
            break

        total = len(pages)
        if progress_callback:
            progress_callback(0, total)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as cbz:
            for index, page_url in enumerate(pages, start=1):
                content = None
                for attempt in range(3):
                    try:
                        response = self._session.get(page_url, timeout=30, headers={'Referer': chapter_url})
                        response.raise_for_status()
                        content = response.content
                        break
                    except requests.RequestException as e:
                        if attempt == 2:
                            raise RuntimeError(f"Page {index} failed to download: {e}") from e
                        time.sleep(1 + attempt)
                ext = os.path.splitext(urlparse(page_url).path)[1].lower() or '.webp'
                cbz.writestr(f"{index:03d}{ext}", content)
                if progress_callback:
                    progress_callback(index, total)

        save_file(cbz_path, buffer.getvalue())
        return cbz_path
