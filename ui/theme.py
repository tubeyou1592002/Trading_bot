"""
ui/theme.py — UI-9 Task 1: dark theme foundation.

ONE place for every visual token of the User Application:

    * the colour palette (background / surface / border / text / accent …),
    * the spacing scale (4 / 8 / 12 / 16 / 24),
    * the geometry rules (uniform control height, corner radius),
    * the complete Qt stylesheet (QSS) built from those tokens,
    * ``apply_theme()`` which applies it to a QApplication or to any
      single widget.

Why a separate module: several existing tests construct a page (or the
whole MainWindow) directly WITHOUT going through ``create_app()``. Applying
the style on the QApplication alone would leave those windows unthemed, so
``apply_theme`` also works on a plain widget and the MainWindow applies it
to itself.

Import contract (UI-3.1 test_14 / C6): this module imports from PySide6
only. It must never import ``main``, ``brokers``, ``core`` or ``market`` —
not even lazily — so importing it can never pull the trading core into a
UI-only import path.

No font file is bundled with the repository (licensing not verified); the
font chain below simply names the families and lets Qt fall back.
"""

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication, QWidget

__all__ = [
    "PALETTE",
    "SPACING",
    "GEOMETRY",
    "FONT_FAMILY_CHAIN",
    "BASE_FONT_SIZE",
    "tokens",
    "palette",
    "spacing",
    "geometry",
    "stylesheet",
    "apply_theme",
    "apply_font",
    "primary_font",
]


# ============================================================
# 1. Design tokens — the single source of truth
# ============================================================

#: Colour palette. Keys are lowerCamelCase names; values are hex strings.
PALETTE = {
    "background": "#12141a",
    "surface": "#1a1d24",
    "surfaceAlt": "#20242d",
    "border": "#2a2f3a",
    "text": "#e6e9ef",
    "textMuted": "#9aa3b2",
    "accent": "#3b82f6",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
}

#: Spacing scale — the ONLY allowed margins/gaps. 4 / 8 / 12 / 16 / 24.
SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
}

#: Application-wide base font size.
BASE_FONT_SIZE = 10

#: Geometry rules: uniform control height and corner radius (6–8px).
GEOMETRY = {
    "controlHeight": 34,
    "radius": 8,
    "radiusSmall": 6,
    "rowHeight": 30,
    # Top margin of a QGroupBox, so its title can sit ON the top border
    # like a tab (see the mockup). Must clear the title height plus the
    # 1px border line, so it is spacing["lg"] + spacing["xs"] rather than
    # a magic number.
    "groupTitleClearance": SPACING["lg"] + SPACING["xs"],
    # Point sizes for the two display values the UI-9.2 layout calls out as
    # visually prominent: the schedule countdown and the scheduling state.
    # Both are larger than BASE_FONT_SIZE; the countdown uses a monospace
    # face so its ticking digits stay column-aligned.
    "countdownFontPt": BASE_FONT_SIZE + 6,
    "statusFontPt": BASE_FONT_SIZE + 2,
}

#: Primary font + approved fallback chain (UI-9 section 0).
FONT_FAMILY_CHAIN = ("IRANSansX", "Vazirmatn", "IRANSans", "Tahoma", "Segoe UI")


def tokens():
    """Return the full token set as a plain dict (copy — never the source)."""
    return {
        "palette": dict(PALETTE),
        "spacing": dict(SPACING),
        "geometry": dict(GEOMETRY),
        "fontFamily": list(FONT_FAMILY_CHAIN),
        "baseFontSize": BASE_FONT_SIZE,
    }


def palette():
    """Return a copy of the colour palette."""
    return dict(PALETTE)


def spacing():
    """Return a copy of the spacing scale."""
    return dict(SPACING)


def geometry():
    """Return a copy of the geometry rules."""
    return dict(GEOMETRY)


# ============================================================
# 2. Stylesheet
# ============================================================


