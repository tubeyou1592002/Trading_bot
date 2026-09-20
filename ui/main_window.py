"""
ui/main_window.py — Main Window of the User Application.

PySide6 main window shell with:

    * a designated Navigation area (Home / Accounts / Settings),
    * a designated Content area holding the current page,
    * an explicit Application Mode (NORMAL / DIAGNOSTIC).

Page architecture (since UI-2.1):

    pages                — all pages of the application
        Home             — placeholder (real Home arrives in a later task)
        Accounts         — the real AccountsPage (UI-2.1: in-memory account
                           management via ui.account_store.AccountStore)
        Settings         — placeholder (real Settings arrives later)

    placeholder_pages    — only the placeholder pages (Home / Settings)

    * Navigation, Content structure and ``select_page`` are the single,
      unchanged navigation mechanism of UI-1.
    * The Accounts page performs no broker instantiation, no
      BrokerManager usage and no network/login/credential access; it only
      mirrors the in-memory AccountStore (Decision 024).
    * Only the mode STATE and STRUCTURE exist; real Diagnostic capabilities
      (Trace ID, Latency, Execution details, Core/Broker/M6 diagnostics)
      belong to UI-6.
    * No brokers/, market/ or main.py import and no network, login,
      credential, broker API or TSETMC access of any kind.
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

from ui.account_store import AccountStore
from ui.accounts_page import AccountsPage
from ui.order_config_state import OrderConfiguration
from ui.order_configuration_page import OrderConfigurationPage


class ApplicationMode(Enum):
    """
    Explicit User Application mode.

    UI-1 defines only the state and structure; actual Diagnostic-mode
    capabilities are UI-6 scope.
    """

    NORMAL = "NORMAL"
    DIAGNOSTIC = "DIAGNOSTIC"


# Navigation entries of the User Application (order = navigation order).
# "Order Configuration" was added by UI-3.1 after the existing entries;
# the original UI-1 order is preserved.
NAVIGATION_ITEMS = ("Home", "Accounts", "Order Configuration", "Settings")

# Entries whose page is still a placeholder (Home/Settings). Accounts is a
# real page since UI-2.1; Order Configuration is real since UI-3.1.
PLACEHOLDER_ITEMS = ("Home", "Settings")


class MainWindow(QMainWindow):
    """
    Main Window of the User Application.

    Structure:

        + ------------------------------------------------- +
        | navigation panel  |  content area (current page)  |
        |  Home             |                               |
        |  Accounts         |   AccountsPage (real, UI-2.1) |
        |  Order Config.    |   OrderConfigurationPage      |
        |  Settings         |   (UI-3.1) + placeholders     |
        |                   |   (later UI-2 ... UI-8 pages) |
        + ------------------------------------------------- +

    The window is presentation only: constructing it performs no network,
    login, credential, broker API or TSETMC access and instantiates no
    broker.
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
        # In-memory application state (UI-2.1)
        # ---------------------------------------------

        self.account_store = AccountStore()

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
        # Navigation buttons (Home / Accounts / Settings)
        # ---------------------------------------------

        self.nav_buttons = {}

        for name in NAVIGATION_ITEMS:
            button = QPushButton(name, self.navigation_area)
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, page_name=name: self.select_page(page_name)
            )
            self.nav_buttons[name] = button
            navigation_layout.addWidget(button)

        navigation_layout.addStretch(1)

        # ---------------------------------------------
        # Pages — Accounts is real (UI-2.1); Home/Settings are placeholders
        # ---------------------------------------------

        self.pages = {}
        self.placeholder_pages = {}

        for name in PLACEHOLDER_ITEMS:
            page = QLabel(
                f"{name}\n\n(placeholder \u2014 implemented in a later UI task)",
                self.content_area,
            )
            page.setAlignment(Qt.AlignCenter)
            page.setWordWrap(True)
            self.pages[name] = page
            self.placeholder_pages[name] = page
            self.content_area.addWidget(page)

        self.accounts_page = AccountsPage(self.account_store, self.content_area)
        self.pages["Accounts"] = self.accounts_page
        self.content_area.addWidget(self.accounts_page)

        # Order Configuration (UI-3.1): form/state only — no execution,
        # no Order object, no Core/Broker/TSETMC access.
        self.order_config = OrderConfiguration()
        self.order_configuration_page = OrderConfigurationPage(
            self.account_store,
            config=self.order_config,
            parent=self.content_area,
        )
        self.pages["Order Configuration"] = self.order_configuration_page
        self.content_area.addWidget(self.order_configuration_page)

        self.select_page(NAVIGATION_ITEMS[0])

        # ---------------------------------------------
        # Application Mode — simple display of the current mode
        # ---------------------------------------------

        self.mode_label = QLabel(self)
        self.statusBar().addPermanentWidget(self.mode_label)
        self._update_mode_label()

    # ---------------------------------------------------------
    # Navigation (single navigation mechanism, unchanged)
    # ---------------------------------------------------------

    def select_page(self, name):
        """Show the page of a navigation entry (no-op if unknown)."""
        page = self.pages.get(name)
        if page is None:
            return
        # UI-3.1: re-read live state when re-entering a page. The Order
        # Configuration page re-mirrors the active account verbatim from
        # the shared UI-2.1 AccountStore — never guessed from an index,
        # symbol or broker.
        if name == "Order Configuration":
            self.order_configuration_page.refresh_active_account()
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
