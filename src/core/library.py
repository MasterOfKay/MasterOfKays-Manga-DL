"""
Library service: everything about manga and chapters that is not the download
queue itself - looking up links, storing manga, checking for new chapters and
keeping the database in sync with the files on disk.

All network-bound methods block; call them from a worker thread.
"""

import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

from ..managers.database_manager import DatabaseManager, ChapterData, MangaMetadata as DBMetadata
from ..sites import (AsuraComicsDownloader, MangaDexDownloader, MangaFreakDownloader, MangaKatanaDownloader,
                     WebtoonDownloader)
from ..sites.base import ChapterInfo, ComicSiteBase
from .events import EventBus
from .models import ChapterRef, FetchedManga, chapter_file_name, chapter_sort_key, fix_text, plain_text
from .paths import covers_dir, sanitize_folder_name

# Covers saved by older versions: Webtoon's transparent banner layer, MangaDex's small thumbnail.
_LOW_QUALITY_COVER = re.compile(r'EpisodeList_PC_Character|_fg\.png|landingpage|uploads\.mangadex\.org/.+\.512\.jpg$',
                                re.IGNORECASE)
_ASURA_SUFFIX = re.compile(r'[\s\-–—|]+asura\s*(scans?|comics?|toon|scan)?\s*$', re.IGNORECASE)
_BOOK_EXTS = ('.cbz', '.cbr', '.cb7', '.zip', '.pdf', '.epub')
_LANG_TAG = re.compile(r'^\s*\[(?P<tag>[A-Za-z]{2,3}(?:-[A-Za-z]{2})?)\]\s*')
_LANG_SUFFIX = re.compile(r'\.(?P<tag>[a-z]{2}(?:-[a-z]{2})?)$')
_CHAPTER_WORD = re.compile(r'(?:^|[^a-z])(?:chapter|chap|ch|episode|ep)\.?\s*(\d+(?:\.\d+)?)', re.IGNORECASE)
_BARE_NUMBER = re.compile(r'^\s*#?\s*(\d+(?:\.\d+)?)\s*(?:\(\d+\))?\s*$')
_TRAILING_NUMBER = re.compile(r'(?:^|[\s_\-#])(\d+(?:\.\d+)?)\s*(?:\(\d{4}\))?\s*$')
_VOLUME_BEFORE = re.compile(r'(?:\bvol(?:ume)?\.?|\bv|\bseason|\bs)\s*$', re.IGNORECASE)


def normalize_title(title: str) -> str:
    """Loose key for matching a manga title to a folder name:
    case, apostrophes, punctuation and an 'Asura Scans' suffix are ignored."""
    title = _ASURA_SUFFIX.sub('', title or '')
    title = re.sub(r"['’`]", '', title.lower())
    return re.sub(r'[^0-9a-z]+', ' ', title).strip()


def parse_chapter_file(filename: str, folder_title: str = '') -> Optional[Tuple[Optional[str], str]]:
    """(language tag or None, chapter number) for a chapter file, None if it isn't one.

    Understands e.g. 'Chapter 12.cbz', 'Chapter 12 - Name.cbz', '[EN] Vol.1 Chapter 12.cbz',
    'Title-Chapter12.cbz', 'Title 176.cbz', 'Ch. 5.cbz', 'Chapter 5.es.cbz'.
    Volume files ('Title v01.cbz') are skipped - they can't be mapped to chapters.
    """
    stem, ext = os.path.splitext(filename)
    if ext.lower() not in _BOOK_EXTS:
        return None
    language = None
    tag = _LANG_TAG.match(stem)
    if tag:
        language = tag.group('tag').lower()
        stem = stem[tag.end():]
    suffix = _LANG_SUFFIX.search(stem)
    if suffix:
        language = language or suffix.group('tag')
        stem = stem[:suffix.start()]

    match = _CHAPTER_WORD.search(stem)
    if match:
        return language, match.group(1)

    words = normalize_title(folder_title).split()
    if words:
        lowered = re.sub(r"['’`]", '', stem.lower())
        pattern = r'^\W*' + r'\W+'.join(map(re.escape, words)) + r'[\s\-_.#]+(\d+(?:\.\d+)?)(?![\d])'
        match = re.match(pattern, lowered)
        if match:
            return language, match.group(1)

    match = _BARE_NUMBER.match(stem)
    if match:
        return language, match.group(1)

    # "<anything> 01" / "<anything> 391 (2022)" - but not "... v01" / "... Volume 16"
    match = _TRAILING_NUMBER.search(stem)
    if match and not _VOLUME_BEFORE.search(stem[:match.start(1)]):
        return language, match.group(1)
    return None


