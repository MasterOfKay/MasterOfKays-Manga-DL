"""
Toast notification widget.
"""

from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QColor


class Toast(QDialog):
    """Toast notification dialog."""
    
    def __init__(self, parent=None, settings_manager=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)  # type: ignore
        self.setAttribute(Qt.WA_TranslucentBackground)  # type: ignore
        self.setModal(False)
        
        self.init_ui()
        
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.hide_toast)
        
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 10, 15, 10)
        
        self.label = QLabel()
        self.label.setFont(QFont("Arial", 11))
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 200);
                color: white;
                border-radius: 8px;
                padding: 12px 16px;
                min-width: 200px;
                max-width: 400px;
            }
        """)
        
        layout.addWidget(self.label)
        self.setLayout(layout)
        
        self.adjustSize()
    
    def show_message(self, message: str, msg_type: str = "info", duration: int = 5000):
        """Show a toast message."""
        self.animation.stop()
        self.timer.stop()
        
        self.label.setText(message)
        
        if self.settings_manager:
            colors = self.settings_manager.get_color_scheme()
            type_colors = {
                "info": colors.get('info_color', '#0078D4'),
                "success": colors.get('success_color', '#107C10'),
                "error": colors.get('error_color', '#D13438'),
                "warning": colors.get('warning_color', '#FF8C00')
            }
        else:
            type_colors = {
                "info": "#0078D4",
                "success": "#107C10", 
                "error": "#D13438",
                "warning": "#FF8C00"
            }
        
        base_color = type_colors.get(msg_type, type_colors["info"])
        hex_color = base_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        rgba_color = f"rgba({r}, {g}, {b}, 200)"
        
        self.label.setStyleSheet(f"""
            QLabel {{
                background-color: {rgba_color};
                color: white;
                border-radius: 8px;
                padding: 12px 16px;
                min-width: 200px;
                max-width: 400px;
                font-weight: bold;
            }}
        """)

        self.adjustSize()
        
        if self.parent():
            try:
                parent_widget = self.parent()
                if hasattr(parent_widget, 'geometry'):
                    parent_rect = parent_widget.geometry()
                    self.move(
                        parent_rect.right() - self.width() - 20,
                        parent_rect.bottom() - self.height() - 50
                    )
                else:
                    self.move(300, 300)
            except (AttributeError, TypeError):
                self.move(300, 300)
        
        self.setWindowOpacity(0)
        self.show()
        
        self.animation.setStartValue(0)
        self.animation.setEndValue(1)
        self.animation.start()
        
        self.timer.stop()
        self.timer.start(duration)
    
    def hide_toast(self):
        """Hide the toast with animation."""
        self.timer.stop()
        
        try:
            self.animation.finished.disconnect()
        except TypeError:
            pass
        
        self.animation.setStartValue(1)
        self.animation.setEndValue(0)
        self.animation.finished.connect(self._close_toast)
        self.animation.start()
    
    def _close_toast(self):
        """Close the toast."""
        try:
            self.animation.finished.disconnect()
        except TypeError:
            pass
        self.close()