"""
Enhanced chapter selection dialog with support for simple and complex manga sites.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QCheckBox, QSpinBox, QGridLayout, QPushButton,
                            QScrollArea, QWidget, QComboBox, QGroupBox,
                            QListWidget, QListWidgetItem, QFrame, QSplitter,
                            QTreeWidget, QTreeWidgetItem, QHeaderView)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont
from threading import Thread
from typing import List, Union, Tuple, Optional, Dict
import requests
import logging

try:
    from ...sites.base import ChapterInfo
except ImportError:
    ChapterInfo = None

try:
    from ..widgets.toast import Toast
except ImportError:
    Toast = None

logger = logging.getLogger(__name__)


class ChapterSelectionDialog(QDialog):
    """Enhanced dialog for selecting chapters to download with support for both simple and complex sites."""
    
    def __init__(self, manga_name: str, chapters: List[Union[Tuple[str, str, str], Tuple[str, str, str, bool]]], 
                 parent=None, include_downloaded: bool = False, 
                 cover_url: str = "", chapters_by_language: Optional[Dict[str, List]] = None,
                 is_enhanced: bool = False, metadata=None, languages=None):
        super().__init__(parent)
        self.manga_name = manga_name
        self.chapters = chapters
        self.include_downloaded = include_downloaded
        self.cover_url = cover_url
        self.chapters_by_language = chapters_by_language or {}
        self.chapter_checkboxes = []
        self.chapter_items = {}
        self.metadata = metadata
        self.languages = languages or []
        self.available_languages = languages or []
        
        self.is_enhanced = True
        self.has_language_features = bool(self.chapters_by_language and ChapterInfo)
        self.current_language = "en"
        self.language_filter = []
        
        if self.is_enhanced:
            if not self.available_languages and self.chapters_by_language:
                self.available_languages = [(lang, self.get_language_display_name(lang)) for lang in self.chapters_by_language.keys()]
            
            available_codes = []
            for lang_item in self.available_languages:
                if isinstance(lang_item, (list, tuple)) and len(lang_item) >= 1:
                    available_codes.append(lang_item[0])
                else:
                    available_codes.append(str(lang_item))
            
            if "en" not in available_codes and available_codes:
                self.current_language = available_codes[0]
            
            self.filtered_chapters = self.chapters_by_language.get(self.current_language, [])
        else:
            self.available_languages = []
            self.filtered_chapters = chapters
        
        self.setWindowTitle(f"Select Chapters - {manga_name}")
        self.setModal(True)
        self.resize(1100 if self.is_enhanced else 600, 700 if self.is_enhanced else 500)
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI."""
        logger.info(f"Initializing dialog UI - Enhanced mode: {self.is_enhanced}")
        logger.info(f"Chapters by language: {bool(self.chapters_by_language)}")
        logger.info(f"Available languages: {len(self.available_languages)}")
        
        if self.is_enhanced:
            logger.info("Using enhanced UI with tree layout")
            self.init_enhanced_ui()
        else:
            logger.info("Using simple UI with grid layout")
            self.init_simple_ui()
    
    def init_enhanced_ui(self):
        """Initialize enhanced UI for MangaDex-style sites."""
        main_layout = QHBoxLayout()
        
        left_panel = self.create_left_panel()
        
        right_panel = self.create_right_panel()
        
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        self.setLayout(main_layout)
        
        self.load_chapters()
    
    def create_left_panel(self) -> QWidget:
        """Create left panel with cover image and manga info."""
        panel = QFrame()
        panel.setFixedWidth(250)
        panel.setFrameStyle(QFrame.StyledPanel)
        layout = QVBoxLayout()
        
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
        layout.addWidget(self.cover_label)
        
        if self.cover_url:
            self.load_cover_image()
        
        title_label = QLabel(self.manga_name)
        title_label.setWordWrap(True)
        title_label.setFont(QFont("Arial", 12, QFont.Bold))
        title_label.setStyleSheet("margin: 10px 0; padding: 5px;")
        layout.addWidget(title_label)
        
        if self.available_languages and self.has_language_features:
            lang_group = QGroupBox("Language Filter")
            lang_layout = QVBoxLayout()
            
            self.show_all_langs = QCheckBox("Show All Languages")
            self.show_all_langs.setChecked(True)
            self.show_all_langs.stateChanged.connect(self.on_language_filter_changed)
            lang_layout.addWidget(self.show_all_langs)
            
            self.language_checkboxes = {}

            for lang_item in self.available_languages:
                if isinstance(lang_item, (list, tuple)) and len(lang_item) >= 2:
                    lang_code, lang_name = lang_item[0], lang_item[1]
                else:
                    lang_code = str(lang_item)
                    lang_name = self.get_language_display_name(lang_code)
                
                display_name = f"[{lang_code.upper()}] {lang_name}"
                checkbox = QCheckBox(display_name)
                checkbox.setChecked(True)
                checkbox.stateChanged.connect(self.on_language_filter_changed)
                self.language_checkboxes[lang_code] = checkbox
                lang_layout.addWidget(checkbox)
            
            lang_group.setLayout(lang_layout)
            layout.addWidget(lang_group)
        
        self.stats_label = QLabel("Loading...")
        self.stats_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
            }
        """)
        layout.addWidget(self.stats_label)
        
        layout.addStretch()
        panel.setLayout(layout)
        return panel
    
    def create_right_panel(self) -> QWidget:
        """Create right panel with chapter selection."""
        panel = QWidget()
        layout = QVBoxLayout()
        
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
        
        layout.addLayout(control_layout)
        
        self.chapter_tree = QTreeWidget()
        self.chapter_tree.setHeaderLabels(["Chapter", "Language", "Volume", "Group"])
        self.chapter_tree.setRootIsDecorated(True)
        self.chapter_tree.setAlternatingRowColors(True)
        self.chapter_tree.setSelectionMode(QTreeWidget.NoSelection)
        
        header = self.chapter_tree.header()
        if header:
            header.setStretchLastSection(False)
            self.chapter_tree.setColumnWidth(0, 450)  # Chapter column
            self.chapter_tree.setColumnWidth(1, 120)  # Language column
            self.chapter_tree.setColumnWidth(2, 80)   # Volume column
            self.chapter_tree.setColumnWidth(3, 150)  # Group column
            header.setSectionResizeMode(0, QHeaderView.Interactive)
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.Interactive)
        
        layout.addWidget(self.chapter_tree)
        
        button_layout = QHBoxLayout()
        
        self.ok_btn = QPushButton("Download Selected")
        self.cancel_btn = QPushButton("Cancel")
        
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.ok_btn.setStyleSheet("""
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
        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        panel.setLayout(layout)
        return panel
    
    def init_simple_ui(self):
        """Initialize simple UI for standard sites."""
        layout = QVBoxLayout()
        
        title_label = QLabel(f"Select chapters to download for: {self.manga_name}")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        control_layout = QHBoxLayout()
        
        self.select_all_btn = QPushButton("Download New")
        self.clear_all_btn = QPushButton("Clear All")
        self.select_downloaded_btn = QPushButton("Select Downloaded")
        self.select_not_downloaded_btn = QPushButton("Select Not Downloaded")
        self.range_from_spin = QSpinBox()
        self.range_to_spin = QSpinBox()
        self.apply_range_btn = QPushButton("Apply Range")
        
        self.select_all_btn.clicked.connect(self.select_all)
        self.clear_all_btn.clicked.connect(self.clear_all)
        self.select_downloaded_btn.clicked.connect(self.select_downloaded)
        self.select_not_downloaded_btn.clicked.connect(self.select_not_downloaded)
        self.apply_range_btn.clicked.connect(self.apply_range)
        
        if self.chapters:
            try:
                if ChapterInfo and isinstance(self.chapters[0], ChapterInfo):
                    first_ch = int(float(getattr(self.chapters[0], 'chapter_number', '1')))
                    last_ch = int(float(getattr(self.chapters[-1], 'chapter_number', '999')))
                else:
                    first_ch = int(float(self.chapters[0][0]))
                    last_ch = int(float(self.chapters[-1][0]))
                self.range_from_spin.setRange(first_ch, last_ch)
                self.range_to_spin.setRange(first_ch, last_ch)
                self.range_from_spin.setValue(first_ch)
                self.range_to_spin.setValue(last_ch)
            except (ValueError, IndexError, AttributeError):
                self.range_from_spin.setRange(1, 999)
                self.range_to_spin.setRange(1, 999)
        
        control_layout.addWidget(self.select_all_btn)
        control_layout.addWidget(self.clear_all_btn)
        control_layout.addWidget(self.select_downloaded_btn)
        control_layout.addWidget(self.select_not_downloaded_btn)
        control_layout.addWidget(QLabel("From:"))
        control_layout.addWidget(self.range_from_spin)
        control_layout.addWidget(QLabel("To:"))
        control_layout.addWidget(self.range_to_spin)
        control_layout.addWidget(self.apply_range_btn)
        control_layout.addStretch()
        
        layout.addLayout(control_layout)
        
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QGridLayout(scroll_widget)
        
        columns = 3
        for i, chapter_data in enumerate(self.chapters):
            if ChapterInfo and isinstance(chapter_data, ChapterInfo):
                chapter_num = getattr(chapter_data, 'chapter_number', '')
                chapter_name = getattr(chapter_data, 'title', '')
                is_downloaded = False
            elif isinstance(chapter_data, (list, tuple)) and len(chapter_data) >= 2:
                chapter_num = chapter_data[0]
                chapter_name = chapter_data[1]
                is_downloaded = len(chapter_data) >= 4 and chapter_data[3]
            else:
                continue
                
            if is_downloaded:
                checkbox_text = f"{chapter_num}: {chapter_name} ✓"
                checkbox = QCheckBox(checkbox_text)
                checkbox.setStyleSheet("""
                    QCheckBox {
                        color: green;
                        font-weight: bold;
                    }
                    QCheckBox:checked {
                        color: #006400;
                        background-color: #e8f5e8;
                        border: 2px solid #228B22;
                        border-radius: 3px;
                        padding: 2px;
                    }
                    QCheckBox::indicator:checked {
                        background-color: #228B22;
                        border: 2px solid #006400;
                    }
                """)
            else:
                checkbox_text = f"{chapter_num}: {chapter_name}"
                checkbox = QCheckBox(checkbox_text)
                checkbox.setStyleSheet("""
                    QCheckBox:checked {
                        background-color: #e8f0ff;
                        border: 2px solid #4285f4;
                        border-radius: 3px;
                        padding: 2px;
                    }
                    QCheckBox::indicator:checked {
                        background-color: #4285f4;
                        border: 2px solid #1a73e8;
                    }
                """)
            
            checkbox.setProperty("chapter_num", chapter_num)
            checkbox.setProperty("is_downloaded", is_downloaded)
            checkbox.stateChanged.connect(self._update_selection_count)
            self.chapter_checkboxes.append(checkbox)
            
            row = i // columns
            col = i % columns
            scroll_layout.addWidget(checkbox, row, col)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        button_layout = QHBoxLayout()
        
        self.ok_btn = QPushButton("Download Selected")
        self.cancel_btn = QPushButton("Cancel")
        
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
        self._update_selection_count()
    

    
    def _update_selection_count(self):
        """Update the dialog title with selection count."""
        selected_count = sum(1 for cb in self.chapter_checkboxes if cb.isChecked())
        total_count = len(self.chapter_checkboxes)
        self.setWindowTitle(f"Select Chapters - {self.manga_name} ({selected_count}/{total_count} selected)")
    
    def apply_range(self):
        """Apply chapter range selection."""
        from_ch = self.range_from_spin.value()
        to_ch = self.range_to_spin.value()
        
        for checkbox in self.chapter_checkboxes:
            try:
                chapter_num = float(checkbox.property("chapter_num"))
                if from_ch <= chapter_num <= to_ch:
                    checkbox.setChecked(True)
                else:
                    checkbox.setChecked(False)
            except (ValueError, TypeError):
                continue
        
        self._update_selection_count()
    
    def get_selected_chapters(self) -> List[str]:
        """Get list of selected chapter numbers."""
        selected = []
        
        if self.is_enhanced and hasattr(self, 'chapter_tree'):
            for chapter, (item, checkbox) in self.chapter_items.items():
                if checkbox.isChecked():
                    if ChapterInfo and isinstance(chapter, ChapterInfo):
                        selected.append(chapter)
                    else:
                        selected.append(str(chapter))
        else:
            for checkbox in self.chapter_checkboxes:
                if checkbox.isChecked():
                    chapter_num = checkbox.property("chapter_num")
                    if chapter_num:
                        selected.append(str(chapter_num))
        
        return selected
    
    def get_selected_language(self) -> str:
        """Get currently selected language."""
        if self.is_enhanced and hasattr(self, 'current_language'):
            return self.current_language
        return 'en'  
    
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
                if not self.cover_url:
                    self.cover_label.setText("No cover\navailable")
                    return
                    
                response = requests.get(self.cover_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                response.raise_for_status()
                
                pixmap = QPixmap()
                if pixmap.loadFromData(response.content):
                    scaled_pixmap = pixmap.scaled(self.cover_label.size())
                    self.cover_label.setPixmap(scaled_pixmap)
                else:
                    self.cover_label.setText("Invalid\nimage")
                
            except Exception as e:
                self.cover_label.setText("Cover not\navailable")
                print(f"Cover image load error: {e}")
        
        thread = Thread(target=load_image, daemon=True)
        thread.start()
    
    def on_language_filter_changed(self):
        """Handle language filter changes."""
        if not hasattr(self, 'language_checkboxes'):
            return
            
        if self.show_all_langs.isChecked():
            for checkbox in self.language_checkboxes.values():
                checkbox.setEnabled(False)
                checkbox.setChecked(True)
            self.language_filter = []
        else:
            for checkbox in self.language_checkboxes.values():
                checkbox.setEnabled(True)
            
            self.language_filter = [
                lang_code for lang_code, checkbox in self.language_checkboxes.items()
                if checkbox.isChecked()
            ]
        
        self.load_chapters()
    
    def load_chapters(self):
        """Load chapters with language filtering and volume organization."""
        if not self.is_enhanced:
            return
            
        logger.info(f"Loading chapters - Has language features: {self.has_language_features}")
        logger.info(f"Chapters by language: {len(self.chapters_by_language)} languages")
        logger.info(f"Simple chapters: {len(self.chapters)} chapters")
            
        self.chapter_tree.clear()
        self.chapter_items.clear()
        
        if self.has_language_features and self.chapters_by_language:
            all_chapters = []
            languages_to_show = []
            
            if not self.language_filter:
                languages_to_show = []
                for lang_item in self.available_languages:
                    if isinstance(lang_item, (list, tuple)) and len(lang_item) >= 1:
                        languages_to_show.append(lang_item[0])
                    else:
                        languages_to_show.append(str(lang_item))
            else:
                languages_to_show = self.language_filter
            
            for lang_code in languages_to_show:
                chapters = self.chapters_by_language.get(lang_code, [])
                for chapter in chapters:
                    all_chapters.append((lang_code, chapter))
            
            if all_chapters:
                self.load_enhanced_chapters_tree(all_chapters)
        else:
            self.load_simple_chapters_in_tree()
        
        self.update_stats()
        self.update_selection_count()

    def load_enhanced_chapters_tree(self, chapters_with_lang):
        """Load ChapterInfo objects with volume and language grouping in tree structure."""
        volumes = {}
        
        for lang_code, chapter in chapters_with_lang:
            if not (ChapterInfo and isinstance(chapter, ChapterInfo)):
                continue
                
            vol_key = getattr(chapter, 'volume_number', '') or "No Volume"
            if vol_key not in volumes:
                volumes[vol_key] = {}
            if lang_code not in volumes[vol_key]:
                volumes[vol_key][lang_code] = []
            volumes[vol_key][lang_code].append(chapter)
        
        sorted_vols = sorted(volumes.keys(), key=lambda x: (x == "No Volume", float(x) if x.replace('.', '').isdigit() else float('inf')))
        
        for vol_key in sorted_vols:
            vol_item = QTreeWidgetItem(self.chapter_tree)
            vol_text = f"📁 Volume {vol_key}" if vol_key != "No Volume" else "📁 No Volume"
            vol_item.setText(0, vol_text)
            vol_item.setExpanded(True)
            
            for lang_code in sorted(volumes[vol_key].keys()):
                lang_chapters = volumes[vol_key][lang_code]
                
                lang_chapters.sort(key=lambda c: float(getattr(c, 'chapter_number', '0')) if getattr(c, 'chapter_number', '0').replace('.', '').isdigit() else float('inf'))
                
                for chapter in lang_chapters:
                    chapter_item = QTreeWidgetItem(vol_item)
                    
                    ch_num = getattr(chapter, 'chapter_number', '')
                    title = getattr(chapter, 'title', '')
                    group = (
                        getattr(chapter, 'scanlation_group', '') or 
                        getattr(chapter, 'translator', '') or 
                        getattr(chapter, 'group', '') or 
                        getattr(chapter, 'uploader', '') or
                        'Unknown Group'
                    )
                    lang_name = self.get_language_display_name(lang_code)
                    
                    display_text = f"[{lang_code.upper()}] Ch.{ch_num}"
                    if title:
                        display_text += f": {title}"
                    
                    chapter_item.setText(0, display_text)
                    chapter_item.setText(1, lang_name)
                    chapter_item.setText(2, vol_key if vol_key != "No Volume" else "")
                    chapter_item.setText(3, group or "")
                    
                    checkbox = QCheckBox()
                    from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
                    container = QWidget()
                    layout = QHBoxLayout(container)
                    layout.setContentsMargins(2, 0, 2, 0)
                    layout.addWidget(checkbox)
                    label = QLabel(display_text)
                    layout.addWidget(label)
                    layout.addStretch()
                    
                    chapter_item.setText(0, "")
                    self.chapter_tree.setItemWidget(chapter_item, 0, container)
                    
                    checkbox.chapter_data = chapter
                    checkbox.stateChanged.connect(self.update_selection_count)
                    self.chapter_items[chapter] = (chapter_item, checkbox)
    
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
                    display_parts.append(f"{ch_num}")
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
                self.chapter_items[chapter] = (item, checkbox)
    
    def load_simple_chapters_in_tree(self):
        """Load simple chapter tuples in tree format for standard sites."""
        if not self.chapters:
            return
            
        logger.info(f"Loading {len(self.chapters)} simple chapters")
        logger.info(f"First chapter sample: {self.chapters[0] if self.chapters else 'None'}")
            
        volumes = {"Chapters": []}
        
        for chapter_data in self.chapters:
            if isinstance(chapter_data, (list, tuple)) and len(chapter_data) >= 3:
                volumes["Chapters"].append(chapter_data)
            elif ChapterInfo and isinstance(chapter_data, ChapterInfo):
                vol_key = getattr(chapter_data, 'volume_number', '') or "Chapters"
                if vol_key not in volumes:
                    volumes[vol_key] = []
                volumes[vol_key].append(chapter_data)
        
        sorted_vols = sorted(volumes.keys(), key=lambda x: (x == "Chapters", x))
        
        for vol_key in sorted_vols:
            vol_chapters = volumes[vol_key]
            
            vol_item = QTreeWidgetItem(self.chapter_tree)
            vol_text = f"📁 Volume {vol_key}" if vol_key != "Chapters" else "📁 All Chapters"
            vol_item.setText(0, vol_text)
            vol_item.setExpanded(True)
            
            if vol_chapters and ChapterInfo and isinstance(vol_chapters[0], ChapterInfo):
                vol_chapters.sort(key=lambda c: float(getattr(c, 'chapter_number', '0')) if getattr(c, 'chapter_number', '0').replace('.', '').isdigit() else float('inf'))
            else:
                vol_chapters.sort(key=lambda c: float(c[0]) if isinstance(c, (list, tuple)) and str(c[0]).replace('.', '').isdigit() else float('inf'))
            
            for chapter in vol_chapters:
                chapter_item = QTreeWidgetItem(vol_item)
                
                if ChapterInfo and isinstance(chapter, ChapterInfo):
                    ch_num = getattr(chapter, 'chapter_number', '')
                    title = getattr(chapter, 'title', '')
                    group = getattr(chapter, 'scanlation_group', '') or getattr(chapter, 'translator', '')
                    
                    display_text = f"Ch.{ch_num}"
                    if title:
                        display_text += f": {title}"
                    
                    chapter_item.setText(0, display_text)
                    chapter_item.setText(1, "English")  # Default language for ChapterInfo
                    chapter_item.setText(2, vol_key if vol_key != "Chapters" else "")
                    chapter_item.setText(3, group or "Unknown")
                else:
                    ch_num, ch_name, ch_url = chapter[:3]
                    is_downloaded = len(chapter) >= 4 and chapter[3]
                    
                    display_text = f"Ch.{ch_num}: {ch_name}"
                    if is_downloaded:
                        display_text += " ✓"
                    
                    chapter_item.setText(0, display_text)
                    chapter_item.setText(1, "English")  # Default language for standard sites
                    chapter_item.setText(2, vol_key if vol_key != "Chapters" else "")
                    chapter_item.setText(3, "Standard")  # Default group for standard sites
                
                checkbox = QCheckBox()
                if isinstance(chapter, (list, tuple)):
                    if len(chapter) >= 4 and chapter[3]:
                        checkbox.setStyleSheet("QCheckBox { color: green; font-weight: bold; }")
                
                from PyQt5.QtWidgets import QWidget as QW, QHBoxLayout as QHL, QLabel as QL
                container = QW()
                layout = QHL(container)
                layout.setContentsMargins(2, 0, 2, 0)
                layout.addWidget(checkbox)
                
                current_text = chapter_item.text(0)
                label = QL(current_text)
                layout.addWidget(label)
                layout.addStretch()
                
                chapter_item.setText(0, "")
                self.chapter_tree.setItemWidget(chapter_item, 0, container)
                
                checkbox.chapter_data = chapter
                checkbox.stateChanged.connect(self.update_selection_count)
                self.chapter_items[chapter] = (chapter_item, checkbox)
    
    def load_simple_chapters_in_list(self, chapters):
        """Load simple chapter tuples in list widget."""
        for chapter_data in chapters:
            if isinstance(chapter_data, (list, tuple)) and len(chapter_data) >= 3:
                ch_num, ch_name, ch_url = chapter_data[:3]
                is_downloaded = len(chapter_data) >= 4 and chapter_data[3]
                
                item = QListWidgetItem()
                checkbox = QCheckBox()
                
                display_text = f"{ch_num}: {ch_name}"
                if is_downloaded:
                    display_text += " ✓"
                    checkbox.setStyleSheet("color: green; font-weight: bold;")
                
                checkbox.setText(display_text)
                checkbox.stateChanged.connect(self.update_selection_count)
                checkbox.chapter_data = chapter_data
                
                self.chapter_list.addItem(item)
                self.chapter_list.setItemWidget(item, checkbox)
                self.chapter_items[chapter_data] = (item, checkbox)
    
    def update_stats(self):
        """Update statistics display."""
        if not self.is_enhanced or not hasattr(self, 'stats_label'):
            return
        
        total = len(self.chapter_items)
        stats_text = ""
        
        if self.has_language_features and self.available_languages:
            visible_languages = []
            
            if not self.language_filter:
                for lang_item in self.available_languages:
                    if isinstance(lang_item, (list, tuple)) and len(lang_item) >= 1:
                        visible_languages.append(lang_item[0])
                    else:
                        visible_languages.append(str(lang_item))
            else:
                visible_languages = self.language_filter
            
            stats_text = f"Filtered Languages: {', '.join(visible_languages)}\n"
        
        stats_text += f"Total Chapters: {total}"
        
        if self.chapter_items:
            volumes = set()
            groups = set()
            
            for chapter in self.chapter_items.keys():
                if ChapterInfo and isinstance(chapter, ChapterInfo):
                    vol = getattr(chapter, 'volume_number', '')
                    if vol:
                        volumes.add(vol)
                    group = getattr(chapter, 'scanlation_group', '') or getattr(chapter, 'translator', '')
                    if group:
                        groups.add(group)
                elif isinstance(chapter, (list, tuple)) and len(chapter) >= 4:
                    pass
            
            if volumes:
                stats_text += f"\nVolumes: {len(volumes)}"
            if groups:
                stats_text += f"\nGroups: {len(groups)}"
        
        self.stats_label.setText(stats_text)
    
    def select_range(self):
        """Show range selection dialog for enhanced mode."""
        if not self.is_enhanced:
            return
            
        from PyQt5.QtWidgets import QInputDialog
        
        chapters = self.chapters_by_language.get(self.current_language, [])
        if not chapters:
            return
        
        ch_numbers = []
        if chapters and ChapterInfo and isinstance(chapters[0], ChapterInfo):
            ch_numbers = [float(getattr(ch, 'chapter_number', '0')) for ch in chapters if getattr(ch, 'chapter_number', '0').replace('.', '').isdigit()]
        else:
            ch_numbers = [float(ch[0]) for ch in chapters if isinstance(ch, (list, tuple)) and len(ch) > 0 and str(ch[0]).replace('.', '').isdigit()]
        
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
        
        for chapter, (item, checkbox) in self.chapter_items.items():
            if ChapterInfo and isinstance(chapter, ChapterInfo):
                ch_num_str = getattr(chapter, 'chapter_number', '0')
            else:
                continue
            
            try:
                ch_num = float(ch_num_str)
                if start <= ch_num <= end:
                    checkbox.setChecked(True)
                else:
                    checkbox.setChecked(False)
            except ValueError:
                continue
    
    def update_selection_count(self):
        """Update button text with selection count."""
        if self.is_enhanced and hasattr(self, 'chapter_tree'):
            selected_count = sum(1 for _, (_, checkbox) in self.chapter_items.items() if checkbox.isChecked())
            
            if hasattr(self, 'ok_btn'):
                self.ok_btn.setText(f"Download Selected ({selected_count})")
        else:
            self._update_selection_count()
    
    def select_all(self):
        """Select all visible chapters."""
        selected_count = 0
        if self.is_enhanced and hasattr(self, 'chapter_tree'):
            for _, (_, checkbox) in self.chapter_items.items():
                checkbox.setChecked(True)
                selected_count += 1
        else:
            for checkbox in self.chapter_checkboxes:
                checkbox.setChecked(True)
                selected_count += 1
        
        self.show_toast(f"Selected all {selected_count} chapters")
        logger.info(f"Selected all {selected_count} chapters")
    
    def clear_all(self):
        """Clear all chapter selections."""
        if self.is_enhanced and hasattr(self, 'chapter_tree'):
            for _, (_, checkbox) in self.chapter_items.items():
                checkbox.setChecked(False)
        else:
            for checkbox in self.chapter_checkboxes:
                checkbox.setChecked(False)
        self.show_toast("All selections cleared")
        logger.info("All chapter selections cleared")
    
    def select_downloaded(self):
        """Select only downloaded chapters."""
        selected_count = 0
        if self.is_enhanced and hasattr(self, 'chapter_tree'):
            for chapter_info, (_, checkbox) in self.chapter_items.items():
                is_downloaded = False
                if hasattr(chapter_info, 'is_downloaded'):
                    is_downloaded = chapter_info.is_downloaded
                
                if is_downloaded:
                    checkbox.setChecked(True)
                    selected_count += 1
                else:
                    checkbox.setChecked(False)
        else:
            for i, checkbox in enumerate(self.chapter_checkboxes):
                is_downloaded = False
                if i < len(self.chapters):
                    if len(self.chapters[i]) > 3:
                        is_downloaded = bool(self.chapters[i][3])
                
                if is_downloaded:
                    checkbox.setChecked(True)
                    selected_count += 1
                else:
                    checkbox.setChecked(False)
        
        self.show_toast(f"Selected {selected_count} downloaded chapters")
        logger.info(f"Selected {selected_count} downloaded chapters")
    
    def select_not_downloaded(self):
        """Select only chapters that haven't been downloaded."""
        selected_count = 0
        if self.is_enhanced and hasattr(self, 'chapter_tree'):
            for chapter_info, (_, checkbox) in self.chapter_items.items():
                is_downloaded = False
                if hasattr(chapter_info, 'is_downloaded'):
                    is_downloaded = chapter_info.is_downloaded
                
                if not is_downloaded:
                    checkbox.setChecked(True)
                    selected_count += 1
                else:
                    checkbox.setChecked(False)
        else:
            for i, checkbox in enumerate(self.chapter_checkboxes):
                is_downloaded = False
                if i < len(self.chapters):
                    if len(self.chapters[i]) > 3:
                        is_downloaded = bool(self.chapters[i][3])
                
                if not is_downloaded:
                    checkbox.setChecked(True)
                    selected_count += 1
                else:
                    checkbox.setChecked(False)
        
        self.show_toast(f"Selected {selected_count} undownloaded chapters")
        logger.info(f"Selected {selected_count} undownloaded chapters")
    
    def show_toast(self, message: str):
        """Show a toast notification."""
        try:
            if Toast and hasattr(self, 'parent') and self.parent():
                toast = Toast(self.parent())
                toast.show_message(message)
            elif Toast:
                toast = Toast(self)
                toast.show_message(message)
            else:
                logger.info(f"Toast notification: {message}")
        except Exception as e:
            logger.warning(f"Failed to show toast notification: {e}")