def _build_stylesheet():
    """Build the complete QSS from the tokens above."""
    p = PALETTE
    g = GEOMETRY
    s = SPACING

    control_h = g["controlHeight"]
    radius = g["radius"]
    radius_small = g["radiusSmall"]
    title_clearance = g["groupTitleClearance"]

    # A slightly darker accent for the :hover / :pressed states so the
    # primary button keeps a visible depth on a dark background.
    accent_hover = QColor(p["accent"]).lighter(115).name()
    accent_pressed = QColor(p["accent"]).darker(115).name()
    danger_hover = QColor(p["danger"]).lighter(115).name()
    danger_pressed = QColor(p["danger"]).darker(115).name()
    surface_hover = QColor(p["surfaceAlt"]).lighter(112).name()

    return f"""
/* ---------------------------------------------------------
   UI-9 dark theme — generated from ui/theme.py tokens.
   Do not hand-edit: change the token and rebuild.
   --------------------------------------------------------- */

QWidget {{
    background-color: {p["background"]};
    color: {p["text"]};
    font-size: {BASE_FONT_SIZE}pt;
    selection-background-color: {p["accent"]};
    selection-color: #ffffff;
}}

QMainWindow {{
    background-color: {p["background"]};
}}

QDialog {{
    background-color: {p["background"]};
}}

/* --- Group boxes ---------------------------------------- */

QGroupBox {{
    background-color: {p["surface"]};
    border: 1px solid {p["border"]};
    border-radius: {radius}px;
    margin-top: {title_clearance}px;
    padding: {s["md"]}px {s["md"]}px {s["md"]}px {s["md"]}px;
    font-weight: bold;
}}

/* The title sits ON the top border like a tab (see the mockup); the
   margin-top above is GEOMETRY["groupTitleClearance"] for that reason. */
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {s["md"]}px;
    padding: 0px {s["sm"]}px;
    color: {p["text"]};
    background-color: transparent;
}}

/* --- Labels --------------------------------------------- */

QLabel {{
    background-color: transparent;
    color: {p["text"]};
    padding: {s["xs"]}px;
}}

QLabel[muted="true"] {{
    color: {p["textMuted"]};
}}

QLabel[role="title"] {{
    font-size: 12pt;
    font-weight: bold;
    color: {p["text"]};
}}

/* Semantic text roles — the accent/success/warning/danger colours as
   foreground, so a status line reads correctly on the dark surface.
   Purely visual: no widget's text or behaviour is changed here. */
QLabel[role="success"] {{
    color: {p["success"]};
}}

QLabel[role="warning"] {{
    color: {p["warning"]};
}}

QLabel[role="danger"] {{
    color: {p["danger"]};
}}

QLabel[role="accent"] {{
    color: {p["accent"]};
}}

/* — Navigation panel (sidebar) ------------------------------------------- */

QFrame#navPanel {{
    background-color: {p["surface"]};
    border-right: 1px solid {p["border"]};
}}

/* --- Buttons -------------------------------------------- */

QPushButton {{
    background-color: {p["surfaceAlt"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: {radius_small}px;
    padding: 0px {s["md"]}px;
    min-height: {control_h}px;
}}

QPushButton:hover {{
    background-color: {surface_hover};
    border-color: {p["textMuted"]};
}}

QPushButton:pressed {{
    background-color: {p["border"]};
}}

QPushButton:disabled {{
    color: {p["textMuted"]};
    background-color: {p["surface"]};
    border-color: {p["border"]};
}}

QPushButton:checked {{
    background-color: {p["accent"]};
    border-color: {p["accent"]};
    color: #ffffff;
}}

/* — Empty-state panel -------------------------------------------------- */

QFrame#panel {{
    background-color: {p["surface"]};
    border: 1px solid {p["border"]};
    border-radius: {radius}px;
    padding: {s["lg"]}px;
}}

QLabel[labelType="emptyTitle"] {{
    color: {p["text"]};
}}

QLabel[labelType="emptyDesc"] {{
    color: {p["textMuted"]};
    margin-top: {s["md"]}px;
}}

QPushButton[variant="primary"] {{
    background-color: {p["accent"]};
    border-color: {p["accent"]};
    color: #ffffff;
    font-weight: bold;
}}

QPushButton[variant="primary"]:hover {{
    background-color: {accent_hover};
    border-color: {accent_hover};
}}

QPushButton[variant="primary"]:pressed {{
    background-color: {accent_pressed};
    border-color: {accent_pressed};
}}

QPushButton[variant="primary"]:disabled {{
    background-color: {p["surfaceAlt"]};
    border-color: {p["border"]};
    color: {p["textMuted"]};
}}

QPushButton[variant="danger"] {{
    background-color: {p["danger"]};
    border-color: {p["danger"]};
    color: #ffffff;
    font-weight: bold;
}}

QPushButton[variant="danger"]:hover {{
    background-color: {danger_hover};
    border-color: {danger_hover};
}}

QPushButton[variant="danger"]:pressed {{
    background-color: {danger_pressed};
    border-color: {danger_pressed};
}}

QPushButton[variant="danger"]:disabled {{
    background-color: {p["surfaceAlt"]};
    border-color: {p["border"]};
    color: {p["textMuted"]};
}}

/* --- Radio buttons / check boxes ------------------------- */

/* UI-10: side radio buttons — BUY reads green, SELL reads red. The
   colours are the existing success/danger palette tokens; only the
   variant-keyed rules are new. */
QRadioButton[variant="buy"] {{
    color: {p["success"]};
}}

QRadioButton[variant="sell"] {{
    color: {p["danger"]};
}}

QRadioButton, QCheckBox {{
    background-color: transparent;
    color: {p["text"]};
    spacing: {s["sm"]}px;
    padding: {s["xs"]}px;
}}

QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p["border"]};
    border-radius: {radius_small}px;
    background-color: {p["surfaceAlt"]};
}}

QRadioButton::indicator:checked {{
    background-color: {p["accent"]};
    border-color: {p["accent"]};
}}

QCheckBox::indicator {{
    border-radius: 4px;
}}

QCheckBox::indicator:checked {{
    background-color: {p["accent"]};
    border-color: {p["accent"]};
}}

QRadioButton:disabled, QCheckBox:disabled {{
    color: {p["textMuted"]};
}}

/* --- Line edits ----------------------------------------- */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {p["surfaceAlt"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: {radius_small}px;
    padding: 0px {s["sm"]}px;
    min-height: {control_h}px;
    selection-background-color: {p["accent"]};
    selection-color: #ffffff;
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {p["accent"]};
}}

QLineEdit:read-only, QPlainTextEdit:read-only, QTextEdit:read-only,
QSpinBox:read-only, QDoubleSpinBox:read-only {{
    background-color: {p["surface"]};
    color: {p["textMuted"]};
}}

QLineEdit[variant="invalid"], QSpinBox[variant="invalid"],
QDoubleSpinBox[variant="invalid"] {{
    border-color: {p["danger"]};
    background-color: {p["danger"]};
    color: #ffffff;
}}

QLineEdit::placeholder {{
    color: {p["textMuted"]};
}}

/* --- Combo box ------------------------------------------ */

QComboBox {{
    background-color: {p["surfaceAlt"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: {radius_small}px;
    padding: 0px {s["sm"]}px;
    min-height: {control_h}px;
}}

QComboBox:hover {{
    border-color: {p["textMuted"]};
}}

QComboBox:focus {{
    border-color: {p["accent"]};
}}

QComboBox:disabled {{
    color: {p["textMuted"]};
    background-color: {p["surface"]};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center left;
    width: 22px;
    background-color: {p["surface"]};
    border-left: 1px solid {p["border"]};
    border-top-left-radius: {radius_small}px;
    border-bottom-left-radius: {radius_small}px;
}}

QComboBox::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p["textMuted"]};
    margin-right: 6px;
}}

QComboBox QAbstractItemView {{
    background-color: {p["surfaceAlt"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    selection-background-color: {p["accent"]};
    selection-color: #ffffff;
    outline: none;
}}

/* --- Lists ----------------------------------------------- */

QListWidget, QTreeWidget, QTableView {{
    background-color: {p["surfaceAlt"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: {radius_small}px;
    outline: none;
}}

QListWidget::item, QTreeWidget::item {{
    padding: {s["xs"]}px {s["sm"]}px;
    border-radius: 4px;
    color: {p["text"]};
}}

QListWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {p["accent"]};
    color: #ffffff;
}}

QListWidget::item:hover, QTreeWidget::item:hover {{
    background-color: {surface_hover};
}}

/* --- Tables ---------------------------------------------- */

QTableWidget, QTableView {{
    background-color: {p["surfaceAlt"]};
    alternate-background-color: {p["surface"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: {radius_small}px;
    gridline-color: {p["border"]};
    outline: none;
}}

QTableWidget::item, QTableView::item {{
    padding: {s["xs"]}px {s["sm"]}px;
    color: {p["text"]};
    border: none;
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {p["accent"]};
    color: #ffffff;
}}

QTableWidget::item:hover, QTableView::item:hover {{
    background-color: {surface_hover};
}}

QHeaderView {{
    background-color: {p["surface"]};
}}

QHeaderView::section {{
    background-color: {p["surface"]};
    color: {p["textMuted"]};
    border: none;
    border-bottom: 1px solid {p["border"]};
    border-right: 1px solid {p["border"]};
    padding: {s["sm"]}px;
    font-weight: bold;
    text-align: center;
}}

QHeaderView::section:hover {{
    color: {p["text"]};
    background-color: {p["surfaceAlt"]};
}}

QTableCornerButton::section {{
    background-color: {p["surface"]};
    border: none;
    border-bottom: 1px solid {p["border"]};
}}

/* --- Scroll areas and scroll bars ------------------------ */

QScrollArea {{
    background-color: {p["background"]};
    border: none;
}}

QScrollBar:vertical {{
    background-color: {p["background"]};
    width: 12px;
    margin: 0px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background-color: {p["border"]};
    min-height: 28px;
    border-radius: 6px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {p["textMuted"]};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    background-color: {p["background"]};
    height: 0px;
    border: none;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background-color: transparent;
}}

QScrollBar:horizontal {{
    background-color: {p["background"]};
    height: 12px;
    margin: 0px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background-color: {p["border"]};
    min-width: 28px;
    border-radius: 6px;
    margin: 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {p["textMuted"]};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    background-color: {p["background"]};
    width: 0px;
    border: none;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background-color: transparent;
}}

/* --- Status bar ------------------------------------------ */

QStatusBar {{
    background-color: {p["surface"]};
    color: {p["textMuted"]};
    border-top: 1px solid {p["border"]};
}}

QStatusBar::item {{
    border: none;
}}

/* --- Tabs / progress / separators ------------------------ */

QTabWidget::pane {{
    border: 1px solid {p["border"]};
    border-radius: {radius_small}px;
    background-color: {p["surface"]};
}}

QTabBar::tab {{
    background-color: {p["surface"]};
    color: {p["textMuted"]};
    border: 1px solid {p["border"]};
    border-bottom: none;
    border-top-left-radius: {radius_small}px;
    border-top-right-radius: {radius_small}px;
    padding: {s["sm"]}px {s["md"]}px;
    min-height: {control_h}px;
}}

QTabBar::tab:selected {{
    background-color: {p["surfaceAlt"]};
    color: {p["text"]};
}}

QProgressBar {{
    background-color: {p["surfaceAlt"]};
    border: 1px solid {p["border"]};
    border-radius: {radius_small}px;
    text-align: center;
    color: {p["text"]};
    min-height: {control_h}px;
}}

QProgressBar::chunk {{
    background-color: {p["accent"]};
    border-radius: {radius_small}px;
}}

QToolTip {{
    background-color: {p["surfaceAlt"]};
    color: {p["text"]};
    border: 1px solid {p["accent"]};
    padding: {s["xs"]}px;
}}

QSplitter::handle {{
    background-color: {p["border"]};
}}

QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {p["border"]};
}}

/* --- Menu / message box ---------------------------------- */

QMenu {{
    background-color: {p["surfaceAlt"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    padding: {s["xs"]}px;
}}

QMenu::item:selected {{
    background-color: {p["accent"]};
}}

QMessageBox {{
    background-color: {p["background"]};
}}

QMessageBox QLabel {{
    color: {p["text"]};
}}
""".strip()


