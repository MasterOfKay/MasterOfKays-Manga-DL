"""
Metadata files for media servers and readers.

What each server reads (checked against their source code):

* Komga    - ComicInfo.xml *inside* each CBZ (book title/number/summary/authors/genres/
             language/reading direction/Count), Mylar `series.json` in the series folder
             (series summary, status, publisher - "Import Mylar metadata" library option),
             series poster `cover|folder|poster|series|default.<img>` in the folder.
* Kavita   - ComicInfo.xml inside each CBZ, cover.* in the folder.
* Jellyfin - Bookshelf plugin: ComicInfo.xml inside the CBZ, else `<chapter>.xml` next to it,
             else ComicInfo.xml in the folder (per book, no series level); folder/poster/cover image.

The settings decide which of these files are written.
"""

import io
import json
import logging
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from typing import Dict, List, Optional
from xml.sax.saxutils import escape

from .models import fix_text, site_label

COMICINFO = 'ComicInfo.xml'
COVER_PAGE = '000_cover.png'       # sorts before every real page, so it becomes the thumbnail
ARCHIVE_EXTS = ('.cbz', '.zip')

# Settings presets for the "Quick setup" buttons.
PRESETS = {
    'komga': {'download.embed_comicinfo_in_cbz': True, 'download.save_series_json': True,
              'download.save_cover': True, 'download.save_comicinfo': False},
    'kavita': {'download.embed_comicinfo_in_cbz': True, 'download.save_series_json': False,
               'download.save_cover': True, 'download.save_comicinfo': False},
    'jellyfin': {'download.embed_comicinfo_in_cbz': True, 'download.save_series_json': False,
                 'download.save_cover': True, 'download.save_comicinfo': True},
    'all': {'download.embed_comicinfo_in_cbz': True, 'download.save_series_json': True,
            'download.save_cover': True, 'download.save_comicinfo': True},
    'none': {'download.embed_comicinfo_in_cbz': False, 'download.save_series_json': False,
             'download.save_cover': False, 'download.save_comicinfo': False,
             'download.embed_cover_in_cbz': False},
}


# ------------------------------------------------------------------ helpers
def _genres(manga: Dict) -> List[str]:
    value = manga.get('genres')
    if isinstance(value, list):
        return [g for g in value if g]
    if isinstance(value, str) and value:
        try:
            return [g for g in json.loads(value) if g]
        except ValueError:
            return [g.strip() for g in value.split(',') if g.strip()]
    return []


def _people(manga: Dict) -> tuple:
    """(writer, artist) from our combined author field ("Writer / Artist")."""
    author = (manga.get('author') or '').strip()
    if not any(ch.isalnum() for ch in author):
        return '', ''
    author = re.sub(r'^artist:\s*', '', author, flags=re.I)
    parts = [p.strip() for p in author.split(' / ') if p.strip()]
    writer = parts[0] if parts else ''
    artist = parts[1] if len(parts) > 1 else ''
    return writer, artist


def _status(manga: Dict) -> str:
    return (manga.get('status') or '').lower()


def _el(name: str, value) -> str:
    if value is None or value == '':
        return ''
    return f"    <{name}>{escape(unicodedata.normalize('NFC', fix_text(str(value))))}</{name}>\n"


def _comicinfo(fields: List[tuple]) -> str:
    body = ''.join(_el(k, v) for k, v in fields)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<ComicInfo xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n' + body + '</ComicInfo>\n')


def _series_fields(manga: Dict, settings, total: int, language: str) -> List[tuple]:
    writer, artist = _people(manga)
    rtl = settings.get('metadata.reading_direction', 'ltr') == 'rtl'
    count = total if _status(manga) in ('completed', 'ended') and total else None
    return [
        ('Series', manga.get('title', '')),
        ('Count', count),
        ('Writer', writer),
        ('Penciller', artist),
        ('Publisher', site_label(manga.get('site_type', '')) if settings.get('metadata.publisher_from_site', True) else ''),
        ('Genre', ', '.join(_genres(manga))),
        ('Web', manga.get('url', '')),
        ('LanguageISO', language or 'en'),
        ('Manga', 'YesAndRightToLeft' if rtl else 'Yes'),
    ]


