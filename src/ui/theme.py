"""
Design tokens, palette and the application stylesheet.

Everything visual reads from `current()`, so switching light/dark or the
accent color at runtime only needs `apply()` + the `notifier.changed` signal.
"""

from dataclasses import dataclass
from typing import Dict

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

ACCENTS = {
    'Indigo': '#6366F1',
    'Blue': '#3B82F6',
    'Teal': '#14B8A6',
    'Green': '#22C55E',
    'Orange': '#F97316',
    'Rose': '#F43F5E',
    'Violet': '#8B5CF6',
}

LIGHT = {
    'bg': '#F4F5F7', 'sidebar': '#FAFAFB', 'surface': '#FFFFFF', 'surface_alt': '#F6F7F9',
    'hover': '#EEF0F3', 'pressed': '#E5E8EC', 'border': '#E3E5E9', 'border_strong': '#CDD1D8',
    'text': '#15171B', 'text_muted': '#5E6571', 'text_faint': '#959BA5',
    'success': '#1F9D62', 'warning': '#D97A1E', 'danger': '#DC3F45', 'info': '#2F7CF6',
    'shadow': '#14000000', 'scrim': '#66000000',
}

DARK = {
    'bg': '#0F1115', 'sidebar': '#12151A', 'surface': '#181B21', 'surface_alt': '#1E2229',
    'hover': '#232830', 'pressed': '#2B313A', 'border': '#262B33', 'border_strong': '#363C47',
    'text': '#E9EBEF', 'text_muted': '#A1A7B2', 'text_faint': '#6C727D',
    'success': '#3DBE84', 'warning': '#F0A24E', 'danger': '#FF6468', 'info': '#5B9BFF',
    'shadow': '#50000000', 'scrim': '#99000000',
}


def _mix(a: str, b: str, amount: float) -> str:
    """Blend color a toward b by amount (0..1)."""
    ca, cb = QColor(a), QColor(b)
    r = round(ca.red() + (cb.red() - ca.red()) * amount)
    g = round(ca.green() + (cb.green() - ca.green()) * amount)
    bl = round(ca.blue() + (cb.blue() - ca.blue()) * amount)
    return QColor(r, g, bl).name()


@dataclass
class Theme:
    dark: bool
    tokens: Dict[str, str]

    def __getitem__(self, key: str) -> str:
        return self.tokens[key]

    def q(self, key: str) -> QColor:
        return QColor(self.tokens[key])


class _Notifier(QObject):
    changed = Signal()


notifier = _Notifier()
_current = Theme(False, dict(LIGHT))


def current() -> Theme:
    return _current


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def build(mode: str, accent: str) -> Theme:
    dark = system_is_dark() if mode == 'system' else mode == 'dark'
    t = dict(DARK if dark else LIGHT)
    accent = accent if QColor(accent).isValid() else ACCENTS['Indigo']
    t['accent'] = accent
    t['accent_hover'] = _mix(accent, '#FFFFFF' if dark else '#000000', 0.12)
    t['accent_pressed'] = _mix(accent, '#FFFFFF' if dark else '#000000', 0.22)
    t['accent_soft'] = _mix(t['surface'], accent, 0.16 if dark else 0.10)
    t['accent_soft_strong'] = _mix(t['surface'], accent, 0.26 if dark else 0.18)
    t['accent_text'] = _mix(accent, '#FFFFFF', 0.35) if dark else _mix(accent, '#000000', 0.15)
    t['on_accent'] = '#FFFFFF'
    for name in ('success', 'warning', 'danger', 'info'):
        t[f'{name}_soft'] = _mix(t['surface'], t[name], 0.16 if dark else 0.11)
    return Theme(dark, t)


def apply(app: QApplication, mode: str, accent: str) -> Theme:
    global _current
    _current = build(mode, accent)
    app.setPalette(_palette(_current))
    app.setStyleSheet(stylesheet(_current))
    notifier.changed.emit()
    return _current


