"""
ui/main_window.py — UI-1 Main Window of the User Application.

PySide6 main window shell with:

    * a designated Navigation area (Home / Accounts / Settings placeholders),
    * a designated, extensible Content area where the real pages of
      UI-2 ... UI-8 will later be placed,
    * an explicit Application Mode (NORMAL / DIAGNOSTIC).

Foundation scope only (UI-1):

    * Navigation entries display placeholder pages only — no Account
      Management, Broker Management, Settings, Symbol Search or Order
      functionality exists.
    * Only the mode STATE and STRUCTURE exist; real Diagnostic capabilities
      (Trace ID, Latency, Execution details, Core/Broker/M6 diagnostics)
      belong to UI-6.
    * No core/, brokers/, market/, models/ or main.py import; no network,
      login, credential, broker API or TSETMC access of any kind.
"""

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class ApplicationMode(Enum):
    """
    Explicit User Application mode.

    UI-1 defines only the state and structure; actual Diagnostic-mode
    capabilities are UI-6 scope.
    """

    NORMAL = "NORMAL"
    DIAGNOSTIC = "DIAGNOSTIC"


# Navigation placeholders (UI-1). No real functionality behind them yet.
NAVIGATION_ITEMS = ("Home", "Accounts", "Settings")


class MainWindow(QMainWindow):
    """
    Main Window of the User Application.

    Structure:

        + ------------------------------------------------- +
        | navigation panel  |  content area (current page)  |
        |  Home             |                               |
        |  Accounts         |   designated, extensible      |
        |  Settings         |   area for the real pages of  |
        |                   |   UI-2 ... UI-8               |
        + ------------------------------------------------- +

    The window is a pure presentation shell: constructing it performs no
    network, login, credential, broker API or TSETMC access and imports no
    trading module.
    """

    def __init__(self, mode=ApplicationMode.NORMAL):
        super().__init__()

        if not isinstance(mode, ApplicationMode):
            raise ValueError(
                "Invalid initial application mode: "
                f"{mode!r} (expected ApplicationMode.NORMAL "
                "or ApplicationMode.DIAGNOSTIC)"
            )
        self.mode = mode

        # ---------------------------------------------
        # Window identity / initial logical size
        # ---------------------------------------------

        self.setWindowTitle("Trading Bot \u2014 User Application")
        self.resize(1024, 680)
        self.setMinimumSize(800, 560)

        # ---------------------------------------------
        # Main layout: Navigation area | Content area
        # ---------------------------------------------

        central_widget = QWidget(self)
        root_layout = QHBoxLayout(central_widget)

        self.navigation_area = QWidget(central_widget)
        self.navigation_area.setFixedWidth(180)
        navigation_layout = QVBoxLayout(self.navigation_area)

        self.content_area = QStackedWidget(central_widget)

        root_layout.addWidget(self.navigation_area)
        root_layout.addWidget(self.content_area, stretch=1)
        self.setCentralWidget(central_widget)

        # ---------------------------------------------
        # Navigation placeholders (Home / Accounts / Settings)
        # ---------------------------------------------

        self.nav_buttons = {}
        self.placeholder_pages = {}

        for name in NAVIGATION_ITEMS:
            button = QPushButton(name, self.navigation_area)
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, page_name=name: self.select_page(page_name)
            )
            self.nav_buttons[name] = button
            navigation_layout.addWidget(button)

        navigation_layout.addStretch(1)

        for name in NAVIGATION_ITEMS:
            page = QLabel(
                f"{name}\n\n(placeholder \u2014 implemented in a later UI task)",
                self.content_area,
            )
            page.setAlignment(Qt.AlignCenter)
            page.setWordWrap(True)
            self.placeholder_pages[name] = page
            self.content_area.addWidget(page)

        self.select_page(NAVIGATION_ITEMS[0])

        # ---------------------------------------------
        # Application Mode — simple display of the current mode
        # ---------------------------------------------

        self.mode_label = QLabel(self)
        self.statusBar().addPermanentWidget(self.mode_label)
        self._update_mode_label()

    # ---------------------------------------------------------
    # Navigation (placeholder display only)
    # ---------------------------------------------------------

    def select_page(self, name):
        """Show the placeholder page of a navigation entry (no-op if unknown)."""
        page = self.placeholder_pages.get(name)
        if page is None:
            return
        self.content_area.setCurrentWidget(page)
        for entry_name, button in self.nav_buttons.items():
            button.setChecked(entry_name == name)

    # ---------------------------------------------------------
    # Application Mode (NORMAL / DIAGNOSTIC) — state and structure only
    # ---------------------------------------------------------

    def set_mode(self, mode):
        """
        Set the application mode.

        UI-1 stores and simply displays the mode only; no diagnostic
        feature is attached to it in this task (UI-6 scope).
        """
        if not isinstance(mode, ApplicationMode):
            raise ValueError(
                f"Invalid application mode: {mode!r} "
                "(expected ApplicationMode.NORMAL or ApplicationMode.DIAGNOSTIC)"
            )
        self.mode = mode
        self._update_mode_label()
        return self.mode

    def _update_mode_label(self):
        self.mode_label.setText(f"Mode: {self.mode.value}")
