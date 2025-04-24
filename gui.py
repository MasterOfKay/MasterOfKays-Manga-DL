import sys
import os
import threading
import queue
from typing import Dict, List, Tuple
import re
import json
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                            QProgressBar, QScrollArea, QFrame, QMessageBox,
                            QTabWidget, QListWidget, QListWidgetItem, QDialog,
                            QCheckBox, QSpinBox, QGridLayout, QAction, QFileDialog,
                            QSplitter, QToolButton, QMenu, QSizePolicy, QStackedWidget)
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QTimer, QEvent, QSize, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QColor, QMouseEvent, QIcon, QPalette, QBrush, QPixmap

import time
from concurrent.futures import ThreadPoolExecutor
import threading
import random

from assuracomics import get_chapter_links as asura_get_chapter_links
from assuracomics import download_chapter as asura_download_chapter
from assuracomics import get_manga_name as asura_get_manga_name
from mangakatana import get_chapter_links as katana_get_chapter_links
from mangakatana import download_chapter as katana_download_chapter
from mangakatana import get_manga_name as katana_get_manga_name
from webtoon import get_chapter_links as webtoon_get_chapter_links
from webtoon import download_chapter as webtoon_download_chapter
from webtoon import get_manga_name as webtoon_get_manga_name

import traceback
import logging