#: The generated stylesheet. Built once at import time — it is a pure
#: string derived from module-level tokens, so it never goes stale.
STYLESHEET = _build_stylesheet()


def stylesheet():
    """Return the complete QSS string of the dark theme."""
    return STYLESHEET


# ============================================================
# 3. Applying the theme
# ============================================================


def primary_font():
    """Return the QFont of the approved family chain at the base size."""
    font = QFont()
    font.setFamilies(list(FONT_FAMILY_CHAIN))
    font.setPointSize(BASE_FONT_SIZE)
    return font


def apply_font(target):
    """
    Apply the font chain to a QApplication or to any QWidget.

    Returns the target, so it can be chained. Never raises if the font is
    not installed: Qt falls back through the chain on its own.
    """
    if target is None:
        return target
    font = primary_font()
    if isinstance(target, QApplication):
        target.setFont(font)
    elif isinstance(target, QWidget):
        target.setFont(font)
    return target


def apply_theme(target):
    """
    Apply the dark theme to a QApplication, a QMainWindow or any QWidget.

    Works for both, because several existing tests build a page or the whole
    MainWindow directly without ever calling ``create_app()`` — the widget
    then has no application-level stylesheet and would stay unthemed.

    Passing a QApplication sets the palette-wide font too; passing a widget
    only styles that widget and its children, leaving the rest of the
    process untouched.

    Returns the target, so it can be chained.
    """
    if target is None:
        return target
    if isinstance(target, QApplication):
        target.setStyleSheet(STYLESHEET)
        apply_font(target)
    elif isinstance(target, QWidget):
        target.setStyleSheet(STYLESHEET)
        apply_font(target)
    return target
