"""
Plain data structures shared by the core and the UI.
"""

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..sites.base import fix_text  # noqa: F401  (re-exported for the core)

ChapterKey = Tuple[str, str]   # (language, chapter_number)


SITE_LABELS = {
    'asura': 'Asura Comics',
    'asuracomics': 'Asura Comics',
    'mangakatana': 'MangaKatana',
    'katana': 'MangaKatana',
    'webtoon': 'Webtoon',
    'mangadex': 'MangaDex',
    'mangafreak': 'MangaFreak',
    'atsumaru': 'Atsumaru',
    'mangaball': 'MangaBall',
}

# Sites where one chapter can come from several release (scanlation) groups.
GROUP_SITES = ('mangadex', 'atsumaru', 'mangaball')

# Sites with chapters in several languages: the language is part of every chapter's identity.
MULTI_LANGUAGE_SITES = ('mangadex', 'mangaball')

# Formats a light novel chapter can be saved as: key -> (label, file extension).
NOVEL_FORMATS = {
    'epub': ('EPUB', '.epub'),
    'pdf': ('PDF', '.pdf'),
    'docx': ('Word', '.docx'),
    'html': ('HTML', '.html'),
    'md': ('Markdown', '.md'),
    'txt': ('Text', '.txt'),
}


def is_novel_url(url: str) -> bool:
    """Light novels (text chapters) have their own address, e.g. https://atsu.moe/novel/<id>."""
    return '/novel/' in (url or '')

LANGUAGE_NAMES = {
    'en': 'English', 'ja': 'Japanese', 'ko': 'Korean', 'zh': 'Chinese', 'zh-hk': 'Chinese (HK)',
    'es': 'Spanish', 'es-la': 'Spanish (LATAM)', 'fr': 'French', 'de': 'German', 'it': 'Italian',
    'pt': 'Portuguese', 'pt-br': 'Portuguese (BR)', 'ru': 'Russian', 'pl': 'Polish', 'tr': 'Turkish',
    'ar': 'Arabic', 'id': 'Indonesian', 'vi': 'Vietnamese', 'th': 'Thai', 'uk': 'Ukrainian',
    'nl': 'Dutch', 'hu': 'Hungarian', 'cs': 'Czech', 'ro': 'Romanian', 'fa': 'Persian',
    'he': 'Hebrew', 'ms': 'Malay', 'tl': 'Filipino', 'fil': 'Filipino', 'bg': 'Bulgarian',
    'el': 'Greek', 'sv': 'Swedish', 'fi': 'Finnish', 'da': 'Danish', 'no': 'Norwegian',
    'ca': 'Catalan', 'lt': 'Lithuanian', 'hi': 'Hindi', 'bn': 'Bengali', 'mn': 'Mongolian',
}


def site_label(site_type: str) -> str:
    return SITE_LABELS.get((site_type or '').lower(), (site_type or 'Unknown').title())


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get((code or '').lower(), (code or '?').upper())


def plain_text(text: str) -> str:
    """Descriptions from some sites contain HTML ('<p>…</p><p>…</p>'): keep the text and paragraphs."""
    if not text or '<' not in text:
        return text or ''
    text = re.sub(r'(?i)<br\s*/?>', '\n', text)
    text = re.sub(r'(?i)</p>\s*', '\n\n', text)
    # Only real tags - manhwa blurbs use brackets as text, e.g. "<Status Window>".
    text = re.sub(r'(?i)</?(?:p|div|span|b|i|u|em|strong|a|ul|ol|li|h[1-6]|font|small|center)\b[^>]*>', '', text)
    text = html.unescape(text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


# Any number: Webtoon episode numbers are often one lower than our chapter numbers.
_NUMBER_PREFIX = re.compile(r'^\s*(?:\[[^\]]*\]\s*)?(?:chapter|ch\.?|episode|ep\.?)\s*#?\d+(?:\.\d+)?\s*(?:[:\-–—.]\s*|$)',
                            re.IGNORECASE)


def chapter_title_only(name: str) -> str:
    """'Ep. 1 - Chirp!' -> 'Chirp!', 'Episode 1' -> '' (no real name)."""
    return _NUMBER_PREFIX.sub('', (name or '').strip()).strip()


def chapter_file_name(number: str, name: str, ext: str = '.cbz') -> str:
    """'Chapter 1 - Chirp!.cbz' (or 'Chapter 1.cbz' without a name) - the Asura/Katana style."""
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', chapter_title_only(name))
    title = re.sub(r'\s+', ' ', title).strip(' .')[:120].strip()
    return f"Chapter {number} - {title}{ext}" if title else f"Chapter {number}{ext}"


def parse_utc(value: str):
    """'2026-10-24T01:40:02.04Z' -> aware datetime, None if empty/invalid."""
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def chapter_sort_key(number: str) -> Tuple[float, str]:
    match = re.match(r'^\s*(\d+(?:\.\d+)?)', str(number))
    return (float(match.group(1)) if match else float('inf'), str(number))


@dataclass
class ChapterSource:
    """One upload of a chapter by one release group."""
    group: str
    url: str
    name: str = ''
    volume: str = ''


def pick_source(sources: List['ChapterSource'], preferred: str = '') -> Optional['ChapterSource']:
    """The upload of the preferred group, else the first one (sites list their best first)."""
    if not sources:
        return None
    if preferred:
        wanted = preferred.casefold()
        for source in sources:
            if source.group.casefold() == wanted:
                return source
    return sources[0]


@dataclass
class ChapterRef:
    number: str
    name: str = ''
    url: str = ''
    language: str = 'en'
    volume: str = ''
    group: str = ''
    downloaded: bool = False
    is_new: bool = False
    file_path: str = ''
    free_at: str = ''          # early access: when the chapter becomes free (ISO, UTC)
    sources: List['ChapterSource'] = field(default_factory=list)   # every group's upload (2+ only)
    group_locked: bool = False  # the user picked this group for this chapter

    def use_source(self, source: 'ChapterSource') -> None:
        self.url, self.group = source.url, source.group
        self.name = source.name or self.name
        self.volume = source.volume or self.volume

    @property
    def key(self) -> ChapterKey:
        return (self.language, self.number)

    @property
    def early_access(self) -> bool:
        """Still behind the site's paywall - can't be downloaded yet."""
        stamp = parse_utc(self.free_at)
        return bool(stamp and stamp > datetime.now(timezone.utc))

    @property
    def free_label(self) -> str:
        """'Free 24 Oct, 03:40' in local time."""
        stamp = parse_utc(self.free_at)
        if not stamp:
            return ''
        local = stamp.astimezone()
        day = 'today' if local.date() == datetime.now().date() else f"{local.day} {local:%b}"
        return f"Free {day}, {local:%H:%M}"

    @property
    def display_name(self) -> str:
        """Chapter title without a redundant 'Chapter N' prefix."""
        return chapter_title_only(self.name)


@dataclass
class FetchedManga:
    """Result of looking up a URL on its site; not stored until the user confirms."""
    url: str
    site_type: str
    title: str
    metadata: object                     # sites.base.MangaMetadata
    chapters: Dict[str, List[ChapterRef]] = field(default_factory=dict)   # language -> chapters
    cover_path: str = ''
    manga_id: Optional[int] = None       # set when this URL is already in the library
    preferred_group: str = ''            # release group filter picked before saving

    @property
    def is_novel(self) -> bool:
        return is_novel_url(self.url)
