"""
Main application window for the Manga Downloader.
"""

import sys
import os
import re
import logging
from typing import Optional

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QLineEdit, QPushButton, QStackedWidget,
                            QApplication, QSplitter, QMessageBox, QFileDialog,
                            QListWidget, QListWidgetItem, QScrollArea, QGroupBox,
                            QCheckBox, QGridLayout, QColorDialog)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QCloseEvent, QColor

try:
    from .widgets.sidebar import Sidebar
    from .widgets.toast import Toast
    from .widgets.download_item import DownloadItemWidget
    from .widgets.chapter_viewer import ChapterViewer
    from .widgets.history_item import HistoryItemWidget
    from .dialogs.chapter_selection import ChapterSelectionDialog
    from .dialogs.mangadex_chapter_selection import MangaDexChapterSelectionDialog

    from ..managers.download_manager import DownloadManager, DownloadSignals
    from ..managers.database_manager import DatabaseManager
    from ..managers.settings_manager import SettingsManager
    from ..managers.metadata_manager import MetadataManager
    from ..managers.history_manager import HistoryManager
    from ..sites.mangadex import MangaDexDownloader
    from ..sites.base import ChapterInfo
except ImportError:
    gui_dir = os.path.dirname(__file__)
    parent_dir = os.path.dirname(gui_dir)
    sys.path.append(parent_dir)
    sys.path.append(gui_dir)
    from widgets.sidebar import Sidebar
    from widgets.toast import Toast
    from widgets.download_item import DownloadItemWidget
    from widgets.chapter_viewer import ChapterViewer
    from widgets.history_item import HistoryItemWidget
    try:
        from dialogs.chapter_selection import ChapterSelectionDialog
        from src.gui.dialogs.mangadex_chapter_selection import MangaDexChapterSelectionDialog
    except ImportError:
        ChapterSelectionDialog = None


    from managers.download_manager import DownloadManager, DownloadSignals
    from managers.database_manager import DatabaseManager
    from managers.settings_manager import SettingsManager
    from managers.metadata_manager import MetadataManager
    from managers.history_manager import HistoryManager
    try:
        from sites.mangadex import MangaDexDownloader
        from sites.base import ChapterInfo
    except ImportError:
        MangaDexDownloader = None
        ChapterInfo = None


