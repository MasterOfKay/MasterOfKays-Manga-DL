"""
MangaDex-specific chapter selection dialog with language and volume support.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QCheckBox, QSpinBox, QGridLayout, QPushButton,
                            QScrollArea, QWidget, QComboBox, QGroupBox,
                            QListWidget, QListWidgetItem, QFrame)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont
from typing import List, Tuple, Union, Dict, Optional
import requests
from threading import Thread

try:
    from ...sites.base import ChapterInfo
except (ImportError, ModuleNotFoundError):
    ChapterInfo = None


class MangaDexChapterSelectionDialog(QDialog):
    """MangaDex-specific chapter selection dialog with language filtering and better organization."""
    
    def __init__(self, manga_name: str, chapters_by_language: Dict[str, List], 
                 parent=None, cover_url: str = ""):
        super().__init__(parent)
        self.manga_name = manga_name
        self.chapters_by_language = chapters_by_language
        self.cover_url = cover_url
        self.selected_chapters = []
        self.current_language = "en"
        
        self.available_languages = list(chapters_by_language.keys())
        if "en" not in self.available_languages and self.available_languages:
            self.current_language = self.available_languages[0]
        
        self.setWindowTitle(f"Select Chapters - {manga_name}")
        self.setModal(True)
        self.resize(900, 600)
        
        self.init_ui()
        self.load_chapters()
    
    def init_ui(self):
        """Initialize the UI."""
        main_layout = QHBoxLayout()
        
        left_panel = QFrame()
        left_panel.setFixedWidth(250)
        left_panel.setFrameStyle(QFrame.StyledPanel)
        left_layout = QVBoxLayout()
        
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(200, 280)
        self.cover_label.setStyleSheet("""
            QLabel {
                border: 2px solid #ddd;
                border-radius: 8px;
                background-color: #f5f5f5;
            }
        """)
        self.cover_label.setText("Loading...")
        left_layout.addWidget(self.cover_label)
        
        if self.cover_url:
            self.load_cover_image()
        
        title_label = QLabel(self.manga_name)
        title_label.setWordWrap(True)
        title_label.setFont(QFont("Arial", 12, QFont.Bold))
        title_label.setStyleSheet("margin: 10px 0; padding: 5px;")
        left_layout.addWidget(title_label)
        
        lang_group = QGroupBox("Language")
        lang_layout = QVBoxLayout()
        
        self.language_combo = QComboBox()
        for lang in self.available_languages:
            display_name = self.get_language_display_name(lang)
            self.language_combo.addItem(display_name, lang)
        
        self.language_combo.currentIndexChanged.connect(self.on_language_changed)
        lang_layout.addWidget(self.language_combo)
        lang_group.setLayout(lang_layout)
        left_layout.addWidget(lang_group)
        
        self.stats_label = QLabel("Loading...")
        self.stats_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
            }
        """)
        left_layout.addWidget(self.stats_label)
        
        left_layout.addStretch()
        left_panel.setLayout(left_layout)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        
        control_layout = QHBoxLayout()
        
        self.select_all_btn = QPushButton("Select All")
        self.clear_all_btn = QPushButton("Clear All")
        self.select_range_btn = QPushButton("Range...")
        
        self.select_all_btn.clicked.connect(self.select_all)
        self.clear_all_btn.clicked.connect(self.clear_all)
        self.select_range_btn.clicked.connect(self.select_range)
        
        control_layout.addWidget(self.select_all_btn)
        control_layout.addWidget(self.clear_all_btn)
        control_layout.addWidget(self.select_range_btn)
        control_layout.addStretch()
        
        right_layout.addLayout(control_layout)
        
        self.chapter_list = QListWidget()
        self.chapter_list.setAlternatingRowColors(True)
        right_layout.addWidget(self.chapter_list)
        
        button_layout = QHBoxLayout()
        
        self.download_btn = QPushButton("Download Selected")
        self.cancel_btn = QPushButton("Cancel")
        
        self.download_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #4285f4;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3367d6;
            }
        """)
        
        button_layout.addStretch()
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(self.cancel_btn)
        
        right_layout.addLayout(button_layout)
        right_panel.setLayout(right_layout)
        
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        self.setLayout(main_layout)
    
    def get_language_display_name(self, lang_code: str) -> str:
        """Get display name for language code."""
        lang_names = {
            'en': 'English',
            'ja': 'Japanese',
            'ja-ro': 'Japanese (Romanized)',
            'ko': 'Korean',
            'ko-ro': 'Korean (Romanized)',
            'zh': 'Chinese (Simplified)',
            'zh-hk': 'Chinese (Traditional)',
            'fr': 'French',
            'es': 'Spanish',
            'es-la': 'Spanish (Latin America)',
            'de': 'German',
            'it': 'Italian',
            'pt': 'Portuguese',
            'pt-br': 'Portuguese (Brazil)',
            'ru': 'Russian',
            'ar': 'Arabic',
            'vi': 'Vietnamese',
            'id': 'Indonesian',
            'th': 'Thai',
            'tr': 'Turkish',
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
            'fa': 'Persian',
        }
        return lang_names.get(lang_code, lang_code.upper())
    
    def load_cover_image(self):
        """Load cover image in background."""
        def load_image():
            try:
                response = requests.get(self.cover_url, timeout=10)
                response.raise_for_status()
                
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                
                scaled_pixmap = pixmap.scaled(self.cover_label.size())
                
                self.cover_label.setPixmap(scaled_pixmap)
                
            except Exception:
                self.cover_label.setText("Cover not\\navailable")
        
        thread = Thread(target=load_image, daemon=True)
        thread.start()
    
    def on_language_changed(self):
        """Handle language change."""
        lang_code = self.language_combo.currentData()
        if lang_code and lang_code != self.current_language:
            self.current_language = lang_code
            self.load_chapters()
    
    def load_chapters(self):
        """Load chapters for current language."""
        self.chapter_list.clear()
        
        chapters = self.chapters_by_language.get(self.current_language, [])
        
        if chapters and ChapterInfo and isinstance(chapters[0], ChapterInfo):
            self.load_enhanced_chapters(chapters)
        else:
            self.load_simple_chapters(chapters)
        
        self.update_stats()
    
    def load_enhanced_chapters(self, chapters):
        """Load ChapterInfo objects with volume grouping."""
        volumes = {}
        for chapter in chapters:
            vol_key = getattr(chapter, 'volume_number', '') or "No Volume"
            if vol_key not in volumes:
                volumes[vol_key] = []
            volumes[vol_key].append(chapter)
        
        sorted_vols = sorted(volumes.keys(), key=lambda x: (x == "No Volume", x))
        
        for vol_key in sorted_vols:
            vol_chapters = volumes[vol_key]
            
            if len(volumes) > 1:
                vol_item = QListWidgetItem(f"📁 Volume {vol_key}" if vol_key != "No Volume" else f"📁 {vol_key}")
                vol_font = vol_item.font()
                vol_font.setBold(True)
                vol_item.setFont(vol_font)
                self.chapter_list.addItem(vol_item)
            
            vol_chapters.sort(key=lambda c: float(getattr(c, 'chapter_number', '0')) if getattr(c, 'chapter_number', '0').replace('.', '').isdigit() else float('inf'))
            
            for chapter in vol_chapters:
                item = QListWidgetItem()
                
                checkbox = QCheckBox()
                
                display_parts = []
                ch_num = getattr(chapter, 'chapter_number', '')
                title = getattr(chapter, 'title', '')
                group = getattr(chapter, 'scanlation_group', '') or getattr(chapter, 'translator', '')
                
                if ch_num:
                    display_parts.append(f"Ch.{ch_num}")
                if title:
                    display_parts.append(title)
                
                display_text = " - ".join(display_parts)
                
                if group:
                    display_text += f" [{group}]"
                
                checkbox.setText(display_text)
                checkbox.stateChanged.connect(self.update_selection_count)
                
                checkbox.chapter_data = chapter
                
                self.chapter_list.addItem(item)
                self.chapter_list.setItemWidget(item, checkbox)
    
    def load_simple_chapters(self, chapters):
        """Load simple chapter tuples."""
        for chapter_data in chapters:
            if isinstance(chapter_data, (list, tuple)) and len(chapter_data) >= 3:
                ch_num, ch_name, ch_url = chapter_data[:3]
                is_downloaded = len(chapter_data) >= 4 and chapter_data[3]
                
                item = QListWidgetItem()
                checkbox = QCheckBox()
                
                display_text = f"Ch.{ch_num}: {ch_name}"
                if is_downloaded:
                    display_text += " ✓"
                    checkbox.setStyleSheet("color: green; font-weight: bold;")
                
                checkbox.setText(display_text)
                checkbox.stateChanged.connect(self.update_selection_count)
                checkbox.chapter_data = chapter_data
                
                self.chapter_list.addItem(item)
                self.chapter_list.setItemWidget(item, checkbox)
    
    def update_stats(self):
        """Update statistics display."""
        chapters = self.chapters_by_language.get(self.current_language, [])
        total = len(chapters)
        
        stats_text = f"Language: {self.get_language_display_name(self.current_language)}\\n"
        stats_text += f"Total Chapters: {total}"
        
        if chapters and ChapterInfo and isinstance(chapters[0], ChapterInfo):
            volumes = set()
            groups = set()
            
            for chapter in chapters:
                vol = getattr(chapter, 'volume_number', '')
                if vol:
                    volumes.add(vol)
                group = getattr(chapter, 'scanlation_group', '') or getattr(chapter, 'translator', '')
                if group:
                    groups.add(group)
            
            if volumes:
                stats_text += f"\\nVolumes: {len(volumes)}"
            if groups:
                stats_text += f"\\nGroups: {len(groups)}"
        
        self.stats_label.setText(stats_text)
    
    def select_all(self):
        """Select all chapters."""
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            widget = self.chapter_list.itemWidget(item)
            if isinstance(widget, QCheckBox):
                widget.setChecked(True)
    
    def clear_all(self):
        """Clear all selections."""
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            widget = self.chapter_list.itemWidget(item)
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)
    
    def select_range(self):
        """Show range selection dialog."""
        from PyQt5.QtWidgets import QInputDialog
        
        chapters = self.chapters_by_language.get(self.current_language, [])
        if not chapters:
            return
        
        ch_numbers = []
        if ChapterInfo and isinstance(chapters[0], ChapterInfo):
            ch_numbers = [float(getattr(ch, 'chapter_number', '0')) for ch in chapters if getattr(ch, 'chapter_number', '0').replace('.', '').isdigit()]
        else:
            ch_numbers = [float(ch[0]) for ch in chapters if isinstance(ch, (list, tuple)) and ch[0].replace('.', '').isdigit()]
        
        if not ch_numbers:
            return
        
        min_ch = min(ch_numbers)
        max_ch = max(ch_numbers)
        
        start, ok1 = QInputDialog.getDouble(self, "Select Range", f"From chapter ({min_ch}-{max_ch}):", min_ch, min_ch, max_ch, 1)
        if not ok1:
            return
        
        end, ok2 = QInputDialog.getDouble(self, "Select Range", f"To chapter ({start}-{max_ch}):", max_ch, start, max_ch, 1)
        if not ok2:
            return
        
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            widget = self.chapter_list.itemWidget(item)
            if isinstance(widget, QCheckBox) and hasattr(widget, 'chapter_data'):
                chapter = widget.chapter_data
                
                ch_num = None
                if ChapterInfo and isinstance(chapter, ChapterInfo):
                    ch_num_str = getattr(chapter, 'chapter_number', '0')
                elif isinstance(chapter, (list, tuple)):
                    ch_num_str = chapter[0]
                else:
                    continue
                
                try:
                    ch_num = float(ch_num_str)
                    if start <= ch_num <= end:
                        widget.setChecked(True)
                    else:
                        widget.setChecked(False)
                except ValueError:
                    continue
    
    def update_selection_count(self):
        """Update button text with selection count."""
        selected_count = 0
        
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            widget = self.chapter_list.itemWidget(item)
            if isinstance(widget, QCheckBox) and widget.isChecked():
                selected_count += 1
        
        self.download_btn.setText(f"Download Selected ({selected_count})")
    
    def get_selected_chapters(self):
        """Get selected chapters data."""
        selected = []
        
        for i in range(self.chapter_list.count()):
            item = self.chapter_list.item(i)
            widget = self.chapter_list.itemWidget(item)
            if isinstance(widget, QCheckBox) and widget.isChecked() and hasattr(widget, 'chapter_data'):
                selected.append(widget.chapter_data)
        
        return selected
    
    def get_selected_language(self):
        """Get currently selected language."""
        return self.current_language