def default_font() -> QFont:
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text",
                      "Helvetica Neue", "Cantarell", "Noto Sans", "Ubuntu", "sans-serif"])
    font.setPointSizeF(9.75)
    font.setHintingPreference(QFont.PreferNoHinting)
    return font


def _palette(t: Theme) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.Window: t['bg'], QPalette.WindowText: t['text'], QPalette.Base: t['surface'],
        QPalette.AlternateBase: t['surface_alt'], QPalette.Text: t['text'], QPalette.Button: t['surface'],
        QPalette.ButtonText: t['text'], QPalette.Highlight: t['accent'], QPalette.HighlightedText: t['on_accent'],
        QPalette.ToolTipBase: t['surface'], QPalette.ToolTipText: t['text'], QPalette.PlaceholderText: t['text_faint'],
        QPalette.Link: t['accent'], QPalette.Mid: t['border'], QPalette.Midlight: t['border'],
        QPalette.Dark: t['border_strong'], QPalette.Light: t['surface'], QPalette.Shadow: '#000000',
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(t['text_faint']))
    return p


def stylesheet(t: Theme) -> str:
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t['text']}; }}
QMainWindow, QWidget#Root {{ background: {t['bg']}; }}
QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border_strong']};
           border-radius: 6px; padding: 5px 8px; }}

/* ---------- sidebar ---------- */
QWidget#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['border']}; }}
QLabel#Brand {{ font-size: 11.5pt; font-weight: 700; }}
QLabel#BrandSub {{ color: {t['text_faint']}; font-size: 8.5pt; }}
QPushButton#NavButton {{ background: transparent; border: none; border-radius: 8px; text-align: left;
                        padding: 8px 10px; color: {t['text_muted']}; font-weight: 500; }}
QPushButton#NavButton:hover {{ background: {t['hover']}; color: {t['text']}; }}
QPushButton#NavButton:checked {{ background: {t['accent_soft']}; color: {t['accent_text']}; font-weight: 600; }}

/* ---------- typography ---------- */
QLabel[role="h1"] {{ font-size: 17pt; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 11.5pt; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 10.5pt; font-weight: 600; }}
QLabel[role="section"] {{ color: {t['text_faint']}; font-size: 8.5pt; font-weight: 700; }}
QLabel[role="muted"] {{ color: {t['text_muted']}; }}
QLabel[role="faint"] {{ color: {t['text_faint']}; }}
QLabel[role="error"] {{ color: {t['danger']}; }}
QLabel[role="link"] {{ font-weight: 600; }}
QLabel[role="link"]:hover {{ color: {t['accent_text']}; }}

QLabel[pill="true"] {{ border-radius: 9px; padding: 1px 8px; font-size: 8.5pt; font-weight: 600; }}
QLabel[pill="true"][tone="accent"] {{ background: {t['accent_soft']}; color: {t['accent_text']}; }}
QLabel[pill="true"][tone="success"] {{ background: {t['success_soft']}; color: {t['success']}; }}
QLabel[pill="true"][tone="warning"] {{ background: {t['warning_soft']}; color: {t['warning']}; }}
QLabel[pill="true"][tone="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
QLabel[pill="true"][tone="neutral"] {{ background: {t['surface_alt']}; color: {t['text_muted']};
                                      border: 1px solid {t['border']}; }}
QLabel#NavBadge {{ background: {t['accent']}; color: {t['on_accent']}; border-radius: 9px;
                  padding: 0px 6px; font-size: 8pt; font-weight: 700; }}

/* ---------- cards ---------- */
QFrame[card="true"] {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
QFrame[card="true"][clickable="true"]:hover {{ border-color: {t['border_strong']}; }}
QFrame[card="true"][active="true"] {{ border: 1px solid {t['accent']}; }}
QFrame#Divider {{ background: {t['border']}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#ChapterPanel {{ background: {t['surface']}; border-left: 1px solid {t['border']}; }}

/* ---------- buttons ---------- */
QPushButton {{ background: {t['surface']}; border: 1px solid {t['border_strong']}; border-radius: 8px;
              padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['pressed']}; }}
