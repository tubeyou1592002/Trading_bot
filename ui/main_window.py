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
      belong to later UI-6 tasks. UI-6 Task 1 adds the DISPLAY BOUNDARY of
      those capabilities: a minimal, REAL diagnostic section on the Order
      Configuration page that is hidden in NORMAL mode and may be shown in
      DIAGNOSTIC mode, plus the mode toggle in the status bar.
    * No brokers/, market/ or main.py import and no network, login,
      credential, broker API or TSETMC access of any kind.
"""

from enum import Enum

from PySide6.QtCore import Qt, QTimer
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
from ui import strings as STRINGS
from ui.order_config_state import OrderConfiguration
from ui.order_configuration_page import OrderConfigurationPage
from ui.theme import apply_theme

# UI-7 Task 2 — delay between showing the window and the ONE startup clock
# sync. The sync must start only once the window is up and the event loop
# is running (never during construction, so building the UI stays offline),
# and it must not fire inside a bare ``processEvents()`` that a test may
# call right after ``show()``. Non-blocking: the request runs on a worker
# thread.
STARTUP_SYNC_DELAY_MS = 100


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
        # Lazy shared BrokerManager (UI-5 Task 4 Stage 3 prerequisite)
        # ---------------------------------------------
        # One BrokerManager per MainWindow instance, created only on first
        # actual request. Every lazy factory below returns the SAME manager
        # instance (and thus the SAME AgaahBroker), so the broker that
        # receives OMS feedback (via OrderFeedbackService) is the exact
        # same instance used by the order execution path (via TestRunner ->
        # DispatchCore -> broker_manager.get("آگاه")).
        self._broker_manager_cache = None
        self._feedback_service = None

        # ---------------------------------------------
        # Window identity / initial logical size
        # ---------------------------------------------

        self.setWindowTitle(STRINGS.WINDOW_TITLE)
        self.resize(1024, 680)
        self.setMinimumSize(800, 560)

        # ---------------------------------------------
        # UI-9 Task 1 — dark theme
        # ---------------------------------------------

        # Applied to the WINDOW (not only to the QApplication) so a
        # directly-constructed MainWindow is themed too: several existing
        # tests build the window without ever calling create_app().
        # Presentation only — no attribute, slot, string or logic change.
        apply_theme(self)

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
            # UI-9 Task 3: `name` stays the PAGE KEY (tests look pages up
            # by key). Only the DISPLAYED text is Persian.
            button = QPushButton(STRINGS.nav_display(name), self.navigation_area)
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
                f"{STRINGS.nav_display(name)}\n\n{STRINGS.PLACEHOLDER_PAGE_BODY}",
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

        # Order Configuration (UI-3.1/3.2A): form/state + REAL symbol
        # search through the existing market.SymbolResolver — resolved
        # lazily via the factory below, so construction stays offline.
        # No execution, no Order object, no Core/Broker access.
        self.order_config = OrderConfiguration()
        self.order_configuration_page = OrderConfigurationPage(
            self.account_store,
            config=self.order_config,
            parent=self.content_area,
        )
        self.order_configuration_page.set_resolver_factory(
            self._real_symbol_resolver
        )
        # UI-3.2B: the trading-state display reads the status through the
        # EXISTING read-only TradingStateQuery seam, built lazily (only
        # when a real state is actually queried) so construction stays
        # offline. No Order, no submission path, no ordering call.
        self.order_configuration_page.set_trading_state_query_factory(
            self._real_trading_state_query
        )
        # UI-5 Task 2: the Test action drives its pending entries through
        # the EXISTING dry-run execution chain. The runner is built lazily
        # (only on the first real Test pass, never here), so construction
        # stays offline — no Core/Broker module is imported below.
        self.order_configuration_page.set_test_runner_factory(
            self._real_test_runner
        )
        # UI-5 Task 4 Stage 3 Task 3: bind the order log to the EXISTING
        # order-feedback path (matching-engine registration / green row).
        # The factory hands the page the already-existing shared feedback
        # service object; the page connects lazily on the first real send
        # and only uses the signal's existence — nothing is started here.
        self.order_configuration_page.set_feedback_binder_factory(
            lambda: self.feedback_service
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
        # UI-6 Task 1: sync the page's diagnostic display boundary with the
        # INITIAL mode (NORMAL by default → section stays hidden).
        self.order_configuration_page.apply_mode(self.mode)

        # ---------------------------------------------
        # UI-6 Task 1 — the mode CHANGER of the existing Application Mode
        # ---------------------------------------------
        # UI-1 stored and displayed the mode state only; UI-6 Task 1 adds
        # the UI mechanism that changes it. The toggle mirrors the EXISTING
        # ApplicationMode state holder (self.mode / set_mode) — no new
        # architecture, no settings system, no separate state object.
        self.mode_toggle = QPushButton(STRINGS.BUTTON_DIAGNOSTIC_MODE, self)
        self.mode_toggle.setCheckable(True)
        self.mode_toggle.setToolTip(STRINGS.TOOLTIP_DIAGNOSTIC_MODE)
        self.mode_toggle.clicked.connect(self._on_mode_toggle_clicked)
        self.statusBar().addPermanentWidget(self.mode_toggle)
        self._sync_mode_toggle()

        # ---------------------------------------------
        # UI-7 Task 2 — startup clock sync (after show, once)
        # ---------------------------------------------
        # Construction performs NO network request; the single non-blocking
        # TSETMC clock sync is scheduled by ``showEvent`` below, i.e. once
        # the window is actually shown and the event loop is running. It is
        # deliberately NOT tied to opening the Order Configuration page.
        self._startup_sync_started = False
        self.startup_sync_delay_ms = STARTUP_SYNC_DELAY_MS

    # ---------------------------------------------------------
    # UI-7 Task 2 — startup clock sync
    # ---------------------------------------------------------

    def showEvent(self, event):
        """
        Schedule the one-shot, non-blocking startup clock sync.

        Fired only when the window is really shown (the application starts
        on the Home page), on the first turn of the event loop. The sync
        runs on a worker thread, so the GUI never blocks and no request is
        made during construction or import.
        """
        super().showEvent(event)
        if self._startup_sync_started:
            return
        self._startup_sync_started = True
        QTimer.singleShot(self.startup_sync_delay_ms, self._startup_clock_sync)

    def _startup_clock_sync(self):
        """Start the page's one-shot startup sync (idempotent)."""
        page = self.order_configuration_page
        start = getattr(page, "start_startup_sync", None)
        if callable(start):
            start()

    # ---------------------------------------------------------
    # Navigation (single navigation mechanism, unchanged)
    # ---------------------------------------------------------

    def _real_symbol_resolver(self):
        """
        Lazily build the REAL repository resolver (market.SymbolResolver).

        Called on the worker thread right before an actual search/resolve,
        so MainWindow construction itself never imports market/
        requests/TSETMC (offline contracts of UI-1..UI-3.1 preserved).
        The resolver is REUSED — never copied or re-implemented.
        """
        from market.symbol_resolver import SymbolResolver

        return SymbolResolver()

    def _real_trading_state_query(self):
        """
        Lazily build the REAL read-only trading-state query seam
        (core.trading_state_query.TradingStateQuery) backed by the shared
        BrokerManager broker/provider pair — the same path the Core
        already uses; nothing new is implemented here.

        Called on the worker thread right before an actual state query,
        so MainWindow construction never imports brokers/core (offline
        contracts of UI-1..UI-3.1 preserved). Read-only: it never
        creates, submits or dispatches an Order.
        """
        from core.trading_state_query import TradingStateQuery

        manager = self._shared_broker_manager()
        broker = manager.get("آگاه")
        provider = manager.get_instrument_provider("آگاه")
        return TradingStateQuery(broker, provider)

    def _real_test_runner(self):
        """
        Lazily build the REAL UI-5 Test runner, passing the shared
        BrokerManager so that DispatchCore resolves the SAME AgaahBroker
        instance that OrderFeedbackService listens on.

        Imported on the first real Test pass, never at MainWindow
        construction, so the offline UI contracts (UI-1..UI-3.1) stay
        intact: the runner itself imports the existing Core dispatch chain
        only when it actually runs.
        """
        from ui.test_runner import TestRunner

        return TestRunner(
            broker_manager=self._shared_broker_manager()
        )

    def _shared_broker_manager(self):
        """
        Lazily create and cache the single BrokerManager for this
        MainWindow instance.

        Created only on first call (never during construction), so
        MainWindow construction stays fully offline. Every subsequent
        call returns the exact same instance.
        """
        if self._broker_manager_cache is None:
            from brokers.manager import BrokerManager

            self._broker_manager_cache = BrokerManager()
        return self._broker_manager_cache

    def _real_feedback_broker_factory(self):
        """
        Return the shared AgaahBroker for OrderFeedbackService.

        The SAME BrokerManager.get("آگاه") instance that DispatchCore
        will resolve — guaranteeing decisionId registration and
        AcceptedByBourse feedback land on the same broker object.
        """
        return self._shared_broker_manager().get("آگاه")

    @property
    def feedback_service(self):
        """
        Lazily create and cache the OrderFeedbackService.

        Built only on first access (never during construction), using the
        shared AgaahBroker via ``_real_feedback_broker_factory``. The service
        is NOT started here — callers start it when feedback needs to be
        active (e.g. after authentication, or before order tracking).
        """
        if self._feedback_service is None:
            from ui.order_feedback_service import OrderFeedbackService

            self._feedback_service = OrderFeedbackService(
                broker_factory=self._real_feedback_broker_factory,
            )
        return self._feedback_service

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
            self.feedback_service.start_service()
        self.content_area.setCurrentWidget(page)
        for entry_name, button in self.nav_buttons.items():
            button.setChecked(entry_name == name)

    def closeEvent(self, event):
        """
        Stop the feedback service when the window is closing.

        If the service was never created, closing is a no-op (no error).
        """
        if self._feedback_service is not None:
            self._feedback_service.stop_service()
        event.accept()

    # ---------------------------------------------------------
    # Application Mode (NORMAL / DIAGNOSTIC) — state and structure only
    # ---------------------------------------------------------

    def set_mode(self, mode):
        """
        Set the application mode.

        Set the application mode.

        The state holder and label are the existing UI-1 mechanism.
        UI-6 Task 1 additionally keeps the Diagnostic-section display
        boundary of the Order Configuration page in sync with the mode:
        the section is hidden in NORMAL mode and may be shown in
        DIAGNOSTIC mode.
        """
        if not isinstance(mode, ApplicationMode):
            raise ValueError(
                f"Invalid application mode: {mode!r} "
                "(expected ApplicationMode.NORMAL or ApplicationMode.DIAGNOSTIC)"
            )
        self.mode = mode
        self._update_mode_label()
        self._sync_mode_toggle()
        # UI-6 Task 1: the display boundary of the real diagnostic section
        # follows the mode on every change (visibility only — the page's
        # ordering/queue/result/feedback behavior is never touched).
        self.order_configuration_page.apply_mode(mode)
        return self.mode

    def _update_mode_label(self):
        # UI-9 Task 3: the mode VALUE stays the Core/enum-owned English
        # token; only the surrounding label text is Persian.
        label = (
            STRINGS.MODE_DIAGNOSTIC
            if self.mode.value == "DIAGNOSTIC"
            else STRINGS.MODE_NORMAL
        )
        self.mode_label.setText(f"{STRINGS.MODE_LABEL_PREFIX} {label}")

    # ---------------------------------------------------------
    # UI-6 Task 1 — mode changer (reuses the existing ApplicationMode)
    # ---------------------------------------------------------

    def _on_mode_toggle_clicked(self, checked=False):
        """
        Apply the mode the user picked with the toggle.

        The single mode state stays ``self.mode`` (the existing UI-1
        holder, updated through the existing ``set_mode``); the toggle
        is the UI mirror of that state, nothing else.
        """
        self.set_mode(
            ApplicationMode.DIAGNOSTIC if self.mode_toggle.isChecked()
            else ApplicationMode.NORMAL
        )

    def _sync_mode_toggle(self):
        """Mirror the current mode state onto the toggle button."""
        self.mode_toggle.setChecked(self.mode is ApplicationMode.DIAGNOSTIC)
