"""
Download item widget with progress tracking and detailed status.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QPushButton, QProgressBar, QFrame, QTextEdit,
                            QScrollArea, QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QPalette, QPixmap
from typing import Optional, List, Dict
import os


class DownloadItemWidget(QWidget):
    """Enhanced download item widget with progress tracking."""
    
    clicked = pyqtSignal(str)
    pause_clicked = pyqtSignal(str, bool)
    cancel_clicked = pyqtSignal(str)
    
    def __init__(self, manga_name: str, total_chapters: int = 0, site_type: str = "",
                 description: str = "", author: str = "", genres: Optional[List[str]] = None,
                 status_text: str = "unknown", cover_path: str = "", parent=None):
        super().__init__(parent)
        self.manga_name = manga_name
        self.total_chapters = total_chapters
        self.current_chapter = 0
        self.is_paused = False
        self.status = "Queued"
        self.site_type = site_type
        self.description = description
        self.author = author
        self.genres = genres or []
        self.status_text = status_text
        self.cover_path = cover_path
        self.chapter_progress = {}
        self.current_chapter_name = ""
        self.expanded = False
        
        self.init_ui()
        
    def init_ui(self):
        """Initialize the UI."""
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(10)
        
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(120, 160)
        self.cover_label.setStyleSheet("""
            QLabel {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background-color: #f8f9fa;
            }
        """)
        self.cover_label.setAlignment(Qt.AlignCenter)  # type: ignore
        self.load_cover_image()
        
        content_layout = QVBoxLayout()
        content_layout.setSpacing(4)
        
        title_layout = QHBoxLayout()
        
        self.manga_label = QLabel(self.manga_name)
        self.manga_label.setFont(QFont("Arial", 14, QFont.Bold))
        self.manga_label.setWordWrap(True)
        self.manga_label.setMinimumHeight(50)
        self.manga_label.setMaximumHeight(70)
        
        self.status_indicator = QLabel(self.status_text.upper())
        self.status_indicator.setFont(QFont("Arial", 8, QFont.Bold))
        status_colors = {
            'ongoing': '#28a745',
            'completed': '#007bff',
            'cancelled': '#dc3545',
            'unknown': '#6c757d'
        }
        color = status_colors.get(self.status_text.lower(), '#6c757d')
        self.status_indicator.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: white;
                padding: 2px 6px;
                border-radius: 8px;
            }}
        """)
        
        title_layout.addWidget(self.manga_label, 1)
        title_layout.addWidget(self.status_indicator)
        
        info_layout = QHBoxLayout()
        
        self.site_label = QLabel(f"Site: {self.site_type.title()}")
        self.site_label.setFont(QFont("Arial", 8))
        self.site_label.setStyleSheet("color: #6c757d;")
        
        self.author_label = QLabel(f"Author: {self.author}" if self.author else "")
        self.author_label.setFont(QFont("Arial", 8))
        self.author_label.setStyleSheet("color: #6c757d;")
        
        info_layout.addWidget(self.site_label)
        if self.author:
            info_layout.addWidget(self.author_label)
        info_layout.addStretch()
        
        progress_info_layout = QHBoxLayout()
        
        self.status_label = QLabel("Queued")
        self.status_label.setFont(QFont("Arial", 9))
        self.status_label.setStyleSheet("color: #7f8c8d;")
        
        self.chapter_counter = QLabel("0/0")
        self.chapter_counter.setFont(QFont("Arial", 9, QFont.Bold))
        self.chapter_counter.setStyleSheet("color: #3498db;")
        
        progress_info_layout.addWidget(self.status_label)
        progress_info_layout.addStretch()
        progress_info_layout.addWidget(self.chapter_counter)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bdc3c7;
                border-radius: 3px;
                text-align: center;
                font-size: 8px;
                height: 16px;
            }
            QProgressBar::chunk {
                background-color: #3498db;
                border-radius: 3px;
            }
        """)
        
        self.chapter_progress_bar = QProgressBar()
        self.chapter_progress_bar.setMinimum(0)
        self.chapter_progress_bar.setMaximum(100)
        self.chapter_progress_bar.setValue(0)
        self.chapter_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #e9ecef;
                border-radius: 2px;
                text-align: center;
                font-size: 7px;
                height: 12px;
            }
            QProgressBar::chunk {
                background-color: #28a745;
                border-radius: 2px;
            }
        """)
        self.chapter_progress_bar.setVisible(False)
        
        self.current_chapter_label = QLabel("")
        self.current_chapter_label.setFont(QFont("Arial", 8))
        self.current_chapter_label.setStyleSheet("color: #95a5a6;")
        
        content_layout.addLayout(title_layout)
        content_layout.addLayout(info_layout)
        content_layout.addLayout(progress_info_layout)
        content_layout.addWidget(self.progress_bar)
        content_layout.addWidget(self.chapter_progress_bar)
        content_layout.addWidget(self.current_chapter_label)
        
        controls_layout = QVBoxLayout()
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setMaximumWidth(60)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #f39c12;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 9px;
            }
            QPushButton:hover {
                background-color: #e67e22;
            }
        """)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.cancel_btn.setMaximumWidth(60)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 9px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        
        controls_layout.addWidget(self.pause_btn)
        controls_layout.addWidget(self.cancel_btn)
        controls_layout.addStretch()
        
        main_layout.addWidget(self.cover_label)
        main_layout.addLayout(content_layout, 1)
        main_layout.addLayout(controls_layout)
        
        self.setLayout(main_layout)
        
        self.setStyleSheet("""
            DownloadItemWidget {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 6px;
                margin: 2px;
            }
            DownloadItemWidget:hover {
                background-color: #e3f2fd;
                border-color: #2196f3;
            }
        """)
        
        self.setMaximumHeight(200)
        self.setMinimumHeight(180)
        self.update_display()
    
    def load_cover_image(self):
        """Load and display the cover image."""
        if self.cover_path:
            if os.path.exists(self.cover_path):
                try:
                    pixmap = QPixmap(self.cover_path)
                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(self.cover_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)  # type: ignore
                        self.cover_label.setPixmap(scaled_pixmap)
                    else:
                        self.set_placeholder_cover()
                except Exception:
                    self.set_placeholder_cover()
            elif self.cover_path.startswith('http'):
                self.download_cover_from_url()
            else:
                self.set_placeholder_cover()
        else:
            self.set_placeholder_cover()
    
    def download_cover_from_url(self):
        """Download cover from URL in background."""
        import requests
        from threading import Thread
        
        def download():
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                url_lower = self.cover_path.lower()
                if 'asuracomic.net' in url_lower or 'asura.gg' in url_lower:
                    headers['Referer'] = 'https://asuracomic.net/'
                elif 'webtoons.com' in url_lower or 'webtoon-phinf' in url_lower:
                    headers['Referer'] = 'https://www.webtoons.com/'
                response = requests.get(self.cover_path, timeout=10, headers=headers)
                response.raise_for_status()
                
                pixmap = QPixmap()
                if pixmap.loadFromData(response.content):
                    scaled_pixmap = pixmap.scaled(self.cover_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)  # type: ignore
                    self.cover_label.setPixmap(scaled_pixmap)
                else:
                    self.set_placeholder_cover()
            except Exception:
                self.set_placeholder_cover()
        
        thread = Thread(target=download, daemon=True)
        thread.start()
    
    def set_placeholder_cover(self):
        """Set a placeholder cover image."""
        self.cover_label.setText("No\nCover")
        self.cover_label.setStyleSheet("""
            QLabel {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background-color: #f8f9fa;
                color: #6c757d;
                font-size: 10px;
            }
        """)
    
    def update_display(self):
        """Update the display with current status."""
        if self.total_chapters > 0:
            self.chapter_counter.setText(f"{self.current_chapter}/{self.total_chapters}")

            progress = int((self.current_chapter / self.total_chapters) * 100) if self.total_chapters > 0 else 0
            self.progress_bar.setValue(progress)
        else:
            self.chapter_counter.setText("0/0")
            self.progress_bar.setValue(0)
        
        self.status_label.setText(self.status)
        
        if self.is_paused:
            self.pause_btn.setText("Resume")
            self.pause_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border: none;
                    padding: 4px 8px;
                    border-radius: 3px;
                    font-size: 9px;
                }
                QPushButton:hover {
                    background-color: #229954;
                }
            """)
        else:
            self.pause_btn.setText("Pause")
            self.pause_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f39c12;
                    color: white;
                    border: none;
                    padding: 4px 8px;
                    border-radius: 3px;
                    font-size: 9px;
                }
                QPushButton:hover {
                    background-color: #e67e22;
                }
            """)
    
    def set_total_chapters(self, total: int):
        """Set the total number of chapters."""
        self.total_chapters = total
        self.update_display()
    
    def set_current_chapter_number(self, current: int):
        """Set the current chapter number being downloaded."""
        self.current_chapter = current
        self.update_display()
    
    def set_status(self, status: str):
        """Set the download status."""
        self.status = status
        self.update_display()
    
    def set_current_chapter_info(self, chapter_name: str):
        """Set the current chapter being downloaded."""
        if chapter_name:
            self.current_chapter_label.setText(f"Downloading: {chapter_name}")
        else:
            self.current_chapter_label.setText("")
    
    def set_current_chapter(self, chapter_name: str):
        """Set the current chapter name being downloaded."""
        self.set_current_chapter_info(chapter_name)
    
    def set_chapter_progress(self, chapter_num: str, progress: int):
        """Set the progress of a specific chapter (0-100)."""
        self.chapter_progress[chapter_num] = progress
        
        if progress > 0 and progress < 100:
            self.chapter_progress_bar.setValue(progress)
            self.chapter_progress_bar.setVisible(True)
            self.chapter_progress_bar.setFormat(f"Chapter {chapter_num}: {progress}%")
        elif progress >= 100:
            self.chapter_progress_bar.setVisible(False)
    
    def get_chapter_progress(self, chapter_num: str) -> int:
        """Get the progress of a specific chapter."""
        return self.chapter_progress.get(chapter_num, 0)
    
    def increment_completed_chapters(self):
        """Increment the count of completed chapters."""
        self.current_chapter += 1
        self.update_display()
    
    def update_chapter_counts(self, completed: int, total: int):
        """Update the chapter counts with fresh data from database."""
        self.current_chapter = completed
        self.total_chapters = total
        self.update_display()
    
    def set_overall_progress(self, progress: int):
        """Set the overall download progress (0-100)."""
        self.progress_bar.setValue(progress)
    
    def set_paused(self, paused: bool):
        """Set pause state."""
        self.is_paused = paused
        self.update_display()
    
    def toggle_pause(self):
        """Toggle pause state."""
        self.is_paused = not self.is_paused
        self.pause_clicked.emit(self.manga_name, self.is_paused)
        self.update_display()
    
    def cancel_download(self):
        """Cancel the download."""
        self.cancel_clicked.emit(self.manga_name)
    
    def mousePressEvent(self, a0):
        """Handle mouse click to show details."""
        if a0 and hasattr(a0, 'button') and a0.button() == 1:
            self.clicked.emit(self.manga_name)