def chapter_title(chapter: Dict, settings) -> str:
    number, name = chapter.get('number', ''), (chapter.get('name') or '').strip()
    if re.fullmatch(rf'(chapter|ch\.?|episode|ep\.?)\s*{re.escape(str(number))}', name, re.I):
        name = ''
    if settings.get('metadata.chapter_title', 'name') == 'full':
        return f"Chapter {number} - {name}" if name else f"Chapter {number}"
    return name or f"Chapter {number}"


def summary_mode(settings) -> str:
    """Where the series description goes: 'first' chapter only, 'all' chapters, or 'none'."""
    value = settings.get('metadata.chapter_summary', 'first')
    if value is True:            # older boolean setting
        return 'first'
    if value is False:
        return 'none'
    return value if value in ('first', 'all', 'none') else 'first'


def chapter_comic_info(manga: Dict, chapter: Dict, settings, total: int = 0) -> str:
    """ComicInfo.xml for one chapter archive.

    chapter['is_first'] marks the lowest-numbered downloaded chapter. Komga uses the
    summary of the lowest-numbered book as the series description, so with the
    'first' mode the description shows once instead of on every chapter."""
    language = chapter.get('language') or manga.get('language') or 'en'
    series = _series_fields(manga, settings, total, language)
    mode = summary_mode(settings)
    with_summary = mode == 'all' or (mode == 'first' and chapter.get('is_first'))
    summary = re.sub(r'\s+', ' ', manga.get('description') or '').strip() if with_summary else ''
    fields = [('Title', chapter_title(chapter, settings)), series[0], ('Number', chapter.get('number', '')),
              series[1], ('Summary', summary)] + series[2:]
    return _comicinfo(fields)


def folder_comic_info(manga: Dict, settings, total: int = 0) -> str:
    """Series-level ComicInfo.xml for the manga folder (Jellyfin fallback). Deliberately
    has no <Title>: Jellyfin would otherwise name every chapter after the series."""
    summary = re.sub(r'\s+', ' ', manga.get('description') or '').strip()
    series = _series_fields(manga, settings, total, manga.get('language') or 'en')
    return _comicinfo([series[0], series[1], ('Summary', summary)] + series[2:])


def mylar_series_json(manga: Dict, total: int = 0) -> Dict:
    """series.json in Mylar's format - the only series.json Komga understands."""
    year = 0
    for value in (manga.get('release_date'), manga.get('first_download')):
        match = re.match(r'^\s*(\d{4})', str(value or ''))
        if match:
            year = int(match.group(1))
            break
    status = 'Ended' if _status(manga) in ('completed', 'ended', 'cancelled') else 'Continuing'
    description = unicodedata.normalize('NFC', fix_text(re.sub(r'\s+', ' ', manga.get('description') or '').strip()))
    return {
        "metadata": {
            "type": "comicSeries",
            "publisher": site_label(manga.get('site_type', '')) or "Unknown",
            "imprint": None,
            "name": manga.get('title', ''),
            "comicid": str(manga.get('id') or abs(hash(manga.get('url', ''))) % 10 ** 8),
            "year": year or datetime.now().year,
            "description_text": description or None,
            "description_formatted": None,
            "volume": None,
            "booktype": "Print",
            "age_rating": None,
            "comic_image": manga.get('cover_image_url', '') or '',
            "total_issues": int(total or 0),
            "publication_run": "",
            "status": status,
        }
    }


def _png_bytes(source: str) -> bytes:
    try:
        from PIL import Image
        with Image.open(source) as img:
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            buf = io.BytesIO()
            img.save(buf, 'PNG', optimize=True)
            return buf.getvalue()
    except Exception as e:
        logging.warning(f"Cover conversion failed, using original bytes: {e}")
        with open(source, 'rb') as f:
            return f.read()


def _cover_source(manga: Dict, folder: str) -> str:
    for name in ('cover.png', 'cover.jpg', 'folder.jpg', 'poster.jpg'):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    path = manga.get('cover_image_path') or ''
    return path if path and os.path.exists(path) else ''


