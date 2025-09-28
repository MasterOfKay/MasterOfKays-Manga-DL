"""
Chapter viewer widget for displaying manga chapters with status.
"""

from typing import List, Dict, Optional
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QScrollArea, QPushButton, QFrame, QListWidget,
                             QListWidgetItem, QMenu, QAction, QCheckBox)
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
        
        self.init_ui()
        
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        header_layout = QHBoxLayout()
        
        self.title_label = QLabel("No Manga Selected")
        self.title_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.title_label.setWordWrap(True)
        
        self.count_label = QLabel("0 chapters")
        self.count_label.setFont(QFont("Arial", 9))
        self.count_label.setStyleSheet("color: #666;")
        
        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.count_label)
        
        layout.addLayout(header_layout)
        
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        self.chapters_layout = QVBoxLayout(scroll_widget)
        self.chapters_layout.setContentsMargins(0, 0, 0, 0)
        self.chapters_layout.setSpacing(2)
        self.chapters_layout.addStretch()
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # type: ignore
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore
        
        layout.addWidget(scroll_area, 1)
    
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
        
    def set_manga(self, manga_name: str, manga_url: str = "", chapters: Optional[List] = None, chapter_status: Optional[Dict] = None):
        """Set the manga and its chapters."""
        self.manga_name = manga_name
        self.manga_url = manga_url
        self.chapters = chapters or []
        
        self.title_label.setText(manga_name or "No Manga Selected")
        self.count_label.setText(f"{len(self.chapters)} chapters")
        
        self.clear_chapters()

        if self.chapters:
            for chapter in self.chapters:
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
        
    def update_chapter_status(self, chapter_name: str, status: str):
        """Update the status of a specific chapter."""
        if chapter_name in self.chapter_items:
            self.chapter_items[chapter_name].set_status(status)
            
    def redownload_failed_chapters(self):
        """Request redownload of all failed chapters."""
        for chapter_name, item in self.chapter_items.items():
            if item.status == "failed":
                self.chapter_redownload_requested.emit(self.manga_name, chapter_name)
                
    def select_all_chapters(self):
        """Select all chapters for download."""
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
    
    def get_selected_chapters(self) -> List[Dict]:
        """Get list of selected chapters."""
        selected = []
        for chapter_name, item in self.chapter_items.items():
            if item.is_selected():
                selected.append({
                    'name': chapter_name,
                    'url': item.chapter_url,
                    'status': item.status
                })
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