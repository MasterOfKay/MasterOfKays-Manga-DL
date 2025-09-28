"""
Chapter selection dialog.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QCheckBox, QSpinBox, QGridLayout, QPushButton,
                            QScrollArea, QWidget)
from PyQt5.QtCore import Qt
from typing import List, Tuple, Union


class ChapterSelectionDialog(QDialog):
    """Dialog for selecting chapters to download."""
    
    def __init__(self, manga_name: str, chapters: List[Union[Tuple[str, str, str], Tuple[str, str, str, bool]]], parent=None, include_downloaded: bool = False):
        super().__init__(parent)
        self.manga_name = manga_name
        self.chapters = chapters
        self.include_downloaded = include_downloaded
        self.chapter_checkboxes = []
        
        self.setWindowTitle(f"Select Chapters - {manga_name}")
        self.setModal(True)
        self.resize(600, 500)
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI."""
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
                first_ch = int(float(self.chapters[0][0]))
                last_ch = int(float(self.chapters[-1][0]))
                self.range_from_spin.setRange(first_ch, last_ch)
                self.range_to_spin.setRange(first_ch, last_ch)
                self.range_from_spin.setValue(first_ch)
                self.range_to_spin.setValue(last_ch)
            except (ValueError, IndexError):
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
            if len(chapter_data) >= 4:
                chapter_num, chapter_name, _, is_downloaded = chapter_data[:4]
                if is_downloaded:
                    checkbox_text = f"Ch. {chapter_num}: {chapter_name} ✓"
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
                    checkbox_text = f"Ch. {chapter_num}: {chapter_name}"
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
            else:
                chapter_num, chapter_name = chapter_data[:2]
                checkbox_text = f"Ch. {chapter_num}: {chapter_name}"
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
            checkbox.setProperty("is_downloaded", len(chapter_data) >= 4 and chapter_data[3])
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
    
    def select_all(self):
        """Select only new (not downloaded) chapters for download."""
        for checkbox in self.chapter_checkboxes:
            is_downloaded = checkbox.property("is_downloaded")
            checkbox.setChecked(not bool(is_downloaded))
        self._update_selection_count()
    
    def clear_all(self):
        """Clear all chapter selections."""
        for checkbox in self.chapter_checkboxes:
            checkbox.setChecked(False)
        self._update_selection_count()
    
    def select_downloaded(self):
        """Select only downloaded chapters."""
        for checkbox in self.chapter_checkboxes:
            is_downloaded = checkbox.property("is_downloaded")
            checkbox.setChecked(bool(is_downloaded))
        self._update_selection_count()
    
    def select_not_downloaded(self):
        """Select only not downloaded chapters."""
        for checkbox in self.chapter_checkboxes:
            is_downloaded = checkbox.property("is_downloaded")
            checkbox.setChecked(not bool(is_downloaded))
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
        for checkbox in self.chapter_checkboxes:
            if checkbox.isChecked():
                chapter_num = checkbox.property("chapter_num")
                if chapter_num:
                    selected.append(str(chapter_num))
        return selected