_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'


def clean_title(title: str, site_type: str) -> str:
    title = (title or '').strip()
    if site_type in ('asura', 'asuracomics'):
        title = _ASURA_SUFFIX.sub('', title).strip() or title
    return title


class Library:
    def __init__(self, db: DatabaseManager, settings, bus: EventBus):
        self.db = db
        self.settings = settings
        self.bus = bus
        self.sites: Dict[str, ComicSiteBase] = {
            'asura': AsuraComicsDownloader(),
            'mangakatana': MangaKatanaDownloader(),
            'webtoon': WebtoonDownloader(),
            'mangadex': MangaDexDownloader(),
            'mangafreak': MangaFreakDownloader(),
        }
        self._folder_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}
        self._folder_lock = threading.Lock()

    # ------------------------------------------------------------------ sites
    def resolve(self, url: str) -> Tuple[Optional[str], Optional[ComicSiteBase]]:
        url = (url or '').strip()
        for key, site in self.sites.items():
            try:
                if site.validate_url(url):
                    return key, site
            except Exception:
                continue
        return None, None

    def canonical_url(self, url: str) -> str:
        """Current address of a series link (sites that moved map old links to new ones)."""
        _key, site = self.resolve(url)
        if site is not None and hasattr(site, 'canonical_url'):
            try:
                return site.canonical_url(url) or url
            except Exception as e:
                logging.warning(f"Could not map {url}: {e}")
        return url

    def clean_titles(self) -> int:
        """Strip site suffixes ("Infinite Mage - Asura Scans" -> "Infinite Mage") from stored
        titles. If the clean title already exists, the two entries are merged."""
        changed = 0
        for manga in self.db.get_manga_list():
            title = manga['title']
            clean = _ASURA_SUFFIX.sub('', title).strip()
            if not clean or clean == title:
                continue
            keeper = self.db.get_manga_by_title(clean)
            if keeper and keeper['id'] != manga['id']:
                self.db.merge_manga(keeper['id'], manga['id'])
                logging.info(f"Merged duplicate '{title}' into '{clean}'")
            else:
                self.db.rename_manga_title(manga['id'], clean)
                logging.info(f"Renamed '{title}' -> '{clean}'")
            changed += 1
        return changed

    def migrate_links(self) -> int:
        """Update stored links of sites that moved (e.g. asuracomic.net -> asurascans.com)."""
        changed = 0
        for manga in self.db.get_manga_list():
            url = manga.get('url') or ''
            _key, site = self.resolve(url)
            if site is None or not getattr(site, 'is_legacy_url', lambda _u: False)(url):
                continue
            new_url = self.canonical_url(url)
            if new_url and new_url != url:
                self.db.update_manga_url(manga['id'], new_url)
                changed += 1
                logging.info(f"Updated link of {manga['title']}: {url} -> {new_url}")
        return changed

    def fix_metadata(self) -> int:
        """One-off repairs of stored metadata: HTML in descriptions, and low quality covers
        (Webtoon's transparent banner layer instead of the poster, MangaDex thumbnails)."""
        from .metadata_files import _png_bytes
        fixed = 0
        for manga in self.db.get_manga_list():
            full = self.db.get_manga_by_id(manga['id']) or {}
            description = full.get('description') or ''
            if plain_text(description) != description:
                self.db.update_manga_description(manga['id'], plain_text(description))
                fixed += 1
            if not _LOW_QUALITY_COVER.search(full.get('cover_image_url') or ''):
                continue
            _key, site = self.resolve(full.get('url') or '')
            if not site:
                continue
            try:
                old = full.get('cover_image_path') or ''
                if old and os.path.exists(old):
                    os.remove(old)          # download_cover() reuses an existing file
                full['cover_image_path'] = ''
                self._refresh_metadata(full, site)
                new = (self.db.get_manga_by_id(manga['id']) or {}).get('cover_image_path') or ''
                folder = os.path.join(self.download_root(), sanitize_folder_name(full['title']))
                if new and os.path.exists(new) and os.path.exists(os.path.join(folder, 'cover.png')):
                    with open(os.path.join(folder, 'cover.png'), 'wb') as f:
                        f.write(_png_bytes(new))
                fixed += 1
                logging.info(f"Replaced the cover of {full['title']}")
            except Exception as e:
                logging.warning(f"Couldn't replace the cover of {full.get('title')}: {e}")
        return fixed

    def supported_sites(self) -> List[str]:
        return ['Asura Comics', 'MangaKatana', 'Webtoon', 'MangaDex', 'MangaFreak']

    # ---------------------------------------------------------------- folders
    def download_root(self) -> str:
        return self.settings.get_download_path()

    def manga_folder(self, title: str) -> str:
        """Folder of a manga: the exact name if it exists, otherwise an existing
        folder whose name matches loosely (e.g. "Omniscient Reader's Viewpoint"
        -> "Omniscient Readers Viewpoint"), otherwise the exact name (to be created)."""
        root = self.download_root()
        # Never put site branding like "- Asura Scans" into the folder name.
        title = _ASURA_SUFFIX.sub('', title or '').strip() or title
        exact = os.path.join(root, sanitize_folder_name(title))
        if os.path.isdir(exact):
            return exact
        match = self._folder_index(root).get(normalize_title(title))
        return os.path.join(root, match) if match else exact

    def _folder_index(self, root: str) -> Dict[str, str]:
        """normalized name -> folder name, cached briefly (network shares are slow to list)."""
        with self._folder_lock:
            cached = self._folder_cache.get(root)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
        index: Dict[str, str] = {}
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.is_dir():
                        index.setdefault(normalize_title(entry.name), entry.name)
        except OSError as e:
            logging.warning(f"Could not list {root}: {e}")
        with self._folder_lock:
            self._folder_cache[root] = (time.monotonic(), index)
        return index

    # ------------------------------------------------------------------ reads
    def list_manga(self) -> List[Dict]:
        return self.db.get_manga_list()

    def get_manga(self, manga_id: int) -> Optional[Dict]:
        return self.db.get_manga_by_id(manga_id)

    def chapters(self, manga_id: int) -> List[ChapterRef]:
        return [self._ref_from_row(row) for row in self.db.get_chapters_for_manga(manga_id)]

    def mark_seen(self, manga_id: int) -> None:
        self.db.clear_new_flags(manga_id)
        self.bus.emit('library_changed', manga_id)

    def remove(self, manga_id: int) -> None:
        self.db.delete_manga_by_id(manga_id)
        self.bus.emit('library_changed', manga_id)

    # ---------------------------------------------------------------- network
    def fetch(self, url: str) -> FetchedManga:
        """Look a link up on its site. Nothing is stored yet."""
        original = url.strip()
        key, site = self.resolve(original)
        if not site:
            raise ValueError("This link isn't from a supported site.")
        url = self.canonical_url(original)

        meta = site.get_manga_metadata(url)
        for attr in ('title', 'description', 'author'):
            setattr(meta, attr, fix_text(getattr(meta, attr, '') or ''))
        meta.description = plain_text(meta.description)
        title = clean_title(fix_text(getattr(meta, 'title', '') or site.get_manga_name(url)), key)
        existing = (self.db.get_manga_by_url(url) or self.db.get_manga_by_url(original)
                    or self.db.get_manga_by_title(title))

        chapters = self._fetch_chapters(key, site, url, existing['id'] if existing else None)
        if not chapters:
            raise ValueError("No chapters found. The link may be wrong or the site is unreachable.")

        cover = ''
        if getattr(meta, 'cover_image_url', ''):
            cover = self.download_cover(meta.cover_image_url, title)
        if not cover and existing:
            cover = existing.get('cover_image_path') or ''

        return FetchedManga(url=url, site_type=key, title=title, metadata=meta,
                            chapters=chapters, cover_path=cover,
                            manga_id=existing['id'] if existing else None)

    def register(self, fetched: FetchedManga) -> int:
        """Store a fetched manga (or merge into the existing entry). Returns its id."""
        meta = fetched.metadata
        now = datetime.now().isoformat()
        manga_id = self.db.add_or_update_manga(DBMetadata(
            title=fetched.title,
            url=fetched.url,
            site_type=fetched.site_type,
            description=fix_text(getattr(meta, 'description', '') or ''),
            author=fix_text(getattr(meta, 'author', '') or ''),
            genres=list(getattr(meta, 'genres', []) or []),
            status=getattr(meta, 'status', '') or 'unknown',
            release_date=getattr(meta, 'release_date', '') or '',
            alternative_names=list(getattr(meta, 'alternative_names', []) or []),
            cover_image_url=getattr(meta, 'cover_image_url', '') or '',
            language='en',
            translation_type=getattr(meta, 'translation_type', '') or 'official',
            last_updated=now,
            first_download=now,
        ), fetched.cover_path)

        rows = [self._chapter_data(ref) for refs in fetched.chapters.values() for ref in refs]
        self.db.merge_chapters(manga_id, rows, mark_new=False)
        self.db.set_last_checked(manga_id)
        self.sync_files(manga_id)
        self.bus.emit('library_changed', manga_id)
        return manga_id

    def refresh(self, manga_id: int, with_metadata: bool = False) -> List[ChapterRef]:
        """Check the site for chapters we don't know yet. Returns the new ones
        (only in languages the user actually follows)."""
        manga = self.db.get_manga_by_id(manga_id)
        if not manga or not manga.get('url'):
            raise ValueError("This manga has no source link.")
        key, site = self.resolve(manga['url'])
        if not site:
            raise ValueError("The source link is no longer supported.")
        url = self.canonical_url(manga['url'])
        if url != manga['url']:
            self.db.update_manga_url(manga_id, url)
            manga['url'] = url

        fetched = self._fetch_chapters(key, site, url, manga_id)
        if not fetched:
            raise RuntimeError("The site returned no chapters (it may be down).")

        known = self.db.get_chapters_for_manga(manga_id)
        followed = {c['language'] for c in known if c['is_downloaded']} or {'en'}
        first_scan = not known

        new_refs: List[ChapterRef] = []
        for language, refs in fetched.items():
            interesting = not first_scan and (key != 'mangadex' or language in followed)
            inserted = self.db.merge_chapters(manga_id, [self._chapter_data(r) for r in refs], mark_new=interesting)
            if interesting:
                inserted_keys = {(c.language, c.chapter_number) for c in inserted}
                new_refs.extend(r for r in refs if r.key in inserted_keys)

        if key == 'mangadex':
            # MangaDex deletes chapters (takedowns, re-uploads under a new id). The API always
            # returns the full list, so anything not in it is gone - downloaded files are kept.
            listed = {r.key for refs in fetched.values() for r in refs}
            removed = self.db.remove_missing_chapters(manga_id, listed)
            if removed:
                logging.info(f"{manga['title']}: removed {removed} chapters that are no longer on MangaDex")

        if with_metadata or self._needs_metadata(manga):
            try:
                self._refresh_metadata(manga, site)
            except Exception as e:
                logging.warning(f"Metadata refresh failed for {manga['title']}: {e}")

        # Chapters may already exist on disk (e.g. downloaded elsewhere into the same folder).
        self.sync_files(manga_id)
        self.db.set_last_checked(manga_id)
        self.bus.emit('library_changed', manga_id)
        downloaded = {r.key for r in self.chapters(manga_id) if r.downloaded}
        new_refs = [r for r in new_refs if r.key not in downloaded]
        return sorted(new_refs, key=lambda r: chapter_sort_key(r.number))

    # ------------------------------------------------------------ disk sync
    def sync_files(self, manga_id: int) -> int:
        """Align download flags in the database with the CBZ files on disk."""
        manga = self.db.get_manga_by_id(manga_id)
        if not manga:
            return 0
        if not os.path.isdir(self.download_root()):
            return 0        # e.g. network share offline - never reset anything then
        folder = self.manga_folder(manga['title'])
        is_mangadex = manga.get('site_type') == 'mangadex'
        if not os.path.isdir(folder):
            # Nothing of this manga is in the library folder (yet).
            changed = 0
            for ch in self.db.get_chapters_for_manga(manga_id):
                if ch['is_downloaded']:
                    self.db.reset_chapter_download_status(manga_id, ch['chapter_number'],
                                                          language=ch['language'] if is_mangadex else None)
                    changed += 1
            return changed

        folder_title = os.path.basename(folder)
        on_disk: Dict[Tuple[Optional[str], str], str] = {}
        try:
            names = sorted(os.listdir(folder))
        except OSError as e:
            logging.warning(f"Could not scan {folder}: {e}")
            return 0
        for name in names:
            parsed = parse_chapter_file(name, folder_title)
            if not parsed:
                continue
            language, number = parsed
            language = (language or 'en') if is_mangadex else None
            on_disk.setdefault((language, self._norm(number)), os.path.join(folder, name))

        changed = 0
        for ch in self.db.get_chapters_for_manga(manga_id):
            number = ch['chapter_number']
            language = ch['language'] if is_mangadex else None
            # A copy left in an old download location doesn't count - only the current folder does.
            stored = ch['file_path'] or ''
            path = stored if stored and self._inside(stored, folder) and os.path.exists(stored) else None
            disk_key = ((language or 'en').lower() if is_mangadex else None, self._norm(number))
            path = path or on_disk.get(disk_key)
            moved = bool(path) and os.path.normcase(os.path.normpath(path)) != os.path.normcase(os.path.normpath(stored))
            if path and (not ch['is_downloaded'] or moved):      # new, or renamed/moved on disk
                self.db.mark_chapter_downloaded(manga_id, number, path, language=language)
                changed += 1
            elif not path and ch['is_downloaded']:
                self.db.reset_chapter_download_status(manga_id, number, language=language)
                changed += 1
        return changed

    @staticmethod
    def first_chapter_number(rows: List[Dict]) -> Optional[str]:
        """Lowest chapter number among DB rows (the chapter that carries the description)."""
        numbers = [r['chapter_number'] for r in rows]
        return min(numbers, key=chapter_sort_key) if numbers else None

    def chapter_total(self, manga_id: int) -> int:
        rows = self.db.get_chapters_for_manga(manga_id)
        return len({r['chapter_number'] for r in rows})

    def write_metadata(self, manga_id: int, overwrite: bool = False) -> Dict[str, int]:
        """(Re)write metadata for a manga that is already on disk: folder files plus
        ComicInfo.xml inside every downloaded chapter archive, according to the settings."""
        from .metadata_files import embed_chapter_metadata, write_folder_metadata
        manga = self.db.get_manga_by_id(manga_id)
        result = {'added': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0, 'error': 0, 'folder_files': 0}
        if not manga:
            return result
        folder = self.manga_folder(manga['title'])
        if not os.path.isdir(folder):
            return result
        rows = self.db.get_chapters_for_manga(manga_id)
        total = len({r['chapter_number'] for r in rows})
        result['folder_files'] = len(write_folder_metadata(manga, folder, self.settings, total, force=overwrite))
        on_disk = [r for r in rows if r.get('is_downloaded') and r.get('file_path') and os.path.exists(r['file_path'])]
        first = self.first_chapter_number(on_disk)
        for row in on_disk:
            path = row['file_path']
            ref = self._ref_from_row(row)
            chapter = {'number': ref.number, 'name': ref.display_name, 'language': ref.language, 'volume': ref.volume,
                       'is_first': ref.number == first}
            status = embed_chapter_metadata(path, manga, chapter, self.settings, total, folder, overwrite)
            result[status] = result.get(status, 0) + 1
        return result

    @staticmethod
    def name_chapter_file(path: str, ref: ChapterRef) -> str:
        """'Chapter 1.cbz' -> 'Chapter 1 - Chirp!.cbz' when the chapter has a real name.
        Other file names (already named, MangaDex style, ...) are left alone."""
        if not path or not re.fullmatch(rf'Chapter {re.escape(ref.number)}\.cbz', os.path.basename(path), re.I):
            return path
        target = os.path.join(os.path.dirname(path), chapter_file_name(ref.number, ref.name))
        if os.path.normcase(target) == os.path.normcase(path):
            return path
        try:
            os.replace(path, target)
            return target
        except OSError as e:
            logging.warning(f"Couldn't rename {path} to {os.path.basename(target)}: {e}")
            return path

    def add_chapter_names(self, manga_id: Optional[int] = None, dry_run: bool = False) -> List[Tuple[str, str]]:
        """Rename downloaded 'Chapter N.cbz' files to 'Chapter N - Name.cbz' and rewrite the
        title inside them. Only files in the current download folder. Returns (old, new) names."""
        from .metadata_files import embed_chapter_metadata
        done: List[Tuple[str, str]] = []
        mangas = [self.db.get_manga_by_id(manga_id)] if manga_id else self.db.get_manga_list()
        for manga in filter(None, mangas):
            if manga.get('site_type') == 'mangadex':
                continue
            manga = self.db.get_manga_by_id(manga['id']) or manga
            folder = self.manga_folder(manga['title'])
            rows = self.db.get_chapters_for_manga(manga['id'])
            total = len({r['chapter_number'] for r in rows})
            on_disk = [r for r in rows if r.get('is_downloaded') and r.get('file_path')
                       and self._inside(r['file_path'], folder) and os.path.exists(r['file_path'])]
            first = self.first_chapter_number(on_disk)
            for row in on_disk:
                ref = self._ref_from_row(row)
                old = row['file_path']
                target = os.path.join(os.path.dirname(old), chapter_file_name(ref.number, ref.name))
                if os.path.basename(target) == os.path.basename(old) or not re.fullmatch(
                        rf'Chapter {re.escape(ref.number)}\.cbz', os.path.basename(old), re.I):
                    continue
                if dry_run:
                    done.append((old, target))
                    continue
                new = self.name_chapter_file(old, ref)
                if new == old:
                    continue
                self.db.mark_chapter_downloaded(manga['id'], ref.number, new, language=None)
                chapter = {'number': ref.number, 'name': ref.display_name, 'language': ref.language,
                           'volume': ref.volume, 'is_first': ref.number == first}
                embed_chapter_metadata(new, manga, chapter, self.settings, total, folder, overwrite=True)
                done.append((old, new))
                logging.info(f"Renamed {old} -> {os.path.basename(new)}")
        return done

    def sync_all(self) -> None:
        for manga in self.db.get_manga_list():
            try:
                self.sync_files(manga['id'])
            except Exception as e:
                logging.error(f"Sync failed for {manga.get('title')}: {e}")

    # ---------------------------------------------------------------- covers
    def download_cover(self, cover_url: str, title: str) -> str:
        if not cover_url:
            return ''
        try:
            safe = re.sub(r'[<>:"/\\|?*]', '_', title)
            ext = os.path.splitext(cover_url.split('?')[0])[1] or '.jpg'
            path = os.path.join(covers_dir(), f"{safe}_cover{ext}")
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
            headers = {'User-Agent': _UA, 'Accept': 'image/avif,image/webp,image/png,image/*,*/*;q=0.8'}
            if 'webtoon' in cover_url or 'pstatic.net' in cover_url:
                headers['Referer'] = 'https://www.webtoons.com/'
            elif 'asura' in cover_url:
                headers['Referer'] = 'https://asuracomic.net/'
            elif 'mangadex' in cover_url:
                headers['Referer'] = 'https://mangadex.org/'
            elif 'mangafreak' in cover_url:
                headers['Referer'] = 'https://ww3.mangafreak.me/'
            response = requests.get(cover_url, headers=headers, timeout=30)
            response.raise_for_status()
            with open(path, 'wb') as f:
                f.write(response.content)
            return path
        except Exception as e:
            logging.warning(f"Cover download failed ({cover_url}): {e}")
            return ''

    # --------------------------------------------------------------- helpers
    def _fetch_chapters(self, key: str, site: ComicSiteBase, url: str,
                        manga_id: Optional[int]) -> Dict[str, List[ChapterRef]]:
        if key == 'webtoon' and manga_id:
            items = site.get_chapter_links(url, db_manager=self.db, manga_id=manga_id)  # incremental scan
        else:
            items = site.get_chapter_links(url)

        by_language: Dict[str, Dict[str, ChapterRef]] = {}
        for item in items or []:
            if isinstance(item, ChapterInfo):
                number = str(item.chapter_number or '0')
                ref = ChapterRef(number=number, name=fix_text(item.title) or f"Chapter {number}",
                                 url=item.chapter_url or item.chapter_id, language=(item.language or 'en'),
                                 volume=item.volume_number or '', group=item.scanlation_group or '')
            elif isinstance(item, (tuple, list)) and len(item) >= 3:
                ref = ChapterRef(number=str(item[0]), name=fix_text(str(item[1] or '')), url=str(item[2] or ''),
                                 free_at=str(item[3] or '') if len(item) > 3 else '')
            else:
                continue
            by_language.setdefault(ref.language, {}).setdefault(ref.number, ref)

        return {lang: sorted(refs.values(), key=lambda r: chapter_sort_key(r.number))
                for lang, refs in by_language.items()}

    def _needs_metadata(self, manga: Dict) -> bool:
        cover = manga.get('cover_image_path') or ''
        return not cover or not os.path.exists(cover) or not (manga.get('description') or '').strip()

    def _refresh_metadata(self, manga: Dict, site: ComicSiteBase) -> None:
        meta = site.get_manga_metadata(manga['url'])
        cover = manga.get('cover_image_path') or ''
        if getattr(meta, 'cover_image_url', '') and (not cover or not os.path.exists(cover)):
            cover = self.download_cover(meta.cover_image_url, manga['title'])
        self.db.add_or_update_manga(DBMetadata(
            title=manga['title'],
            url=manga['url'],
            site_type=manga['site_type'],
            description=plain_text(fix_text(getattr(meta, 'description', '') or '')),
            author=fix_text(getattr(meta, 'author', '') or ''),
            genres=list(getattr(meta, 'genres', []) or []),
            status=getattr(meta, 'status', '') or 'unknown',
            release_date=getattr(meta, 'release_date', '') or '',
            alternative_names=list(getattr(meta, 'alternative_names', []) or []),
            cover_image_url=getattr(meta, 'cover_image_url', '') or '',
            language='en',
            translation_type=getattr(meta, 'translation_type', '') or 'official',
        ), cover)

    @staticmethod
    def _inside(path: str, folder: str) -> bool:
        def canon(p: str) -> str:
            return os.path.normcase(os.path.normpath(os.path.abspath(p)))
        try:
            return os.path.commonpath([canon(path), canon(folder)]) == canon(folder)
        except ValueError:          # different drives / UNC vs local
            return False

    @staticmethod
    def _norm(number: str) -> str:
        try:
            value = float(number)
            return str(int(value)) if value.is_integer() else str(value)
        except (TypeError, ValueError):
            return str(number).strip()

    @staticmethod
    def _chapter_data(ref: ChapterRef) -> ChapterData:
        return ChapterData(chapter_number=ref.number, chapter_name=ref.name or f"Chapter {ref.number}",
                           chapter_url=ref.url, language=ref.language, volume_number=ref.volume,
                           free_at=ref.free_at)

    @staticmethod
    def _ref_from_row(row: Dict) -> ChapterRef:
        return ChapterRef(number=row['chapter_number'], name=row.get('chapter_name') or '',
                          url=row.get('chapter_url') or '', language=row.get('language') or 'en',
                          volume=row.get('volume_number') or '', downloaded=bool(row.get('is_downloaded')),
                          is_new=bool(row.get('is_new')), file_path=row.get('file_path') or '',
                          free_at=row.get('free_at') or '')
