"""
Chapter viewer widget for displaying manga chapters with status.
"""

import logging
from typing import List, Dict, Optional
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QScrollArea, QPushButton, QFrame, QListWidget,
                             QListWidgetItem, QMenu, QAction, QCheckBox,
                             QComboBox, QGroupBox, QTreeWidget, QTreeWidgetItem,
                             QHeaderView)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QPalette


class ChapterItem(QFrame):
    """Individual chapter item widget."""
    
    redownload_requested = pyqtSignal(str, str)
    selection_changed = pyqtSignal()
    
    def __init__(self, chapter_number: str, chapter_name: str, chapter_url: str = "", 
                 is_downloaded: bool = False, status: str = "not_selected", parent=None):
        super().__init__(parent)
        self.chapter_number = chapter_number
        self.chapter_name = chapter_name
        self.chapter_url = chapter_url
        self.is_downloaded = is_downloaded or status == "success"
        self.status = status
        
        self.init_ui()
        self.update_appearance()
        
    def init_ui(self):
        """Initialize the UI."""
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        
        self.status_indicator = QLabel("●")
        self.status_indicator.setFont(QFont("Arial", 12))
        self.status_indicator.setFixedSize(20, 20)
        self.status_indicator.setAlignment(Qt.AlignCenter)  # type: ignore
        
        self.checkbox = QCheckBox()
        self.checkbox.setFixedSize(20, 20)
        self.checkbox.stateChanged.connect(self.on_checkbox_changed)
        
        display_name = f"Chapter {self.chapter_number}"
        if self.chapter_name and self.chapter_name != f"Chapter {self.chapter_number}":
            display_name += f" - {self.chapter_name}"
        
        self.name_label = QLabel(display_name)
        self.name_label.setFont(QFont("Arial", 9))
        self.name_label.setWordWrap(False)
        
        self.redownload_btn = QPushButton("↻")
        self.redownload_btn.setFixedSize(20, 20)
        self.redownload_btn.setFont(QFont("Arial", 8))
        self.redownload_btn.setToolTip("Redownload this chapter")
        self.redownload_btn.clicked.connect(self.on_redownload_clicked)
        self.redownload_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #ccc;
                border-radius: 10px;
                background-color: #f0f0f0;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
                border-color: #999;
            }
        """)
        
        layout.addWidget(self.status_indicator)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.redownload_btn)
        
        self.setLayout(layout)
        
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(1)
        
    def update_appearance(self):
        """Update the visual appearance based on download status."""
        self.checkbox.show()
        
        if self.is_downloaded or self.status == "success":
            self.status_indicator.setText("✓")
            self.status_indicator.setStyleSheet("color: #28a745; font-weight: bold;")
            self.redownload_btn.show()
            self.name_label.setStyleSheet("color: #28a745; font-weight: bold;")
            
            self.setStyleSheet("""
                QFrame {
                    background-color: #d4edda;
                    border: 2px solid #28a745;
                    border-radius: 5px;
                    margin: 1px;
                }
                QFrame:hover {
                    background-color: #c3e6cb;
                    border-color: #1e7e34;
                }
            """)
        else:
            if self.status == "downloading":
                self.status_indicator.setText("⟳")
                self.status_indicator.setStyleSheet("color: #ffa500; font-weight: bold;")
                self.name_label.setStyleSheet("color: #ffa500; font-weight: bold;")
            elif self.status == "failed":
                self.status_indicator.setText("✗")
                self.status_indicator.setStyleSheet("color: #dc3545; font-weight: bold;")
                self.name_label.setStyleSheet("color: #dc3545;")
            else:
                self.status_indicator.setText("●")
                self.status_indicator.setStyleSheet("color: #6c757d;")
                self.name_label.setStyleSheet("color: #343a40;")
            
            self.redownload_btn.hide()
            
            self.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #dee2e6;
                    border-radius: 3px;
                    margin: 1px;
                }
                QFrame:hover {
                    background-color: #f8f9fa;
                    border-color: #007bff;
                }
            """)
    
    def on_checkbox_changed(self):
        """Handle checkbox state change."""
        self.selection_changed.emit()
        
    def is_selected(self) -> bool:
        """Return whether this chapter is selected for download."""
        return self.checkbox.isChecked()
        
    def set_selected(self, selected: bool):
        """Set the selection state of this chapter."""
        self.checkbox.setChecked(selected)
    
    def set_downloaded(self, downloaded: bool):
        """Update the downloaded state of the chapter."""
        self.is_downloaded = downloaded
        if downloaded:
            self.status = "success"
        self.update_appearance()
    
    def set_status(self, status: str):
        """Update the chapter status."""
        self.status = status
        self.update_appearance()
    
    def set_progress(self, progress: int):
        """Set download progress for this chapter (0-100)."""
        if progress > 0 and progress < 100:
            self.status = "downloading"
            self.status_indicator.setText(f"{progress}%")
            self.status_indicator.setStyleSheet("color: #ffa500; font-weight: bold;")
            self.name_label.setStyleSheet("color: #ffa500; font-weight: bold;")
        elif progress >= 100:
            self.status = "success"
            self.is_downloaded = True
            self.update_appearance()
        
    def on_redownload_clicked(self):
        """Handle redownload button click."""
        parent_widget = self.parent()
        while parent_widget and not hasattr(parent_widget, 'manga_name'):
            parent_widget = parent_widget.parent()
            
        if parent_widget and hasattr(parent_widget, 'manga_name'):
            manga_name = getattr(parent_widget, 'manga_name', '')  # type: ignore
            self.redownload_requested.emit(manga_name, self.chapter_name)
    
    def apply_colors(self, background: str, text: str, success: str, 
                    error: str, pending: str, new: str):
        """Apply color scheme to the chapter item."""
        self.name_label.setStyleSheet(f"color: {text};")
        
        status_colors = {
            "success": success,
            "failed": error,
            "downloading": new,
            "not_selected": pending
        }
        
        color = status_colors.get(self.status, pending)
        self.status_indicator.setStyleSheet(f"color: {color};")
        
        self.setStyleSheet(f"""
            ChapterItem {{
                background-color: {background};
                border: 1px solid #ddd;
                border-radius: 3px;
                margin: 1px;
            }}
            ChapterItem:hover {{
                background-color: {background};
                border-color: {success};
            }}
        """)


