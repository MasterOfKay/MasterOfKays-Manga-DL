"""
Download manager for handling manga downloads with database integration.
"""

import re
import logging
import os
import requests
import inspect
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtCore import QObject, pyqtSignal, QThread

try:
    from ..sites import AsuraComicsDownloader, MangaKatanaDownloader, WebtoonDownloader
    from ..sites.base import MangaMetadata as SiteMetadata
    from ..managers.database_manager import DatabaseManager, MangaMetadata as DBMetadata, ChapterData
except ImportError:
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from sites import AsuraComicsDownloader, MangaKatanaDownloader, WebtoonDownloader
    from sites.base import MangaMetadata as SiteMetadata
    from managers.database_manager import DatabaseManager, MangaMetadata as DBMetadata, ChapterData


class DownloadSignals(QObject):
    """Signals for download events."""
    manga_started = pyqtSignal(str)
    manga_completed = pyqtSignal(str)
    manga_failed = pyqtSignal(str, str)
    chapter_started = pyqtSignal(str, str)
    chapter_progress = pyqtSignal(str, str, int)
    chapter_completed = pyqtSignal(str, str, str)
    chapter_failed = pyqtSignal(str, str, str)
    show_toast = pyqtSignal(str, str)
    manga_progress = pyqtSignal(str, int)
    download_cancelled = pyqtSignal(str)
    queue_updated = pyqtSignal()
    download_paused = pyqtSignal(str)
    download_resumed = pyqtSignal(str)
    metadata_updated = pyqtSignal(str)


