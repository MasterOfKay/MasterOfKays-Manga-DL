import sys
import os
import threading
import queue
from typing import Dict, List, Tuple
import re
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                            QProgressBar, QScrollArea, QFrame, QMessageBox,
                            QTabWidget, QListWidget, QListWidgetItem, QDialog,
                            QCheckBox, QSpinBox, QGridLayout, QAction, QFileDialog)
from PyQt5.QtCore import Qt, QObject, pyqtSignal, QTimer, QEvent
from PyQt5.QtGui import QFont, QColor, QMouseEvent

import time
from concurrent.futures import ThreadPoolExecutor
import threading

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
                cbz_path = katana_download_chapter(chapter_url, chapter_num, manga_name, 
                                                   self.download_path)
                self.signals.chapter_progress.emit(manga_name, chapter_num, 90)
            elif site_type == "webtoon":
                self.signals.chapter_progress.emit(manga_name, chapter_num, 20)
                cbz_path = webtoon_download_chapter(chapter_url, chapter_num, manga_name,
                                                    self.download_path)
                self.signals.chapter_progress.emit(manga_name, chapter_num, 90)
            else:
                logging.error(f"Unknown site type: {site_type}")
                return ""
            
            if cbz_path and os.path.exists(cbz_path) and os.path.getsize(cbz_path) > 0:
                logging.info(f"Successfully downloaded chapter {chapter_num} to {cbz_path}")
                self.signals.chapter_progress.emit(manga_name, chapter_num, 100)
                return cbz_path
            else:
                logging.warning(f"Download complete but file not found or empty: {cbz_path}")
                return ""
                
        except Exception as e:
            logging.error(f"Error downloading chapter {chapter_num}: {str(e)}")
            logging.error(traceback.format_exc())
            self.signals.chapter_progress.emit(manga_name, chapter_num, 0)
            return ""
    
    def _track_download_progress(self, download_func, chapter_url, chapter_num, manga_name, site_type):
        """Simplified download progress tracking that won't interfere with the download process"""
        original_get = requests.get
        
        try:
            self.signals.chapter_progress.emit(manga_name, chapter_num, 0)
            
            result = download_func(chapter_url, chapter_num, manga_name)
            
            self.signals.chapter_progress.emit(manga_name, chapter_num, 100)
            
            return result
            
        except Exception as e:
            print(f"Error in download process: {e}")
            self.signals.chapter_progress.emit(manga_name, chapter_num, 0)
            raise
            
        finally:
            requests.get = original_get
    
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
        
        for i, cb in self.chapter_checkboxes:
            cb.setChecked(start <= i <= end)
    
    def get_selected_chapters(self):
        selected = []
        for i, cb in enumerate(self.chapter_checkboxes):
            if cb.isChecked():
                selected.append(self.chapters[i])
        return selected

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
        self.resize(800, 600)
        
        self.download_path = os.path.abspath(os.getcwd())
        self.load_download_path()
        
        self.signals = DownloadSignals()
        self.download_manager = DownloadManager(self.signals)
        
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
        
        self.manga_status = {}  # manga_name -> status
        self.chapter_status = {}  # manga_name -> {chapter_num -> status}
        self.chapter_progress = {}  # manga_name -> {chapter_num -> progress}
        
        self.init_ui()
    
    def init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        
        header = QLabel("MasterOfKay's Manga Downloader")
        header.setFont(QFont("Arial", 16, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header)
        
        url_layout = QHBoxLayout()
        url_label = QLabel("Manga URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter manga URL (e.g., https://asuracomic.net/series/manga-title)")
        download_btn = QPushButton("Download")
        download_btn.clicked.connect(self.start_download)
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(download_btn)
        main_layout.addLayout(url_layout)
        
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
        main_layout.addLayout(path_layout)
        
        tabs = QTabWidget()
        
        downloads_tab = QWidget()
        downloads_layout = QVBoxLayout(downloads_tab)
        
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
        
        tabs.addTab(downloads_tab, "Downloads")
        
        self.chapter_details = QWidget()
        self.chapter_details_layout = QVBoxLayout(self.chapter_details)
        self.chapter_details_title = QLabel("Select a manga to view chapters")
        self.chapter_details_title.setFont(QFont("Arial", 12, QFont.Bold))
        self.chapter_details_layout.addWidget(self.chapter_details_title)
        
        self.chapter_list = QListWidget()
        self.chapter_details_layout.addWidget(self.chapter_list)
        
        main_layout.addWidget(tabs)
        main_layout.addWidget(self.chapter_details)
        
        self.setCentralWidget(central_widget)
        
        self.create_menu_bar()
    
    def create_menu_bar(self):
        """Create application menu bar"""
        menu_bar = self.menuBar()
        
        file_menu = menu_bar.addMenu("&File")
        
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
            <h3>MasterOfKay's Manga Downloader v1.2</h3>
            <p>Download manga from popular sites.</p>
            <p>Supported sites:</p>
            <ul>
                <li>AsuraScans</li>
                <li>MangaKatana</li>
                <li>Webtoon</li>
            </ul>
            <p>For personal use only.</p>
            """
        )
    
    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            self.show_toast("Please enter a manga URL", "error")
            return
        
        valid, site_type = self.download_manager.validate_manga_url(url)
        if not valid:
            self.show_toast(f"Invalid URL format. Supported sites: AsuraScans, MangaKatana, Webtoon", "error")
            return
        
        try:
            if site_type == "asura":
                manga_name = asura_get_manga_name(url)
                chapters = asura_get_chapter_links(url)
            elif site_type == "katana":
                manga_name = katana_get_manga_name(url)
                chapters = katana_get_chapter_links(url)
            else:
                manga_name = webtoon_get_manga_name(url)
                chapters = webtoon_get_chapter_links(url)
            
            if not chapters:
                self.show_toast(f"No chapters found for {manga_name}", "error")
                return
            
            dialog = ChapterSelectionDialog(manga_name, chapters, self)
            if dialog.exec_():
                selected_chapters = dialog.get_selected_chapters()
                if not selected_chapters:
                    self.show_toast("No chapters selected", "info")
                    return
                
                self.download_manager.add_to_queue(url, selected_chapters)
                
                self.add_manga_to_list(manga_name, "Queued")
                self.show_toast(f"Added {manga_name} to download queue", "success")
                
                self.url_input.clear()
        except Exception as e:
            self.show_toast(f"Error: {str(e)}", "error")
    
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
        
        list_item.clicked.connect(self.display_chapter_details)
        
        self.downloads_layout.addWidget(list_item)
        
        self.manga_status[manga_name] = status
    
    def toggle_pause_download(self, manga_name, is_paused):
        """Toggle the pause state of a download"""
        if is_paused:
            self.download_manager.pause_download(manga_name)
        else:
            self.download_manager.resume_download(manga_name)
    
    def update_manga_status(self, manga_name, status):
        """Update manga status in the UI"""
        self.manga_status[manga_name] = status
        
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
                item.update_status(status)
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
        
        if self.chapter_details_title.text().startswith(manga_name):
            for i in range(self.chapter_list.count()):
                item = self.chapter_list.item(i)
                item_text = item.text()

                if f"Chapter {chapter_num}" in item_text:
                    if status == "Completed":
                        item.setText(f"Chapter {chapter_num} - Completed")
                        item.setForeground(QColor("#4CAF50"))  # Green
                    elif status == "Downloading":
                        item.setText(f"Chapter {chapter_num} - Downloading ({progress}%)")
                        item.setForeground(QColor("#2196F3"))  # Blue
                    elif status == "Failed":
                        item.setText(f"Chapter {chapter_num} - Failed")
                        item.setForeground(QColor("#F44336"))  # Red
                    else:
                        item.setText(f"Chapter {chapter_num} - {status}")
                        item.setForeground(QColor("#9E9E9E"))  # Gray
                    
                    return
            
            if hasattr(self, '_last_displayed_manga'):
                delattr(self, '_last_displayed_manga')
            self.display_chapter_details(manga_name)

    def display_chapter_details(self, manga_name):
        """Display all chapters for the specified manga, including those not in download queue"""
        if hasattr(self, '_last_displayed_manga') and self._last_displayed_manga == manga_name:
            return
        
        self._last_displayed_manga = manga_name
        print(f"Displaying chapters for: {manga_name}")

        self.chapter_details_title.setText(f"{manga_name} - Chapters")

        self.chapter_list.clear()

        loading_item = QListWidgetItem("Loading chapters...")
        self.chapter_list.addItem(loading_item)
        QApplication.processEvents()
        
        manga_url = None
        manga_site_type = None
        for item in self.download_manager.download_queue_list:
            if item['manga_name'] == manga_name:
                manga_url = item['url']
                manga_site_type = item['site_type']
                break
        
        if manga_url and manga_site_type:
            try:
                all_chapters = []
                if manga_site_type == "asura":
                    all_chapters = asura_get_chapter_links(manga_url)
                elif manga_site_type == "katana":
                    all_chapters = katana_get_chapter_links(manga_url)
                else:  
                    all_chapters = webtoon_get_chapter_links(manga_url)
                
                self.chapter_list.clear()
                
                if not all_chapters:
                    item = QListWidgetItem("No chapters found")
                    self.chapter_list.addItem(item)
                    return
                    
                chapter_dict = {}
                for chapter_num, chapter_name, chapter_url in all_chapters:
                    chapter_dict[chapter_num] = {
                        'name': chapter_name,
                        'url': chapter_url,
                        'status': "Available"
                    }
                
                if manga_name in self.chapter_status:
                    for ch_num, status in self.chapter_status[manga_name].items():
                        if ch_num in chapter_dict:
                            chapter_dict[ch_num]['status'] = status
                
                sorted_chapters = sorted(
                    chapter_dict.items(), 
                    key=lambda x: float(x[0]) if x[0].replace('.', '', 1).isdigit() else 0
                )
                
                for chapter_num, data in sorted_chapters:
                    status = data['status']
                    chapter_name = data['name']
                    
                    if status == "Completed":
                        item = QListWidgetItem(f"Chapter {chapter_num}: {chapter_name} - Completed")
                        item.setForeground(QColor("#4CAF50"))  # Green
                    elif status == "Downloading":
                        progress = 0
                        if manga_name in self.chapter_progress and chapter_num in self.chapter_progress[manga_name]:
                            progress = self.chapter_progress[manga_name][chapter_num]
                        item = QListWidgetItem(f"Chapter {chapter_num}: {chapter_name} - Downloading ({progress}%)")
                        item.setForeground(QColor("#2196F3"))  # Blue
                    elif status == "Failed":
                        item = QListWidgetItem(f"Chapter {chapter_num}: {chapter_name} - Failed")
                        item.setForeground(QColor("#F44336"))  # Red
                    elif status == "Queued":
                        item = QListWidgetItem(f"Chapter {chapter_num}: {chapter_name} - Queued")
                        item.setForeground(QColor("#9E9E9E"))  # Gray
                    else:
                        item = QListWidgetItem(f"Chapter {chapter_num}: {chapter_name}")
                        item.setForeground(QColor("#000000"))  # Black
                    
                    self.chapter_list.addItem(item)
                
                return
                    
            except Exception as e:
                self.chapter_list.clear()
                item = QListWidgetItem(f"Error loading chapters: {str(e)}")
                item.setForeground(QColor("#F44336"))  # Red
                self.chapter_list.addItem(item)
                return
        
        if manga_name in self.chapter_status:
            try:
                for chapter_num, status in sorted(self.chapter_status[manga_name].items(), 
                                                key=lambda x: float(x[0]) if x[0].replace('.', '', 1).isdigit() else 0):
                    if status == "Completed":
                        item = QListWidgetItem(f"Chapter {chapter_num} - Completed")
                        item.setForeground(QColor("#4CAF50"))  # Green
                    elif status == "Downloading":
                        progress = 0
                        if manga_name in self.chapter_progress and chapter_num in self.chapter_progress[manga_name]:
                            progress = self.chapter_progress[manga_name][chapter_num]
                        item = QListWidgetItem(f"Chapter {chapter_num} - Downloading ({progress}%)")
                        item.setForeground(QColor("#2196F3"))  # Blue
                    elif status == "Failed":
                        item = QListWidgetItem(f"Chapter {chapter_num} - Failed")
                        item.setForeground(QColor("#F44336"))  # Red
                    else:
                        item = QListWidgetItem(f"Chapter {chapter_num} - {status}")
                        item.setForeground(QColor("#9E9E9E"))  # Gray
                    
                    self.chapter_list.addItem(item)
            except Exception as e:
                print(f"Error displaying chapters: {e}")
                item = QListWidgetItem(f"Error displaying chapters: {str(e)}")
                item.setForeground(QColor("#F44336"))  # Red
                self.chapter_list.addItem(item)
        else:
            item = QListWidgetItem("No chapter data available for this manga")
            self.chapter_list.addItem(item)
    
    def on_manga_clicked(self, item):
        manga_name = item.data(Qt.UserRole)
        self.display_chapter_details(manga_name)
    
    def show_toast(self, message, type="info"):
        toast = Toast(self)
        toast.show_message(message, type)

    def on_manga_started(self, manga_name):
        self.update_manga_status(manga_name, "Downloading")
    
    def on_manga_completed(self, manga_name):
        self.update_manga_status(manga_name, "Completed")
    
    def on_manga_failed(self, manga_name, reason):
        self.update_manga_status(manga_name, "Failed")
        self.show_toast(f"Failed to download {manga_name}: {reason}", "error")
    
    def on_chapter_started(self, manga_name, chapter_num):
        self.update_chapter_status(manga_name, chapter_num, "Downloading", 0)
    
    def on_chapter_progress(self, manga_name, chapter_num, progress):
        """Handle chapter download progress updates with forced UI refresh"""
        print(f"Progress update: {manga_name} - Chapter {chapter_num}: {progress}%")

        self.update_chapter_status(manga_name, chapter_num, "Downloading", progress)

        QApplication.processEvents()
    
    def on_chapter_completed(self, manga_name, chapter_num, path):
        """Handle completed chapter download with proper status updates"""
        print(f"Chapter completed: {manga_name} - Chapter {chapter_num}")
        self.update_chapter_status(manga_name, chapter_num, "Completed", 100, path)
    
    def on_chapter_failed(self, manga_name, chapter_num, reason):
        """Handle a failed chapter download with proper error messaging"""
        print(f"Chapter failed: {manga_name} - Chapter {chapter_num} - {reason}")
        self.update_chapter_status(manga_name, chapter_num, "Failed")
        
        if "doesn't exist" not in reason.lower() and "no file created" not in reason.lower():
            self.show_toast(f"Failed to download {manga_name} Chapter {chapter_num}: {reason}", "error")
    
    def on_manga_progress(self, manga_name, progress):
        """Update manga overall progress"""
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
                item.update_progress(progress)
                break
    
    def cancel_download(self, manga_name):
        """Cancel a download"""
        self.download_manager.cancel_download(manga_name)
    
    def on_download_cancelled(self, manga_name):
        """Handle cancelled download"""
        self.update_manga_status(manga_name, "Cancelled")
    
    def on_download_paused(self, manga_name):
        """Handle download paused signal"""
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
                item.update_status("Paused")
                break
    
    def on_download_resumed(self, manga_name):
        """Handle download resumed signal"""
        for i in range(self.downloads_layout.count()):
            item = self.downloads_layout.itemAt(i).widget()
            if isinstance(item, DownloadListItemWidget) and item.manga_name == manga_name:
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
    
    def save_history(self):
        """Save download history to file"""
        try:
            with open("download_history.txt", "a") as f:
                for manga_name, status in self.manga_status.items():
                    f.write(f"{manga_name}: {status}\n")
            self.show_toast("History saved", "success")
        except Exception as e:
            self.show_toast(f"Error saving history: {str(e)}", "error")
    
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

    def on_path_changed(self, path):
        """Handle when user types or pastes a path"""
        if os.path.isdir(path):
            self.download_path = path
            self.save_download_path()
            self.download_manager.download_path = self.download_path

    def save_download_path(self):
        """Save download path to a config file"""
        config_dir = os.path.join(os.path.expanduser("~"), ".mangadownloader")
        os.makedirs(config_dir, exist_ok=True)
        
        config_path = os.path.join(config_dir, "config.txt")
        with open(config_path, "w") as f:
            f.write(f"download_path={self.download_path}")

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

def main():
    app = QApplication(sys.argv)
    window = MangaDownloaderApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