class ChapterViewer(QWidget):
    """Chapter viewer widget showing all chapters of a manga."""
    
    chapter_redownload_requested = pyqtSignal(str, str)
    selection_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manga_name = ""
        self.manga_url = ""
        self.chapters = []
        self.chapter_items = {}
        self.site_type = ""
        self.available_languages = []
        self.current_language = "en"
        self.chapters_by_language = {}
        
        self.init_ui()
        
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        header_layout = QVBoxLayout()
        
        title_row = QHBoxLayout()
        self.title_label = QLabel("No Manga Selected")
        self.title_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.title_label.setWordWrap(True)
        
        self.count_label = QLabel("0 chapters")
        self.count_label.setFont(QFont("Arial", 9))
        self.count_label.setStyleSheet("color: #666;")
        
        title_row.addWidget(self.title_label, 1)
        title_row.addWidget(self.count_label)
        header_layout.addLayout(title_row)

        self.language_layout = QHBoxLayout()
        self.language_label = QLabel("Language:")
        self.language_label.setFont(QFont("Arial", 9))
        
        self.language_combo = QComboBox()
        self.language_combo.currentTextChanged.connect(self.on_language_changed)
        
        self.language_layout.addWidget(self.language_label)
        self.language_layout.addWidget(self.language_combo)
        self.language_layout.addStretch()
        
        self.language_label.hide()
        self.language_combo.hide()
        
        header_layout.addLayout(self.language_layout)
        
        layout.addLayout(header_layout)
        
        self.scroll_area = QScrollArea()
        scroll_widget = QWidget()
        self.chapters_layout = QVBoxLayout(scroll_widget)
        self.chapters_layout.setContentsMargins(0, 0, 0, 0)
        self.chapters_layout.setSpacing(2)
        self.chapters_layout.addStretch()
        
        self.scroll_area.setWidget(scroll_widget)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # type: ignore
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setRootIsDecorated(True)
        self.tree_widget.setAlternatingRowColors(True)
        self.tree_widget.hide()
        
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.tree_widget, 1)
    
        button_layout = QHBoxLayout()
        
        self.redownload_failed_btn = QPushButton("Redownload Failed")
        self.redownload_failed_btn.clicked.connect(self.redownload_failed_chapters)
        self.redownload_failed_btn.setEnabled(False)
        
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all_chapters)
        self.select_all_btn.setEnabled(False)
        
        button_layout.addWidget(self.redownload_failed_btn)
        button_layout.addWidget(self.select_all_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        self.setMinimumWidth(350)
        self.setStyleSheet("""
            QWidget {
                background-color: #f8f9fa;
                border-left: 1px solid #dee2e6;
            }
        """)
    
    def setup_language_selection(self):
        """Setup language selection for MangaDex."""
        if not self.chapters_by_language:
            return
            
        self.language_label.show()
        self.language_combo.show()
        
        self.language_combo.clear()
        self.available_languages = list(self.chapters_by_language.keys())
        
        for lang_code in self.available_languages:
            lang_name = self.get_language_display_name(lang_code)
            chapter_count = len(self.chapters_by_language[lang_code])
            display_text = f"{lang_name} ({chapter_count})"
            self.language_combo.addItem(display_text, lang_code)
        
        if "en" in self.available_languages:
            self.current_language = "en"
            idx = self.available_languages.index("en")
            self.language_combo.setCurrentIndex(idx)
        elif self.available_languages:
            self.current_language = self.available_languages[0]
            self.language_combo.setCurrentIndex(0)
    
    def get_language_display_name(self, lang_code: str) -> str:
        """Get display name for language code."""
        language_names = {
            'en': 'English',
            'ja': 'Japanese',
            'ja-ro': 'Japanese (Romanized)',
            'ko': 'Korean',
            'ko-ro': 'Korean (Romanized)',
            'zh': 'Chinese (Simplified)',
            'zh-hk': 'Chinese (Traditional)',
            'fr': 'French',
            'de': 'German',
            'es': 'Spanish',
            'es-la': 'Spanish (Latin America)',
            'pt': 'Portuguese',
            'pt-br': 'Portuguese (Brazil)',
            'ru': 'Russian',
            'vi': 'Vietnamese',
            'id': 'Indonesian',
            'th': 'Thai',
            'ar': 'Arabic',
            'tr': 'Turkish',
            'it': 'Italian',
            'pl': 'Polish',
            'ms': 'Malay',
            'tl': 'Filipino',
            'uk': 'Ukrainian',
            'nl': 'Dutch',
            'hu': 'Hungarian',
            'cs': 'Czech',
            'ro': 'Romanian',
            'bg': 'Bulgarian',
            'hr': 'Croatian',
            'he': 'Hebrew',
            'sr': 'Serbian',
            'hi': 'Hindi',
            'mn': 'Mongolian',
            'my': 'Burmese',
            'ca': 'Catalan',
            'sv': 'Swedish',
            'fi': 'Finnish',
            'da': 'Danish',
            'lt': 'Lithuanian',
            'sk': 'Slovak',
            'fa': 'Persian',
        }
        return language_names.get(lang_code, lang_code.upper())
    
    def on_language_changed(self, text: str):
        """Handle language selection change."""
        if not self.language_combo.currentData():
            return
            
        new_language = self.language_combo.currentData()
        if new_language == self.current_language:
            return  # No change, don't reload
            
        self.current_language = new_language
        current_chapters = self.get_current_chapters()
        logging.info(f"Language changed to {self.current_language}, loading {len(current_chapters)} chapters")
        self.count_label.setText(f"{len(current_chapters)} chapters ({self.current_language.upper()})")
        
        self.clear_chapters()
        self.load_chapters()
        self.selection_changed.emit()
    
    def get_current_chapters(self) -> List:
        """Get chapters for current language."""
        if self.chapters_by_language and self.current_language in self.chapters_by_language:
            return self.chapters_by_language[self.current_language]
        return self.chapters
        
    def set_manga(self, manga_name: str, manga_url: str = "", chapters: Optional[List] = None, chapter_status: Optional[Dict] = None, site_type: str = "", chapters_by_language: Optional[Dict] = None):
        """Set the manga and its chapters."""
        self.manga_name = manga_name
        self.manga_url = manga_url
        self.chapters = chapters or []
        self.site_type = site_type
        self.chapters_by_language = chapters_by_language or {}

        is_mangadex = (site_type.lower() == 'mangadex' or 'mangadex.org' in manga_url.lower())
        
        self.title_label.setText(manga_name or "No Manga Selected")
        
        if is_mangadex and self.chapters_by_language:
            self.setup_language_selection()
            self.count_label.setText(f"{len(self.get_current_chapters())} chapters ({self.current_language.upper()})")
        else:
            self.language_label.hide()
            self.language_combo.hide()
            self.count_label.setText(f"{len(self.chapters)} chapters")
        
        self.clear_chapters()
        self.load_chapters(chapter_status)

    def load_chapters(self, chapter_status: Optional[Dict] = None):
        """Load chapters based on current settings."""
        current_chapters = self.get_current_chapters()
        
        is_mangadex_with_volumes = (self.site_type.lower() == 'mangadex' and 
                                  current_chapters and 
                                  (hasattr(current_chapters[0], 'volume_number') or 
                                   (isinstance(current_chapters[0], dict) and 'volume_number' in current_chapters[0])))
        
        if is_mangadex_with_volumes:
            self.load_mangadex_chapters_with_volumes(current_chapters, chapter_status)
        else:
            self.load_simple_chapters(current_chapters, chapter_status)
    
    def load_mangadex_chapters_with_volumes(self, chapters: List, chapter_status: Optional[Dict] = None):
        """Load MangaDex chapters grouped by volume."""
        self.scroll_area.hide()
        self.tree_widget.show()
        
        volumes = {}
        no_volume_chapters = []
        
        for chapter in chapters:
            vol_num = None
            if isinstance(chapter, dict):
                vol_num = chapter.get('volume_number')
            elif hasattr(chapter, 'volume_number'):
                vol_num = chapter.volume_number
            
            if vol_num:
                if vol_num not in volumes:
                    volumes[vol_num] = []
                volumes[vol_num].append(chapter)
            else:
                no_volume_chapters.append(chapter)
        
        for vol_num in sorted(volumes.keys(), key=lambda x: float(x) if str(x).replace('.', '').isdigit() else 999):
            vol_item = QTreeWidgetItem(self.tree_widget)
            vol_item.setText(0, f"Volume {vol_num} ({len(volumes[vol_num])} chapters)")
            vol_item.setExpanded(True)
            
            for chapter in volumes[vol_num]:
                chapter_item = QTreeWidgetItem(vol_item)
                
                if isinstance(chapter, dict):
                    chapter_num = chapter.get('chapter_number', '')
                    chapter_title = chapter.get('chapter_name', '')
                else:
                    chapter_num = chapter.chapter_number if hasattr(chapter, 'chapter_number') else ''
                    chapter_title = None
                    if hasattr(chapter, 'title') and chapter.title:
                        chapter_title = chapter.title
                    elif hasattr(chapter, 'chapter_name') and chapter.chapter_name:
                        chapter_title = chapter.chapter_name
                
                display_name = f"Chapter {chapter_num}" if chapter_num else "Unknown Chapter"
                
                if chapter_title and chapter_title != f"Chapter {chapter_num}" and chapter_title.strip():
                    display_name += f" - {chapter_title}"
                
                chapter_item.setData(0, Qt.UserRole, chapter)  # type: ignore
                
                is_downloaded = (chapter.get('is_downloaded', False)
                                 if isinstance(chapter, dict)
                                 else getattr(chapter, 'is_downloaded', False))
                
                checkbox = QCheckBox(display_name)
                checkbox.stateChanged.connect(self.on_chapter_selection_changed)
                if is_downloaded:
                    checkbox.setText(f"✓ {display_name}")
                    checkbox.setStyleSheet("color: #4CAF50;")
                self.tree_widget.setItemWidget(chapter_item, 0, checkbox)
        
        if no_volume_chapters:
            no_vol_item = QTreeWidgetItem(self.tree_widget)
            no_vol_item.setText(0, f"No Volume ({len(no_volume_chapters)} chapters)")
            no_vol_item.setExpanded(True)
            
            for chapter in no_volume_chapters:
                chapter_item = QTreeWidgetItem(no_vol_item)
                
                if isinstance(chapter, dict):
                    chapter_num = chapter.get('chapter_number', '')
                    chapter_title = chapter.get('chapter_name', '')
                else:
                    chapter_num = chapter.chapter_number if hasattr(chapter, 'chapter_number') else ''
                    chapter_title = None
                    if hasattr(chapter, 'title') and chapter.title:
                        chapter_title = chapter.title
                    elif hasattr(chapter, 'chapter_name') and chapter.chapter_name:
                        chapter_title = chapter.chapter_name
                
                display_name = f"Ch. {chapter_num}" if chapter_num else "Unknown Chapter"
                
                if chapter_title and chapter_title.strip():
                    if chapter_title != f"Chapter {chapter_num}" and chapter_title != f"Ch. {chapter_num}" and chapter_title != f"Ch.{chapter_num}":
                        display_name += f" - {chapter_title}"
                elif not chapter_title or not chapter_title.strip():
                    pass
                
                chapter_item.setData(0, Qt.UserRole, chapter)  # type: ignore
                
                is_downloaded = (chapter.get('is_downloaded', False)
                                 if isinstance(chapter, dict)
                                 else getattr(chapter, 'is_downloaded', False))
                
                checkbox = QCheckBox(display_name)
                checkbox.stateChanged.connect(self.on_chapter_selection_changed)
                if is_downloaded:
                    checkbox.setText(f"✓ {display_name}")
                    checkbox.setStyleSheet("color: #4CAF50;")
                self.tree_widget.setItemWidget(chapter_item, 0, checkbox)
    
    def load_simple_chapters(self, chapters: List, chapter_status: Optional[Dict] = None):
        """Load chapters in simple list format."""
        self.tree_widget.hide()
        self.scroll_area.show()
        
        if chapters:
            for chapter in chapters:
                if isinstance(chapter, str):
                    chapter_name = chapter
                    chapter_url = ''
                elif isinstance(chapter, tuple) and len(chapter) >= 3:
                    if chapter[1] and chapter[1].strip():
                        if chapter[1].startswith('Chapter'):
                            chapter_name = chapter[1]
                        else:
                            chapter_name = f"Chapter {chapter[0]}: {chapter[1]}"
                    else:
                        chapter_name = f"Chapter {chapter[0]}"
                    chapter_url = chapter[2]
                elif isinstance(chapter, dict):
                    chapter_name = chapter.get('name', 'Unknown')
                    chapter_url = chapter.get('url', '')
                elif hasattr(chapter, 'chapter_number'):
                    chapter_name = f"Chapter {chapter.chapter_number}"
                    if hasattr(chapter, 'title') and chapter.title:
                        chapter_name += f" - {chapter.title}"
                    chapter_url = getattr(chapter, 'url', '')
                else:
                    chapter_name = str(chapter)
                    chapter_url = ''
                
                status = "not_selected"
                is_downloaded = False
                if chapter_status:
                    if chapter in chapter_status:
                        status = chapter_status[chapter]
                    elif chapter_name in chapter_status:
                        status = chapter_status[chapter_name]
                    elif isinstance(chapter, tuple) and len(chapter) > 0 and chapter[0] in chapter_status:
                        status = chapter_status[chapter[0]]
                    
                    is_downloaded = status in ["success", "downloaded"]
                
                if isinstance(chapter, tuple) and len(chapter) >= 1:
                    chapter_num = str(chapter[0])
                else:
                    import re
                    match = re.search(r'Chapter (\d+)', chapter_name)
                    chapter_num = match.group(1) if match else "0"
                
                item = ChapterItem(chapter_num, chapter_name, chapter_url, is_downloaded, status)
                item.redownload_requested.connect(self.chapter_redownload_requested.emit)
                item.selection_changed.connect(self.on_selection_changed)
                
                self.chapters_layout.insertWidget(self.chapters_layout.count() - 1, item)
                self.chapter_items[chapter_name] = item
        
        self.redownload_failed_btn.setEnabled(len(self.chapters) > 0)
        self.select_all_btn.setEnabled(len(self.chapters) > 0)
        self.update_select_all_button_text()
        
    def on_selection_changed(self):
        """Handle when chapter selection changes."""
        self.update_select_all_button_text()
        self.selection_changed.emit()
        
    def update_select_all_button_text(self):
        """Update the select all button text based on current selection state."""
        all_items = list(self.chapter_items.values())
        if not all_items:
            self.select_all_btn.setText("Select All")
            return
            
        all_selected = all(item.is_selected() for item in all_items)
        if all_selected:
            self.select_all_btn.setText("Deselect All")
        else:
            self.select_all_btn.setText("Select All")
        
    def clear_chapters(self):
        """Clear all chapter items."""
        for item in self.chapter_items.values():
            self.chapters_layout.removeWidget(item)
            item.deleteLater()
        self.chapter_items.clear()
        
        self.tree_widget.clear()
        
    def update_chapter_status(self, chapter_name: str, status: str):
        """Update the status of a specific chapter."""
        if chapter_name in self.chapter_items:
            self.chapter_items[chapter_name].set_status(status)
    
    def on_chapter_selection_changed(self):
        """Handle chapter selection change in tree widget."""
        self.selection_changed.emit()
            
    def redownload_failed_chapters(self):
        """Request redownload of all failed chapters."""
        for chapter_name, item in self.chapter_items.items():
            if item.status == "failed":
                self.chapter_redownload_requested.emit(self.manga_name, chapter_name)
                
    def select_all_chapters(self):
        """Select all chapters for download."""
        if self.tree_widget.isVisible():
            root = self.tree_widget.invisibleRootItem()
            if root:
                all_checked = True
                
                for i in range(root.childCount()):
                    volume_item = root.child(i)
                    if volume_item:
                        for j in range(volume_item.childCount()):
                            chapter_item = volume_item.child(j)
                            if chapter_item:
                                checkbox = self.tree_widget.itemWidget(chapter_item, 0)
                                if checkbox and not checkbox.text().startswith("✓") and not checkbox.isChecked():
                                    all_checked = False
                                    break
                    if not all_checked:
                        break
                
                select_state = not all_checked
                for i in range(root.childCount()):
                    volume_item = root.child(i)
                    if volume_item:
                        for j in range(volume_item.childCount()):
                            chapter_item = volume_item.child(j)
                            if chapter_item:
                                checkbox = self.tree_widget.itemWidget(chapter_item, 0)
                                if checkbox and not checkbox.text().startswith("✓"):
                                    checkbox.setChecked(select_state)
                
                if select_state:
                    self.select_all_btn.setText("Deselect All")
                else:
                    self.select_all_btn.setText("Select All")
        else:
            non_downloaded_items = [item for item in self.chapter_items.values() if not item.is_downloaded]
            all_selected = all(item.is_selected() for item in non_downloaded_items)
            
            select_state = not all_selected
            
            for item in non_downloaded_items:
                item.set_selected(select_state)
            
            if select_state:
                self.select_all_btn.setText("Deselect All")
            else:
                self.select_all_btn.setText("Select All")
        
        self.selection_changed.emit()
        
    def get_chapter_statuses(self):
        """Get the current status of all chapters."""
        return {name: item.status for name, item in self.chapter_items.items()}
    
    def apply_colors(self, background: str, border: str, text: str, 
                    success: str, error: str, pending: str, new: str):
        """Apply color scheme to the chapter viewer."""
        self.setStyleSheet(f"""
            ChapterViewer {{
                background-color: {background};
                border-left: 1px solid {border};
            }}
            QWidget {{
                background-color: {background};
                color: {text};
            }}
            QLabel {{
                color: {text};
            }}
            QScrollArea {{
                background-color: {background};
                border: none;
            }}
        """)
        
        for item in self.chapter_items.values():
            if hasattr(item, 'apply_colors'):
                item.apply_colors(background, text, success, error, pending, new)
    
    def get_selected_chapters(self) -> List:
        """Get list of selected chapters."""
        selected = []
        
        if self.tree_widget.isVisible():
            root = self.tree_widget.invisibleRootItem()
            if root:
                for i in range(root.childCount()):
                    volume_item = root.child(i)
                    if volume_item:
                        for j in range(volume_item.childCount()):
                            chapter_item = volume_item.child(j)
                            if chapter_item:
                                checkbox = self.tree_widget.itemWidget(chapter_item, 0)
                                if checkbox and checkbox.isChecked():
                                    chapter_data = chapter_item.data(0, 0x0100)  # Qt.UserRole value
                                    if chapter_data:
                                        selected.append(chapter_data)
        else:
            for item in self.chapter_items.values():
                if item.is_selected():
                    selected.append(item)
        
        return selected
    
    def clear_selection(self):
        """Clear all chapter selections."""
        for chapter_name, item in self.chapter_items.items():
            item.set_selected(False)
        self.selection_changed.emit()
    
    def update_chapter_progress(self, chapter_num: str, progress: int):
        """Update the progress of a specific chapter."""
        for item in self.chapter_items.values():
            if item.chapter_number == chapter_num:
                item.set_progress(progress)
                break
    
    def mark_chapter_downloading(self, chapter_num: str):
        """Mark a chapter as currently downloading."""
        for item in self.chapter_items.values():
            if item.chapter_number == chapter_num:
                item.set_status("downloading")
                break
    
    def mark_chapter_completed(self, chapter_num: str):
        """Mark a chapter as completed."""
        for item in self.chapter_items.values():
            if item.chapter_number == chapter_num:
                item.set_status("success")
                item.set_downloaded(True)
                break
        
        if self.chapters_by_language:
            for lang_chapters in self.chapters_by_language.values():
                for chapter in lang_chapters:
                    ch_num = (chapter.get('chapter_number', '')
                              if isinstance(chapter, dict)
                              else getattr(chapter, 'chapter_number', ''))
                    if str(ch_num) == str(chapter_num):
                        if isinstance(chapter, dict):
                            chapter['is_downloaded'] = True
        
        if self.tree_widget.isVisible():
            root = self.tree_widget.invisibleRootItem()
            if root:
                for i in range(root.childCount()):
                    volume_item = root.child(i)
                    if volume_item:
                        for j in range(volume_item.childCount()):
                            chapter_item = volume_item.child(j)
                            if chapter_item:
                                chapter_data = chapter_item.data(0, 0x0100)  # Qt.UserRole
                                if isinstance(chapter_data, dict):
                                    ch_num = chapter_data.get('chapter_number', '')
                                else:
                                    ch_num = getattr(chapter_data, 'chapter_number', '')
                                if str(ch_num) == str(chapter_num):
                                    checkbox = self.tree_widget.itemWidget(chapter_item, 0)
                                    if checkbox:
                                        text = checkbox.text()
                                        if not text.startswith("✓"):
                                            checkbox.setText(f"✓ {text}")
                                        checkbox.setStyleSheet("color: #4CAF50;")
                                        checkbox.setChecked(False)  # deselect now that it's done
    
    def mark_chapter_failed(self, chapter_num: str):
        """Mark a chapter as failed."""
        for item in self.chapter_items.values():
            if item.chapter_number == chapter_num:
                item.set_status("failed")
                break

    @property
    def current_manga_name(self) -> str:
        """Get the current manga name."""
        return self.manga_name
    
    @property 
    def current_manga_url(self) -> str:
        """Get the current manga URL."""
        return getattr(self, 'manga_url', '')
    
    def refresh_chapters(self):
        """Refresh the chapter display (placeholder for now)."""
        self.selection_changed.emit()
        
    def refresh_chapter_status(self):
        try:
            from ...managers.database_manager import DatabaseManager
            db = DatabaseManager()
            
            manga_info = db.get_manga_by_title(self.manga_name)
            if not manga_info:
                return
                
            chapters = db.get_chapters_for_manga(manga_info['id'])
            
            db_chapters_by_name = {chapter['chapter_name']: chapter for chapter in chapters}
            db_chapters_by_num = {chapter['chapter_number']: chapter for chapter in chapters}
            
            for chapter_name, item in self.chapter_items.items():
                db_chapter = db_chapters_by_name.get(chapter_name)
                if not db_chapter:
                    db_chapter = db_chapters_by_num.get(item.chapter_number)
                
                if db_chapter:
                    is_downloaded = db_chapter['is_downloaded']
                    
                    if is_downloaded and not item.is_downloaded:
                        item.set_downloaded(True)
                        item.set_status("success")
                    elif not is_downloaded and item.is_downloaded:
                        item.set_downloaded(False)
                        item.set_status("not_selected")
            
            self.repaint()
            
        except Exception as e:
            print(f"Error refreshing chapter status: {e}")