class DownloadManager:
    """Manages manga downloads and queue with database integration."""
    
    def __init__(self, signals: DownloadSignals):
        self.signals = signals
        self.download_queue = []
        self.is_downloading = False
        self.cancelled_downloads = set()
        self.paused_downloads = set()
        self.current_manga = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        
        default_path = os.path.join(os.path.expanduser("~"), "Downloads", "Manga")
        try:
            os.makedirs(default_path, exist_ok=True)
            self.download_path = default_path
        except Exception as e:
            logging.error(f"Failed to create default download path: {e}")
            self.download_path = None
        
        # Initialize db
        self.db_manager = DatabaseManager()
        
        self.cover_images_dir = os.path.join(os.path.expanduser("~"), ".mangadownloader", "covers")
        os.makedirs(self.cover_images_dir, exist_ok=True)
        
        self.downloaders = {
            'asura': AsuraComicsDownloader(),
            'katana': MangaKatanaDownloader(),
            'mangakatana': MangaKatanaDownloader(),
            'webtoon': WebtoonDownloader()
        }
    
    def validate_manga_url(self, url: str) -> Tuple[bool, str]:
        """Validate if the URL is a supported manga URL and return the site type."""
        for site_type, downloader in self.downloaders.items():
            if downloader.validate_url(url):
                return True, site_type
        return False, ""
    
    def add_to_queue(self, url: str, chapters: Optional[List[str]] = None) -> bool:
        """Add a manga to the download queue."""
        try:
            is_valid, site_type = self.validate_manga_url(url)
            if not is_valid:
                self.signals.show_toast.emit("Invalid URL or unsupported site", "error")
                return False
            
            downloader = self.downloaders[site_type]
            manga_name = downloader.get_manga_name(url)
            
            if any(item['manga_name'] == manga_name for item in self.download_queue):
                self.signals.show_toast.emit(f"{manga_name} is already in queue", "info")
                return False
            
            manga_id = None
            manga_data = self.db_manager.get_manga_by_title(manga_name)
            if not manga_data:
                all_manga = self.db_manager.get_manga_list()
                for manga in all_manga:
                    if manga['title'].lower() == manga_name.lower():
                        manga_data = manga
                        break
            
            if manga_data:
                manga_id = manga_data['id']
                manga_name = manga_data['title']
                
                if chapters and manga_id:
                    for chapter_identifier in chapters:
                        db_chapters = self.db_manager.get_chapters_for_manga(manga_id)
                        for db_chapter in db_chapters:
                            if (db_chapter['chapter_name'] == chapter_identifier or 
                                db_chapter['chapter_number'] == chapter_identifier):
                                self.db_manager.reset_chapter_download_status(manga_id, db_chapter['chapter_number'])
                                logging.info(f"Reset download status for chapter: {db_chapter['chapter_name']}")
                                break
            
            queue_item = {
                'url': url,
                'manga_name': manga_name,
                'site_type': site_type,
                'chapters': chapters,
                'status': 'queued',
                'manga_id': manga_id
            }
            
            self.download_queue.append(queue_item)
            self.signals.queue_updated.emit()
            self.signals.show_toast.emit(f"Added {manga_name} to queue", "success")
            
            if not self.is_downloading:
                self.start_download_thread()
                logging.info(f"Auto-started download thread for {manga_name}")
            
            return True
            
        except Exception as e:
            logging.error(f"Error adding to queue: {e}")
            self.signals.show_toast.emit(f"Error adding to queue: {e}", "error")
            return False
    
    def cancel_download(self, manga_name: str) -> None:
        """Cancel a download."""
        self.cancelled_downloads.add(manga_name)
        
        self.download_queue = [item for item in self.download_queue if item['manga_name'] != manga_name]
        self.signals.queue_updated.emit()
        self.signals.download_cancelled.emit(manga_name)
    
    def download_cover_image(self, cover_url: str, manga_title: str) -> str:
        """Download cover image and return local file path."""
        if not cover_url:
            return ""
        
        try:
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', manga_title)
            
            ext = os.path.splitext(cover_url.split('?')[0])[1]
            if not ext:
                ext = '.jpg'
            
            cover_filename = f"{safe_title}_cover{ext}"
            cover_path = os.path.join(self.cover_images_dir, cover_filename)
            
            if not os.path.exists(cover_path):
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                if 'webtoon-phinf.pstatic.net' in cover_url or 'webtoons.com' in cover_url:
                    headers.update({
                        'Referer': 'https://www.webtoons.com/',
                        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache'
                    })
                elif any(domain in cover_url for domain in ['asuracomic.net', 'asuracomics.com', 'asuratoon.com', 'asura.gg']):
                    headers.update({
                        'Referer': 'https://asuracomic.net/',
                        'Accept': 'image/webp,image/apng,image/png,image/jpeg,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                        'Sec-Fetch-Dest': 'image',
                        'Sec-Fetch-Mode': 'no-cors',
                        'Sec-Fetch-Site': 'same-origin'
                    })
                
                response = requests.get(cover_url, headers=headers, timeout=30)
                response.raise_for_status()
                
                with open(cover_path, 'wb') as f:
                    f.write(response.content)
                    
                logging.info(f"Downloaded cover image: {cover_path}")
            
            return cover_path
            
        except Exception as e:
            logging.error(f"Error downloading cover image: {e}")
            return ""
    
    def get_site_downloader(self, url: str):
        """Get appropriate downloader for URL."""
        for site_type, downloader in self.downloaders.items():
            if downloader.validate_url(url):
                return downloader
        return None
    
    def add_manga_to_database(self, manga_url: str, site_type: str) -> Optional[int]:
        """Add manga to database with metadata extraction."""
        try:
            downloader = self.get_site_downloader(manga_url)
            if not downloader:
                raise ValueError("No suitable downloader found")
            
            test_chapters = downloader.get_chapter_links(manga_url)
            if not test_chapters:
                raise ValueError(f"No chapters found or URL is inaccessible: {manga_url}")
            
            site_metadata = downloader.get_manga_metadata(manga_url)
            title = site_metadata.title or downloader.get_manga_name(manga_url)
            
            cover_image_path = ""
            if site_metadata.cover_image_url:
                cover_image_path = self.download_cover_image(site_metadata.cover_image_url, title)
            
            db_metadata = DBMetadata(
                title=title,
                url=manga_url,
                site_type=site_type,
                description=site_metadata.description,
                author=site_metadata.author,
                genres=site_metadata.genres,
                status=site_metadata.status,
                release_date=site_metadata.release_date,
                alternative_names=site_metadata.alternative_names,
                cover_image_url=site_metadata.cover_image_url,
                language=getattr(site_metadata, 'language', 'en'),
                translation_type=getattr(site_metadata, 'translation_type', 'official'),
                last_updated=datetime.now().isoformat(),
                first_download=datetime.now().isoformat()
            )
            
            manga_id = self.db_manager.add_or_update_manga(db_metadata, cover_image_path)
            
            chapters = downloader.get_chapter_links(manga_url)
            for chapter_num, chapter_name, chapter_url in chapters:
                chapter_data = ChapterData(
                    chapter_number=chapter_num,
                    chapter_name=chapter_name,
                    chapter_url=chapter_url,
                    language=getattr(site_metadata, 'language', 'en'),
                    is_downloaded=False
                )
                self.db_manager.add_or_update_chapter(manga_id, chapter_data)
            
            if hasattr(downloader, 'create_metadata_file') and self.download_path:
                manga_path = os.path.join(self.download_path, title)
                if not os.path.exists(manga_path):
                    os.makedirs(manga_path, exist_ok=True)
                    downloader.create_metadata_file(site_metadata, manga_path)
            
            self.signals.metadata_updated.emit(title)
            return manga_id
            
        except Exception as e:
            logging.error(f"Error adding manga to database: {e}")
            raise
    
    def queue_download(self, manga_url: str, selected_chapters: Optional[List[str]] = None):
        """
        Queue a manga for download with selected chapters.
        If no chapters specified, downloads all chapters.
        """
        try:
            downloader = self.get_site_downloader(manga_url)
            if not downloader:
                self.signals.show_toast.emit(f"Unsupported site: {manga_url}", "error")
                return
            
            site_type = downloader.site_name.lower().replace(' ', '')
            
            try:
                manga_id = self.add_manga_to_database(manga_url, site_type)
            except Exception as db_error:
                logging.error(f"Failed to add manga to database: {db_error}")
                
                try:
                    manga_name = downloader.get_manga_name(manga_url)
                    self.signals.show_toast.emit(f"Failed to process '{manga_name}': {str(db_error)}", "error")
                except:
                    self.signals.show_toast.emit(f"Failed to process manga: {str(db_error)}", "error")
                return
            
            if manga_id is None:
                self.signals.show_toast.emit("Failed to process manga data - please check the URL and try again", "error")
                return
            
            manga_list = self.db_manager.get_manga_list()
            manga_data = None
            for manga in manga_list:
                if manga['url'] == manga_url:
                    manga_data = manga
                    break
            
            if not manga_data:
                self.signals.show_toast.emit("Failed to retrieve manga data", "error")
                return
            
            all_chapters = self.db_manager.get_chapters_for_manga(manga_id, include_not_downloaded=True)
            
            if selected_chapters:
                chapters_to_download = [ch for ch in all_chapters 
                                      if ch['chapter_number'] in selected_chapters and not ch['is_downloaded']]
            else:
                chapters_to_download = [ch for ch in all_chapters if not ch['is_downloaded']]
            
            if not chapters_to_download:
                self.signals.show_toast.emit("No new chapters to download", "info")
                return
            
            download_item = {
                'url': manga_url,
                'manga_name': manga_data['title'],
                'site_type': site_type,
                'chapters': [ch['chapter_number'] for ch in chapters_to_download],
                'status': 'queued',
                'manga_id': manga_id
            }
            
            if any(item['manga_name'] == manga_data['title'] for item in self.download_queue):
                self.signals.show_toast.emit(f"{manga_data['title']} is already in queue", "info")
                return
            
            self.download_queue.append(download_item)
            self.signals.queue_updated.emit()
            self.signals.show_toast.emit(f"Added {manga_data['title']} to queue ({len(chapters_to_download)} chapters)", "success")
            
        except Exception as e:
            logging.error(f"Error queueing download: {e}")
            self.signals.show_toast.emit(f"Error queueing download: {e}", "error")
    
    def pause_download(self, manga_name: str) -> None:
        """Pause a download."""
        self.paused_downloads.add(manga_name)
        self.signals.download_paused.emit(manga_name)
    
    def resume_download(self, manga_name: str) -> None:
        """Resume a download."""
        if manga_name in self.paused_downloads:
            self.paused_downloads.remove(manga_name)
        self.signals.download_resumed.emit(manga_name)
    
    def is_paused(self, manga_name: str) -> bool:
        """Check if a download is paused."""
        return manga_name in self.paused_downloads
    
    def get_queue(self) -> List[Dict]:
        """Get the current download queue."""
        return self.download_queue.copy()
    
    def start_download_thread(self) -> None:
        """Start the download thread."""
        if not self.is_downloading and self.download_queue:
            self.is_downloading = True
            self.executor.submit(self._process_queue)
    
    def _process_queue(self) -> None:
        """Process the download queue."""
        try:
            while self.download_queue and self.is_downloading:
                current_item = self.download_queue[0]
                manga_name = current_item['manga_name']
                
                if manga_name in self.cancelled_downloads:
                    self.cancelled_downloads.remove(manga_name)
                    self.download_queue.pop(0)
                    self.signals.queue_updated.emit()
                    continue
                
                self.current_manga = manga_name
                self.signals.manga_started.emit(manga_name)
                
                try:
                    self._download_manga(current_item)
                    self.signals.manga_completed.emit(manga_name)
                except Exception as e:
                    logging.error(f"Error downloading {manga_name}: {e}")
                    self.signals.manga_failed.emit(manga_name, str(e))
                
                self.download_queue.pop(0)
                self.signals.queue_updated.emit()
                
        except Exception as e:
            logging.error(f"Error in download queue processing: {e}")
        finally:
            self.is_downloading = False
            self.current_manga = None
    
    def _download_manga(self, item: Dict) -> None:
        """Download a single manga."""
        url = item['url']
        manga_name = item['manga_name']
        site_type = item['site_type']
        chapters_to_download = item.get('chapters')
        manga_id = item.get('manga_id')
        
        if not self.download_path:
            error_msg = "Download path is not set. Please set a download path in settings."
            logging.error(error_msg)
            self.signals.manga_failed.emit(manga_name, error_msg)
            return
        
        downloader = self.downloaders[site_type]
        
        try:
            if not chapters_to_download:
                all_chapters = downloader.get_chapter_links(url)
                chapters_to_download = [chapter_num for chapter_num, _, _ in all_chapters]
                logging.info(f"No chapters specified, found {len(chapters_to_download)} chapters from site")
            else:
                logging.info(f"Using specified chapters: {len(chapters_to_download)} chapters")
            
            if not chapters_to_download:
                error_msg = f"No chapters found to download for {manga_name}"
                logging.error(error_msg)
                self.signals.manga_failed.emit(manga_name, error_msg)
                return
            
            self._copy_cover_to_manga_folder(manga_name, manga_id)
            
            self._create_metadata_files(manga_name, manga_id)
            
            total_chapters = len(chapters_to_download)
            completed_chapters = 0
            logging.info(f"Starting download of {total_chapters} chapters for {manga_name}")
            
            for chapter_num in chapters_to_download:
                if manga_name in self.cancelled_downloads:
                    logging.info(f"Download cancelled for {manga_name}")
                    break
                
                while self.is_paused(manga_name):
                    import time
                    time.sleep(1)
                    if manga_name in self.cancelled_downloads:
                        break
                
                if manga_name in self.cancelled_downloads:
                    break
                
                actual_chapter_num = self._extract_chapter_number(chapter_num)
                logging.info(f"Processing chapter: '{chapter_num}' (extracted: '{actual_chapter_num}')")
                
                chapter_data = None
                if manga_id:
                    db_chapters = self.db_manager.get_chapters_for_manga(manga_id)
                    for ch in db_chapters:
                        ch_num_extracted = self._extract_chapter_number(ch['chapter_number'])
                        if (ch['chapter_number'] == chapter_num or 
                            ch_num_extracted == actual_chapter_num or
                            ch['chapter_number'] == actual_chapter_num):
                            chapter_data = ch
                            logging.info(f"Found chapter in database: {ch['chapter_number']}")
                            break
                
                if not chapter_data:
                    logging.warning(f"Chapter {chapter_num} not found in database for {manga_name}, attempting to get chapter info from site")
                    try:
                        all_chapters = downloader.get_chapter_links(url)
                        chapter_url = None
                        chapter_name = f"Chapter {actual_chapter_num}"
                        
                        for ch_num, ch_name, ch_url in all_chapters:
                            if (ch_num == chapter_num or 
                                ch_num == actual_chapter_num or
                                str(ch_num) == str(actual_chapter_num) or
                                ch_num == f"Chapter {actual_chapter_num}"):
                                chapter_url = ch_url
                                chapter_name = ch_name
                                logging.info(f"Found matching chapter: {ch_num} -> {ch_url}")
                                break
                        
                        if not chapter_url:
                            available_chapters = [(ch_num, ch_name) for ch_num, ch_name, _ in all_chapters[:5]]
                            logging.error(f"Could not find chapter {chapter_num} (extracted: {actual_chapter_num}) URL for {manga_name}")
                            logging.error(f"Available chapters (first 5): {available_chapters}")
                            self.signals.chapter_failed.emit(manga_name, chapter_num, "Chapter URL not found")
                            continue
                    except Exception as e:
                        logging.error(f"Failed to get chapter info for {chapter_num}: {e}")
                        self.signals.chapter_failed.emit(manga_name, chapter_num, str(e))
                        continue
                else:
                    chapter_url = chapter_data['chapter_url']
                    chapter_name = chapter_data['chapter_name']
                
                self.signals.chapter_started.emit(manga_name, actual_chapter_num)
                
                try:
                    chapter_path = self._download_chapter(
                        chapter_url, actual_chapter_num, manga_name, site_type, chapter_name
                    )
                    
                    if chapter_path and manga_id:
                        self.db_manager.mark_chapter_downloaded(manga_id, chapter_num, chapter_path)
                        logging.info(f"Marked chapter {chapter_num} as downloaded")
                    
                    self.signals.chapter_completed.emit(manga_name, chapter_num, chapter_path or "")
                    completed_chapters += 1
                    
                    progress = int((completed_chapters / total_chapters) * 100)
                    self.signals.manga_progress.emit(manga_name, progress)
                    
                except Exception as e:
                    logging.error(f"Failed to download chapter {chapter_num}: {e}")
                    self.signals.chapter_failed.emit(manga_name, chapter_num, str(e))
                    continue
            
            logging.info(f"Completed downloading {manga_name}: {completed_chapters}/{total_chapters} chapters")
            
        except Exception as e:
            logging.error(f"Error downloading manga {manga_name}: {e}")
            raise
        
    def _download_chapter(self, chapter_url: str, chapter_num: str, manga_name: str, site_type: str, chapter_name: Optional[str] = None) -> str:
        """Download a single chapter."""
        if not self.download_path:
            error_msg = "Download path is not set"
            logging.error(error_msg)
            return ""
        
        downloader = self.downloaders[site_type]
        
        def progress_callback(current: int, total: int):
            if manga_name not in self.cancelled_downloads:
                progress = int(current / total * 100) if total > 0 else 0
                self.signals.chapter_progress.emit(manga_name, chapter_num, progress)
        
        try:
            logging.info(f"Downloading chapter {chapter_num} to path: {self.download_path}")
            
            if hasattr(downloader, 'download_chapter_with_name') and chapter_name:
                result = downloader.download_chapter_with_name(
                    chapter_url, chapter_num, chapter_name, manga_name, 
                    self.download_path, progress_callback
                )
            else:
                result = downloader.download_chapter(
                    chapter_url, chapter_num, manga_name, 
                    self.download_path, progress_callback
                )
            
            if isinstance(result, dict):
                return result.get('path', '')
            else:
                return result or ''
                
        except Exception as e:
            logging.error(f"Error downloading chapter {chapter_num}: {e}")
            return ""
    
    def set_download_path(self, path: str) -> None:
        """Set the download path."""
        if path:
            try:
                os.makedirs(path, exist_ok=True)
                self.download_path = path
                logging.info(f"Download path set to: {path}")
            except Exception as e:
                logging.error(f"Failed to create download path {path}: {e}")
                default_path = os.path.join(os.path.expanduser("~"), "Downloads", "Manga")
                try:
                    os.makedirs(default_path, exist_ok=True)
                    self.download_path = default_path
                    logging.info(f"Using default download path: {default_path}")
                except Exception as e2:
                    logging.error(f"Failed to create default download path: {e2}")
                    self.download_path = None
        else:
            default_path = os.path.join(os.path.expanduser("~"), "Downloads", "Manga")
            try:
                os.makedirs(default_path, exist_ok=True)
                self.download_path = default_path
                logging.info(f"Using default download path: {default_path}")
            except Exception as e:
                logging.error(f"Failed to create default download path: {e}")
                self.download_path = None
    
    def _copy_cover_to_manga_folder(self, manga_name: str, manga_id: Optional[int]) -> None:
        """Copy cover image to manga download folder."""
        if not manga_id or not self.download_path:
            return
        
        try:
            manga_data = None
            manga_list = self.db_manager.get_manga_list()
            for manga in manga_list:
                if manga['id'] == manga_id:
                    manga_data = manga
                    break
            
            if not manga_data:
                return
            
            cover_path = manga_data.get('cover_image_path', '')
            
            if not cover_path or not os.path.exists(cover_path):
                try:
                    manga_url = manga_data.get('url', '')
                    if manga_url:
                        downloader = self.get_site_downloader(manga_url)
                        if downloader:
                            fresh_metadata = downloader.get_manga_metadata(manga_url)
                            if fresh_metadata.cover_image_url:
                                new_cover_path = self.download_cover_image(
                                    fresh_metadata.cover_image_url, 
                                    manga_name
                                )
                                if new_cover_path and os.path.exists(new_cover_path):
                                    cover_path = new_cover_path
                                    logging.info(f"Downloaded missing cover for {manga_name}")
                except Exception as e:
                    logging.warning(f"Failed to download missing cover for {manga_name}: {e}")
                
                if not cover_path or not os.path.exists(cover_path):
                    return
            
            safe_manga_name = re.sub(r'[<>:"/\\|?*]', '_', manga_name)
            manga_folder = os.path.join(self.download_path, safe_manga_name)
            
            os.makedirs(manga_folder, exist_ok=True)
            
            cover_filename = "cover.png"
            destination_path = os.path.join(manga_folder, cover_filename)
            
            if not os.path.exists(destination_path):
                try:
                    from PIL import Image
                    with Image.open(cover_path) as img:
                        if img.mode in ('RGBA', 'LA', 'P'):
                            img = img.convert('RGB')
                        img.save(destination_path, 'PNG', optimize=True)
                    logging.info(f"Converted and saved cover image to: {destination_path}")
                except ImportError:
                    import shutil
                    shutil.copy2(cover_path, destination_path)
                    logging.info(f"Copied cover image to: {destination_path}")
                except Exception as e:
                    import shutil
                    shutil.copy2(cover_path, destination_path)
                    logging.warning(f"Cover conversion failed, copied original: {e}")
            
        except Exception as e:
            logging.error(f"Error copying cover image: {e}")
    
    def _create_metadata_files(self, manga_name: str, manga_id: Optional[int]) -> None:
        """Create metadata files for Kavita/Komga compatibility."""
        if not manga_id or not self.download_path:
            return
        
        try:
            manga_data = None
            manga_list = self.db_manager.get_manga_list()
            for manga in manga_list:
                if manga['id'] == manga_id:
                    manga_data = manga
                    break
            
            if not manga_data:
                return
            
            safe_manga_name = re.sub(r'[<>:"/\\|?*]', '_', manga_name)
            manga_folder = os.path.join(self.download_path, safe_manga_name)
            
            os.makedirs(manga_folder, exist_ok=True)
            
            import json
            genres_list = []
            try:
                if manga_data.get('genres'):
                    genres_list = json.loads(manga_data['genres'])
            except:
                genres_list = []
            
            comic_info_path = os.path.join(manga_folder, "ComicInfo.xml")
            should_create_comicinfo = False
            
            if not os.path.exists(comic_info_path):
                should_create_comicinfo = True
            else:
                if genres_list:
                    try:
                        with open(comic_info_path, 'r', encoding='utf-8') as f:
                            existing_content = f.read()
                            if '<Genre></Genre>' in existing_content or '<Genre/>' in existing_content:
                                should_create_comicinfo = True
                                logging.info(f"Regenerating ComicInfo.xml with updated genres: {comic_info_path}")
                    except:
                        should_create_comicinfo = True
            
            if should_create_comicinfo:
                comic_info_xml = self._generate_comic_info_xml(manga_data, genres_list)
                with open(comic_info_path, 'w', encoding='utf-8') as f:
                    f.write(comic_info_xml)
                logging.info(f"Created ComicInfo.xml: {comic_info_path}")
            
            series_json_path = os.path.join(manga_folder, "series.json")
            if not os.path.exists(series_json_path):
                series_metadata = self._generate_series_json(manga_data, genres_list)
                with open(series_json_path, 'w', encoding='utf-8') as f:
                    json.dump(series_metadata, f, indent=2, ensure_ascii=False)
                logging.info(f"Created series.json: {series_json_path}")
            
        except Exception as e:
            logging.error(f"Error creating metadata files: {e}")
    
    def _generate_comic_info_xml(self, manga_data: dict, genres_list: List[str]) -> str:
        """Generate ComicInfo.xml content for comic readers."""
        from xml.sax.saxutils import escape
        
        title = escape(manga_data.get('title', ''))
        author = escape(manga_data.get('author', ''))
        description = escape(manga_data.get('description', ''))
        genres = escape(', '.join(genres_list))
        status = manga_data.get('status', 'ongoing')
        language = manga_data.get('language', 'en')
        
        manga_status = "Unknown"
        if status.lower() == 'completed':
            manga_status = "Ended"
        elif status.lower() == 'ongoing':
            manga_status = "Continuing"
        elif status.lower() == 'cancelled':
            manga_status = "Cancelled"
        
        xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
    <Title>{title}</Title>
    <Writer>{author}</Writer>
    <Summary>{description}</Summary>
    <Genre>{genres}</Genre>
    <Manga>Yes</Manga>
    <BlackAndWhite>No</BlackAndWhite>
    <LanguageISO>{language}</LanguageISO>
    <Format>Webtoon</Format>
    <SeriesStatus>{manga_status}</SeriesStatus>
    <Web>{manga_data.get('url', '')}</Web>