QPushButton:disabled {{ color: {t['text_faint']}; background: {t['surface_alt']}; border-color: {t['border']}; }}
QPushButton[variant="primary"] {{ background: {t['accent']}; border: 1px solid {t['accent']}; color: {t['on_accent']}; }}
QPushButton[variant="primary"]:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
QPushButton[variant="primary"]:pressed {{ background: {t['accent_pressed']}; }}
QPushButton[variant="primary"]:disabled {{ background: {t['accent_soft']}; border-color: transparent;
                                          color: {t['text_faint']}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t['text_muted']}; }}
QPushButton[variant="ghost"]:hover {{ background: {t['hover']}; color: {t['text']}; }}
QPushButton[variant="danger"] {{ color: {t['danger']}; }}
QPushButton[variant="danger"]:hover {{ background: {t['danger_soft']}; border-color: {t['danger']}; }}
QPushButton[segment="true"] {{ background: transparent; border: none; border-radius: 6px; padding: 5px 12px;
                              color: {t['text_muted']}; font-weight: 600; }}
QPushButton[segment="true"]:hover {{ color: {t['text']}; }}
QPushButton[segment="true"]:checked {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; }}
QPushButton[chip="true"] {{ background: {t['surface']}; border: 1px solid {t['border_strong']}; border-radius: 14px;
                           padding: 4px 12px; color: {t['text_muted']}; font-weight: 600; }}
QPushButton[chip="true"]:hover {{ color: {t['text']}; background: {t['hover']}; }}
QPushButton[chip="true"]:checked {{ background: {t['accent_soft']}; border-color: {t['accent']}; color: {t['accent_text']}; }}
QFrame#Segmented {{ background: {t['surface_alt']}; border: 1px solid {t['border']}; border-radius: 8px; }}

QToolButton {{ background: transparent; border: none; border-radius: 7px; padding: 5px; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:pressed {{ background: {t['pressed']}; }}
QToolButton:disabled {{ background: transparent; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QPushButton#Swatch {{ border-radius: 13px; padding: 0; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
                     border: 2px solid transparent; }}
QPushButton#Swatch:checked {{ border: 2px solid {t['text']}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QComboBox {{ background: {t['surface_alt']}; border: 1px solid {t['border']}; border-radius: 8px;
                                 padding: 6px 10px; selection-background-color: {t['accent']};
                                 selection-color: {t['on_accent']}; }}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {t['border_strong']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {t['accent']}; background: {t['surface']}; }}
QLineEdit#UrlInput {{ padding: 9px 12px; font-size: 10.5pt; border-radius: 10px; }}
QComboBox {{ combobox-popup: 0; }}   /* list-style popup that respects maxVisibleItems */
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border_strong']}; border-radius: 8px;
                               padding: 4px; selection-background-color: {t['accent_soft']};
                               selection-color: {t['text']}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; background: transparent; }}

/* ---------- progress ---------- */
QProgressBar {{ background: {t['surface_alt']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
               text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}
QProgressBar[tone="success"]::chunk {{ background: {t['success']}; }}
QProgressBar[thin="true"] {{ max-height: 4px; min-height: 4px; border-radius: 2px; }}
QProgressBar[thin="true"]::chunk {{ border-radius: 2px; }}

/* ---------- scrolling ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border_strong']}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text_faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border_strong']}; border-radius: 3px; min-width: 30px; margin: 2px 0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QListView {{ background: transparent; border: none; }}

/* ---------- menus & dialogs ---------- */
QMenu {{ background: {t['surface']}; border: 1px solid {t['border_strong']}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['hover']}; }}
QMenu::item:disabled {{ color: {t['text_faint']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 8px; }}
QMessageBox, QDialog {{ background: {t['surface']}; }}
QSplitter::handle {{ background: transparent; }}

/* ---------- toasts ---------- */
QFrame#Toast {{ background: {t['surface']}; border: 1px solid {t['border_strong']}; border-radius: 12px; }}
QLabel#ToastTitle {{ font-weight: 600; }}
QLabel#ToastBody {{ color: {t['text_muted']}; }}
"""
