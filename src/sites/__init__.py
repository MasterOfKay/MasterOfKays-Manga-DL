"""Comic sites package."""

from .asura_comics import AsuraComicsDownloader
from .manga_katana import MangaKatanaDownloader
from .webtoon import WebtoonDownloader
from .mangadex import MangaDexDownloader
from .mangafreak import MangaFreakDownloader
from .base import ComicSiteBase, ChapterInfo

__all__ = [
    'AsuraComicsDownloader',
    'MangaKatanaDownloader', 
    'WebtoonDownloader',
    'MangaDexDownloader',
    'MangaFreakDownloader',
    'ComicSiteBase',
    'ChapterInfo'
]