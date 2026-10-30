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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
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

    def __init__(self, mode=ApplicationMode.NORMAL, *, account_store=None):
        super().__init__()

        if not isinstance(mode, ApplicationMode):
            raise ValueError(
                "Invalid initial application mode: "
                f"{mode!r} (expected ApplicationMode.NORMAL "
                "or ApplicationMode.DIAGNOSTIC)"
            )
        self.mode = mode

        # ---------------------------------------------
        # Application account state (UI-2.1 + persistence)
        # ---------------------------------------------
        # The real application defaults to the persistent store so the
        # account list and its display order survive restarts (only
        # non-sensitive metadata is stored). Tests inject an in-memory or
        # temporary-database store through ``account_store`` so they never
        # touch the real per-user database.

        self.account_store = (
            account_store
            if account_store is not None
            else AccountStore.persistent_default()
        )

        # ---------------------------------------------
        # Lazy shared BrokerManager (UI-5 Task 4 Stage 3 prerequisite)
        # ---------------------------------------------
        # One BrokerManager per MainWindow instance, created only on first
        # actual request. Every lazy factory below returns the SAME manager
        # instance, so the account-scoped broker that receives OMS feedback
        # (via OrderFeedbackService) is the exact same instance used by the
        # order execution path (via TestRunner -> DispatchCore ->
        # broker_manager.get_for_account(account_id, broker_name)).
        self._broker_manager_cache = None
        # Block 9 Task 9B: ONE feedback runtime per (account_id, broker_name),
        # created lazily and cached. Constructed empty here — building the
        # window composes no service (offline/lazy contract preserved).
        self._feedback_services = {}
        self._authentication_service = None
        self._credential_store = None
        self._session_manager = None

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

        self.navigation_area = QFrame(central_widget)
        self.navigation_area.setObjectName("navPanel")
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
            panel = QFrame(self.content_area)
            panel.setObjectName("panel")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)

            title = QLabel(STRINGS.nav_display(name), panel)
            title.setProperty("labelType", "emptyTitle")
            # UI-9.5 fix 1: the empty-state is a CENTRED GROUP (title above,
            # description below), not two full-width stretched labels. Keep
            # each label at its natural height and let flexible space above
            # and below collect the rest, so the group sits in the middle of
            # the card.
            title.setAlignment(Qt.AlignCenter)
            title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

            desc = QLabel(STRINGS.PLACEHOLDER_PAGE_BODY, panel)
            desc.setProperty("labelType", "emptyDesc")
            desc.setWordWrap(True)
            desc.setAlignment(Qt.AlignCenter)
            desc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

            panel_layout.addStretch(1)
            panel_layout.addWidget(title)
            panel_layout.addWidget(desc)
            panel_layout.addStretch(2)

            page = panel
            self.pages[name] = page
            self.placeholder_pages[name] = page
            self.content_area.addWidget(page)

        self.accounts_page = AccountsPage(
            self.account_store,
            self.content_area,
            authentication_service_factory=lambda: self.authentication_service,
            credential_store_factory=lambda: self.credential_store,
            session_manager_factory=lambda: self.session_manager,
            lifecycle_listener=self._on_account_lifecycle,
        )
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
        # UI-3.2B: display status is queried directly from TSETMC by
        # ins_code, lazily and independently of the selected account.
        self.order_configuration_page.set_trading_state_query_factory(
            self._real_tsetmc_trading_state_query
        )
        self.order_configuration_page.set_session_manager(lambda: self.session_manager)
        self.order_configuration_page.set_order_identity_factory(
            self._real_order_identity_resolver
        )
        self.order_configuration_page.set_buy_preview_factory(
            lambda account_id, broker_name: self.authentication_service
        )
        # UI-5 Task 2: the Test action drives its pending entries through
        # the EXISTING dry-run execution chain. The runner is built lazily
        # (only on the first real Test pass, never here), so construction
        # stays offline — no Core/Broker module is imported below.
        self.order_configuration_page.set_test_runner_factory(
            self._real_test_runner
        )
        # UI-5 Task 4 Stage 3 Task 3 / Block 9 Task 9B: bind the order log to
        # the EXISTING order-feedback path (matching-engine registration /
        # green row), now ACCOUNT-AWARE. The factory resolves the feedback
        # runtime of the exact (account_id, broker_name) the page is sending
        # for; it is called lazily on the first real send and only returns a
        # service when that account's session/authorization is valid, so the
        # page stays fully offline and the order gate is never weakened.
        self.order_configuration_page.set_feedback_binder_factory(
            self._feedback_binder_for_account
        )
        self.order_configuration_page.set_order_authorizer_factory(
            self._real_order_authorizer
        )
        self.order_configuration_page.set_live_readiness_factory(
            self._real_live_readiness
        )
        self.order_configuration_page.set_live_prearm_factory(
            self._real_live_prearm
        )
        self.order_configuration_page.set_manual_live_services(
            self._shared_broker_manager,
            lambda: self.authentication_service,
        )
        self.order_configuration_page.set_scheduled_runtime_factory(
            self._real_scheduled_runtime
        )
        self.order_configuration_page.set_scheduled_broker_manager_factory(
            self._shared_broker_manager
        )
        self.order_configuration_page.set_live_batch_gate_factory(
            self._real_live_batch_gate
        )
        self.order_configuration_page.set_live_batch_validator(
            self._real_validate_live_batch
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

    def _real_trading_state_query(self, account_id=None, broker_name=None):
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

        if account_id is None and broker_name is None:
            record = self._active_account_record()
            if record is None:
                raise ValueError("active account is unavailable")
            account_id, broker_name = record.account_id, record.broker_name
        if account_id is None or broker_name is None:
            raise ValueError("account binding is incomplete")
        manager = self._shared_broker_manager()
        broker = manager.get_for_account(account_id, broker_name)
        provider = manager.get_instrument_provider_for_account(
            account_id, broker_name
        )
        return TradingStateQuery(broker, provider)

    def _real_tsetmc_trading_state_query(self):
        """Lazily create the account-independent direct TSETMC query."""
        from core.trading_state_query import TsetmcTradingStateQuery

        return TsetmcTradingStateQuery()

    def _real_order_identity_resolver(self, account_id, broker_name):
        """Resolve the account-owned instrument provider lazily."""
        manager = self._shared_broker_manager()
        return manager.get_instrument_provider_for_account(account_id, broker_name)

    def _active_account_record(self):
        active_id = self.account_store.active_account_id()
        if active_id is None:
            return None
        try:
            return self.account_store.get(active_id)
        except ValueError:
            return None

    def _real_test_runner(self, *, live=False, safety_gate=None):
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
            broker_manager=self._shared_broker_manager(),
            live=live,
            safety_gate=safety_gate,
        )

    def _real_live_readiness(self, account_id, broker_name, *, human_approval):
        """Resolve Live readiness without inventing missing prerequisites.

        Account/session/authentication are checked by authorize_order, but no
        production provider supplies an authoritative pre-dispatch M6 result
        or a broker live-readiness contract. The broker's independent safety
        lock remains off. This seam therefore fails closed.
        """
        from ui.live_order_gate import check_live_readiness

        try:
            return check_live_readiness(
                account_store=self.account_store,
                authentication_service=self.authentication_service,
                session_manager=self.session_manager,
                broker_manager=self._shared_broker_manager(),
                account_id=account_id,
                broker_name=broker_name,
                explicit_live_request=True,
                human_approval=human_approval,
                prerequisite_provider=None,
            )
        except Exception:
            from ui.live_order_gate import LiveReadiness

            return LiveReadiness(
                False,
                "منبع معتبر وضعیت M6-A…M6-E پیش از ارسال و منبع رسمی آمادگی Live کارگزار متصل نیستند؛ وضعیت حساب/نشست جداگانه بررسی می‌شود.",
            )

    def _real_live_prearm(self, targets):
        """Lazily compose the no-submit preparation coordinator."""
        from ui.prearm_service import LivePrearmService

        return LivePrearmService(
            self.account_store, self.session_manager, self._shared_broker_manager()
        )

    def _real_scheduled_runtime(self, **kwargs):
        """Create a fresh private async runtime for one approved schedule."""
        from ui.scheduled_fire_runtime import ScheduledFireRuntime

        return ScheduledFireRuntime(**kwargs)

    def _real_live_batch_gate(self, **kwargs):
        from ui.live_order_gate import check_live_batch_readiness

        return check_live_batch_readiness(
            account_store=self.account_store,
            authentication_service=self.authentication_service,
            session_manager=self.session_manager,
            broker_manager=self._shared_broker_manager(),
            **kwargs,
        )

    def _real_validate_live_batch(self, **kwargs):
        from ui.live_order_gate import validate_live_batch_authorization

        return validate_live_batch_authorization(
            account_store=self.account_store,
            authentication_service=self.authentication_service,
            session_manager=self.session_manager,
            broker_manager=self._shared_broker_manager(),
            **kwargs,
        )

    def _real_order_authorizer(self):
        """Build the authorization gate only when an order action needs it."""
        from ui.order_authorization import authorize_order

        return lambda account_id, broker_name: authorize_order(
            self.account_store,
            self._authentication_service,
            self._session_manager,
            account_id,
            broker_name,
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

    @property
    def authentication_service(self):
        """Lazily compose the account-scoped authentication service graph."""
        if self._authentication_service is None:
            from importlib import import_module
            from ui.authentication_service import AuthenticationService

            manager = self._shared_broker_manager()
            make_agah_adapter_factory = import_module(
                "brokers.agaah.auth_adapter"
            ).make_agah_adapter_factory
            service = AuthenticationService(
                self.account_store,
                self.credential_store,
                self.session_manager,
                adapter_factories={
                    "آگاه": make_agah_adapter_factory(manager),
                },
            )
            self._authentication_service = service
        return self._authentication_service

    @property
    def credential_store(self):
        """Lazily create the one CredentialStore shared by this window."""
        if self._credential_store is None:
            from ui.credential_store import CredentialStore

            self._credential_store = CredentialStore()
        return self._credential_store

    @property
    def session_manager(self):
        """Lazily create the one SessionManager shared by this window."""
        if self._session_manager is None:
            from ui.session_manager import SessionManager

            self._session_manager = SessionManager()
        return self._session_manager

    # ---------------------------------------------------------
    # Block 9 Task 9B — account-aware order feedback lifecycle
    # ---------------------------------------------------------

    def _feedback_broker_factory(self, account_id, broker_name):
        """
        A zero-arg factory resolving the ACCOUNT-SCOPED broker.

        The broker is resolved through
        ``BrokerManager.get_for_account(account_id, broker_name)`` at the
        moment the service actually starts — never a name-only/global
        ``get(...)``. Deferring the ``BrokerManager`` construction into the
        closure keeps MainWindow construction fully offline.
        """

        def factory():
            return self._shared_broker_manager().get_for_account(
                account_id, broker_name
            )

        return factory

    def feedback_service_for_account(self, account_id, broker_name):
        """
        Lazily create and cache the feedback runtime of one account.

        Exactly one ``OrderFeedbackService`` per ``(account_id,
        broker_name)``: two accounts on the same broker get two independent
        services (and, via the broker factory, two independent broker
        runtimes). The service is created — but NOT started — here; nothing
        is imported or composed at MainWindow construction. Returns ``None``
        for an incomplete identity (fail-closed).
        """
        if not isinstance(account_id, str) or not account_id.strip():
            return None
        if not isinstance(broker_name, str) or not broker_name.strip():
            return None
        key = (account_id, broker_name)
        service = self._feedback_services.get(key)
        if service is None:
            from ui.order_feedback_service import OrderFeedbackService

            service = OrderFeedbackService(
                broker_factory=self._feedback_broker_factory(
                    account_id, broker_name
                ),
                account_id=account_id,
                broker_name=broker_name,
            )
            self._feedback_services[key] = service
        return service

    def _feedback_account_authorized(self, account_id, broker_name):
        """
        True only when the account has a usable session and a valid
        authorization — the EXISTING ``authorize_order`` gate, reused
        unchanged. Never raises; any failure is fail-closed (``False``) so a
        broken/absent feedback path can never crash the UI or weaken the
        order gate.
        """
        try:
            from ui.order_authorization import authorize_order

            result = authorize_order(
                self.account_store,
                self._authentication_service,
                self._session_manager,
                account_id,
                broker_name,
            )
            return bool(result.authorized)
        except Exception:
            return False

    def start_feedback_for_account(self, account_id, broker_name):
        """
        Start the feedback runtime for one account, but only when its
        session/authorization is valid.

        Returns the started service, or ``None`` when the account is not
        authorized (no service is even created in that case). Idempotent:
        starting an already-running account's service is a no-op. Starting
        one account never stops another account's runtime.
        """
        if not self._feedback_account_authorized(account_id, broker_name):
            return None
        service = self.feedback_service_for_account(account_id, broker_name)
        if service is None:
            return None
        try:
            service.start_service()
        except Exception:
            return None
        return service

    def stop_feedback_for_account(self, account_id, broker_name):
        """
        Stop (but keep cached) the feedback runtime of one account.

        Used on logout, account deletion and broker change. Only this
        account's runtime is stopped; every other account's runtime keeps
        running. Keeping the stopped service cached means a later re-login
        restarts the SAME object — and therefore never registers a second
        copy of its broker listeners.
        """
        service = self._feedback_services.get((account_id, broker_name))
        if service is None:
            return
        try:
            service.stop_service()
        except Exception:
            pass

    def stop_all_feedback_services(self):
        """Stop every feedback runtime built so far (window teardown)."""
        for service in list(self._feedback_services.values()):
            try:
                service.stop_service()
            except Exception:
                pass

    def _feedback_binder_for_account(self, account_id, broker_name):
        """
        The page's feedback-binder factory: the account-scoped runtime.

        Returns ``None`` unless the account is authorized, so the page fails
        closed (no listener, no green row) instead of ever binding to a
        different account's runtime.
        """
        return self.start_feedback_for_account(account_id, broker_name)

    def _on_account_lifecycle(self, event, account_id, broker_name):
        """
        React to AccountsPage lifecycle events (Block 9 Task 9B).

        Logout, deletion and broker change STOP the affected account's
        runtime only; other accounts are left untouched. Selecting an active
        account does NOT stop the previous account's runtime (its open
        orders may still receive feedback). Fail-safe: never raises.
        """
        try:
            if event in ("logout", "delete", "broker_changed"):
                page = getattr(self, "order_configuration_page", None)
                if page is not None:
                    page.on_broker_session_event(account_id, event)
            if event in ("logout", "delete", "broker_changed"):
                self.stop_feedback_for_account(account_id, broker_name)
        except Exception:
            pass

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
            # Block 9 Task 9B: start the ACTIVE account's runtime only, and
            # only when it has a usable session/authorization. Entering the
            # page never stops another account's runtime.
            record = self._active_account_record()
            if record is not None:
                self.start_feedback_for_account(
                    record.account_id, record.broker_name
                )
        self.content_area.setCurrentWidget(page)
        for entry_name, button in self.nav_buttons.items():
            button.setChecked(entry_name == name)

    def closeEvent(self, event):
        """
        Stop every feedback runtime when the window is closing.

        If none was ever created, closing is a no-op (no error).
        """
        self.stop_all_feedback_services()
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