logging.basicConfig(
    filename='manga_download.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class DownloadSignals(QObject):
    manga_started = pyqtSignal(str)
    manga_completed = pyqtSignal(str)
    manga_failed = pyqtSignal(str, str)
    chapter_started = pyqtSignal(str, str)
    chapter_progress = pyqtSignal(str, str, int)
    chapter_completed = pyqtSignal(str, str, str)
    chapter_failed = pyqtSignal(str, str, str)
    show_toast = pyqtSignal(str, str)  # message, type (info, error, success)
    manga_progress = pyqtSignal(str, int)  # manga_name, overall_progress
    download_cancelled = pyqtSignal(str)  # manga_name
    queue_updated = pyqtSignal()  # Emitted when queue changes
    download_paused = pyqtSignal(str)  # manga_name
    download_resumed = pyqtSignal(str)  # manga_name

class MangaHistoryManager:
    """Manages history of downloaded manga and chapters"""
    
    def __init__(self):
        self.history_file = os.path.join(os.path.expanduser("~"), ".mangadownloader", "history.json")
        self.history = self._load_history()
        
    def _load_history(self):
        """Load history from file"""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    loaded_data = json.load(f)
                    if isinstance(loaded_data, dict):
                        return loaded_data
                    else:
                        logging.error(f"History file contains invalid format: {type(loaded_data)}. Creating new history.")
                        backup_file = self.history_file + ".backup"
                        try:
                            os.rename(self.history_file, backup_file)
                            logging.info(f"Renamed invalid history file to {backup_file}")
                        except Exception as rename_err:
                            logging.error(f"Failed to rename invalid history file: {rename_err}")
        except Exception as e:
            logging.error(f"Error loading history: {e}")
    
    def _save_history(self):
        """Save history to file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving history: {e}")
    
    def add_manga(self, manga_name, url, site_type):
        """Add a manga to history"""
        if manga_name not in self.history:
            self.history[manga_name] = {
                'url': url,
                'site_type': site_type,
                'added_date': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'chapters': {}
            }
        else:
            self.history[manga_name]['last_updated'] = datetime.now().isoformat()
            
        self._save_history()
    
    def add_downloaded_chapter(self, manga_name, chapter_num, site_type, chapter_url):
        """Record a successfully downloaded chapter"""
        if manga_name not in self.history:
            self.add_manga(manga_name, "", site_type)
            
        self.history[manga_name]['chapters'][chapter_num] = {
            'download_date': datetime.now().isoformat(),
            'url': chapter_url
        }
        self.history[manga_name]['last_updated'] = datetime.now().isoformat()
        
        self._save_history()
    
    def get_manga_list(self):
        """Get list of all manga in history"""
        return list(self.history.keys())
    
    def get_manga_data(self, manga_name):
        """Get data for a specific manga"""
        return self.history.get(manga_name, {})
    
    def get_chapter_data(self, manga_name, chapter_num):
        """Get data for a specific chapter"""
        manga_data = self.get_manga_data(manga_name)
        chapters = manga_data.get('chapters', {})
        return chapters.get(chapter_num, {})
    
    def get_downloaded_chapters(self, manga_name):
        """Get list of downloaded chapters for a manga"""
        manga_data = self.get_manga_data(manga_name)
        return list(manga_data.get('chapters', {}).keys())
    
    def update_manga_url(self, manga_name, url, site_type):
        """Update the URL for a manga in history"""
        if manga_name in self.history:
            self.history[manga_name]['url'] = url
            self.history[manga_name]['site_type'] = site_type
            self.history[manga_name]['last_updated'] = datetime.now().isoformat()
            self._save_history()
    
    def delete_manga(self, manga_name):
        """Delete a manga from history"""
        if manga_name in self.history:
            del self.history[manga_name]
            self._save_history()

class DownloadManager:
    def __init__(self, signals):
        self.signals = signals
        self.download_queue = queue.Queue()
        self.current_downloads = {}
        self.thread = None
        self.running = False
        self.cancel_requested = set()
        self.paused_downloads = set()
        self.download_queue_list = []
        self.download_path = os.getcwd()
        self.history_manager = MangaHistoryManager()
    
    def validate_manga_url(self, url: str) -> Tuple[bool, str]:
        """Validate if the URL is a supported manga URL and return the site type"""
        asura_pattern = r'^https?://asuracomic\.net/series/[a-zA-Z0-9-_]+/?$'
        katana_pattern = r'^https?://mangakatana\.com/manga/[a-zA-Z0-9-_.]+/?$'
        webtoon_pattern = r'^https?://www\.webtoons\.com/[a-z]{2}/[^/]+/[^/]+/list\?title_no=\d+$'
        
        if re.match(asura_pattern, url):
            return True, "asura"
        elif re.match(katana_pattern, url):
            return True, "katana"
        elif re.match(webtoon_pattern, url):
            return True, "webtoon"
        return False, ""
    
    def add_to_queue(self, url, chapters=None):
        valid, site_type = self.validate_manga_url(url)
        
        if not valid:
            self.signals.show_toast.emit("Invalid URL format", "error")
            return False
        
        self.download_queue.put((url, site_type, chapters))
        
        manga_name = self._get_manga_name(url, site_type)
        queue_item = {
            'url': url,
            'site_type': site_type,
            'chapters': chapters,
            'manga_name': manga_name
        }
        self.download_queue_list.append(queue_item)
        self.signals.queue_updated.emit()
        
        if not self.running:
            self.start_download_thread()
        
        return True
    
    def cancel_download(self, manga_name):
        """Cancel a pending or in-progress download"""
        self.cancel_requested.add(manga_name)
        
        for i, item in enumerate(self.download_queue_list):
            if item['manga_name'] == manga_name:
                del self.download_queue_list[i]
                break
        
        self.signals.queue_updated.emit()
        self.signals.download_cancelled.emit(manga_name)
    
    def pause_download(self, manga_name):
        """Pause a download - it will be skipped in the queue until resumed"""
        self.paused_downloads.add(manga_name)
        self.signals.download_paused.emit(manga_name)
    
    def resume_download(self, manga_name):
        """Resume a paused download"""
        if manga_name in self.paused_downloads:
            self.paused_downloads.remove(manga_name)
            self.signals.download_resumed.emit(manga_name)
    
    def is_paused(self, manga_name):
        """Check if a download is paused"""
        return manga_name in self.paused_downloads
    
    def get_queue(self):
        """Return current download queue for display"""
        return self.download_queue_list
    
    def start_download_thread(self):
        self.running = True
        self.thread = threading.Thread(target=self._process_queue)
        self.thread.daemon = True
        self.thread.start()
    
    def _process_queue(self):
        while True:
            try:
                if self.download_queue.empty():
                    self.running = False
                    self.download_queue_list = []
                    self.signals.queue_updated.emit()
                    break
                
                try:
                    url, site_type, chapter_range = self.download_queue.get(block=False)
                    
                    manga_name = self._get_manga_name(url, site_type)
                    logging.info(f"Processing manga: {manga_name} from {site_type}")
                    
                    if manga_name in self.paused_downloads:
                        logging.info(f"Skipping paused manga: {manga_name}")
                        self.download_queue.put((url, site_type, chapter_range))
                        self.download_queue.task_done()
                        time.sleep(0.5)
                        continue
                    
                    self.signals.manga_started.emit(manga_name)
                    
                    chapters = self._get_chapters(url, site_type)
                    if not chapters:
                        logging.warning(f"No chapters found for manga: {manga_name}")
                        self.signals.manga_failed.emit(manga_name, "No chapters found for this manga")
                        self.download_queue.task_done()
                        continue
                    
                    if chapter_range:
                        filtered_chapters = chapter_range
                        
                        if not filtered_chapters:
                            logging.warning(f"No valid chapters in selected range for {manga_name}")
                            self.signals.manga_failed.emit(manga_name, "No valid chapters in the selected range")
                            self.download_queue.task_done()
                            continue
                        
                        chapters = filtered_chapters
                    
                    logging.info(f"Processing {len(chapters)} chapters for {manga_name}")
                    
                    try:
                        chapters.sort(key=lambda x: float(x[0]) if x[0].replace('.', '', 1).isdigit() else x[0])
                        logging.info(f"Successfully sorted chapters for {manga_name}")
                    except Exception as sort_error:
                        logging.warning(f"Error sorting chapters: {sort_error}, using original order")
                    
                    successful_chapters = 0
                    total_chapters = len(chapters)
                    
                    for idx, (chapter_num, chapter_name, chapter_url) in enumerate(chapters):
                        try:
                            logging.info(f"Processing chapter {chapter_num} ({idx+1}/{total_chapters})")
                            
                            if manga_name in self.cancel_requested:
                                logging.info(f"Download cancelled for {manga_name}")
                                self.cancel_requested.remove(manga_name)
                                self.signals.download_cancelled.emit(manga_name)
                                break
                            
                            if manga_name in self.paused_downloads:
                                logging.info(f"Download paused for {manga_name}")
                                remaining_chapters = chapters[idx:]
                                self.download_queue.put((url, site_type, remaining_chapters))
                                self.signals.download_paused.emit(manga_name)
                                break
                            
                            self.signals.chapter_started.emit(manga_name, chapter_num)

                            chapter_path = os.path.join(self.download_path, manga_name, f"Chapter {chapter_num}.cbz")
                            if os.path.exists(chapter_path) and os.path.getsize(chapter_path) > 0:
                                logging.info(f"Chapter {chapter_num} already exists, skipping download")
                                self.signals.chapter_completed.emit(manga_name, chapter_num, chapter_path)
                                successful_chapters += 1
                            else:
                                cbz_path = self._download_chapter(chapter_url, chapter_num, manga_name, site_type)
                                
                                if cbz_path and os.path.exists(cbz_path) and os.path.getsize(cbz_path) > 0:
                                    self.signals.chapter_completed.emit(manga_name, chapter_num, cbz_path)
                                    successful_chapters += 1
                                else:
                                    error_msg = "Download failed - chapter may not exist or download failed"
                                    logging.warning(f"Chapter {chapter_num}: {error_msg}")
                                    self.signals.chapter_failed.emit(manga_name, chapter_num, error_msg)
                            
                            manga_progress = int((idx + 1) / total_chapters * 100)
                            self.signals.manga_progress.emit(manga_name, manga_progress)
                            
                        except Exception as chapter_error:
                            error_message = f"Failed to process chapter {chapter_num}: {str(chapter_error)}"
                            logging.error(error_message)
                            logging.error(traceback.format_exc())
                            self.signals.chapter_failed.emit(manga_name, chapter_num, error_message)
                            
                            manga_progress = int((idx + 1) / total_chapters * 100)
                            self.signals.manga_progress.emit(manga_name, manga_progress)
                    
                    if (manga_name not in self.cancel_requested and 
                        manga_name not in self.paused_downloads):
                        if successful_chapters > 0:
                            if successful_chapters == len(chapters):
                                logging.info(f"All chapters downloaded successfully for {manga_name}")
                                self.signals.manga_completed.emit(manga_name)
                            else:
                                logging.info(f"Partial download for {manga_name}: {successful_chapters}/{len(chapters)}")
                                self.signals.manga_completed.emit(f"{manga_name} (Partial: {successful_chapters}/{len(chapters)})")
                        else:
                            logging.warning(f"All chapters failed to download for {manga_name}")
                            self.signals.manga_failed.emit(manga_name, "All chapters failed to download")
                    
                except Exception as manga_error:
                    if 'manga_name' in locals():
                        logging.error(f"Error processing manga {manga_name}: {manga_error}")
                        logging.error(traceback.format_exc())
                        self.signals.manga_failed.emit(manga_name, f"Error: {str(manga_error)}")
                    else:
                        logging.error(f"Error processing manga (unknown): {manga_error}")
                        logging.error(traceback.format_exc())
                        self.signals.show_toast.emit(f"Error processing manga: {str(manga_error)}", "error")
                
                finally:
                    if not self.download_queue.empty() or ('manga_name' in locals() and manga_name in self.paused_downloads):
                        if 'manga_name' not in locals() or manga_name not in self.paused_downloads:
                            self.download_queue.task_done()
                    else:
                        self.download_queue.task_done()
            
            except queue.Empty:
                self.running = False
                self.download_queue_list = []
                self.signals.queue_updated.emit()
                break
            except Exception as e:
                logging.critical(f"Critical error in queue processing: {e}")
                logging.critical(traceback.format_exc())
                self.signals.show_toast.emit(f"Queue processing error: {str(e)}", "error")
                self.running = False
                break
    
    def _get_manga_name(self, url, site_type):
        if site_type == "asura":
            return asura_get_manga_name(url)
        elif site_type == "katana":
            return katana_get_manga_name(url)
        elif site_type == "webtoon":
            return webtoon_get_manga_name(url)
        return "Unknown Manga"
    
    def _get_chapters(self, url, site_type):
        if site_type == "asura":
            return asura_get_chapter_links(url)
        elif site_type == "katana":
            return katana_get_chapter_links(url)
        elif site_type == "webtoon":
            return webtoon_get_chapter_links(url)
        return []
    
    def _download_chapter(self, chapter_url, chapter_num, manga_name, site_type):
        """Enhanced download method with robust file checking and error handling"""
        if manga_name in self.cancel_requested:
            return ""
        
        self.signals.chapter_progress.emit(manga_name, chapter_num, 0)
        
        try:
            chapter_path = os.path.join(self.download_path, manga_name, f"Chapter {chapter_num}.cbz")
            logging.info(f"Checking if chapter exists: {chapter_path}")
            
            try:
                if os.path.exists(chapter_path) and os.path.getsize(chapter_path) > 0:
                    logging.info(f"Chapter {chapter_num} already exists at {chapter_path}")
                    self.signals.chapter_progress.emit(manga_name, chapter_num, 100)
                    return chapter_path
            except Exception as check_err:
                logging.error(f"Error checking if chapter exists: {check_err}")
            
            logging.info(f"Starting download for chapter {chapter_num} from {site_type}")
            
            if site_type == "asura":
                def progress_callback(current, total):
                    if total <= 0:
                        progress = 0
                    else:
                        progress = int((current / total) * 100)
                    self.signals.chapter_progress.emit(manga_name, chapter_num, progress)
                    
                cbz_path = asura_download_chapter(chapter_url, chapter_num, manga_name, 
                                                  self.download_path,
                                                  progress_callback=progress_callback)
            elif site_type == "katana":
                self.signals.chapter_progress.emit(manga_name, chapter_num, 20)
                result = katana_download_chapter(chapter_url, chapter_num, manga_name, 
                                                 self.download_path)
                
                if isinstance(result, dict):
                    cbz_path = result.get("path", "")
                    chapter_url = result.get("url", chapter_url)
                else:
                    cbz_path = result
                    
                self.signals.chapter_progress.emit(manga_name, chapter_num, 90)
                
                if not manga_name in self.cancel_requested:
                    delay = random.uniform(1, 5)
                    logging.info(f"Adding delay of {delay:.2f} seconds after MangaKatana download")
                    time.sleep(delay)
            elif site_type == "webtoon":
                self.signals.chapter_progress.emit(manga_name, chapter_num, 20)
                cbz_path = webtoon_download_chapter(chapter_url, chapter_num, manga_name,
                                                    self.download_path)
                self.signals.chapter_progress.emit(manga_name, chapter_num, 90)
            else:
                logging.error(f"Unknown site type: {site_type}")
                return ""
            
            if os.path.exists(chapter_path) and os.path.getsize(chapter_path) > 0:
                logging.info(f"Chapter file exists and has content: {chapter_path}")
                self.signals.chapter_progress.emit(manga_name, chapter_num, 100)
                return chapter_path
            elif cbz_path and os.path.exists(cbz_path) and os.path.getsize(cbz_path) > 0:
                logging.info(f"Successfully downloaded chapter {chapter_num} to {cbz_path}")
                self.signals.chapter_progress.emit(manga_name, chapter_num, 100)
                return cbz_path
            else:
                logging.warning(f"Download complete but file not found or empty: {cbz_path}")
                
                if site_type == "katana":
                    if os.path.exists(chapter_path) and os.path.getsize(chapter_path) > 0:
                        logging.info(f"Found chapter file at expected path: {chapter_path}")
                        return chapter_path
                
                return ""
                
        except Exception as e:
            logging.error(f"Error downloading chapter {chapter_num}: {str(e)}")
            logging.error(traceback.format_exc())
            self.signals.chapter_progress.emit(manga_name, chapter_num, 0)
            return ""
    
    def _track_download_progress(self, download_func, chapter_url, chapter_num, manga_name, site_type):
        """Simplified download progress tracking that won't interfere with the download process"""
        try:
            self.signals.chapter_progress.emit(manga_name, chapter_num, 0)
            
            result = download_func(chapter_url, chapter_num, manga_name)
            
            self.signals.chapter_progress.emit(manga_name, chapter_num, 100)
            
            if result:
                self.history_manager.add_downloaded_chapter(manga_name, chapter_num, site_type, chapter_url)
            
            return result
            
        except Exception as e:
            print(f"Error in download process: {e}")
            self.signals.chapter_progress.emit(manga_name, chapter_num, 0)
            raise
    
    def _parse_chapter_range(self, range_str):
        if not range_str:
            return (0, float('inf'))
        
        parts = range_str.strip().split('-')
        try:
            if len(parts) == 1:
                start = float(parts[0])
                return (start, start)
            elif len(parts) == 2:
                start = float(parts[0])
                end = float(parts[1])
                return (start, end)
            else:
                raise ValueError
        except ValueError:
            return (0, float('inf'))

    def set_download_path(self, path):
        """Set the download path for manga chapters"""
        if os.path.isdir(path):
            self.download_path = path
            return True
        return False

    def scan_for_new_chapters(self, manga_name=None):
        """
        Scan for new chapters for manga in history
        If manga_name is provided, only scan that specific manga
        Returns dict with manga names and lists of new chapters
        """
        new_chapters = {}
        manga_list = self.history_manager.get_manga_list()
        
        if manga_name and manga_name in manga_list:
            manga_list = [manga_name]
            
        for manga in manga_list:
            manga_data = self.history_manager.get_manga_data(manga)
            if not manga_data or not manga_data.get('url'):
                continue
                
            site_type = manga_data.get('site_type', '')
            url = manga_data.get('url', '')
            
            if not url or not site_type:
                continue
                
            try:
                all_chapters = self._get_chapters(url, site_type)
                downloaded_chapters = manga_data.get('chapters', {})
                
                missing_chapters = []
                for ch_num, ch_name, ch_url in all_chapters:
                    if ch_num not in downloaded_chapters:
                        missing_chapters.append((ch_num, ch_name, ch_url))
                
                if missing_chapters:
                    new_chapters[manga] = missing_chapters
            except Exception as e:
                logging.error(f"Error scanning chapters for {manga}: {e}")
                
        return new_chapters
    
    def download_new_chapters(self, new_chapters_dict):
        """Add new chapters to the download queue"""
        total_added = 0
        
        for manga_name, chapters in new_chapters_dict.items():
            if not chapters:
                continue
                
            manga_data = self.history_manager.get_manga_data(manga_name)
            if not manga_data or not manga_data.get('url'):
                continue
                
            url = manga_data.get('url')
            site_type = manga_data.get('site_type')
            
            self.add_to_queue(url, chapters)
            total_added += len(chapters)
            
        return total_added

class Toast(QDialog):
    def __init__(self, parent=None):
        super(Toast, self).__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.close)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 10, 15, 15)
        
        top_bar = QHBoxLayout()
        
        self.title_label = QLabel("")
        self.title_label.setFont(QFont("Arial", 10, QFont.Bold))
        top_bar.addWidget(self.title_label)
        
        top_bar.addStretch()
        
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                color: white;
                border-radius: 15px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.4);
            }
        """)
        self.close_btn.clicked.connect(self.close)
        top_bar.addWidget(self.close_btn)
        
        layout.addLayout(top_bar)
        
        self.message_label = QLabel()
        self.message_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.message_label.setWordWrap(True)
        
        font = QFont()
        font.setPointSize(11)
        self.message_label.setFont(font)
        
        self.message_label.setStyleSheet("padding: 10px 5px;")
        
        layout.addWidget(self.message_label)
        self.setLayout(layout)
    
    def show_message(self, message, type="info", duration=3000):
        self.message_label.setText(message)
        
        if type == "error":
            self.setStyleSheet("""
                QDialog {
                    background-color: white;
                    border: 2px solid #E53935;
                    border-radius: 10px;
                }
                QLabel#title_label {
                    color: #E53935;
                    font-weight: bold;
                }
                QLabel {
                    color: #E53935;
                }
                QPushButton {
                    color: #E53935;
                }
            """)
            self.title_label.setText("Error")
            self.close_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(229, 57, 53, 0.2);
                    color: #E53935;
                    border-radius: 15px;
                    font-size: 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(229, 57, 53, 0.4);
                }
            """)
            duration = 30000
        elif type == "success":
            self.setStyleSheet("""
                QDialog {
                    background-color: #43A047;
                    border-radius: 10px;
                }
                QLabel {
                    color: white;
                }
                QPushButton {
                    color: white;
                }
            """)
            self.title_label.setText("Success")
        else:
            self.setStyleSheet("""
                QDialog {
                    background-color: #2196F3;
                    border-radius: 10px;
                }
                QLabel {
                    color: white;
                }
                QPushButton {
                    color: white;
                }
            """)
            self.title_label.setText("Information")
            
        if self.parent():
            parent_rect = self.parent().geometry()
            width = min(400, parent_rect.width() - 40)
            height = min(150, parent_rect.height() - 40)
            
            x = parent_rect.x() + max(20, min(parent_rect.width() - width - 20, 
                                              parent_rect.width() - width - 20))
            y = parent_rect.y() + max(20, min(parent_rect.height() - height - 20,
                                              parent_rect.height() - height - 20))
            
            self.setGeometry(x, y, width, height)
        
        self.show()
        self.timer.start(duration)
        
        self.raise_()
        self.activateWindow()

