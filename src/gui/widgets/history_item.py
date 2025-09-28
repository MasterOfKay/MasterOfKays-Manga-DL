"""
Enhanced history item widget for displaying manga with detailed information.
"""

from typing import Optional, List
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, 
                             QPushButton, QFrame, QProgressBar, QTextEdit,
                             QScrollArea, QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QPixmap
import os


class HistoryItemWidget(QFrame):
    """Enhanced history item widget with detailed manga information."""
    
    clicked = pyqtSignal(str)
    scan_requested = pyqtSignal(str)
    download_new_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    
    def __init__(self, manga_name: str, site_type: str = "", chapter_count: int = 0, 
                 downloaded_count: int = 0, last_update: str = "", has_new_chapters: bool = False,
                 description: str = "", author: str = "", genres: Optional[List[str]] = None,
                 status: str = "unknown", cover_path: str = "", parent=None):
        super().__init__(parent)
        self.manga_name = manga_name
        self.site_type = site_type
        self.chapter_count = chapter_count
        self.downloaded_count = downloaded_count
        self.last_update = last_update
        self.has_new_chapters = has_new_chapters
        self.is_scanning = False
        self.description = description
        self.author = author
        self.genres = genres or []
        self.status = status
        self.cover_path = cover_path
        self.expanded = False
        
        self.init_ui()
        self.update_appearance()
        
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
        
        self.title_label = QLabel(self.manga_name)
        self.title_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.title_label.setWordWrap(False)
        
        self.status_label = QLabel(self.status.upper())
        self.status_label.setFont(QFont("Arial", 8, QFont.Bold))
        status_colors = {
            'ongoing': '#28a745',
            'completed': '#007bff',
            'cancelled': '#dc3545',
            'unknown': '#6c757d'
        }
        color = status_colors.get(self.status.lower(), '#6c757d')
        self.status_label.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: white;
                padding: 2px 6px;
                border-radius: 8px;
            }}
        """)
        
        self.new_indicator = QLabel("NEW")
        self.new_indicator.setFont(QFont("Arial", 8, QFont.Bold))
        self.new_indicator.setStyleSheet("""
            QLabel {
                background-color: #dc3545;
                color: white;
                padding: 2px 6px;
                border-radius: 8px;
            }
        """)
        self.new_indicator.setVisible(self.has_new_chapters)
        
        title_layout.addWidget(self.title_label, 1)
        title_layout.addWidget(self.status_label)
        title_layout.addWidget(self.new_indicator)
        
        content_layout.addLayout(title_layout)
        
        info_layout = QHBoxLayout()
        
        if self.author:
            self.author_label = QLabel(f"By: {self.author}")
            self.author_label.setFont(QFont("Arial", 9))
            self.author_label.setStyleSheet("color: #495057; font-style: italic;")
            info_layout.addWidget(self.author_label)
            info_layout.addWidget(QLabel("•"))
        
        chapter_text = f"{self.downloaded_count}/{self.chapter_count} chapters"
        self.chapter_label = QLabel(chapter_text)
        self.chapter_label.setFont(QFont("Arial", 9))
        self.chapter_label.setStyleSheet("color: #6c757d;")
        
        self.site_label = QLabel(f"Site: {self.site_type.title()}")
        self.site_label.setFont(QFont("Arial", 9))
        self.site_label.setStyleSheet("color: #6c757d;")
        
        if self.last_update:
            self.update_label = QLabel(f"Updated: {self.last_update}")
            self.update_label.setFont(QFont("Arial", 9))
            self.update_label.setStyleSheet("color: #6c757d;")
        else:
            self.update_label = QLabel("No update info")
            self.update_label.setFont(QFont("Arial", 9))
            self.update_label.setStyleSheet("color: #6c757d;")
        
        info_layout.addWidget(self.chapter_label)
        info_layout.addWidget(QLabel("•"))
        info_layout.addWidget(self.site_label)
        info_layout.addWidget(QLabel("•"))
        info_layout.addWidget(self.update_label)
        info_layout.addStretch()
        
        content_layout.addLayout(info_layout)
        
        if self.genres:
            self.genres_layout = QHBoxLayout()
            self.genres_layout.setSpacing(4)
            
            visible_genres = self.genres[:3]
            for genre in visible_genres:
                genre_label = QLabel(genre)
                genre_label.setFont(QFont("Arial", 8))
                genre_label.setStyleSheet("""
                    QLabel {
                        background-color: #e9ecef;
                        color: #495057;
                        padding: 2px 6px;
                        border-radius: 10px;
                        border: 1px solid #ced4da;
                    }
                """)
                self.genres_layout.addWidget(genre_label)
            
            if len(self.genres) > 3:
                more_label = QLabel(f"+{len(self.genres) - 3} more")
                more_label.setFont(QFont("Arial", 8))
                more_label.setStyleSheet("color: #6c757d; font-style: italic;")
                self.genres_layout.addWidget(more_label)
            
            self.genres_layout.addStretch()
            content_layout.addLayout(self.genres_layout)
        
        if self.description:
            desc_text = self.description[:120] + "..." if len(self.description) > 120 else self.description
            self.desc_label = QLabel(desc_text)
            self.desc_label.setFont(QFont("Arial", 9))
            self.desc_label.setStyleSheet("color: #6c757d;")
            self.desc_label.setWordWrap(True)
            content_layout.addWidget(self.desc_label)
        
        self.expand_btn = QPushButton("More...")
        self.expand_btn.setFont(QFont("white", 8))
        self.expand_btn.setStyleSheet("""
            QPushButton {
                border: none;
                color: #007bff;
                text-decoration: underline;
                padding: 2px;
            }
            QPushButton:hover {
                color: #0056b3;
            }
        """)
        self.expand_btn.clicked.connect(self.toggle_expansion)
        
        expand_layout = QHBoxLayout()
        expand_layout.addStretch()
        expand_layout.addWidget(self.expand_btn)
        content_layout.addLayout(expand_layout)
        
        main_layout.addWidget(self.cover_label)
        main_layout.addLayout(content_layout, 1)
        
        button_layout = QVBoxLayout()
        button_layout.setSpacing(4)
        
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setFont(QFont("Arial", 9))
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        self.scan_btn.clicked.connect(self.request_scan)
        
        self.download_new_btn = QPushButton("Download New")
        self.download_new_btn.setFont(QFont("Arial", 9))
        self.download_new_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        self.download_new_btn.clicked.connect(self.request_download_new)
        self.download_new_btn.setVisible(False)
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setFont(QFont("Arial", 9))
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        self.delete_btn.clicked.connect(self.request_delete)
        
        button_layout.addWidget(self.scan_btn)
        button_layout.addWidget(self.download_new_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
        
        self.setFrameStyle(QFrame.Box | QFrame.Raised)  # type: ignore
        self.setLineWidth(1)
    
    def load_cover_image(self):
        """Load and display the cover image."""
        if self.cover_path and os.path.exists(self.cover_path):
            pixmap = QPixmap(self.cover_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(116, 156, Qt.KeepAspectRatio, Qt.SmoothTransformation)  # type: ignore
                self.cover_label.setPixmap(scaled_pixmap)
                return
        
        self.cover_label.setText("No\nCover")
        self.cover_label.setStyleSheet("""
            QLabel {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background-color: #f8f9fa;
                color: #6c757d;
                font-size: 8px;
            }
        """)
    
    def toggle_expansion(self):
        """Toggle the expanded view with full description and genres."""
        if self.expanded:
            self.expand_btn.setText("More...")
            self.expanded = False
        else:
            self.expand_btn.setText("Less...")
            self.expanded = True
    
    def request_scan(self):
        """Emit scan requested signal."""
        self.scan_requested.emit(self.manga_name)
    
    def request_download_new(self):
        """Emit download new requested signal."""
        self.download_new_requested.emit(self.manga_name)
    
    def request_delete(self):
        """Emit delete requested signal."""
        self.delete_requested.emit(self.manga_name)
        
    def update_appearance(self):
        """Update the visual appearance."""
        self.new_indicator.setVisible(self.has_new_chapters)
        
        self.scan_btn.setEnabled(not self.is_scanning)
        if self.is_scanning:
            self.scan_btn.setText("...")
        else:
            self.scan_btn.setText("Scan")
        
        if hasattr(self, 'chapter_label'):
            chapter_text = f"{self.downloaded_count}/{self.chapter_count} chapters"
            self.chapter_label.setText(chapter_text)
        
        if self.has_new_chapters:
            self.setStyleSheet("""
                QFrame {
                    background-color: #fff3cd;
                    border: 1px solid #ffeaa7;
                    border-radius: 8px;
                    margin: 2px;
                }
                QFrame:hover {
                    background-color: #fff8db;
                    border-color: #007bff;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    margin: 2px;
                }
                QFrame:hover {
                    background-color: #f8f9fa;
                    border-color: #007bff;
                }
            """)
                
    def apply_colors(self, card_bg: str, card_border: str, card_text: str, 
                    card_subtitle: str, card_new_bg: str, card_new_border: str, 
                    card_hover_bg: str, accent_color: str):
        """Apply color scheme to the history card."""
        self._card_colors = {
            'card_bg': card_bg,
            'card_border': card_border, 
            'card_text': card_text,
            'card_subtitle': card_subtitle,
            'card_new_bg': card_new_bg,
            'card_new_border': card_new_border,
            'card_hover_bg': card_hover_bg,
            'accent_color': accent_color
        }
        
        self.title_label.setStyleSheet(f"color: {card_text};")
        self.site_label.setStyleSheet(f"color: {card_subtitle};")
        self.chapter_label.setStyleSheet(f"color: {card_subtitle};")
        if hasattr(self, 'update_label'):
            self.update_label.setStyleSheet(f"color: {card_subtitle};")
        
        if self.has_new_chapters:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {card_new_bg};
                    border: 1px solid {card_new_border};
                    border-radius: 5px;
                    margin: 2px;
                }}
                QFrame:hover {{
                    background-color: {card_hover_bg};
                    border-color: {accent_color};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {card_bg};
                    border: 1px solid {card_border};
                    border-radius: 5px;
                    margin: 2px;
                }}
                QFrame:hover {{
                    background-color: {card_hover_bg};
                    border-color: {accent_color};
                }}
            """)
    
    def set_has_new_chapters(self, has_new: bool):
        """Set whether manga has new chapters."""
        self.has_new_chapters = has_new
        self.download_new_btn.setVisible(has_new)
        self.update_appearance()
        
    def set_scanning(self, scanning: bool):
        """Set scanning state."""
        self.is_scanning = scanning
        self.update_appearance()
    
    def update_info(self, chapter_count: Optional[int] = None, downloaded_count: Optional[int] = None, 
                   last_update: Optional[str] = None):
        """Update manga information."""
        if chapter_count is not None:
            self.chapter_count = chapter_count
            
        if downloaded_count is not None:
            self.downloaded_count = downloaded_count
            
        if last_update is not None:
            self.last_update = last_update
            
        self.update_appearance()
    
    def on_scan_clicked(self):
        """Handle scan button click."""
        self.scan_requested.emit(self.manga_name)
        
    def on_delete_clicked(self):
        """Handle delete button click."""
        self.delete_requested.emit(self.manga_name)
        
    def mousePressEvent(self, a0):
        """Handle mouse click to select manga."""
        if a0 and hasattr(a0, 'button') and a0.button() == 1:
            self.clicked.emit(self.manga_name)
        super().mousePressEvent(a0)