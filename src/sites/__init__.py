"""Comic sites package."""

from .asura_comics import AsuraComicsDownloader
from .manga_katana import MangaKatanaDownloader
from .webtoon import WebtoonDownloader
from .mangadex import MangaDexDownloader
from .mangafreak import MangaFreakDownloader
from .atsumaru import AtsumaruDownloader
from .mangaball import MangaBallDownloader
from .weebcentral import WeebCentralDownloader
from .freewebnovel import FreeWebNovelDownloader
from .novelfire import NovelFireDownloader, WuxiaBoxDownloader
from .wuxiaclick import WuxiaClickDownloader
from .novelbuddy import NovelBuddyDownloader
from .novelarchive import NovelArchiveDownloader
from .chikari import ChikariDownloader
from .cyrisia import CyrisiaDownloader
from .lnori import LnoriDownloader
from .base import ComicSiteBase, ChapterInfo

__all__ = [
    'AsuraComicsDownloader',
    'MangaKatanaDownloader', 
    'WebtoonDownloader',
    'MangaDexDownloader',
    'MangaFreakDownloader',
    'AtsumaruDownloader',
    'MangaBallDownloader',
    'WeebCentralDownloader',
    'FreeWebNovelDownloader',
    'NovelFireDownloader',
    'WuxiaBoxDownloader',
    'WuxiaClickDownloader',
    'NovelBuddyDownloader',
    'NovelArchiveDownloader',
    'ChikariDownloader',
    'CyrisiaDownloader',
    'LnoriDownloader',
    'ComicSiteBase',
    'ChapterInfo'
]