class SidebarButton(QToolButton):
    """Custom button for sidebar navigation"""
    def __init__(self, text, icon=None, parent=None):
        super(SidebarButton, self).__init__(parent)
        self.setText(text)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        
        if icon:
            self.setIcon(QIcon(icon))
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(50)
        
        self.setStyleSheet("""
            QToolButton {
                border: none;
                border-radius: 0px;
                text-align: left;
                padding: 10px;
                color: #333;
                font-weight: bold;
            }
            QToolButton:hover {
                background-color: #e0e0e0;
            }
            QToolButton:checked {
                background-color: #2196F3;
                color: white;
            }
        """)

class Sidebar(QWidget):
    """Sidebar navigation widget"""
    itemClicked = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super(Sidebar, self).__init__(parent)
        self.initUI()
        
    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.download_btn = SidebarButton("Downloads")
        self.download_btn.setChecked(True)
        self.download_btn.clicked.connect(lambda: self.itemClicked.emit("downloads"))
        
        self.history_btn = SidebarButton("History")
        self.history_btn.clicked.connect(lambda: self.itemClicked.emit("history"))
        
        logo_label = QLabel("MasterOfKay's\nMangaDL")
        logo_label.setStyleSheet("""
            QLabel {
                color: #2196F3;
                font-size: 18px;
                font-weight: bold;
                padding: 15px;
                background-color: #f5f5f5;
            }
        """)
        
        layout.addWidget(logo_label)
        layout.addWidget(self.download_btn)
        layout.addWidget(self.history_btn)
        layout.addStretch()
        
        settings_btn = SidebarButton("Settings")
        settings_btn.clicked.connect(lambda: self.itemClicked.emit("settings"))
        layout.addWidget(settings_btn)
        
        self.setMaximumWidth(200)
        self.setMinimumWidth(200)

class ChapterSelectionDialog(QDialog):
    def __init__(self, manga_name, chapters, parent=None):
        super(ChapterSelectionDialog, self).__init__(parent)
        self.manga_name = manga_name
        self.chapters = chapters
        self.setWindowTitle(f"Select Chapters - {manga_name}")
        self.resize(500, 400)
        self.selected_chapters = []
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        header = QLabel(f"Select chapters to download for: {self.manga_name}")
        header.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(header)
        
        quick_select = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all)
        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.clicked.connect(self.clear_all)
        
        range_label = QLabel("Or select range:")
        self.range_start = QSpinBox()
        self.range_start.setMinimum(1)
        self.range_start.setMaximum(len(self.chapters))
        self.range_end = QSpinBox()
        self.range_end.setMinimum(1)
        self.range_end.setMaximum(len(self.chapters))
        self.range_end.setValue(len(self.chapters))
        range_apply = QPushButton("Apply Range")
        range_apply.clicked.connect(self.apply_range)
        
        quick_select.addWidget(select_all_btn)
        quick_select.addWidget(clear_all_btn)
        quick_select.addWidget(range_label)
        quick_select.addWidget(self.range_start)
        quick_select.addWidget(QLabel("to"))
        quick_select.addWidget(self.range_end)
        quick_select.addWidget(range_apply)
        layout.addLayout(quick_select)
        
        chapters_area = QScrollArea()
        chapters_area.setWidgetResizable(True)
        chapters_widget = QWidget()
        chapters_layout = QVBoxLayout(chapters_widget)
        
        self.chapter_checkboxes = []
        for i, (chapter_num, chapter_name, _) in enumerate(self.chapters):
            cb = QCheckBox(f"Chapter {chapter_num}: {chapter_name}")
            cb.setChecked(True)
            self.chapter_checkboxes.append(cb)
            chapters_layout.addWidget(cb)
        
        chapters_area.setWidget(chapters_widget)
        layout.addWidget(chapters_area)
        
        buttons = QHBoxLayout()
        ok_btn = QPushButton("Download Selected")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)
        
        self.setLayout(layout)
    
    def select_all(self):
        for cb in self.chapter_checkboxes:
            cb.setChecked(True)
    
    def clear_all(self):
        for cb in self.chapter_checkboxes:
            cb.setChecked(False)
    
    def apply_range(self):
        start = self.range_start.value() - 1
        end = self.range_end.value() - 1
        
        for i, cb in enumerate(self.chapter_checkboxes):
            cb.setChecked(start <= i <= end)
    
    def get_selected_chapters(self):
        selected = []
        for i, cb in enumerate(self.chapter_checkboxes):
            if cb.isChecked():
                selected.append(self.chapters[i])
        return selected

