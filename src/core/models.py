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
}

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
        name = (self.name or '').strip()
        if not name:
            return ''
        if re.fullmatch(rf'(chapter|ch\.?|episode|ep\.?)\s*{re.escape(self.number)}', name, re.IGNORECASE):
            return ''
        return re.sub(rf'^(chapter|ch\.?)\s*{re.escape(self.number)}\s*[:\-–]\s*', '', name, flags=re.IGNORECASE)


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
