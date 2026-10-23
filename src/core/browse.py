"""
Browse service: latest updates, search and categories across all sites.

Categories are merged by a normalized key, so picking "Isekai" uses each site's
own slug (MangaKatana "isekai", Asura "isekai", MangaDex tag id, ...). Sites that
have no such category are reported as unsupported for that filter.
"""

import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from ..sites.browsing import BROWSERS, REFERERS, UA, BrowseItem, genre_key
from .library import normalize_title
from .paths import data_dir


@dataclass
class Category:
    key: str
    name: str
    slugs: Dict[str, str] = field(default_factory=dict)     # site key -> site slug


class BrowseService:
    def __init__(self, library, settings):
        self.library = library
        self.settings = settings
        self.browsers = {}
        for cls in BROWSERS:
            browser = cls()
            if browser.key == 'mangadex':
                browser.language = settings.get('browse.mangadex_language', 'en') or ''
            self.browsers[browser.key] = browser
        self._categories: Optional[List[Category]] = None
        self.thumbs_dir = os.path.join(data_dir(), 'thumbs')
        os.makedirs(self.thumbs_dir, exist_ok=True)

    def sites(self) -> List[Tuple[str, str]]:
        return [(b.key, b.label) for b in self.browsers.values()]

# Categories are merged by a normalized key, so picking "Isekai" uses each site's
# own slug (MangaKatana "isekai", Asura "isekai", MangaDex tag id, ...). 
# Sites that have no such category are reported as unsupported for that filter.
    def categories(self) -> List[Category]:
        """Union of all sites' categories (blocking; fetched once per session)."""
        if self._categories is not None:
            return self._categories
        merged: Dict[str, Category] = {}

        def load(browser):
            try:
                return browser.key, browser.genres()
            except Exception as e:
                logging.warning(f"Could not load categories from {browser.label}: {e}")
                return browser.key, []

        with ThreadPoolExecutor(max_workers=len(self.browsers)) as pool:
            for site, genres in pool.map(load, self.browsers.values()):
                for name, slug in genres:
                    key = genre_key(name)
                    if not key:
                        continue
                    category = merged.setdefault(key, Category(key, name))
                    category.slugs.setdefault(site, slug)
        self._categories = sorted(merged.values(), key=lambda c: c.name.lower())
        return self._categories

    def category(self, key: str) -> Optional[Category]:
        return next((c for c in self._categories or [] if c.key == key), None)

# Browse service: latest updates, search and categories across all sites.
    def supports(self, site: str, category_key: str) -> bool:
        if not category_key:
            return True
        category = self.category(category_key)
        return bool(category and site in category.slugs)

    def browse(self, site: str, query: str = '', category_key: str = '', page: int = 1) -> Tuple[List[BrowseItem], bool]:
        browser = self.browsers[site]
        slug = ''
        if category_key:
            category = self.category(category_key)
            slug = category.slugs.get(site, '') if category else ''
            if not slug:
                return [], False
        return browser.browse(query=query.strip(), genre_slug=slug, page=page)

# Libary index for "In library" badges, so we can show which manga are already in the user's library.
    def library_index(self) -> Tuple[Dict[str, int], Dict[str, int]]:
        """(url -> manga id, normalized title -> manga id) for "In library" badges."""
        by_url, by_title = {}, {}
        for manga in self.library.list_manga():
            if manga.get('url'):
                by_url[manga['url'].rstrip('/')] = manga['id']
            by_title[normalize_title(manga.get('title', ''))] = manga['id']
        return by_url, by_title

    @staticmethod
    def find_in_library(item: BrowseItem, index) -> Optional[int]:
        by_url, by_title = index
        return by_url.get(item.url.rstrip('/')) or by_title.get(normalize_title(item.title))

# Thumbnail caching for cover images, so we don't have to download them every time.
    def thumbnail(self, url: str, site: str) -> str:
        """Download (once) and return a local path for a cover thumbnail."""
        if not url:
            return ''
        ext = os.path.splitext(url.split('?')[0])[1].lower()
        ext = ext if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif') else '.jpg'
        path = os.path.join(self.thumbs_dir, hashlib.sha1(url.encode('utf-8')).hexdigest() + ext)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        browser = self.browsers.get(site)
        session = browser.session if browser else requests
        headers = {'User-Agent': UA, 'Referer': REFERERS.get(site, ''),
                   'Accept': 'image/avif,image/webp,image/png,image/*,*/*;q=0.8'}
        try:
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            tmp = path + '.part'
            with open(tmp, 'wb') as f:
                f.write(response.content)
            os.replace(tmp, path)
            return path
        except Exception as e:
            logging.debug(f"Thumbnail failed {url}: {e}")
            return ''