class HistoryListItemWidget(QWidget):
    clicked = pyqtSignal(str)
    download_new_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)
    
    def __init__(self, manga_name, chapter_count=0, last_update="", has_new=False, site_type="", url="", parent=None):
        super(HistoryListItemWidget, self).__init__(parent)
        self.manga_name = manga_name
        self.has_new = has_new
        self.url = url
        
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        top_layout = QHBoxLayout()
        self.name_label = QLabel(manga_name)
        self.name_label.setFont(QFont("Arial", 10, QFont.Bold))
        
        status_text = f"{chapter_count} chapters"
        if has_new:
            status_text += " • New chapters! 🆕"
        
        self.status_label = QLabel(status_text)
        self.status_label.setStyleSheet("color: #666;")
        
        if has_new:
            self.download_btn = QPushButton("Download New")
            self.download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border-radius: 4px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
            self.download_btn.clicked.connect(lambda: self.download_new_clicked.emit(manga_name))
        else:
            self.download_btn = QPushButton("Check")
            self.download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border-radius: 4px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #0b7dda;
                }
            """)
            self.download_btn.clicked.connect(lambda: self.download_new_clicked.emit(manga_name))
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self.delete_btn.clicked.connect(lambda: self.delete_clicked.emit(manga_name))
        
        self.site_label = QLabel(f"Source: {site_type}")
        self.site_label.setStyleSheet("color: #999; font-size: 9pt;")
        
        self.url_label = QLabel(f"<a href='{url}'>Open Manga</a>")
        self.url_label.setOpenExternalLinks(True)
        self.url_label.setStyleSheet("color: #2196F3; font-size: 9pt;")
        
        top_layout.addWidget(self.name_label)
        top_layout.addStretch()
        top_layout.addWidget(self.download_btn)
        top_layout.addWidget(self.delete_btn)
        
        info_layout = QHBoxLayout()
        date_label = QLabel(f"Last update: {last_update}")
        date_label.setStyleSheet("color: #999; font-size: 9pt;")
        info_layout.addWidget(date_label)
        info_layout.addStretch()
        
        layout.addLayout(top_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.site_label)
        layout.addWidget(self.url_label)
        layout.addLayout(info_layout)
        
        self.setStyleSheet("""
            HistoryListItemWidget {
                background-color: white;
                border-radius: 8px;
                border: 1px solid #ddd;
            }
            HistoryListItemWidget:hover {
                background-color: #f5f5f5;
                border: 1px solid #ccc;
            }
        """)
    
    def set_has_new(self, has_new):
        self.has_new = has_new
        chapter_count = int(self.status_label.text().split()[0])
        status_text = f"{chapter_count} chapters"
        
        if has_new:
            status_text += " • New chapters! 🆕"
            self.download_btn.setText("Download New")
            self.download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border-radius: 4px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)
        else:
            self.download_btn.setText("Check")
            self.download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border-radius: 4px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #0b7dda;
                }
            """)
        
        self.status_label.setText(status_text)
    
    def mousePressEvent(self, event):
        """Handle mouse click events with proper event handling"""
        if event.button() == Qt.LeftButton:
            if not self.download_btn.geometry().contains(event.pos()) and not self.delete_btn.geometry().contains(event.pos()):
                self.clicked.emit(self.manga_name)
                event.accept()
                return
        
        super(HistoryListItemWidget, self).mousePressEvent(event)

class ChapterListItem(QWidget):
    retry_clicked = pyqtSignal(str, str)
    
    def __init__(self, manga_name, chapter_num, chapter_name, status="", parent=None):
        super(ChapterListItem, self).__init__(parent)
        self.manga_name = manga_name
        self.chapter_num = chapter_num
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(16, 16)
        self.status_indicator.setStyleSheet("border-radius: 8px; background-color: #ddd;")
        
        chapter_label = QLabel(f"Chapter {chapter_num}: {chapter_name}")
        chapter_label.setFont(QFont("Arial", 10))
        
        self.status_label = QLabel(status)
        self.status_label.setFixedWidth(100)
        
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setFixedWidth(60)
        self.retry_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                border-radius: 4px;
                padding: 3px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self.retry_btn.clicked.connect(lambda: self.retry_clicked.emit(manga_name, chapter_num))
        self.retry_btn.hide()
        
        layout.addWidget(self.status_indicator)
        layout.addWidget(chapter_label)
        layout.addStretch()
        layout.addWidget(self.status_label)
        layout.addWidget(self.retry_btn)
        
        self.setStyleSheet("padding: 3px; margin: 2px 0;")
        self.update_status("unknown")
    def update_status(self, status):
        """Update visual status indicators"""
        if status == "completed" or status == "downloaded":
            self.status_indicator.setStyleSheet("border-radius: 8px; background-color: #4CAF50;")
            self.status_label.setText("Downloaded")
            self.status_label.setStyleSheet("color: #4CAF50;")
            self.retry_btn.hide()
        elif status == "failed":
            self.status_indicator.setStyleSheet("border-radius: 8px; background-color: #F44336;")
            self.status_label.setText("Failed")
            self.status_label.setStyleSheet("color: #F44336;")
            self.retry_btn.show()
        elif status == "downloading":
            self.status_indicator.setStyleSheet("border-radius: 8px; background-color: #FFC107;")
            self.status_label.setText("Downloading")
            self.status_label.setStyleSheet("color: #FFC107;")
            self.retry_btn.hide()
        elif status == "new":
            self.status_indicator.setStyleSheet("border-radius: 8px; background-color: #2196F3;")
            self.status_label.setText("New! 🆕")
            self.status_label.setStyleSheet("color: #2196F3;")
            self.retry_btn.hide()
        else:
            self.status_indicator.setStyleSheet("border-radius: 8px; background-color: #9E9E9E;")
            self.status_label.setText("Not Downloaded")
            self.status_label.setStyleSheet("color: #9E9E9E;")
            self.retry_btn.hide()