# ---------------------------------------------------------------- writers
def write_folder_metadata(manga: Dict, folder: str, settings, total: int = 0, force: bool = False) -> List[str]:
    """cover.png / series.json / ComicInfo.xml in the manga folder, per settings.
    Returns the names of the files written."""
    written: List[str] = []
    try:
        os.makedirs(folder, exist_ok=True)

        cover = manga.get('cover_image_path') or ''
        existing_cover = any(os.path.exists(os.path.join(folder, n))
                             for n in ('cover.png', 'cover.jpg', 'cover.webp', 'folder.jpg', 'poster.jpg'))
        if settings.get_save_cover() and cover and os.path.exists(cover) and (force or not existing_cover):
            with open(os.path.join(folder, 'cover.png'), 'wb') as f:
                f.write(_png_bytes(cover))
            written.append('cover.png')

        if settings.get_save_series_json():
            path = os.path.join(folder, 'series.json')
            outdated = True
            if os.path.exists(path) and not force:
                try:
                    with open(path, encoding='utf-8') as f:
                        outdated = 'metadata' not in json.load(f)   # our old, non-Mylar format
                except (OSError, ValueError):
                    outdated = True
            if outdated:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(mylar_series_json(manga, total), f, indent=2, ensure_ascii=False)
                written.append('series.json')

        if settings.get_save_comicinfo():
            path = os.path.join(folder, COMICINFO)
            stale = force or not os.path.exists(path)
            if not stale:
                with open(path, encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                stale = '<Title>' in content or '<SeriesStatus>' in content   # old format
            if stale:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(folder_comic_info(manga, settings, total))
                written.append(COMICINFO)
    except Exception as e:
        logging.error(f"Error writing metadata files to {folder}: {e}")
    return written


def embed_chapter_metadata(cbz_path: str, manga: Dict, chapter: Dict, settings, total: int = 0,
                           folder: str = '', overwrite: bool = False) -> str:
    """Put ComicInfo.xml (and optionally the cover as first page) into a chapter archive.

    Missing entries are appended (cheap, even on a network share). Existing ones are only
    replaced with overwrite=True, which rewrites the archive.
    Returns 'added', 'updated', 'unchanged', 'skipped' or 'error'.
    """
    want_info = settings.get_embed_comicinfo_in_cbz()
    want_cover = settings.get_embed_cover_in_cbz()
    if not (want_info or want_cover):
        return 'skipped'
    if not cbz_path or not cbz_path.lower().endswith(ARCHIVE_EXTS) or not os.path.exists(cbz_path):
        return 'skipped'
    try:
        info_xml = chapter_comic_info(manga, chapter, settings, total).encode('utf-8') if want_info else b''
        cover = _cover_source(manga, folder or os.path.dirname(cbz_path)) if want_cover else ''

        with zipfile.ZipFile(cbz_path, 'r') as zf:
            names = set(zf.namelist())
            has_info = COMICINFO in names
            same_info = has_info and want_info and zf.read(COMICINFO) == info_xml
        has_cover = COVER_PAGE in names

        need_info = want_info and (not has_info or (overwrite and not same_info))
        need_cover = bool(cover) and not has_cover
        if not need_info and not need_cover:
            return 'unchanged'

        if has_info and need_info:
            _rewrite_archive(cbz_path, {COMICINFO: info_xml},
                             {COVER_PAGE: _png_bytes(cover)} if need_cover else {})
            return 'updated'

        with zipfile.ZipFile(cbz_path, 'a', zipfile.ZIP_DEFLATED) as zf:
            if need_info:
                zf.writestr(COMICINFO, info_xml)
            if need_cover:
                zf.writestr(COVER_PAGE, _png_bytes(cover), compress_type=zipfile.ZIP_STORED)
        return 'added'
    except Exception as e:
        logging.error(f"Error embedding metadata into {cbz_path}: {e}")
        return 'error'


def _rewrite_archive(path: str, replace: Dict[str, bytes], add: Optional[Dict[str, bytes]] = None) -> None:
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(suffix='.cbz.part', dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(path, 'r') as src, zipfile.ZipFile(tmp, 'w') as dst:
            for item in src.infolist():
                if item.filename in replace:
                    continue
                dst.writestr(item, src.read(item.filename))
            for name, data in {**replace, **(add or {})}.items():
                dst.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED if name.endswith('.xml') else zipfile.ZIP_STORED)
        shutil.copystat(path, tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