class MangaDownloaderApp(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        self.signals = DownloadSignals()
        self.settings_manager = SettingsManager()
        self.download_manager = DownloadManager(self.signals, self.settings_manager)
        self.db_manager = DatabaseManager()
        self.metadata_manager = MetadataManager(self.download_manager)
        self.history_manager = HistoryManager()
        
        self.init_ui()
        self.connect_signals()
        self.load_settings()
        
        self.toast = Toast(self, self.settings_manager)
        
        self.perform_startup_sync()
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Manga Downloader")
        self.setMinimumSize(1000, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.sidebar = Sidebar()
        main_layout.addWidget(self.sidebar)
        
        self.main_splitter = QSplitter()
        main_layout.addWidget(self.main_splitter, 1)
        
        self.stacked_widget = QStackedWidget()
        self.main_splitter.addWidget(self.stacked_widget)
        
        self.chapter_viewer = ChapterViewer()
        self.main_splitter.addWidget(self.chapter_viewer)
        self.chapter_viewer.setVisible(False)
        
        self.chapter_viewer.selection_changed.connect(self.update_download_chapters_button)
        
        self.main_splitter.setSizes([600, 400])
        
        self.create_download_page()
        self.create_history_page()
        self.create_settings_page()
        
        self.stacked_widget.setCurrentIndex(0)
        
    def create_download_page(self):
        """Create the download page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        
        title = QLabel("Download Manga")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        path_layout = QHBoxLayout()
        
        self.download_path_input = QLineEdit()
        self.download_path_input.setText(self.settings_manager.get_download_path())
        self.download_path_input.textChanged.connect(self.on_download_path_changed)
        
        self.browse_download_btn = QPushButton("Browse")
        self.browse_download_btn.clicked.connect(self.browse_for_download_path)
        
        path_layout.addWidget(QLabel("Download Path:"))
        path_layout.addWidget(self.download_path_input)
        path_layout.addWidget(self.browse_download_btn)
        
        layout.addLayout(path_layout)
        
        url_layout = QHBoxLayout()
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter manga URL (AsuraComics, MangaKatana, or Webtoon)")
        self.url_input.returnPressed.connect(self.start_download)
        
        self.download_btn = QPushButton("Download")
        self.download_btn.clicked.connect(self.start_download)
        
        url_layout.addWidget(QLabel("URL:"))
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.download_btn)
        
        layout.addLayout(url_layout)
        
        queue_label = QLabel("Download Queue")
        queue_label.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(queue_label)
        
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        self.queue_layout = QVBoxLayout(scroll_widget)
        self.queue_layout.setContentsMargins(5, 5, 5, 5)
        self.queue_layout.setSpacing(5)
        self.queue_layout.addStretch()
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(200)
        layout.addWidget(scroll_area)
        
        self.download_items = {}
        
        control_layout = QHBoxLayout()
        
        self.clear_completed_btn = QPushButton("Clear Completed")
        self.clear_completed_btn.clicked.connect(self.clear_completed_downloads)
        
        control_layout.addWidget(self.clear_completed_btn)
        control_layout.addStretch()
        
        layout.addLayout(control_layout)
        
        self.stacked_widget.addWidget(page)
    
    def create_history_page(self):
        """Create the enhanced history page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        
        header_layout = QHBoxLayout()
        
        title = QLabel("Download History")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        
        self.scan_all_btn = QPushButton("Scan All Library")
        self.scan_all_btn.clicked.connect(self.scan_all_manga)
        self.scan_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        
        self.download_all_new_btn = QPushButton("Download All New")
        self.download_all_new_btn.clicked.connect(self.download_all_new)
        self.download_all_new_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        
        self.download_chapters_btn = QPushButton("Download Chapters")
        self.download_chapters_btn.clicked.connect(self.download_selected_chapters)
        self.download_chapters_btn.setEnabled(False)
        self.download_chapters_btn.setStyleSheet("""
            QPushButton {
                background-color: #17a2b8;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #138496;
            }
            QPushButton:disabled {
                background-color: #6c757d;
                color: #adb5bd;
            }
        """)
        
        self.refresh_metadata_btn = QPushButton("Refresh Metadata")
        self.refresh_metadata_btn.clicked.connect(self.refresh_all_metadata)
        self.refresh_metadata_btn.setStyleSheet("""
            QPushButton {
                background-color: #6f42c1;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a359a;
            }
        """)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.scan_all_btn)
        header_layout.addWidget(self.download_all_new_btn)
        header_layout.addWidget(self.download_chapters_btn)
        header_layout.addWidget(self.refresh_metadata_btn)
        
        layout.addLayout(header_layout)
        
        history_scroll = QScrollArea()
        history_widget = QWidget()
        self.history_layout = QVBoxLayout(history_widget)
        self.history_layout.setContentsMargins(5, 5, 5, 5)
        self.history_layout.setSpacing(3)
        self.history_layout.addStretch()
        
        history_scroll.setWidget(history_widget)
        history_scroll.setWidgetResizable(True)
        from PyQt5.QtCore import Qt
        history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # type: ignore
        history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore
        
        layout.addWidget(history_scroll, 1)
        
        self.history_items = {}
        
        self.stacked_widget.addWidget(page)
    
    def create_settings_page(self):
        """Create the settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        
        title = QLabel("Settings")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(title)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        path_group = QGroupBox("Download Settings")
        path_group_layout = QVBoxLayout(path_group)
        
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setText(self.settings_manager.get_download_path())
        self.path_input.textChanged.connect(self.on_path_changed)
        
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_for_path)
        
        path_layout.addWidget(QLabel("Download Path:"))
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(self.browse_btn)
        path_group_layout.addLayout(path_layout)
        
        scroll_layout.addWidget(path_group)
        
        debug_group = QGroupBox("Debug Settings")
        debug_group_layout = QVBoxLayout(debug_group)
        
        self.debug_mode_checkbox = QCheckBox("Enable Debug Mode")
        self.debug_mode_checkbox.setChecked(self.settings_manager.is_debug_mode())
        self.debug_mode_checkbox.toggled.connect(self.on_debug_mode_changed)
        
        debug_info = QLabel("When enabled, detailed logs will be saved to manga_download.log")
        debug_info.setStyleSheet("color: #666; font-size: 10px;")
        debug_info.setWordWrap(True)
        
        debug_group_layout.addWidget(self.debug_mode_checkbox)
        debug_group_layout.addWidget(debug_info)
        
        scroll_layout.addWidget(debug_group)
        
        file_output_group = QGroupBox("File Output")
        file_output_layout = QVBoxLayout(file_output_group)
        
        self.save_cover_checkbox = QCheckBox("Save cover.png in manga folder")
        self.save_cover_checkbox.setChecked(self.settings_manager.get_save_cover())
        self.save_cover_checkbox.toggled.connect(self.on_save_cover_changed)
        
        self.save_comicinfo_checkbox = QCheckBox("Save ComicInfo.xml in manga folder")
        self.save_comicinfo_checkbox.setChecked(self.settings_manager.get_save_comicinfo())
        self.save_comicinfo_checkbox.toggled.connect(self.on_save_comicinfo_changed)
        
        self.save_series_json_checkbox = QCheckBox("Save series.json in manga folder")
        self.save_series_json_checkbox.setChecked(self.settings_manager.get_save_series_json())
        self.save_series_json_checkbox.toggled.connect(self.on_save_series_json_changed)
        
        self.embed_comicinfo_checkbox = QCheckBox("Embed ComicInfo.xml inside each chapter CBZ")
        self.embed_comicinfo_checkbox.setChecked(self.settings_manager.get_embed_comicinfo_in_cbz())
        self.embed_comicinfo_checkbox.toggled.connect(self.on_embed_comicinfo_changed)
        
        self.embed_cover_checkbox = QCheckBox("Embed cover.png inside each chapter CBZ")
        self.embed_cover_checkbox.setChecked(self.settings_manager.get_embed_cover_in_cbz())
        self.embed_cover_checkbox.toggled.connect(self.on_embed_cover_changed)
        
        fo_info = QLabel("Embedding adds files into new CBZ chapters only. Existing CBZ files are not modified.")
        fo_info.setStyleSheet("color: #666; font-size: 10px;")
        fo_info.setWordWrap(True)
        
        file_output_layout.addWidget(self.save_cover_checkbox)
        file_output_layout.addWidget(self.save_comicinfo_checkbox)
        file_output_layout.addWidget(self.save_series_json_checkbox)
        file_output_layout.addWidget(self.embed_comicinfo_checkbox)
        file_output_layout.addWidget(self.embed_cover_checkbox)
        file_output_layout.addWidget(fo_info)
        
        scroll_layout.addWidget(file_output_group)
        
        color_group = QGroupBox("Color Scheme")
        color_group_layout = QVBoxLayout(color_group)
        
        self.color_inputs = {}
        colors = self.settings_manager.get_color_scheme()
        
        color_descriptions = {
            'background_color': 'Background Color',
            'text_color': 'Text Color',
            'accent_color': 'Accent Color',
            'sidebar_color': 'Sidebar Color',
            'button_color': 'Button Color',
            'button_hover_color': 'Button Hover Color',
            'success_color': 'Success Color',
            'error_color': 'Error Color',
            'warning_color': 'Warning Color',
            'info_color': 'Info Color',
            'history_card_background': 'History Card Background',
            'history_card_border': 'History Card Border',
            'history_card_text': 'History Card Text',
            'history_card_subtitle': 'History Card Subtitle',
            'history_card_new_background': 'History Card (New) Background',
            'history_card_new_border': 'History Card (New) Border',
            'history_card_hover_background': 'History Card Hover Background',
            'chapter_viewer_background': 'Chapter Viewer Background',
            'chapter_viewer_border': 'Chapter Viewer Border',
            'chapter_viewer_text': 'Chapter Viewer Text',
            'chapter_viewer_success': 'Chapter Success Color',
            'chapter_viewer_error': 'Chapter Error Color',
            'chapter_viewer_pending': 'Chapter Pending Color',
            'chapter_viewer_new': 'Chapter New Color'
        }
        
        color_grid = QGridLayout()
        row = 0
        for color_key, description in color_descriptions.items():
            label = QLabel(description + ":")
            
            color_button = QPushButton()
            color_button.setFixedSize(60, 30)
            current_color = colors.get(color_key, '#000000')
            color_button.setStyleSheet(f"background-color: {current_color}; border: 1px solid #ccc;")
            color_button.clicked.connect(lambda checked, key=color_key, btn=color_button: self.on_color_pick(key, btn))
            
            color_input = QLineEdit(current_color)
            color_input.setMaximumWidth(80)
            color_input.textChanged.connect(lambda text, key=color_key, btn=color_button: self.on_color_input_changed(key, text, btn))
            
            self.color_inputs[color_key] = (color_button, color_input)
            
            color_grid.addWidget(label, row, 0)
            color_grid.addWidget(color_button, row, 1)
            color_grid.addWidget(color_input, row, 2)
            
            row += 1
        
        color_group_layout.addLayout(color_grid)
        
        color_buttons_layout = QHBoxLayout()
        
        reset_colors_btn = QPushButton("Reset to Default")
        reset_colors_btn.clicked.connect(self.on_reset_colors)
        
        apply_colors_btn = QPushButton("Apply Colors")
        apply_colors_btn.clicked.connect(self.on_apply_colors)
        
        color_buttons_layout.addWidget(reset_colors_btn)
        color_buttons_layout.addWidget(apply_colors_btn)
        color_buttons_layout.addStretch()
        
        color_group_layout.addLayout(color_buttons_layout)
        
        scroll_layout.addWidget(color_group)
        
        scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        
        self.stacked_widget.addWidget(page)
    
    def connect_signals(self):
        """Connect signals and slots."""
        self.sidebar.itemClicked.connect(self.on_sidebar_item_clicked)
        
        self.chapter_viewer.chapter_redownload_requested.connect(self.on_chapter_redownload_requested)
        
        self.signals.show_toast.connect(self.show_toast)
        self.signals.queue_updated.connect(self.update_queue_display)
        self.signals.manga_started.connect(self.on_manga_started)
        self.signals.manga_completed.connect(self.on_manga_completed)
        self.signals.manga_failed.connect(self.on_manga_failed)
        self.signals.chapter_started.connect(self.on_chapter_started)
        self.signals.chapter_completed.connect(self.on_chapter_completed)
        self.signals.chapter_failed.connect(self.on_chapter_failed)
        self.signals.chapter_progress.connect(self.on_chapter_progress)
        self.signals.manga_progress.connect(self.on_manga_progress)
        self.signals.download_paused.connect(self.on_download_paused)
        self.signals.download_resumed.connect(self.on_download_resumed)
        self.signals.metadata_updated.connect(self.on_metadata_updated)
        
    def load_settings(self):
        """Load application settings."""
        size = self.settings_manager.get_window_size()
        self.resize(size['width'], size['height'])
        
        pos = self.settings_manager.get_window_position()
        self.move(pos['x'], pos['y'])
        
        download_path = self.settings_manager.get_download_path()
        self.download_manager.set_download_path(download_path)
        
        self.populate_history_list()
        
        self.apply_color_scheme()
    
    def apply_color_scheme(self):
        """Apply the current color scheme to the UI."""
        colors = self.settings_manager.get_color_scheme()
        
        main_style = f"""
            QMainWindow {{
                background-color: {colors['background_color']};
                color: {colors['text_color']};
            }}
            QWidget {{
                background-color: {colors['background_color']};
                color: {colors['text_color']};
            }}
            QWidget#sidebar {{
                background-color: {colors['sidebar_color']} !important;
                border-right: 1px solid {colors['accent_color']} !important;
            }}
            Sidebar {{
                background-color: {colors['sidebar_color']} !important;
                border-right: 1px solid {colors['accent_color']} !important;
            }}
            QMainWindow QWidget#sidebar {{
                background-color: {colors['sidebar_color']} !important;
                border-right: 1px solid {colors['accent_color']} !important;
            }}
            QLabel {{
                color: {colors['text_color']};
            }}
            QPushButton {{
                background-color: {colors['button_color']};
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {colors['button_hover_color']};
            }}
            QPushButton:pressed {{
                background-color: {colors['button_hover_color']};
            }}
            QLineEdit {{
                background-color: white;
                color: black;
                border: 2px solid {colors['accent_color']};
                padding: 6px;
                border-radius: 4px;
            }}
            QLineEdit:focus {{
                border-color: {colors['accent_color']};
            }}
            QListWidget {{
                background-color: {colors['background_color']};
                color: {colors['text_color']};
                border: 1px solid {colors['accent_color']};
                border-radius: 4px;
            }}
            QListWidget::item {{
                border-bottom: 1px solid #ddd;
                padding: 8px;
            }}
            QListWidget::item:selected {{
                background-color: {colors['accent_color']};
                color: white;
            }}
            QGroupBox {{
                font-weight: bold;
                border: 2px solid {colors['accent_color']};
                border-radius: 5px;
                margin-top: 1ex;
                color: {colors['text_color']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: {colors['accent_color']};
            }}
            QCheckBox {{
                color: {colors['text_color']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {colors['accent_color']};
                border: 2px solid {colors['accent_color']};
            }}
            QScrollArea {{
                background-color: {colors['background_color']};
                border: none;
            }}
            QStackedWidget {{
                background-color: {colors['background_color']};
            }}
        """
        
        self.setStyleSheet(main_style)
        
        if hasattr(self, 'sidebar'):
            sidebar_override = f"""
                background-color: {colors['sidebar_color']} !important;
                border-right: 1px solid {colors['accent_color']} !important;
            """
            self.sidebar.setStyleSheet(sidebar_override)
            try:
                from PyQt5.QtGui import QPalette, QColor
                self.sidebar.setAutoFillBackground(True)
                palette = QPalette()
                palette.setColor(QPalette.Window, QColor(colors['sidebar_color']))
                self.sidebar.setPalette(palette)
            except:
                pass
        
        if hasattr(self, 'sidebar'):
            for button in [self.sidebar.download_btn, self.sidebar.history_btn, self.sidebar.settings_btn]:
                button.apply_colors(
                    text_color=colors['text_color'],
                    hover_color=colors['button_hover_color'], 
                    selected_color=colors['accent_color'],
                    selected_text_color='white'
                )
        
        if hasattr(self, 'toast'):
            pass
            
        self.apply_chapter_viewer_colors()
            
        if hasattr(self, 'history_items'):
            for item in self.history_items.values():
                item.apply_colors(
                    card_bg=colors['history_card_background'],
                    card_border=colors['history_card_border'],
                    card_text=colors['history_card_text'],
                    card_subtitle=colors['history_card_subtitle'],
                    card_new_bg=colors['history_card_new_background'],
                    card_new_border=colors['history_card_new_border'],
                    card_hover_bg=colors['history_card_hover_background'],
                    accent_color=colors['accent_color']
                )
    
    def on_sidebar_item_clicked(self, item: str):
        """Handle sidebar navigation."""
        pages = {
            "download": 0,
            "history": 1,
            "settings": 2
        }
        
        page_index = pages.get(item, 0)
        self.stacked_widget.setCurrentIndex(page_index)
        
        if item == "history":
            self.populate_history_list()
    
    def start_download(self):
        """Start downloading manga."""
        url = self.url_input.text().strip()
        if not url:
            self.show_toast("Please enter a manga URL", "warning")
            return
        
        is_valid, site_type = self.download_manager.validate_manga_url(url)
        if not is_valid:
            self.show_toast("Invalid URL or unsupported site", "error")
            return
        
        downloader = self.download_manager.downloaders[site_type]
        manga_name = downloader.get_manga_name(url)
        
        try:
            if site_type == 'mangadex' and MangaDexDownloader:
                self.handle_mangadex_download(url, downloader, manga_name)
            else:
                chapters = downloader.get_chapter_links(url)
                if not chapters:
                    self.show_toast("No chapters found", "error")
                    return
                
                if ChapterSelectionDialog:
                    dialog = ChapterSelectionDialog(
                        manga_name, 
                        chapters, 
                        self,
                        is_enhanced=True  # Use enhanced UI for all sites
                    )
                    if dialog.exec_() == dialog.Accepted:
                        selected_chapters = dialog.get_selected_chapters()
                        if selected_chapters:
                            chapter_status = {ch: "not_selected" for ch in chapters}
                            for ch in selected_chapters:
                                chapter_status[ch] = "queued"
                            self.chapter_viewer.set_manga(manga_name, url, chapters, chapter_status)
                            
                            selected_chapter_nums = [ch[0] for ch in selected_chapters]
                            success = self.download_manager.add_to_queue(url, selected_chapter_nums)
                            if success:
                                self.url_input.clear()
                else:
                    chapter_status = {ch: "queued" for ch in chapters}
                    self.chapter_viewer.set_manga(manga_name, url, chapters, chapter_status)
                    
                    chapter_nums = [ch[0] for ch in chapters]
                    success = self.download_manager.add_to_queue(url, chapter_nums)
                    if success:
                        self.url_input.clear()
                    
        except Exception as e:
            self.show_toast(f"Error getting chapters: {e}", "error")
    
    def handle_mangadex_download(self, url: str, downloader, manga_name: str):
        """Handle MangaDex-specific download with language selection."""
        try:
            metadata = downloader.get_manga_metadata(url)
            if metadata:
                metadata.site_type = 'mangadex'  # Ensure consistent site type
                metadata.url = url  # Ensure URL is set
                from datetime import datetime
                if not hasattr(metadata, 'first_download') or not metadata.first_download:
                    metadata.first_download = datetime.now().isoformat()
                if not hasattr(metadata, 'last_updated') or not metadata.last_updated:
                    metadata.last_updated = datetime.now().isoformat()
            cover_url = metadata.cover_image_url if metadata else ""
            manga_status = metadata.status if metadata else "unknown"
            
            logging.info(f"Manga metadata - Status: {manga_status}, Cover: {bool(cover_url)}")
            
            available_languages = downloader.get_available_languages(url)
            
            chapters_by_language = {}
            for lang_code, lang_name in available_languages:
                chapters = downloader.get_chapters_by_language(url, lang_code)
                if chapters:
                    chapters_by_language[lang_code] = chapters
            
            if not chapters_by_language:
                self.show_toast("No chapters found for any language", "error")
                return
            
            dialog = ChapterSelectionDialog(
                manga_name, 
                [],  # Empty chapters list for enhanced mode
                self,
                chapters_by_language=chapters_by_language,
                is_enhanced=True,
                metadata=metadata,
                cover_url=cover_url,
                languages=available_languages
            )
            
            if dialog.exec_() == dialog.Accepted:
                selected_chapters = dialog.get_selected_chapters()
                selected_language = dialog.get_selected_language()
                
                try:
                    from ..managers.database_manager import ChapterData, MangaMetadata as DBMetadata
                    
                    cover_image_path = ""
                    if cover_url:
                        cover_image_path = self.download_manager.download_cover_image(cover_url, manga_name)
                    
                    db_metadata = DBMetadata(
                        title=manga_name,
                        url=url,
                        site_type='mangadex',
                        description=metadata.description if metadata else "",
                        author=metadata.author if metadata else "",
                        genres=metadata.genres if metadata else [],
                        status=manga_status,
                        release_date=metadata.release_date if metadata else "",
                        alternative_names=metadata.alternative_names if metadata else [],
                        cover_image_url=cover_url,
                        language='en',  # Default to en, but we're storing all languages
                        translation_type='fan',
                        last_updated=datetime.now().isoformat(),
                        first_download=datetime.now().isoformat()
                    )
                    
                    manga_id = self.db_manager.add_or_update_manga(db_metadata, cover_image_path)
                    
                    total_chapters = 0
                    for lang_code, chapters in chapters_by_language.items():
                        for chapter in chapters:
                            if ChapterInfo and isinstance(chapter, ChapterInfo):
                                chapter_data = ChapterData(
                                    chapter_number=chapter.chapter_number,
                                    chapter_name=chapter.title or f"Chapter {chapter.chapter_number}",
                                    chapter_url=chapter.chapter_url or chapter.chapter_id,
                                    language=lang_code,
                                    volume_number=chapter.volume_number or "",
                                    is_downloaded=False
                                )
                                
                                self.db_manager.add_or_update_chapter(manga_id, chapter_data)
                                total_chapters += 1
                    
                    logging.info(f"Stored {total_chapters} chapters across {len(chapters_by_language)} languages in database for {manga_name}")
                    
                except Exception as e:
                    logging.error(f"Error storing MangaDex chapters in database: {e}")
                
                if selected_chapters:
                    self.show_toast(f"Adding {len(selected_chapters)} chapters to download queue...", "info")
                    
                    self.download_manager.set_chapter_context(selected_language, selected_chapters[0] if selected_chapters else None)
                    
                    chapter_numbers = []
                    for chapter in selected_chapters:
                        if ChapterInfo and isinstance(chapter, ChapterInfo):
                            chapter_numbers.append(chapter.chapter_number)
                        else:
                            chapter_numbers.append(str(chapter))
                    
                    success = self.download_manager.add_to_queue(url, chapter_numbers, metadata=metadata, language=selected_language)
                    
                    if success:
                        self.history_manager.add_manga(manga_name, url, 'mangadex')
                        logging.info(f"Added {manga_name} to history with status: {manga_status}")
                        
                        if manga_name in self.download_items:
                            download_item = self.download_items[manga_name]
                            if cover_url and hasattr(download_item, 'cover_path'):
                                download_item.cover_path = cover_url
                                download_item.load_cover_image()
                    if success:
                        self.url_input.clear()
                        self.show_toast(f"Added {manga_name} to download queue", "success")
                        
                        self.populate_history_list()
            
        except Exception as e:
            self.show_toast(f"Error processing MangaDex manga: {e}", "error")
    
    def populate_history_list(self):
        """Populate the history list with manga from database."""
        for item in list(self.history_items.values()):
            self.history_layout.removeWidget(item)
            item.deleteLater()
        self.history_items.clear()

        import re as _re
        _asura_suffix = _re.compile(
            r'[\s\-\u2013\u2014|]+asura\s*(scans?|comics?|toon|scan)?\s*$',
            _re.IGNORECASE
        )
        for _manga in self.db_manager.get_manga_list():
            if _manga.get('site_type', '') in ('asura', 'asuracomics'):
                _clean = _asura_suffix.sub('', _manga['title']).strip()
                if _clean and _clean != _manga['title']:
                    self.db_manager.rename_manga_title(_manga['id'], _clean)
                    logging.info(f"Renamed '{_manga['title']}' → '{_clean}' in DB")
        
        manga_list = self.db_manager.get_manga_list()
        
        for manga_data in manga_list:
            manga_id = manga_data.get('id')
            if manga_id:
                chapters = self.db_manager.get_chapters_for_manga(manga_id)
                if chapters:
                    self._sync_database_with_files(manga_data, chapters)
        
        manga_list.sort(key=lambda x: x.get('last_updated', ''), reverse=True)
        
        for manga_data in manga_list:
            manga_name = manga_data.get('title', 'Unknown')
            site_type = manga_data.get('site_type', 'unknown')
            manga_id = manga_data.get('id', 0)

            if self.metadata_manager.needs_metadata_update(manga_data):
                try:
                    QTimer.singleShot(100, lambda mid=manga_id: self._update_manga_metadata_async(mid))
                except Exception as e:
                    logging.warning(f"Could not schedule metadata update for {manga_name}: {e}")
            
            chapters = self.db_manager.get_chapters_for_manga(manga_id)
            unique_nums = set(ch['chapter_number'] for ch in chapters)
            total_chapters = len(unique_nums)
            downloaded_chapters = len(set(ch['chapter_number'] for ch in chapters if ch.get('is_downloaded', False)))
            
            last_update = manga_data.get('last_updated', 'Never')
            
            if last_update != 'Never':
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                    last_update = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
            
            description = manga_data.get('description', '')
            author = manga_data.get('author', '')
            genres = manga_data.get('genres', '')
            if isinstance(genres, str) and genres:
                try:
                    import json
                    genres = json.loads(genres)
                except:
                    genres = [genres] if genres else []
            elif not isinstance(genres, list):
                genres = []
            
            status = manga_data.get('status', 'unknown')
            cover_path = manga_data.get('cover_image_path', '')
            
            item = HistoryItemWidget(
                manga_name=manga_name,
                site_type=site_type,
                chapter_count=total_chapters,
                downloaded_count=downloaded_chapters,
                last_update=last_update,
                has_new_chapters=False,
                description=description,
                author=author,
                genres=genres,
                status=status,
                cover_path=cover_path
            )
            
            item.clicked.connect(self.on_history_item_clicked)
            item.scan_requested.connect(self.on_history_scan_requested)
            item.download_new_requested.connect(self.on_history_download_new_requested)
            item.delete_requested.connect(self.on_history_delete_requested)
            
            colors = self.settings_manager.get_color_scheme()
            item.apply_colors(
                card_bg=colors['history_card_background'],
                card_border=colors['history_card_border'],
                card_text=colors['history_card_text'],
                card_subtitle=colors['history_card_subtitle'],
                card_new_bg=colors['history_card_new_background'],
                card_new_border=colors['history_card_new_border'],
                card_hover_bg=colors['history_card_hover_background'],
                accent_color=colors['accent_color']
            )
            
            self.history_layout.insertWidget(self.history_layout.count() - 1, item)
            self.history_items[manga_name] = item
    
    def on_history_item_clicked(self, manga_name: str):
        """Handle history item click to show chapters."""
        manga_data = self.db_manager.get_manga_by_title(manga_name)
        if not manga_data:
            return
            
        manga_id = manga_data.get('id', 0)
        
        chapters = self.db_manager.get_chapters_for_manga(manga_id)
        
        chapter_list = []
        chapter_status = {}
        
        for chapter in chapters:
            chapter_num = chapter.get('chapter_number', '')
            chapter_name = chapter.get('chapter_name', f'Chapter {chapter_num}')
            chapter_url = chapter.get('chapter_url', '')
            
            chapter_tuple = (chapter_num, chapter_name, chapter_url)
            chapter_list.append(chapter_tuple)
            
            if chapter.get('is_downloaded', False):
                chapter_status[chapter_tuple] = "success"
            else:
                chapter_status[chapter_tuple] = "not_downloaded"
        
        try:
            chapter_list.sort(key=lambda x: float(x[0]) if x[0].replace('.', '', 1).isdigit() else 0)
        except:
            pass
        
        manga_url = manga_data.get('url', '')
        site_type = manga_data.get('site_type', '')
        
        chapters_by_language = None
        if site_type.lower() == 'mangadex':
            if len(chapters) == 0:
                logging.info(f"No chapters in database for {manga_name}, fetching from MangaDex API")
                try:
                    downloader = self.download_manager.downloaders.get('mangadex')
                    if downloader:
                        from ..managers.database_manager import ChapterData
                        languages = downloader.get_available_languages(manga_url)
                        chapters_by_language = {}
                        total_stored = 0
                        
                        for lang_code, lang_name in languages:
                            lang_chapters = downloader.get_chapters_by_language(manga_url, lang_code)
                            if lang_chapters:
                                chapters_by_language[lang_code] = lang_chapters
                                
                                for chapter in lang_chapters:
                                    if ChapterInfo and isinstance(chapter, ChapterInfo):
                                        chapter_data = ChapterData(
                                            chapter_number=chapter.chapter_number,
                                            chapter_name=chapter.title or f"Chapter {chapter.chapter_number}",
                                            chapter_url=chapter.chapter_url or chapter.chapter_id,
                                            language=lang_code,
                                            volume_number=chapter.volume_number or "",
                                            is_downloaded=False
                                        )
                                        self.db_manager.add_or_update_chapter(manga_id, chapter_data)
                                        total_stored += 1
                        
                        logging.info(f"Stored {total_stored} chapters in database for {manga_name}")
                        chapters = self.db_manager.get_chapters_for_manga(manga_id)
                        self.populate_history_list()
                        
                except Exception as e:
                    logging.error(f"Failed to fetch and store MangaDex chapters: {e}")
            
            if len(chapters) > 0:
                try:
                    chapters_by_language = {}
                    chapter_status = {}
                    
                    for chapter in chapters:
                        lang = chapter.get('language', 'en')
                        if lang not in chapters_by_language:
                            chapters_by_language[lang] = []
                        chapters_by_language[lang].append(chapter)
                        
                        chapter_num = chapter.get('chapter_number', '')
                        if chapter.get('is_downloaded', False):
                            chapter_status[chapter_num] = "success"
                        else:
                            chapter_status[chapter_num] = "not_downloaded"
                    
                    logging.info(f"Grouped {len(chapters)} chapters into {len(chapters_by_language)} languages for {manga_name}")
                    logging.info(f"Languages available: {list(chapters_by_language.keys())}")
                    for lang, lang_chapters in chapters_by_language.items():
                        logging.info(f"  {lang}: {len(lang_chapters)} chapters")
                except Exception as e:
                    logging.error(f"Failed to group chapters by language: {e}")
        
        if site_type.lower() == 'mangadex' and chapters_by_language:
            self.chapter_viewer.set_manga(manga_name, manga_url, [], chapter_status, site_type, chapters_by_language)
        else:
            self.chapter_viewer.set_manga(manga_name, manga_url, chapter_list, chapter_status, site_type, None)
        
        self.chapter_viewer.setVisible(True)
        self.apply_chapter_viewer_colors()
        
    def apply_chapter_viewer_colors(self):
        """Apply color scheme to chapter viewer."""
        if hasattr(self, 'chapter_viewer') and hasattr(self.chapter_viewer, 'apply_colors'):
            colors = self.settings_manager.get_color_scheme()
            self.chapter_viewer.apply_colors(
                background=colors['chapter_viewer_background'],
                border=colors['chapter_viewer_border'],
                text=colors['chapter_viewer_text'],
                success=colors['chapter_viewer_success'],
                error=colors['chapter_viewer_error'],
                pending=colors['chapter_viewer_pending'],
                new=colors['chapter_viewer_new']
            )
        
    def on_history_scan_requested(self, manga_name: str):
        """Handle scan request for specific manga."""
        if manga_name in self.history_items:
            item = self.history_items[manga_name]
            item.set_scanning(True)
            
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)
            
            def scan_manga():
                return self._scan_manga_for_updates(manga_name)
            
            future = executor.submit(scan_manga)
            
            def check_completion():
                if future.done():
                    try:
                        has_new_chapters = future.result()
                        self.on_scan_completed(manga_name, has_new_chapters)
                    except Exception as e:
                        logging.error(f"Error scanning {manga_name}: {e}")
                        self.on_scan_completed(manga_name, False)
                        self.show_toast(f"Error scanning {manga_name}: {e}", "error")
                else:
                    QTimer.singleShot(500, check_completion)
            
            QTimer.singleShot(500, check_completion)
            
    def on_history_download_new_requested(self, manga_name: str):
        """Handle download new request for manga."""
        try:
            manga_data = self.db_manager.get_manga_by_title(manga_name)
            if not manga_data or not manga_data.get('url'):
                self.show_toast(f"No URL found for {manga_name}", "error")
                return
            
            url = manga_data['url']
            manga_id = manga_data['id']
            
            all_chapters = self.db_manager.get_chapters_for_manga(manga_id)
            downloaded_count = len([ch for ch in all_chapters if ch['is_downloaded']])
            total_count = len(all_chapters)
            
            is_valid, site_type = self.download_manager.validate_manga_url(url)
            chapters_to_download = []
            action_text = ""
            redownload_mode = "missing_only"
            
            if site_type == 'webtoon':
                logging.info(f"Detected Webtoon URL for {manga_name}, showing language selection dialog")
                
                if ChapterSelectionDialog:
                    chapter_tuples = [(ch['chapter_number'], ch['chapter_name'], '', ch['is_downloaded']) for ch in all_chapters]
                    
                    dialog = ChapterSelectionDialog(manga_name, self, include_downloaded=True)
                    if dialog.exec_() == dialog.Accepted:
                        selected_chapter_nums = dialog.get_selected_chapters()
                        if not selected_chapter_nums:
                            self.show_toast("No chapters selected", "warning")
                            return
                        
                        for chapter_num in selected_chapter_nums:
                            chapter_data = next((ch for ch in all_chapters if ch['chapter_number'] == chapter_num), None)
                            if chapter_data and chapter_data['is_downloaded']:
                                self.db_manager.reset_chapter_download_status(manga_id, chapter_num)
                                logging.info(f"Reset download status for chapter: {chapter_num}")
                        
                        chapters_to_download = selected_chapter_nums
                        action_text = f"download selected {len(chapters_to_download)} chapters"
                        logging.info(f"Custom selection mode: {len(chapters_to_download)} chapters")
                    else:
                        return
                else:
                    undownloaded_chapters = [ch['chapter_number'] for ch in all_chapters if not ch['is_downloaded']]
                    chapters_to_download = undownloaded_chapters
                    action_text = f"download {len(chapters_to_download)} missing chapters"
                    logging.info(f"Missing only mode: {len(chapters_to_download)} chapters")
            else:
                if ChapterSelectionDialog:
                    chapter_tuples = [(ch['chapter_number'], ch['chapter_name'], '', ch['is_downloaded']) for ch in all_chapters]
                    
                    dialog = ChapterSelectionDialog(manga_name, self, include_downloaded=True)
                    if dialog.exec_() == dialog.Accepted:
                        selected_chapter_nums = dialog.get_selected_chapters()
                        if not selected_chapter_nums:
                            self.show_toast("No chapters selected", "warning")
                            return
                        
                        for chapter_num in selected_chapter_nums:
                            chapter_data = next((ch for ch in all_chapters if ch['chapter_number'] == chapter_num), None)
                            if chapter_data and chapter_data['is_downloaded']:
                                self.db_manager.reset_chapter_download_status(manga_id, chapter_num)
                                logging.info(f"Reset download status for chapter: {chapter_num}")
                        
                        chapters_to_download = selected_chapter_nums
                        action_text = f"download selected {len(chapters_to_download)} chapters"
                    else:
                        return
                else:
                    undownloaded_chapters = [ch['chapter_number'] for ch in all_chapters if not ch['is_downloaded']]
                    chapters_to_download = undownloaded_chapters
                    action_text = f"download {len(chapters_to_download)} missing chapters"
            
            if not chapters_to_download:
                if redownload_mode == "missing_only":
                    self.show_toast(f"No new chapters to download for {manga_name}", "info")
                else:
                    self.show_toast(f"No chapters found for {manga_name}", "info")
                return
            
            self.download_manager.queue_download(url, chapters_to_download)
            
            if redownload_mode == "missing_only" and manga_name in self.history_items:
                item = self.history_items[manga_name]
                item.set_has_new_chapters(False)
            
            self.stacked_widget.setCurrentIndex(0)
            
            self.show_toast(f"Queued to {action_text} for {manga_name}", "success")
            
        except Exception as e:
            logging.error(f"Error downloading chapters for {manga_name}: {e}")
            self.show_toast(f"Error downloading chapters: {e}", "error")
    
    def on_history_delete_requested(self, manga_name: str):
        """Handle delete request for manga."""
        from PyQt5.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self, 
            "Confirm Delete",
            f"Are you sure you want to remove '{manga_name}' from history?\n\nThis will not delete the downloaded files.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.db_manager.delete_manga(manga_name)
            
            if manga_name in self.history_items:
                item = self.history_items[manga_name]
                self.history_layout.removeWidget(item)
                item.deleteLater()
                del self.history_items[manga_name]
                
            self.show_toast(f"Removed {manga_name} from history", "info")
    
    def on_scan_completed(self, manga_name: str, has_new_chapters: bool):
        """Handle scan completion."""
        if manga_name in self.history_items:
            item = self.history_items[manga_name]
            item.set_scanning(False)
            item.set_has_new_chapters(has_new_chapters)
            
            try:
                manga_data = self.db_manager.get_manga_by_title(manga_name)
                if manga_data:
                    chapters = self.db_manager.get_chapters_for_manga(manga_data['id'])
                    total = len(set(ch['chapter_number'] for ch in chapters))
                    downloaded = len(set(ch['chapter_number'] for ch in chapters if ch.get('is_downloaded', False)))
                    item.update_info(chapter_count=total, downloaded_count=downloaded)
            except Exception as e:
                logging.warning(f"Could not refresh chapter count for {manga_name}: {e}")
            
            if has_new_chapters:
                self.show_toast(f"New chapters found for {manga_name}", "success")
    
    def _scan_manga_for_updates(self, manga_name: str) -> bool:
        """Scan a specific manga for updates. Returns True if new chapters found."""
        try:
            manga_data = self.db_manager.get_manga_by_title(manga_name)
            if not manga_data or not manga_data.get('url'):
                return False
            
            url = manga_data['url']
            manga_id = manga_data['id']
            
            downloader = self.download_manager.get_site_downloader(url)
            if not downloader:
                return False
            
            try:
                site_chapters = downloader.get_chapter_links(url)
            except Exception as e:
                logging.error(f"Error fetching chapters for {manga_name}: {e}")
                return False
            
            if not site_chapters:
                return False
            
            existing_chapters = self.db_manager.get_chapters_for_manga(manga_id)
            existing_chapter_nums = set(ch['chapter_number'] for ch in existing_chapters)
            
            new_chapters_found = False
            for chapter_num, chapter_name, chapter_url in site_chapters:
                if chapter_num not in existing_chapter_nums:
                    from ..managers.database_manager import ChapterData
                    chapter_data = ChapterData(
                        chapter_number=chapter_num,
                        chapter_name=chapter_name,
                        chapter_url=chapter_url,
                        language=manga_data.get('language', 'en'),
                        is_downloaded=False
                    )
                    self.db_manager.add_or_update_chapter(manga_id, chapter_data)
                    new_chapters_found = True
                    logging.info(f"Added new chapter {chapter_num} for {manga_name}")
            
            return new_chapters_found
            
        except Exception as e:
            logging.error(f"Error scanning {manga_name} for updates: {e}")
            return False
    
    def scan_all_manga(self):
        """Scan all manga for new chapters."""
        self.show_toast("Scanning all manga for updates...", "info")
        
        manga_list = self.db_manager.get_manga_list()
        manga_with_urls = [manga for manga in manga_list if manga.get('url')]
        
        if not manga_with_urls:
            self.show_toast("No manga with URLs found to scan", "info")
            return
        
        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=1)
        
        def scan_all():
            total_new_chapters = 0
            for manga in manga_with_urls:
                try:
                    has_new = self._scan_manga_for_updates(manga['title'])
                    if has_new:
                        total_new_chapters += 1
                        if manga['title'] in self.history_items:
                            QTimer.singleShot(0, lambda name=manga['title']: self.history_items[name].set_has_new_chapters(True))
                except Exception as e:
                    logging.error(f"Error scanning {manga['title']}: {e}")
            return total_new_chapters
        
        future = executor.submit(scan_all)
        
        def check_completion():
            if future.done():
                try:
                    total_new = future.result()
                    if total_new > 0:
                        self.show_toast(f"Scan complete! Found new chapters in {total_new} manga", "success")
                        self.populate_history_list()
                    else:
                        self.show_toast("Scan complete! No new chapters found", "info")
                except Exception as e:
                    self.show_toast(f"Error during scan: {e}", "error")
            else:
                QTimer.singleShot(1000, check_completion)
        
        QTimer.singleShot(1000, check_completion)
        
    def download_selected_chapters(self):
        """Download all selected chapters from the chapter viewer."""
        if not self.chapter_viewer.isVisible():
            self.show_toast("No manga selected. Click on a manga to view chapters.", "warning")
            return
            
        selected_chapters = self.chapter_viewer.get_selected_chapters()
        if not selected_chapters:
            self.show_toast("No chapters selected. Check the chapters you want to download.", "warning")
            return
            
        manga_name = self.chapter_viewer.current_manga_name
        current_url = self.chapter_viewer.current_manga_url
        if not manga_name or not current_url:
            self.show_toast("No manga selected.", "error")
            return
            
        self.show_toast(f"Starting download of {len(selected_chapters)} chapters from {manga_name}...", "info")
        
        chapter_list = []
        for chapter in selected_chapters:
            if isinstance(chapter, dict):
                chapter_list.append(
                    chapter.get('chapter_number', '') or
                    chapter.get('name', '') or
                    chapter.get('title', '')
                )
            elif hasattr(chapter, 'chapter_number'):
                chapter_list.append(chapter.chapter_number)
            else:
                chapter_list.append(str(chapter))
        
        language = getattr(self.chapter_viewer, 'current_language', 'en') or 'en'
        
        self.download_manager.add_to_queue(current_url, chapter_list, language=language)
        
        self.chapter_viewer.clear_selection()
        self.chapter_viewer.hide()
        
        self.update_queue_display()
    
    def update_download_chapters_button(self):
        """Enable/disable the Download Chapters button based on selection."""
        if hasattr(self, 'download_chapters_btn') and hasattr(self, 'chapter_viewer'):
            selected_count = len(self.chapter_viewer.get_selected_chapters()) if self.chapter_viewer.isVisible() else 0
            self.download_chapters_btn.setEnabled(selected_count > 0)
            if selected_count > 0:
                self.download_chapters_btn.setText(f"Download Chapters ({selected_count})")
            else:
                self.download_chapters_btn.setText("Download Chapters")
    
    def update_queue_display(self):
        """Update the download queue display."""
        for item in list(self.download_items.values()):
            self.queue_layout.removeWidget(item)
            item.deleteLater()
        self.download_items.clear()
        
        queue = self.download_manager.get_queue()
        for item in queue:
            manga_name = item['manga_name']
            manga_id = item.get('manga_id')
            
            site_type = item.get('site_type', '')
            description = ""
            author = ""
            genres = []
            status_text = "unknown"
            cover_path = ""
            
            if manga_id:
                manga_list = self.db_manager.get_manga_list()
                for manga_data in manga_list:
                    if manga_data['id'] == manga_id:
                        description = manga_data.get('description', '')
                        author = manga_data.get('author', '')
                        try:
                            import json
                            genres = json.loads(manga_data.get('genres', '[]')) if manga_data.get('genres') else []
                        except:
                            genres = []
                        status_text = manga_data.get('status', 'unknown')
                        
                        if manga_name == item.get('manga_name') and item.get('metadata'):
                            status_text = getattr(item['metadata'], 'status', 'unknown')
                        cover_path = manga_data.get('cover_image_path', '')
                        break
            
            if item.get('metadata') and hasattr(item['metadata'], 'status'):
                actual_status = item['metadata'].status
            else:
                actual_status = status_text
                
            download_widget = DownloadItemWidget(
                manga_name, 
                site_type=site_type,
                description=description,
                author=author,
                genres=genres,
                status_text=actual_status,
                cover_path=cover_path
            )
            current_downloading = getattr(self.download_manager, 'current_manga', None)
            effective_status = 'Downloading' if manga_name == current_downloading else item.get('status', 'Queued')
            download_widget.set_status(effective_status)
            
            if 'chapters' in item and item['chapters']:
                download_widget.set_total_chapters(len(item['chapters']))
            
            download_widget.clicked.connect(self.on_download_item_clicked)
            download_widget.pause_clicked.connect(self.on_download_pause_clicked)
            download_widget.cancel_clicked.connect(self.on_download_cancel_clicked)
            
            self.queue_layout.insertWidget(self.queue_layout.count() - 1, download_widget)
            self.download_items[manga_name] = download_widget
    
    def on_download_item_clicked(self):
        """Handle download item click to show details."""
        sender = self.sender()
        if sender and hasattr(sender, 'manga_name'):
            manga_name = sender.manga_name  # type: ignore
            self.show_download_details(manga_name)
    
    def on_download_pause_clicked(self, manga_name: str, is_paused: bool):
        """Handle pause button click."""
        if is_paused:
            self.download_manager.pause_download(manga_name)
        else:
            self.download_manager.resume_download(manga_name)
    
    def on_download_cancel_clicked(self, manga_name: str):
        """Handle cancel button click."""
        self.download_manager.cancel_download(manga_name)
    
    def show_download_details(self, manga_name):
        """Show chapter viewer for the downloading manga."""
        queue = self.download_manager.get_queue()
        for item in queue:
            if item['manga_name'] == manga_name:
                manga_id = item.get('manga_id')
                if manga_id:
                    chapters = self.db_manager.get_chapters_for_manga(manga_id, include_not_downloaded=True)
                    manga_data = None
                    manga_list = self.db_manager.get_manga_list()
                    for manga in manga_list:
                        if manga['id'] == manga_id:
                            manga_data = manga
                            break

                    if manga_data:
                        self._sync_database_with_files(manga_data, chapters)

                        if manga_name in self.download_items:
                            widget = self.download_items[manga_name]
                            queued_chapters = item.get('chapters', [])
                            if queued_chapters:
                                chapters = self.db_manager.get_chapters_for_manga(manga_id, include_not_downloaded=True)
                                queued_downloaded_count = sum(
                                    1 for ch in chapters
                                    if ch['chapter_number'] in queued_chapters and ch['is_downloaded']
                                )
                                widget.update_chapter_counts(queued_downloaded_count, len(queued_chapters))

                        self.on_history_item_clicked(manga_name)
                break
    
    def on_path_changed(self, path: str):
        """Handle download path change."""
        self.settings_manager.set_download_path(path)
        self.download_manager.set_download_path(path)
    
    def on_download_path_changed(self, path: str):
        """Handle download path change from download page."""
        self.settings_manager.set_download_path(path)
        self.download_manager.set_download_path(path)
    
    def browse_for_download_path(self):
        """Browse for download path from download page."""
        current_path = self.settings_manager.get_download_path()
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory", current_path)
        if path:
            self.download_path_input.setText(path)
    
    def browse_for_path(self):
        """Browse for download path."""
        current_path = self.settings_manager.get_download_path()
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory", current_path)
        if path:
            self.path_input.setText(path)
    
    def on_debug_mode_changed(self, enabled: bool):
        """Handle debug mode toggle."""
        self.settings_manager.set_debug_mode(enabled)
        if enabled:
            self.show_toast("Debug mode enabled. Logs will be saved to manga_download.log", "info")
        else:
            self.show_toast("Debug mode disabled", "info")

    def on_save_cover_changed(self, enabled: bool):
        self.settings_manager.set_save_cover(enabled)

    def on_save_comicinfo_changed(self, enabled: bool):
        self.settings_manager.set_save_comicinfo(enabled)

    def on_save_series_json_changed(self, enabled: bool):
        self.settings_manager.set_save_series_json(enabled)

    def on_embed_comicinfo_changed(self, enabled: bool):
        self.settings_manager.set_embed_comicinfo_in_cbz(enabled)

    def on_embed_cover_changed(self, enabled: bool):
        self.settings_manager.set_embed_cover_in_cbz(enabled)

    def on_color_pick(self, color_key: str, button: QPushButton):
        """Handle color picker button click."""
        current_color_hex = self.settings_manager.get_individual_color(color_key)
        current_color = QColor(current_color_hex)
        color = QColorDialog.getColor(current_color, self, f"Select {color_key.replace('_', ' ').title()}")
        
        if color.isValid():
            color_hex = color.name()
            button.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #ccc;")
            if color_key in self.color_inputs:
                _, input_field = self.color_inputs[color_key]
                input_field.setText(color_hex)
    
    def on_color_input_changed(self, color_key: str, color_value: str, button: QPushButton):
        """Handle manual color input change."""
        if color_value.startswith('#') and len(color_value) == 7:
            try:
                int(color_value[1:], 16)
                button.setStyleSheet(f"background-color: {color_value}; border: 1px solid #ccc;")
            except ValueError:
                current_color = self.settings_manager.get_individual_color(color_key)
                button.setStyleSheet(f"background-color: {current_color}; border: 1px solid #ccc;")
    
    def on_apply_colors(self):
        """Apply the current color scheme."""
        colors = {}
        for color_key, (button, input_field) in self.color_inputs.items():
            color_value = input_field.text()
            if color_value.startswith('#') and len(color_value) == 7:
                try:
                    int(color_value[1:], 16)
                    colors[color_key] = color_value
                except ValueError:
                    continue
        
        if colors:
            self.settings_manager.set_color_scheme(colors)
            self.apply_color_scheme()
            self.show_toast("Color scheme applied successfully!", "success")
        else:
            self.show_toast("No valid colors to apply", "warning")
    
    def on_reset_colors(self):
        """Reset color scheme to default."""
        self.settings_manager.reset_color_scheme_to_default()
        
        default_colors = self.settings_manager.get_color_scheme()
        for color_key, (button, input_field) in self.color_inputs.items():
            color_value = default_colors.get(color_key, '#000000')
            button.setStyleSheet(f"background-color: {color_value}; border: 1px solid #ccc;")
            input_field.setText(color_value)
        
        self.apply_color_scheme()
        self.show_toast("Color scheme reset to default", "info")
    
    def on_manga_started(self, manga_name: str):
        """Handle manga download started."""
        self.show_toast(f"Started downloading {manga_name}", "info")
        if manga_name in self.download_items:
            self.download_items[manga_name].set_status("Downloading")
    
    def on_manga_completed(self, manga_name: str):
        """Handle manga download completed."""
        self.show_toast(f"Completed downloading {manga_name}", "success")
        if manga_name in self.download_items:
            self.download_items[manga_name].set_status("Completed")
        
        try:
            manga_data = self.db_manager.get_manga_by_title(manga_name)
            if manga_data:
                manga_id = manga_data['id']
                self.download_manager._copy_cover_to_manga_folder(manga_name, manga_id)
                self.download_manager._create_metadata_files(manga_name, manga_id)
        except Exception as e:
            logging.error(f"Error creating cover/metadata files for {manga_name}: {e}")
        
        self.populate_history_list()
    
    def on_manga_failed(self, manga_name: str, reason: str):
        """Handle manga download failed."""
        self.show_toast(f"Failed to download {manga_name}: {reason}", "error")
        if manga_name in self.download_items:
            self.download_items[manga_name].set_status("Failed")
    
    def on_chapter_started(self, manga_name: str, chapter_num: str):
        """Handle chapter download started."""
        if manga_name in self.download_items:
            self.download_items[manga_name].set_status("Downloading")
            self.download_items[manga_name].set_current_chapter_info(f"Chapter {chapter_num}")
        
        if self.chapter_viewer.current_manga_name == manga_name:
            self.chapter_viewer.mark_chapter_downloading(chapter_num)
    
    def on_chapter_progress(self, manga_name: str, chapter_num: str, progress: int):
        """Handle chapter download progress."""
        if manga_name in self.download_items:
            self.download_items[manga_name].set_chapter_progress(chapter_num, progress)
        
        if self.chapter_viewer.current_manga_name == manga_name:
            self.chapter_viewer.update_chapter_progress(chapter_num, progress)
    
    def on_chapter_completed(self, manga_name: str, chapter_num: str, path: str):
        """Handle chapter download completed."""
        if manga_name in self.download_items:
            widget = self.download_items[manga_name]
            widget.increment_completed_chapters()
            
            queue = self.download_manager.get_queue()
            for item in queue:
                if item['manga_name'] == manga_name:
                    queued_chapters = item.get('chapters', [])
                    if queued_chapters:
                        manga_id = item.get('manga_id')
                        if manga_id:
                            chapters = self.db_manager.get_chapters_for_manga(manga_id, include_not_downloaded=True)
                            queued_downloaded_count = 0
                            for ch in chapters:
                                if ch['chapter_number'] in queued_chapters and ch['is_downloaded']:
                                    queued_downloaded_count += 1
                            widget.update_chapter_counts(queued_downloaded_count, len(queued_chapters))
                    break
        
        if self.chapter_viewer.current_manga_name == manga_name:
            self.chapter_viewer.mark_chapter_completed(chapter_num)
            self.chapter_viewer.refresh_chapter_status()
        
        if manga_name in self.history_items:
            manga_info = self.db_manager.get_manga_by_title(manga_name)
            if manga_info:
                manga_id = manga_info['id']
                chapters = self.db_manager.get_chapters_for_manga(manga_id, include_not_downloaded=True)
                total_count = len(set(ch['chapter_number'] for ch in chapters))
                downloaded_count = len(set(ch['chapter_number'] for ch in chapters if ch['is_downloaded']))
                history_item = self.history_items[manga_name]
                history_item.downloaded_count = downloaded_count
                history_item.chapter_count = total_count
                history_item.update_appearance()
                history_item.repaint()
        else:
            QTimer.singleShot(100, self.populate_history_list)
        
        self.show_toast(f"Downloaded chapter {chapter_num} of {manga_name}", "success")
        
    
    def on_chapter_failed(self, manga_name: str, chapter_num: str, reason: str):
        """Handle chapter download failed."""
        self.show_toast(f"Failed to download chapter {chapter_num} of {manga_name}: {reason}", "error")
        if manga_name in self.download_items:
            self.download_items[manga_name].set_status(f"Error on Ch. {chapter_num}")
        
        if self.chapter_viewer.current_manga_name == manga_name:
            self.chapter_viewer.mark_chapter_failed(chapter_num)
    
    def on_metadata_updated(self, manga_name: str):
        """Handle metadata update for a manga."""
        current_page = self.sidebar.get_current_item()
        if current_page == "history":
            self.populate_history_list()
    
    def _update_manga_metadata_async(self, manga_id: int):
        """Update manga metadata asynchronously."""
        try:
            success = self.metadata_manager.refresh_manga_metadata(manga_id)
            if success:
                logging.info(f"Successfully updated metadata for manga ID {manga_id}")
                manga_list = self.db_manager.get_manga_list()
                for manga in manga_list:
                    if manga['id'] == manga_id:
                        self.signals.metadata_updated.emit(manga['title'])
                        break
            else:
                logging.warning(f"Failed to update metadata for manga ID {manga_id}")
        except Exception as e:
            logging.error(f"Error updating metadata for manga ID {manga_id}: {e}")
    
    def refresh_all_metadata(self):
        """Refresh metadata for all manga that need updates."""
        try:
            needs_update = self.metadata_manager.get_manga_needing_updates()
            if not needs_update:
                self.show_toast("All manga metadata is up to date", "info")
                return
            
            self.show_toast(f"Refreshing metadata for {len(needs_update)} manga...", "info")
            
            def progress_callback(current, total, manga_name):
                self.show_toast(f"Updating {manga_name} ({current}/{total})", "info")
            
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)
            
            def run_backfill():
                successful, total = self.metadata_manager.backfill_all_metadata(progress_callback)
                return successful, total
            
            future = executor.submit(run_backfill)
            
            def on_complete():
                try:
                    successful, total = future.result()
                    self.show_toast(f"Updated metadata for {successful}/{total} manga", "success")
                    self.populate_history_list()
                except Exception as e:
                    self.show_toast(f"Error refreshing metadata: {e}", "error")
            
            def check_completion():
                if future.done():
                    on_complete()
                else:
                    QTimer.singleShot(500, check_completion)
            
            QTimer.singleShot(500, check_completion)
            
        except Exception as e:
            self.show_toast(f"Error starting metadata refresh: {e}", "error")
    
    def on_chapter_redownload_requested(self, manga_name: str, chapter_name: str):
        """Handle chapter redownload request."""
        try:
            queue = self.download_manager.get_queue()
            manga_url = None
            
            for item in queue:
                if item['manga_name'] == manga_name:
                    manga_url = item['url']
                    break
            
            if not manga_url:
                manga_data = self.db_manager.get_manga_by_title(manga_name)
                if manga_data:
                    manga_url = manga_data.get('url', '')
            
            if manga_url:
                is_valid, site_type = self.download_manager.validate_manga_url(manga_url)
                if site_type == 'webtoon':
                    self.show_toast(f"Redownloading {chapter_name}", "info")
                
                language = getattr(self.chapter_viewer, 'current_language', 'en') or 'en'
                success = self.download_manager.add_to_queue(manga_url, [chapter_name], language=language)
                if success:
                    self.show_toast(f"Added {chapter_name} to download queue", "info")
                    self.chapter_viewer.update_chapter_status(chapter_name, "queued")
                    
                    is_downloading = self.download_manager.is_downloading
                    queue_size = len(self.download_manager.get_queue())
                    
                    logging.info(f"Starting download: is_downloading={is_downloading}, queue_size={queue_size}")
                    
                    if not is_downloading and queue_size > 0:
                        self.download_manager.start_download_thread()
                        logging.info("Started download thread")
                    elif is_downloading:
                        logging.info("Download already in progress, chapter will be processed when current download completes")
                    else:
                        logging.warning("No items in queue to download")
                else:
                    self.show_toast(f"Failed to add {chapter_name} to queue", "error")
            else:
                self.show_toast("Could not find manga URL for redownload", "error")
                
        except Exception as e:
            logging.error(f"Error redownloading chapter: {e}")
            self.show_toast(f"Error redownloading chapter: {e}", "error")
    
    def on_manga_progress(self, manga_name: str, progress: int):
        """Handle overall manga download progress."""
        if manga_name in self.download_items:
            self.download_items[manga_name].set_overall_progress(progress)
    
    def on_download_paused(self, manga_name: str):
        """Handle download paused."""
        if manga_name in self.download_items:
            self.download_items[manga_name].set_status("Paused")
    
    def on_download_resumed(self, manga_name: str):
        """Handle download resumed."""
        if manga_name in self.download_items:
            self.download_items[manga_name].set_status("Downloading")
    
    def download_all_new(self):
        """Download all new chapters for manga that have new chapters available."""
        try:
            manga_with_new_chapters = []
            
            for manga_name, history_item in self.history_items.items():
                if hasattr(history_item, 'has_new_chapters') and history_item.has_new_chapters:
                    manga_with_new_chapters.append(manga_name)
            
            if not manga_with_new_chapters:
                self.show_toast("No manga with new chapters found", "info")
                return
            
            total_queued = 0
            
            for manga_name in manga_with_new_chapters:
                try:
                    manga_data = self.db_manager.get_manga_by_title(manga_name)
                    if not manga_data or not manga_data.get('url'):
                        continue
                    
                    url = manga_data['url']
                    manga_id = manga_data['id']
                    
                    all_chapters = self.db_manager.get_chapters_for_manga(manga_id)
                    undownloaded_chapters = [ch['chapter_number'] for ch in all_chapters if not ch['is_downloaded']]
                    
                    if undownloaded_chapters:
                        self.download_manager.queue_download(url, undownloaded_chapters)
                        total_queued += 1
                        
                        if manga_name in self.history_items:
                            self.history_items[manga_name].set_has_new_chapters(False)
                        
                        logging.info(f"Queued {len(undownloaded_chapters)} chapters for {manga_name}")
                    
                except Exception as e:
                    logging.error(f"Error queueing {manga_name}: {e}")
                    continue
            
            if total_queued > 0:
                self.stacked_widget.setCurrentIndex(0)
                self.show_toast(f"Queued {total_queued} manga with new chapters for download", "success")
            else:
                self.show_toast("No new chapters were queued for download", "info")
                
        except Exception as e:
            logging.error(f"Error in download_all_new: {e}")
            self.show_toast(f"Error downloading all new chapters: {e}", "error")
    
    def clear_completed_downloads(self):
        """Clear completed downloads from the queue."""
        try:
            queue = self.download_manager.get_queue()
            completed_items = []
            
            for item in queue:
                manga_name = item['manga_name']
                if manga_name in self.download_items:
                    widget = self.download_items[manga_name]
                    status = widget.status
                    if status in ["Completed", "Failed"] or widget.current_chapter >= widget.total_chapters:
                        completed_items.append(manga_name)
            
            for manga_name in completed_items:
                if manga_name in self.download_items:
                    widget = self.download_items[manga_name]
                    widget.setParent(None)
                    widget.deleteLater()
                    del self.download_items[manga_name]
            
            self.update_queue_display()
            
            if completed_items:
                self.show_toast(f"Cleared {len(completed_items)} completed downloads", "success")
            else:
                self.show_toast("No completed downloads to clear", "info")
                
        except Exception as e:
            self.show_toast(f"Error clearing completed downloads: {e}", "error")
    
    def _sync_database_with_files(self, manga_data, chapters):
        """Synchronize database with actual files on disk for all site types."""
        try:
            manga_name = manga_data.get('title', '')
            manga_id = manga_data.get('id')
            site_type = manga_data.get('site_type', '')
            if not manga_id:
                return
                
            download_path = self.settings_manager.get_download_path()
            if not download_path:
                return
                
            safe_manga_name = re.sub(r'[<>:"/\\|?*]', '', manga_name)
            manga_folder = os.path.join(download_path, safe_manga_name)
            
            if not os.path.exists(manga_folder):
                return
                
            for chapter in chapters:
                chapter_num = chapter['chapter_number']
                chapter_name = chapter.get('chapter_name', f'Chapter {chapter_num}')
                is_downloaded = chapter['is_downloaded']
                    
                possible_files = []
                
                if site_type == 'asura_comics':
                    possible_files = [
                        f"Chapter {chapter_num}.cbz",
                        f"Chapter {chapter_num} - {chapter_name}.cbz" if chapter_name != f'Chapter {chapter_num}' else None
                    ]
                elif site_type in ['manga_katana', 'mangakatana', 'katana']:
                    possible_files = [
                        f"Chapter {chapter_num}.cbz"
                    ]
                    if chapter_name != f'Chapter {chapter_num}':
                        clean_chapter_name = chapter_name.replace(':', ' -')
                        clean_chapter_name = re.sub(r'[<>"/\\|?*]', '', clean_chapter_name)
                        possible_files.append(f"{clean_chapter_name}.cbz")
                        
                        old_clean_name = re.sub(r'[<>"/\\|?*]', '', chapter_name)
                        possible_files.append(f"{old_clean_name}.cbz")
                elif site_type == 'webtoon':
                    possible_files = [
                        f"Chapter {chapter_num}.cbz"
                    ]
                else:
                    possible_files = [
                        f"Chapter {chapter_num}.cbz",
                        f"Chapter {chapter_num} - {chapter_name}.cbz" if chapter_name != f'Chapter {chapter_num}' else None
                    ]
                
                file_exists = False
                valid_file_path = ""
                
                for filename in possible_files:
                    if filename:
                        file_path = os.path.join(manga_folder, filename)
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:  # At least 1KB
                            file_exists = True
                            valid_file_path = file_path
                            break
                
                if file_exists and not is_downloaded:
                    self.db_manager.mark_chapter_downloaded(manga_id, chapter_num, valid_file_path)
                    logging.info(f"Synchronized chapter {chapter_num} with existing file (site: {site_type})")
                elif not file_exists and is_downloaded:
                    self.db_manager.reset_chapter_download_status(manga_id, chapter_num)
                    logging.info(f"Reset chapter {chapter_num} download status (file missing, site: {site_type})")
                        
        except Exception as e:
            logging.error(f"Error synchronizing database with files: {e}")
    
    def perform_startup_sync(self):
        """Perform startup synchronization for all manga to ensure database matches files."""
        try:
            manga_list = self.db_manager.get_manga_list()
            if not manga_list:
                return
                
            logging.info(f"Performing startup sync for {len(manga_list)} manga...")
            
            for manga_data in manga_list:
                try:
                    manga_id = manga_data.get('id')
                    if not manga_id:
                        continue
                        
                    chapters = self.db_manager.get_chapters_for_manga(manga_id)
                    if chapters:
                        self._sync_database_with_files(manga_data, chapters)
                except Exception as e:
                    logging.error(f"Error syncing manga {manga_data.get('title', 'Unknown')}: {e}")
                    continue
            
            logging.info("Startup sync completed")
            
        except Exception as e:
            logging.error(f"Error during startup sync: {e}")
    
    def show_toast(self, message: str, msg_type: str = "info"):
        """Show a toast notification."""
        self.toast.show_message(message, msg_type)
    
    def closeEvent(self, a0):
        """Handle application close."""
        self.settings_manager.set_window_size(self.width(), self.height())
        self.settings_manager.set_window_position(self.x(), self.y())
        
        if a0:
            a0.accept()


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    
    app.setApplicationName("Manga Downloader")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("MangaDownloader")
    
    window = MangaDownloaderApp()
    window.show()
    
    sys.exit(app.exec_())


    def refresh_mangadex_chapters_for_existing_manga(self, manga_name: str):
        """Refresh chapters for existing MangaDex manga that have 0 chapters in database."""
        try:
            manga_data = self.db_manager.get_manga_by_title(manga_name)
            if not manga_data or manga_data.get('site_type') != 'mangadex':
                return False
                
            manga_url = manga_data.get('url', '')
            if not manga_url:
                logging.warning(f"No URL found for {manga_name}")
                return False
                
            downloader = self.download_manager.downloaders.get('mangadex')
            if not downloader:
                logging.warning("MangaDex downloader not available")
                return False
                
            available_languages = downloader.get_available_languages(manga_url)
            chapters_by_language = {}
            for lang_code, lang_name in available_languages:
                chapters = downloader.get_chapters_by_language(manga_url, lang_code)
                if chapters:
                    chapters_by_language[lang_code] = chapters
            
            if not chapters_by_language:
                logging.warning(f"No chapters found for {manga_name}")
                return False
                
            from ..managers.database_manager import ChapterData
            manga_id = manga_data.get('id')
            total_chapters = 0
            
            for lang_code, chapters in chapters_by_language.items():
                for chapter in chapters:
                    if ChapterInfo and isinstance(chapter, ChapterInfo):
                        chapter_data = ChapterData(
                            chapter_number=chapter.chapter_number,
                            chapter_name=chapter.title or f"Chapter {chapter.chapter_number}",
                            chapter_url=chapter.chapter_url,
                            language=lang_code,
                            is_downloaded=False
                        )
                        self.db_manager.add_or_update_chapter(manga_id, chapter_data)
                        total_chapters += 1

            logging.info(f"Refreshed {total_chapters} chapters for existing MangaDex manga: {manga_name}")
            self.populate_history_list()
            return True
            
        except Exception as e:
            logging.error(f"Error refreshing MangaDex chapters for {manga_name}: {e}")
            return False


if __name__ == "__main__":
    main()