class DownloadListItemWidget(QWidget):
    clicked = pyqtSignal(str)
    pause_clicked = pyqtSignal(str, bool)
    
    def __init__(self, manga_name, status="Queued", parent=None):
        super(DownloadListItemWidget, self).__init__(parent)
        self.manga_name = manga_name
        self.status = status
        self.progress = 0
        self.paused = False
        
        self.setMouseTracking(True)
        
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        top_layout = QHBoxLayout()
        self.name_label = QLabel(manga_name)
        self.name_label.setFont(QFont("Arial", 10, QFont.Bold))
        self.status_label = QLabel(status)
        
        self.pause_btn = QPushButton("⏸")
        self.pause_btn.setFixedSize(24, 24)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border-radius: 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.pause_btn.clicked.connect(self.toggle_pause)
        
        self.cancel_btn = QPushButton("×")
        self.cancel_btn.setFixedSize(24, 24)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                border-radius: 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #E53935;
            }
        """)

        top_layout.addWidget(self.name_label)
        top_layout.addStretch()
        top_layout.addWidget(self.status_label)
        top_layout.addWidget(self.pause_btn)
        top_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(top_layout)
        
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        
        layout.addWidget(self.progress_bar)
        
        self.update_status(status)
        
        self.setLayout(layout)
    
    def update_progress(self, progress):
        """Update the progress bar value"""
        if not hasattr(self, 'progress_bar') or self.progress_bar is None:
            self.progress_bar = QProgressBar(self)
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(100)
            self.layout().addWidget(self.progress_bar)
        
        self.progress = progress
        if hasattr(self, 'progress_bar') and self.progress_bar is not None:
            self.progress_bar.setValue(progress)
        
        if self.status == "Downloading" and not self.paused:
                    self.status_label.setText(f"Downloading ({progress}%)")
    
    def toggle_pause(self):
        """Toggle the paused state and emit signal"""
        self.paused = not self.paused
        self.update_pause_button()
        self.pause_clicked.emit(self.manga_name, self.paused)
    
    def update_pause_button(self):
        """Update the pause button appearance based on state"""
        if self.paused:
            self.pause_btn.setText("▶")
            self.pause_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border-radius: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #388E3C;
                }
            """)
        else:
            self.pause_btn.setText("⏸")
            self.pause_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border-radius: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1976D2;
                }
            """)

    def set_paused(self, paused):
        """Set the paused state without triggering signals"""
        self.paused = paused
        self.update_pause_button()
        if self.status == "Downloading":
            if paused:
                self.status_label.setText("Paused")
            else:
                self.status_label.setText(f"Downloading ({self.progress}%)")
    
    def update_status(self, status):
        """Update status and styling"""
        self.status = status
        self.status_label.setText(status)
        
        if status == "Completed":
            self.name_label.setStyleSheet("color: #4CAF50;")  # Green
            self.status_label.setStyleSheet("color: #4CAF50;")
            self.progress_bar.hide()
            self.pause_btn.hide()
        elif status == "Failed":
            self.name_label.setStyleSheet("color: #F44336;")  # Red
            self.status_label.setStyleSheet("color: #F44336;")
            self.progress_bar.hide()
            self.pause_btn.hide()
        elif status == "Downloading":
            self.name_label.setStyleSheet("color: #2196F3;")  # Blue
            self.status_label.setStyleSheet("color: #2196F3;")
            self.progress_bar.show()
            self.pause_btn.show()
            if self.paused:
                self.status_label.setText("Paused")
        elif status == "Paused":
            self.name_label.setStyleSheet("color: #FFC107;")  # Amber
            self.status_label.setStyleSheet("color: #FFC107;")
            self.progress_bar.show()
            self.pause_btn.show()
            self.paused = True
            self.update_pause_button()
        else:
            self.name_label.setStyleSheet("color: #9E9E9E;")  # Gray
            self.status_label.setStyleSheet("color: #9E9E9E;")
            self.progress_bar.show()
            self.pause_btn.show()
    
    def mousePressEvent(self, event):
        """Handle mouse click events with proper event handling"""
        if event.button() == Qt.LeftButton:
            if (self.pause_btn.geometry().contains(event.pos()) or 
                self.cancel_btn.geometry().contains(event.pos())):
                super(DownloadListItemWidget, self).mousePressEvent(event)
                return
            else:
                self.clicked.emit(self.manga_name)
                event.accept()
                return
        
        super(DownloadListItemWidget, self).mousePressEvent(event)

class MangaDownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Manga Downloader")
        self.resize(1000, 700)
        
        self.download_path = os.path.abspath(os.getcwd())
        self.load_download_path()
        
        self.signals = DownloadSignals()
        self.download_manager = DownloadManager(self.signals)
        self.history_manager = self.download_manager.history_manager
        
        self.download_manager.download_path = self.download_path
        
        self.signals.manga_started.connect(self.on_manga_started)
        self.signals.manga_completed.connect(self.on_manga_completed)
        self.signals.manga_failed.connect(self.on_manga_failed)
        self.signals.chapter_started.connect(self.on_chapter_started)
        self.signals.chapter_progress.connect(self.on_chapter_progress)
        self.signals.chapter_completed.connect(self.on_chapter_completed)
        self.signals.chapter_failed.connect(self.on_chapter_failed)
        self.signals.show_toast.connect(self.show_toast)
        self.signals.manga_progress.connect(self.on_manga_progress)
        self.signals.download_cancelled.connect(self.on_download_cancelled)
        self.signals.queue_updated.connect(self.update_queue_display)
        self.signals.download_paused.connect(self.on_download_paused)
        self.signals.download_resumed.connect(self.on_download_resumed)
        
        self.manga_status = {} 
        self.chapter_status = {}
        self.chapter_progress = {}
        
        self.chapter_panel_closed_by_user = False

        self.init_ui()
        
        QTimer.singleShot(1000, self.scan_all_manga)
    
    def load_download_path(self):
        """Load download path from config if available"""
        config_path = os.path.join(os.path.expanduser("~"), ".mangadownloader", "config.txt")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    for line in f:
                        if line.startswith("download_path="):
                            path = line.strip().split("=", 1)[1]
                            if os.path.isdir(path):
                                self.download_path = path
                                break
            except Exception as e:
                print(f"Error loading config: {e}")
    
    def save_download_path(self):
        """Save download path to a config file"""
        config_dir = os.path.join(os.path.expanduser("~"), ".mangadownloader")
        os.makedirs(config_dir, exist_ok=True)
        
        config_path = os.path.join(config_dir, "config.txt")
        with open(config_path, "w") as f:
            f.write(f"download_path={self.download_path}")
    
    def on_path_changed(self, path):
        """Handle when user types or pastes a path"""
        if os.path.isdir(path):
            self.download_path = path
            self.save_download_path()
            self.download_manager.download_path = self.download_path
    
    def browse_for_path(self):
        """Open file dialog to select download directory"""
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Download Folder",
            self.download_path,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if path:
            self.download_path = path
            self.path_input.setText(path)
            self.save_download_path()
            self.download_manager.download_path = self.download_path
    
    def init_ui(self):
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.sidebar = Sidebar()
        self.sidebar.itemClicked.connect(self.on_sidebar_item_clicked)
        
        self.content_stack = QStackedWidget()
        
        downloads_page = QWidget()
        downloads_layout = QVBoxLayout(downloads_page)
        downloads_layout.setContentsMargins(20, 20, 20, 20)
        
        url_layout = QHBoxLayout()
        url_label = QLabel("Manga URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter manga URL (e.g., https://asuracomic.net/series/manga-title)")
        download_btn = QPushButton("Download")
        download_btn.clicked.connect(self.start_download)
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(download_btn)
        downloads_layout.addLayout(url_layout)
        
        path_layout = QHBoxLayout()
        path_label = QLabel("Save Path:")
        self.path_input = QLineEdit(self.download_path)
        self.path_input.setPlaceholderText("Path where manga will be saved")
        self.path_input.textChanged.connect(self.on_path_changed)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_for_path)
        
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(browse_btn)
        downloads_layout.addLayout(path_layout)
        
        self.queue_status_label = QLabel("No downloads in queue")
        downloads_layout.addWidget(self.queue_status_label)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        self.downloads_layout = QVBoxLayout(scroll_content)
        self.downloads_layout.setAlignment(Qt.AlignTop)
        scroll_area.setWidget(scroll_content)
        downloads_layout.addWidget(scroll_area)
        
        clear_btn = QPushButton("Clear Completed")
        clear_btn.clicked.connect(self.clear_completed_downloads)
        downloads_layout.addWidget(clear_btn)
        
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(20, 20, 20, 20)
        
        history_header = QLabel("Download History")
        history_header.setFont(QFont("Arial", 16, QFont.Bold))
        history_layout.addWidget(history_header)
        
        scan_layout = QHBoxLayout()
        scan_btn = QPushButton("Scan All for New Chapters")
        scan_btn.clicked.connect(self.scan_all_manga)
        scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border-radius: 4px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
        """)
        
        scan_external_btn = QPushButton("Scan External Chapters")
        scan_external_btn.clicked.connect(self.scan_all_external_chapters)
        scan_external_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border-radius: 4px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
        """)
        
        download_all_btn = QPushButton("Download All New")
        download_all_btn.clicked.connect(self.download_all_new)
        download_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border-radius: 4px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        scan_layout.addWidget(scan_btn)
        scan_layout.addWidget(scan_external_btn)
        scan_layout.addWidget(download_all_btn)
        history_layout.addLayout(scan_layout)
        
        self.history_list_scroll = QScrollArea()
        self.history_list_scroll.setWidgetResizable(True)
        history_content = QWidget()
        self.history_layout = QVBoxLayout(history_content)
        self.history_layout.setAlignment(Qt.AlignTop)
        self.history_layout.setSpacing(10)
        self.history_list_scroll.setWidget(history_content)
        history_layout.addWidget(self.history_list_scroll)
        
        settings_page = QWidget()
        settings_layout = QVBoxLayout(settings_page)
        settings_layout.setContentsMargins(20, 20, 20, 20)
        
        settings_header = QLabel("Settings")
        settings_header.setFont(QFont("Arial", 16, QFont.Bold))
        settings_layout.addWidget(settings_header)
        
        settings_layout.addStretch()
        
        self.content_stack.addWidget(downloads_page)
        self.content_stack.addWidget(history_page)
        self.content_stack.addWidget(settings_page)
        
        self.chapter_panel = QWidget()
        self.chapter_panel.setMaximumWidth(0)
        self.chapter_panel.setMinimumWidth(0)
        
        chapter_panel_layout = QVBoxLayout(self.chapter_panel)
        chapter_panel_layout.setContentsMargins(0, 0, 0, 0)
        
        chapter_header_layout = QHBoxLayout()
        self.chapter_details_title = QLabel("Manga Title")
        self.chapter_details_title.setFont(QFont("Arial", 12, QFont.Bold))
        
        close_btn = QPushButton("×")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                color: #333;
                border-radius: 15px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
        """)
        close_btn.clicked.connect(self.hide_chapter_panel)
        
        chapter_header_layout.addWidget(self.chapter_details_title)
        chapter_header_layout.addStretch()
        chapter_header_layout.addWidget(close_btn)
        
        chapter_panel_layout.addLayout(chapter_header_layout)
        
        chapter_scroll = QScrollArea()
        chapter_scroll.setWidgetResizable(True)
        
        chapter_content = QWidget()
        self.chapter_list_layout = QVBoxLayout(chapter_content)
        self.chapter_list_layout.setAlignment(Qt.AlignTop)
        chapter_scroll.setWidget(chapter_content)
        
        chapter_panel_layout.addWidget(chapter_scroll)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.sidebar)
        
        content_container = QWidget()
        container_layout = QHBoxLayout(content_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.content_stack)
        container_layout.addWidget(self.chapter_panel)
        
        splitter.addWidget(content_container)
        
        main_layout.addWidget(splitter)
        
        self.setCentralWidget(central_widget)
        
        self.create_menu_bar()
        
        self.populate_history_list()
    
    def create_menu_bar(self):
        """Create application menu bar"""
        menu_bar = self.menuBar()
        
        file_menu = menu_bar.addMenu("&File")
        
        scan_action = QAction("&Scan for New Chapters", self)
        scan_action.triggered.connect(self.scan_all_manga)
        file_menu.addAction(scan_action)
        
        scan_external_action = QAction("Scan for &External Chapters", self)
        scan_external_action.triggered.connect(self.scan_all_external_chapters)
        file_menu.addAction(scan_external_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        help_menu = menu_bar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About MasterOfKay's Manga Downloader",
            """
            <h3>MasterOfKay's Manga Downloader v1.3.1</h3>
            <p>Download manga from popular sites with history tracking.</p>
            <p>Supported sites:</p>
            <ul>
                <li>AsuraScans</li>
                <li>MangaKatana</li>
                <li>Webtoon</li>
            </ul>
            <p>For personal use only.</p>
            """
        )
    
    def on_sidebar_item_clicked(self, item):
        """Handle sidebar navigation"""
        if item == "downloads":
            self.content_stack.setCurrentIndex(0)
        elif item == "history":
            self.content_stack.setCurrentIndex(1)
            self.populate_history_list()
        elif item == "settings":
            self.content_stack.setCurrentIndex(2)
    
    def populate_history_list(self):
        """Populate the history list with manga from history"""

        while self.history_layout.count():
            item = self.history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        manga_list = self.history_manager.get_manga_list()
        
        if not manga_list:
            empty_label = QLabel("No manga in history")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("color: #999; font-size: 14px; padding: 20px;")
            self.history_layout.addWidget(empty_label)
            return
        
        sorted_manga = []
        for manga_name in manga_list:
            manga_data = self.history_manager.get_manga_data(manga_name)
            last_updated = manga_data.get('last_updated', '')
            
            if last_updated:
                try:
                    last_updated_date = datetime.fromisoformat(last_updated)
                    sorted_manga.append((manga_name, last_updated_date))
                except ValueError:
                    sorted_manga.append((manga_name, datetime.min))
            else:
                sorted_manga.append((manga_name, datetime.min))
        
        sorted_manga.sort(key=lambda x: x[1], reverse=True)
        
        for manga_name, last_updated_date in sorted_manga:
            manga_data = self.history_manager.get_manga_data(manga_name)
            chapters = manga_data.get('chapters', {})
            site_type = manga_data.get('site_type', 'unknown')
            url = manga_data.get('url', '')
            
            last_updated_str = last_updated_date.strftime("%Y-%m-%d %H:%M")
            
            if hasattr(self, 'new_chapters_cache') and manga_name in self.new_chapters_cache:
                has_new = True
            else:
                has_new = False
            
            item = HistoryListItemWidget(
                manga_name=manga_name,
                chapter_count=len(chapters),
                last_update=last_updated_str,
                has_new=has_new,
                site_type=site_type,
                url=url
            )
            
            item.clicked.connect(self.display_manga_chapters)
            item.download_new_clicked.connect(self.download_manga_new_chapters)
            item.delete_clicked.connect(self.delete_manga)
            
            self.history_layout.addWidget(item)
    
    def delete_manga(self, manga_name):
        """Delete a manga from history"""
        try:
            confirm = QMessageBox.question(
                self,
                "Confirm Deletion",
                f"Are you sure you want to delete {manga_name} from your history?\n\nThis will not delete the downloaded files.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if confirm == QMessageBox.Yes:
                self.history_manager.delete_manga(manga_name)
                
                if hasattr(self, 'new_chapters_cache') and manga_name in self.new_chapters_cache:
                    del self.new_chapters_cache[manga_name]
                
                if hasattr(self, '_last_displayed_manga') and self._last_displayed_manga == manga_name:
                    self.hide_chapter_panel()
                    
                self.populate_history_list()
                
                self.show_toast(f"Removed {manga_name} from history", "success")
        except Exception as e:
            logging.error(f"Error deleting manga: {e}")
            self.show_toast(f"Error deleting manga: {str(e)}", "error")
    
    def scan_all_manga(self):
        """Scan all manga in history for new chapters"""
        self.signals.show_toast.emit("Scanning for new chapters...", "info")
        
        def scan_task():
            new_chapters = self.download_manager.scan_for_new_chapters()
            
            self.new_chapters_cache = new_chapters
            
            total_new = sum(len(chapters) for chapters in new_chapters.values())
            manga_count = len(new_chapters)
            
            if total_new > 0:
                self.signals.show_toast.emit(
                    f"Found {total_new} new chapters for {manga_count} manga!", 
                    "success"
                )
                
                for i in range(self.history_layout.count()):
                    item = self.history_layout.itemAt(i).widget()
                    if isinstance(item, HistoryListItemWidget):
                        if item.manga_name in new_chapters:
                            item.set_has_new(True)
            else:
                self.signals.show_toast.emit("No new chapters found", "info")
        
        threading.Thread(target=scan_task, daemon=True).start()
    
    def scan_all_external_chapters(self):
        """Scan all manga directories for externally downloaded chapters"""
        self.signals.show_toast.emit("Scanning for external chapters...", "info")
        
        def scan_task():
            try:
                total_added = 0
                manga_list = self.history_manager.get_manga_list()
                
                try:
                    if os.path.exists(self.download_path):
                        for dirname in os.listdir(self.download_path):
                            if os.path.isdir(os.path.join(self.download_path, dirname)):
                                if dirname not in manga_list:
                                    self.history_manager.add_manga(dirname, "", "unknown")
                                    manga_list.append(dirname)
                except Exception as dir_scan_err:
                    logging.error(f"Error scanning directories: {dir_scan_err}")
                
                for manga_name in manga_list:
                    added = self.scan_external_chapters(manga_name)
                    if added:
                        total_added += 1
                
                if total_added > 0:
                    self.signals.show_toast.emit(
                        f"Found external chapters for {total_added} manga", 
                        "success"
                    )
                    if hasattr(self, '_last_displayed_manga'):
                        self.display_manga_chapters(self._last_displayed_manga)
                else:
                    self.signals.show_toast.emit("No new external chapters found", "info")
            
            except Exception as e:
                logging.error(f"Error in external chapter scan: {e}")
                self.signals.show_toast.emit(f"Error scanning: {str(e)}", "error")
        
        threading.Thread(target=scan_task, daemon=True).start()
    
    def check_manga_for_updates(self, manga_name):
        """Check single manga for updates"""
        self.signals.show_toast.emit(f"Checking {manga_name} for updates...", "info")
        
        def check_task():
            try:
                new_chapters = self.download_manager.scan_for_new_chapters(manga_name)
                
                if not hasattr(self, 'new_chapters_cache'):
                    self.new_chapters_cache = {}
                
                if manga_name in new_chapters and new_chapters[manga_name]:
                    self.new_chapters_cache[manga_name] = new_chapters[manga_name]
                    count = len(new_chapters[manga_name])
                    
                    def on_chapters_found():
                        self.signals.show_toast.emit(
                            f"Found {count} new chapters for {manga_name}!", 
                            "success"
                        )
                        
                        for i in range(self.history_layout.count()):
                            item = self.history_layout.itemAt(i).widget()
                            if isinstance(item, HistoryListItemWidget) and item.manga_name == manga_name:
                                item.set_has_new(True)
                                break
                        
                        if hasattr(self, '_last_displayed_manga') and self._last_displayed_manga == manga_name:
                            self.display_manga_chapters(manga_name)
                        
                        response = QMessageBox.question(
                            self, 
                            "New Chapters Found", 
                            f"Download {count} new chapters for {manga_name} now?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        
                        if response == QMessageBox.Yes:
                            chapters_to_download = {manga_name: new_chapters[manga_name][:]}
                            self.download_new_chapters_safe(chapters_to_download)
                            self.update_queue_display()
                    
                    QTimer.singleShot(0, on_chapters_found)
                else:
                    def on_no_chapters():
                        if manga_name in self.new_chapters_cache:
                            del self.new_chapters_cache[manga_name]
                        
                        self.signals.show_toast.emit(f"No new chapters found for {manga_name}", "info")
                        
                        for i in range(self.history_layout.count()):
                            item = self.history_layout.itemAt(i).widget()
                            if isinstance(item, HistoryListItemWidget) and item.manga_name == manga_name:
                                item.set_has_new(False)
                                break
                    
                    QTimer.singleShot(0, on_no_chapters)
            except Exception as e:
                def on_error():
                    self.signals.show_toast.emit(f"Error checking for updates: {str(e)}", "error")
                
                QTimer.singleShot(0, on_error)
        
        threading.Thread(target=check_task, daemon=True).start()

    def download_manga_new_chapters(self, manga_name):
        """Directly download new chapters for a specific manga"""
        if not hasattr(self, 'new_chapters_cache') or manga_name not in self.new_chapters_cache:
            self.signals.show_toast.emit(f"No new chapters found for {manga_name}", "info")
            return
        
        chapters = self.new_chapters_cache[manga_name]
        if not chapters:
            self.signals.show_toast.emit(f"No new chapters found for {manga_name}", "info")
            return
        
        chapters_to_download = {manga_name: chapters[:]}
        
        count = len(chapters)
        self.download_new_chapters_safe(chapters_to_download)
        
        self.signals.show_toast.emit(f"Added {count} new chapters of {manga_name} to download queue", "success")
        
        self.sidebar.download_btn.setChecked(True)
        self.content_stack.setCurrentIndex(0)
        
        self.update_queue_display()
        
        for i in range(self.history_layout.count()):
            item = self.history_layout.itemAt(i).widget()
            if isinstance(item, HistoryListItemWidget) and item.manga_name == manga_name:
                item.set_has_new(False)
                break

    def download_new_chapters_safe(self, new_chapters_dict):
        """Thread-safe version to add new chapters to download queue"""
        added = 0
        
        for manga_name, chapters in new_chapters_dict.items():
            if not chapters:
                continue
                
            manga_data = self.history_manager.get_manga_data(manga_name)
            if not manga_data or not manga_data.get('url'):
                continue
                
            url = manga_data.get('url')
            site_type = manga_data.get('site_type')
            
            success = self.download_manager.add_to_queue(url, chapters)
            if success:
                added += len(chapters)
                
                if hasattr(self, 'new_chapters_cache') and manga_name in self.new_chapters_cache:
                    del self.new_chapters_cache[manga_name]
        
        if added > 0:
            self.signals.show_toast.emit(f"Added {added} chapters to download queue", "success")
            
            self.sidebar.download_btn.setChecked(True)
            self.content_stack.setCurrentIndex(0)
            
            self.populate_history_list()
            self.update_queue_display()
        else:
            self.signals.show_toast.emit("Failed to add chapters to queue", "error")

    def download_all_new(self):
        """Download all new chapters that have been found"""
        if not hasattr(self, 'new_chapters_cache') or not self.new_chapters_cache:
            self.signals.show_toast.emit("No new chapters found to download", "info")
            return
        
        count = sum(len(chapters) for chapters in self.new_chapters_cache.values())
        manga_count = len(self.new_chapters_cache)
        
        response = QMessageBox.question(
            self, 
            "Download New Chapters", 
            f"Download {count} new chapters for {manga_count} manga?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if response == QMessageBox.Yes:
            import copy
            cache_copy = copy.deepcopy(self.new_chapters_cache)
            self.download_new_chapters_safe(cache_copy)
            self.update_queue_display()

    def display_manga_chapters(self, manga_name):
        """Display chapters for a manga in the side panel"""
        logging.info(f"Displaying chapters for {manga_name}")
        self._last_displayed_manga = manga_name
        self.chapter_details_title.setText(manga_name)
        
        while self.chapter_list_layout.count():
            item = self.chapter_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        loading = QLabel("Loading chapters...")
        loading.setAlignment(Qt.AlignCenter)
        self.chapter_list_layout.addWidget(loading)
        
        self.animate_chapter_panel_show()
        
        class ChapterLoaderThread(threading.Thread):
            def __init__(self, parent, manga_name):
                super().__init__(daemon=True)
                self.parent = parent
                self.manga_name = manga_name
                self.chapters = []
                self.error = None
                
            def run(self):
                try:
                    manga_data = self.parent.history_manager.get_manga_data(self.manga_name)
                    if not manga_data or not manga_data.get('url'):
                        self.error = "No data available for this manga"
                        return
                    
                    url = manga_data.get('url')
                    site_type = manga_data.get('site_type')
                    
                    self.chapters = self.parent.download_manager._get_chapters(url, site_type)
                    
                    if not self.chapters:
                        self.error = "No chapters found"
                except Exception as e:
                    self.error = str(e)
                    logging.error(f"Error loading chapters: {e}")
        
        loader = ChapterLoaderThread(self, manga_name)
        loader.start()
        
        def check_loader():
            if not loader.is_alive():
                if loader.error:
                    while self.chapter_list_layout.count():
                        item = self.chapter_list_layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                    
                    error_label = QLabel(f"Error: {loader.error}")
                    error_label.setStyleSheet("color: #F44336; padding: 20px;")
                    error_label.setAlignment(Qt.AlignCenter)
                    self.chapter_list_layout.addWidget(error_label)
                elif not loader.chapters:
                    while self.chapter_list_layout.count():
                        item = self.chapter_list_layout.takeAt(0)
                        if item.widget():
                            item.widget().deleteLater()
                    
                    empty_label = QLabel("No chapters found")
                    empty_label.setStyleSheet("color: #999; padding: 20px;")
                    empty_label.setAlignment(Qt.AlignCenter)
                    self.chapter_list_layout.addWidget(empty_label)
                else:
                    self.populate_chapter_list(manga_name, loader.chapters)
            else:
                QTimer.singleShot(100, check_loader)
        
        QTimer.singleShot(100, check_loader)

    def populate_chapter_list(self, manga_name, chapters):
        """Populate chapter list with downloaded status - called in main thread"""
        logging.info(f"Populating chapter list for {manga_name} with {len(chapters)} chapters")
        
        while self.chapter_list_layout.count():
            item = self.chapter_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        downloaded_chapters = self.history_manager.get_downloaded_chapters(manga_name)
        
        self.scan_external_chapters(manga_name)
        
        downloaded_chapters = self.history_manager.get_downloaded_chapters(manga_name)
        
        downloading_chapters = set()
        if manga_name in self.chapter_status:
            for ch_num, status in self.chapter_status[manga_name].items():
                if status == "Downloading":
                    downloading_chapters.add(ch_num)
        
        new_chapters = set()
        if hasattr(self, 'new_chapters_cache') and manga_name in self.new_chapters_cache:
            new_chapters = {ch[0] for ch in self.new_chapters_cache[manga_name]}
        
        try:
            sorted_chapters = sorted(
                chapters, 
                key=lambda x: float(x[0]) if x[0].replace('.', '', 1).isdigit() else 0
            )
        except Exception as e:
            logging.error(f"Error sorting chapters: {e}")
            sorted_chapters = chapters
        
        total_chapters = len(sorted_chapters)
        downloaded_count = len(downloaded_chapters)
        
        progress_percent = int((downloaded_count / total_chapters) * 100) if total_chapters > 0 else 0
        
        header = QLabel(f"Progress: {downloaded_count}/{total_chapters} chapters ({progress_percent}%)")
        header.setStyleSheet("font-weight: bold; margin-bottom: 10px;")
        self.chapter_list_layout.addWidget(header)
        
        progress_bar = QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(100)
        progress_bar.setValue(progress_percent)
        self.chapter_list_layout.addWidget(progress_bar)
        
        for chapter_num, chapter_name, chapter_url in sorted_chapters:
            status = "unknown"
            
            if chapter_num in downloaded_chapters:
                status = "completed"
            elif chapter_num in downloading_chapters:
                status = "downloading"
            elif chapter_num in new_chapters:
                status = "new"
            
            chapter_item = ChapterListItem(
                manga_name=manga_name,
                chapter_num=chapter_num,
                chapter_name=chapter_name,
                status=status
            )
            
            chapter_item.update_status(status)
            
            chapter_item.retry_clicked.connect(self.retry_chapter_download)
            
            self.chapter_list_layout.addWidget(chapter_item)

    def scan_external_chapters(self, manga_name):
        """Scan filesystem for chapters that were downloaded outside of the app"""
        logging.info(f"Scanning for external chapters for {manga_name}")
        try:
            manga_folder = os.path.join(self.download_path, manga_name)
            if not os.path.exists(manga_folder) or not os.path.isdir(manga_folder):
                logging.info(f"No manga folder found at {manga_folder}")
                return
            
            manga_data = self.history_manager.get_manga_data(manga_name)
            site_type = manga_data.get('site_type', 'unknown')
            
            known_chapters = self.history_manager.get_downloaded_chapters(manga_name)
            
            added_count = 0
            for filename in os.listdir(manga_folder):
                if filename.endswith('.cbz'):
                    match = re.search(r'Chapter\s+(\d+(?:\.\d+)?)', filename)
                    if match:
                        chapter_num = match.group(1)
                        
                        if chapter_num not in known_chapters:
                            cbz_path = os.path.join(manga_folder, filename)
                            
                            if os.path.exists(cbz_path) and os.path.getsize(cbz_path) > 0:
                                logging.info(f"Found external chapter: {manga_name} Chapter {chapter_num}")
                                self.history_manager.add_downloaded_chapter(
                                    manga_name, 
                                    chapter_num, 
                                    site_type,
                                    ""
                                )
                                added_count += 1
            
            if added_count > 0:
                logging.info(f"Added {added_count} external chapters for {manga_name}")
                return True
            
            return False
        except Exception as e:
            logging.error(f"Error scanning external chapters: {e}")
            logging.error(traceback.format_exc())
            return False
    
    def retry_chapter_download(self, manga_name, chapter_num):
        """Retry downloading a failed chapter"""
        manga_data = self.history_manager.get_manga_data(manga_name)
        if not manga_data or not manga_data.get('url'):
            self.signals.show_toast.emit(f"No data available for {manga_name}", "error")
            return
        
        url = manga_data.get('url')
        site_type = manga_data.get('site_type')
        
        try:
            all_chapters = self.download_manager._get_chapters(url, site_type)
            matching_chapters = [ch for ch in all_chapters if ch[0] == chapter_num]
            
            if matching_chapters:
                self.download_manager.add_to_queue(url, matching_chapters)
                self.signals.show_toast.emit(f"Added Chapter {chapter_num} to download queue", "success")
                
                self.sidebar.download_btn.setChecked(True)
                self.content_stack.setCurrentIndex(0)
            else:
                self.signals.show_toast.emit(f"Could not find Chapter {chapter_num}", "error")
        except Exception as e:
            self.signals.show_toast.emit(f"Error: {str(e)}", "error")
    
    def start_download(self):
        """Start a new manga download - thread-safe"""
        url = self.url_input.text().strip()
        if not url:
            self.show_toast("Please enter a manga URL", "error")
            return
        
        valid, site_type = self.download_manager.validate_manga_url(url)
        if not valid:
            self.show_toast(f"Invalid URL format. Supported sites: AsuraScans, MangaKatana, Webtoon", "error")
            return
        
        self.show_toast("Fetching manga information...", "info")
        
        class MangaFetchThread(threading.Thread):
            def __init__(self, parent, url, site_type):
                super().__init__(daemon=True)
                self.parent = parent
                self.url = url
                self.site_type = site_type
                self.manga_name = None
                self.chapters = None
                self.error = None
                
            def run(self):
                try:
                    if self.site_type == "asura":
                        self.manga_name = asura_get_manga_name(self.url)
                        self.chapters = asura_get_chapter_links(self.url)
                    elif self.site_type == "katana":
                        self.manga_name = katana_get_manga_name(self.url)
                        self.chapters = katana_get_chapter_links(self.url)
                    else:
                        self.manga_name = webtoon_get_manga_name(self.url)
                        self.chapters = webtoon_get_chapter_links(self.url)
                        
                    if not self.chapters:
                        self.error = f"No chapters found for {self.manga_name}"
                except Exception as e:
                    self.error = str(e)
                    logging.error(f"Error fetching manga: {e}")
        
        fetcher = MangaFetchThread(self, url, site_type)
        fetcher.start()
        
        def check_fetcher():
            if not fetcher.is_alive():
                if fetcher.error:
                    self.show_toast(f"Error: {fetcher.error}", "error")
                elif fetcher.manga_name and fetcher.chapters:
                    self.history_manager.add_manga(fetcher.manga_name, url, site_type)
                    
                    dialog = ChapterSelectionDialog(fetcher.manga_name, fetcher.chapters, self)
                    if dialog.exec_():
                        selected_chapters = dialog.get_selected_chapters()
                        if not selected_chapters:
                            self.show_toast("No chapters selected", "info")
                            return
                        
                        self.download_manager.add_to_queue(url, selected_chapters)
                        self.add_manga_to_list(fetcher.manga_name, "Queued")
                        self.show_toast(f"Added {fetcher.manga_name} to download queue", "success")
                        self.url_input.clear()
                        self.update_queue_display()
            else:
                QTimer.singleShot(100, check_fetcher)
        
        QTimer.singleShot(100, check_fetcher)
    
    def on_chapter_completed(self, manga_name, chapter_num, path):
        """Handle completed chapter download with proper status updates"""
        print(f"Chapter completed: {manga_name} - Chapter {chapter_num}")
        self.update_chapter_status(manga_name, chapter_num, "Completed", 100, path)
        
        if path and os.path.exists(path):
            manga_data = self.history_manager.get_manga_data(manga_name)
            site_type = manga_data.get('site_type', '')
            chapter_url = ""
            self.history_manager.add_downloaded_chapter(manga_name, chapter_num, site_type, chapter_url)
            
            if (hasattr(self, '_last_displayed_manga') and 
                self._last_displayed_manga == manga_name and 
                not self.chapter_panel_closed_by_user and
                self.chapter_panel.width() > 0):
                
                self.update_chapter_list_item(manga_name, chapter_num, "completed")
    
    def update_chapter_list_item(self, manga_name, chapter_num, status):
        """Update a single chapter item in the list without reloading all chapters"""
        if not hasattr(self, 'chapter_list_layout'):
            return
            
        for i in range(self.chapter_list_layout.count()):
            item = self.chapter_list_layout.itemAt(i).widget()
            if isinstance(item, ChapterListItem) and item.chapter_num == chapter_num:
                item.update_status(status)
                
                if self.chapter_list_layout.count() > 0:
                    header_item = self.chapter_list_layout.itemAt(0).widget()
                    if isinstance(header_item, QLabel) and "Progress:" in header_item.text():
 
                        manga_data = self.history_manager.get_manga_data(manga_name)
                        downloaded_chapters = list(manga_data.get('chapters', {}).keys())
                        
                        if self.chapter_list_layout.count() > 1:
                            progress_bar = self.chapter_list_layout.itemAt(1).widget()
                            if isinstance(progress_bar, QProgressBar):
                                total_chapters = progress_bar.maximum()
                                downloaded_count = len(downloaded_chapters)
                                progress_percent = int((downloaded_count / total_chapters) * 100) if total_chapters > 0 else 0
                                
                                header_item.setText(f"Progress: {downloaded_count}/{total_chapters} chapters ({progress_percent}%)")
                                progress_bar.setValue(progress_percent)
                
                break
    
    def update_chapter_status(self, manga_name, chapter_num, status, progress=None, path=None):
        """Update chapter status in both data model and UI without full redraw"""
        if manga_name not in self.chapter_status:
            self.chapter_status[manga_name] = {}
        
        print(f"Updating status for {manga_name}, Chapter {chapter_num}: {status} ({progress if progress is not None else 'no progress'})")
       
        self.chapter_status[manga_name][chapter_num] = status
 
        if progress is not None:
            if manga_name not in self.chapter_progress:
                self.chapter_progress[manga_name] = {}
            self.chapter_progress[manga_name][chapter_num] = progress
        
        panel_open = (hasattr(self, '_last_displayed_manga') and 
                     self._last_displayed_manga == manga_name and 
                     not self.chapter_panel_closed_by_user and
                     self.chapter_panel.width() > 0)
                     
        if panel_open:
            status_map = {
                "Completed": "completed",
                "Downloading": "downloading",
                "Failed": "failed"
            }
            self.update_chapter_list_item(manga_name, chapter_num, status_map.get(status, "unknown"))

    def toggle_pause_download(self, manga_name, is_paused):
        """Toggle the pause state of a download"""
        if is_paused:
            self.download_manager.pause_download(manga_name)
        else:
            self.download_manager.resume_download(manga_name)

    def on_manga_started(self, manga_name):
        """Handle manga download started signal"""
        self.add_manga_to_list(manga_name, "Downloading")

    def on_manga_completed(self, manga_name):
        """Handle manga download completed signal"""
        self.update_manga_status(manga_name, "Completed")

    def on_manga_failed(self, manga_name, reason):
        """Handle manga download failed signal"""
        self.update_manga_status(manga_name, "Failed")
        self.show_toast(f"Failed to download {manga_name}: {reason}", "error")

    def on_chapter_started(self, manga_name, chapter_num):
        """Handle chapter download started signal"""
        self.update_chapter_status(manga_name, chapter_num, "Downloading", 0)

    def on_chapter_progress(self, manga_name, chapter_num, progress):
        """Handle chapter progress signal"""
        self.update_chapter_status(manga_name, chapter_num, "Downloading", progress)

    def on_chapter_failed(self, manga_name, chapter_num, reason):
        """Handle chapter download failed signal"""
        self.update_chapter_status(manga_name, chapter_num, "Failed")
        self.show_toast(f"Failed to download {manga_name} Chapter {chapter_num}: {reason}", "error")

    def add_manga_to_list(self, manga_name, status="Queued"):
        """Add a manga to the downloads list with progress bar"""
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
                item.update_status(status)
                return
        
        list_item = DownloadListItemWidget(manga_name, status)
        
        list_item.cancel_btn.clicked.connect(lambda: self.cancel_download(manga_name))
        
        list_item.pause_clicked.connect(self.toggle_pause_download)
        
        list_item.clicked.connect(self.display_manga_chapters)
        
        self.downloads_layout.addWidget(list_item)
        
        self.manga_status[manga_name] = status

    def update_manga_status(self, manga_name, status):
        """Update manga status in the UI"""
        self.manga_status[manga_name] = status
        
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
                item.update_status(status)
                break

    def cancel_download(self, manga_name):
        """Cancel a download"""
        self.download_manager.cancel_download(manga_name)

    def on_download_cancelled(self, manga_name):
        """Handle download cancelled signal"""
        self.update_manga_status(manga_name, "Cancelled")

    def on_download_paused(self, manga_name):
        """Handle download paused signal"""
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
                item.set_paused(True)
                item.update_status("Paused")
                break

    def on_download_resumed(self, manga_name):
        """Handle download resumed signal"""
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
                item.set_paused(False)
                item.update_status("Downloading")
                break

    def clear_completed_downloads(self):
        """Remove completed downloads from the UI"""
        for i in range(self.downloads_layout.count() - 1, -1, -1):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.status in ["Completed", "Failed", "Cancelled"]:
                self.downloads_layout.removeWidget(item)
                item.deleteLater()

    def update_queue_display(self):
        """Update the queue display to show pending downloads"""
        queue = self.download_manager.get_queue()
        
        if not queue:
            self.queue_status_label.setText("No downloads in queue")
        else:
            self.queue_status_label.setText(f"{len(queue)} downloads in queue")
            
            for item in queue:
                manga_name = item['manga_name']
                
                found = False
                for i in range(self.downloads_layout.count()):
                    widget = self.downloads_layout.itemAt(i).widget()
                    if isinstance(widget, DownloadListItemWidget) and widget.manga_name == manga_name:
                        found = True
                        break
                
                if not found:
                    self.add_manga_to_list(manga_name, "Queued")

    def show_toast(self, message, type="info"):
        """Show a toast notification"""
        toast = Toast(self)
        toast.show_message(message, type)
    
    def on_manga_progress(self, manga_name, progress):
        """Handle manga overall progress updates"""
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
                item.update_progress(progress)
                break

    def hide_chapter_panel(self):
        """Hide the chapter details panel"""
        self.chapter_panel.setProperty("closing", True)
        self.chapter_panel_closed_by_user = True
        
        self.animate_chapter_panel_hide()
        
        QTimer.singleShot(300, self._ensure_panel_closed)
    
    def _ensure_panel_closed(self):
        """Make sure the panel is closed completely"""
        self.chapter_panel.setMinimumWidth(0)
        self.chapter_panel.setMaximumWidth(0)
        self.chapter_panel.updateGeometry()
        self.chapter_panel.setProperty("closing", False)

    def animate_chapter_panel_show(self):
        """Show chapter panel with animation"""
        if self.chapter_panel.property("closing"):
            return
        
        self.chapter_panel_closed_by_user = False
        
        self.chapter_panel.setMaximumWidth(350)
        
        animation = QPropertyAnimation(self.chapter_panel, b"minimumWidth")
        animation.setDuration(250)
        animation.setStartValue(0)
        animation.setEndValue(350)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.start()

    def animate_chapter_panel_hide(self):
        """Hide chapter panel with animation"""
        animation = QPropertyAnimation(self.chapter_panel, b"minimumWidth")
        animation.setDuration(250)
        animation.setStartValue(self.chapter_panel.width())
        animation.setEndValue(0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.start()

def main():
    app = QApplication(sys.argv)
    window = MangaDownloaderApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
