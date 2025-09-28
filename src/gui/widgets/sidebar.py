"""
Sidebar navigation widget.
"""

from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QToolButton
from PyQt5.QtGui import QFont, QIcon


class SidebarButton(QToolButton):
    """Custom button for sidebar navigation."""
    
    def __init__(self, text: str, icon=None, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setToolButtonStyle(2) 
        self.setMinimumSize(QSize(80, 60))
        self.setMaximumSize(QSize(80, 60))
        
        if icon:
            self.setIcon(icon)
            self.setIconSize(QSize(24, 24))
    
    def apply_colors(self, text_color: str, hover_color: str, selected_color: str, selected_text_color: str):
        """Apply color scheme to the button."""
        style = f"""
            QToolButton {{
                border: none;
                background-color: transparent;
                color: {text_color};
                font-size: 10px;
                font-weight: bold;
                text-align: center;
                padding: 8px 4px;
                border-radius: 4px;
                margin: 2px;
            }}
            QToolButton:hover {{
                background-color: {hover_color};
            }}
            QToolButton:checked {{
                background-color: {selected_color};
                color: {selected_text_color};
            }}
        """
        self.setStyleSheet(style)


class Sidebar(QWidget):
    """Sidebar navigation widget."""
    
    itemClicked = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        """Initialize the UI."""
        self.setObjectName("sidebar")
        
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        self.download_btn = SidebarButton("Download")
        self.history_btn = SidebarButton("History") 
        self.settings_btn = SidebarButton("Settings")
        
        self.download_btn.clicked.connect(lambda: self.itemClicked.emit("download"))
        self.history_btn.clicked.connect(lambda: self.itemClicked.emit("history"))
        self.settings_btn.clicked.connect(lambda: self.itemClicked.emit("settings"))
        
        self.download_btn.setChecked(True)
        
        layout.addWidget(self.download_btn)
        layout.addWidget(self.history_btn)
        layout.addWidget(self.settings_btn)
        layout.addStretch()
        
        self.setLayout(layout)
        
        self.setFixedWidth(100)
        
        self.setAutoFillBackground(True)
        
        self.setStyleSheet("""
            QWidget#sidebar {
                background-color: #f0f0f0;
                border-right: 1px solid #ccc;
            }
        """)
    
    def apply_colors(self, bg_color: str, border_color: str, text_color: str, 
                    hover_color: str, selected_color: str, selected_text_color: str):
        """Apply color scheme to the sidebar and its buttons."""
        try:
            from PyQt5.QtGui import QPalette, QColor
            from PyQt5.QtCore import Qt
            
            self.setAutoFillBackground(True)
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor(bg_color))
            palette.setColor(QPalette.Background, QColor(bg_color))
            self.setPalette(palette)
        except Exception as e:
            pass
        
        sidebar_style = f"""
            QWidget#sidebar {{
                background-color: {bg_color} !important;
                border-right: 1px solid {border_color} !important;
            }}
            Sidebar {{
                background-color: {bg_color} !important;
                border-right: 1px solid {border_color} !important;
            }}
        """
        self.setStyleSheet(sidebar_style)
        
        self.update()
        self.repaint()
        
        for button in [self.download_btn, self.history_btn, self.settings_btn]:
            button.apply_colors(text_color, hover_color, selected_color, selected_text_color)
    
    def set_active_item(self, item: str):
        """Set the active navigation item."""
        buttons = {
            "download": self.download_btn,
            "history": self.history_btn,
            "settings": self.settings_btn
        }
        
        button = buttons.get(item)
        if button:
            button.setChecked(True)
    
    def get_current_item(self) -> str:
        """Get the currently active navigation item."""
        if self.download_btn.isChecked():
            return "download"
        elif self.history_btn.isChecked():
            return "history"
        elif self.settings_btn.isChecked():
            return "settings"
        else:
            return "download"