</ComicInfo>'''
        
        return xml_content
    
    def _generate_series_json(self, manga_data: dict, genres_list: List[str]) -> dict:
        """Generate series.json metadata for additional information."""
        return {
            "title": manga_data.get('title', ''),
            "author": manga_data.get('author', ''),
            "description": manga_data.get('description', ''),
            "genres": genres_list,
            "status": manga_data.get('status', 'unknown'),
            "language": manga_data.get('language', 'en'),
            "translation_type": manga_data.get('translation_type', 'official'),
            "site_type": manga_data.get('site_type', ''),
            "url": manga_data.get('url', ''),
            "release_date": manga_data.get('release_date', ''),
            "alternative_names": manga_data.get('alternative_names', ''),
            "cover_image_url": manga_data.get('cover_image_url', ''),
            "cover_image_file": "cover.png",  # Local cover file reference
            "first_download": manga_data.get('first_download', ''),
            "last_updated": manga_data.get('last_updated', ''),
            "created_at": manga_data.get('created_at', ''),
            "updated_at": manga_data.get('updated_at', '')
        }
    
    def scan_for_new_chapters(self, manga_name: Optional[str] = None):
        """Scan for new chapters (placeholder for future implementation)."""
        pass
    
    def _extract_chapter_number(self, chapter_str: str) -> str:
        """Extract the actual chapter number from formatted chapter strings.
        
        Examples:
        - "Chapter 1: First 1" -> "1"
        - "Chapter 2.5" -> "2.5" 
        - "1" -> "1"
        - "[Season 1] Ep. 1 - 1F.Headon's Floor" -> "1"
        """
        import re
        
        if re.match(r'^\d+(\.\d+)?$', chapter_str.strip()):
            return chapter_str.strip()
        
        chapter_match = re.search(r'Chapter\s+(\d+(?:\.\d+)?)', chapter_str, re.IGNORECASE)
        if chapter_match:
            return chapter_match.group(1)
        
        ep_match = re.search(r'Ep\.\s+(\d+(?:\.\d+)?)', chapter_str, re.IGNORECASE)
        if ep_match:
            return ep_match.group(1)
        
        number_match = re.search(r'(\d+(?:\.\d+)?)', chapter_str)
        if number_match:
            return number_match.group(1)
        
        return chapter_str
    
    def _parse_chapter_range(self, range_str: str) -> List[str]:
        """Parse chapter range string (e.g., '5' or '0-20')."""
        if not range_str:
            return []
        
        try:
            if '-' in range_str:
                start, end = range_str.split('-', 1)
                start_num = float(start.strip())
                end_num = float(end.strip())
                
                chapters = []
                current = start_num
                while current <= end_num:
                    if current == int(current):
                        chapters.append(str(int(current)))
                    else:
                        chapters.append(str(current))
                    current += 1
                
                return chapters
            else:
                num = float(range_str.strip())
                if num == int(num):
                    return [str(int(num))]
                else:
                    return [str(num)]
        except ValueError:
            return []