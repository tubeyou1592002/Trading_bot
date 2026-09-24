"""
ui/order_configuration_page.py — UI-3.1/3.2A Order Configuration page.

Presentation of the order-configuration form:

    * Symbol       — editable input with REAL debounced symbol search
                     (UI-3.2A): typing triggers (after a 300 ms debounce,
                     the legacy application's existing pattern) a
                     background ``SymbolResolver.search()`` run on a
                     QThread; the resolver object is handed in lazily so
                     plain construction stays fully offline.
                     Selection stores ONLY a real resolver-produced
                     models.instrument.Instrument — the UI never parses
                     display text back into identity, never guesses
                     ``ins_code`` and never builds an instrument.
    * Symbol info  — display area for the selected instrument's
                     information, fed only from that real Instrument.
    * Symbol Status— display placeholder: "Not available" without a
                     verified source; NEVER shown as tradable/permitted
                     (real trading state is a LATER task — never touched
                     here).
    * Trading State — UI-3.2B: after a REAL instrument selection the
                     status is read from the EXISTING project path
                     (core.trading_state_query.TradingStateQuery →
                     provider.get_instrument → broker.get_trading_state
                     → TradingState) on a background QThread and
                     rendered ONLY from the returned ``TradingState``:
                     قابل معامله / غیرقابل معامله / نامشخص. Fail-closed:
                     TradingStateUnavailable and UNVERIFIED are shown as
                     نامشخص — never a crash, never "tradable". The raw
                     broker status mapping is never duplicated in the UI;
                     the state is never guessed from the symbol text,
                     and a changed/cleared symbol always drops the
                     previous instrument's state.
    * Side         — Buy / Sell radio pair bound to the real project
                     constants models.order.BUY / models.order.SELL
    * Price        — numeric input (basic input-level validation only)
    * Quantity     — numeric input (basic input-level validation only)
    * Base Amount  — price * quantity (display only; NOT the final amount)
    * Fee          — placeholder: "Not available" (no fee contract yet;
                     UI-3.3 scope)
    * Final Amount — placeholder: "Not available" (never fabricated)

    * Active account — read verbatim from the existing AccountStore
                     (UI-2.1); never guessed from an index/symbol/broker;
                     clearly shown when no account is active.
    * Order Queue  — UI-4: a real "Add to Queue" action that prepares ONE
                      models.order.Order (real nsc_id resolved through the
                      broker provider off the GUI thread) and appends it
                      to the EXISTING core.order_queue.OrderQueue together
                      with the active account/broker binding — plus a
                      visible queue list rendered ONLY from
                      ``OrderQueue.list_pending()`` (the exact queued
                      objects, never clones).
    * Test Button  — UI-5 Task 1: a UI-ONLY toggle next to the queue
                      controls. OFF -> "Test", ON -> "Test (On)". It holds
                      ONE UI-local boolean (Test Mode, default OFF) and is
                      disabled while the queue is empty or the required
                      active account / selected instrument is missing. It
                      must NEVER execute, dispatch, or submit an order —
                      no DispatchIntegration/DispatchCore/OrderEngine, no
                      broker call, no network activity (Task 2 owns
                      execution).

Stale-result protection (UI-3.2A): every search carries a monotonically
increasing sequence number; only the result of the LATEST sequence may
update the results list — an older, late-finishing result is discarded.

Stale-result protection (UI-4): a resolved nsc_id belongs to one
(ins_code, broker_name) pair only — a symbol change or an account
switch always drops it (fail-closed) and never binds another broker's
identity to the new selection.

Boundaries: no OrderEngine, DispatchCore, SafetyGate, BrokerManager
run for ordering, no Broker API call from the UI, and no direct TSETMC
access from the UI; the only market seam is the real ``SymbolResolver``
(search/resolve) run on a background thread, the only state seam is the
real ``TradingStateQuery`` (read-only) on a background thread, the only
identity seam is the broker ``InstrumentProvider.get_nsc_id(ins_code)``
(read-only, background thread) and the only holder is the existing
``OrderQueue`` (lazy — the first queue access, never at construction).
The UI creates an ``Order`` ONLY on the explicit Add-to-Queue action,
always fail-closed: without a selected Instrument, side, price,
quantity, resolved nsc_id and an active account nothing is queued.
"""

from models.order import BUY, SELL, Order
from models.trading_state import (
    TradingState,
    TradingStateUnavailable,
)

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ui.order_config_state import (
    SYMBOL_STATUS_NOT_AVAILABLE,
    OrderConfigError,
    OrderConfiguration,
)
from ui.symbol_search_worker import (
    SYMBOL_SEARCH_DEBOUNCE_MS,
    SymbolResolveWorker,
    SymbolSearchWorker,
)
from ui.trading_state_worker import TradingStateWorker

# User-facing side labels — mapped 1:1 to the real project constants.
SIDE_LABELS = ((BUY, "خرید"), (SELL, "فروش"))

# Result identity travels inside Qt.UserRole — display text is NEVER
# parsed back into symbol/ins_code.
RESULT_DATA_ROLE = Qt.UserRole

# The search generation a row belongs to — a row from a superseded
# generation (the user already retyped) can never be resolved into a
# selection, even if the caller keeps a reference to the old item.
RESULT_SEQUENCE_ROLE = Qt.UserRole + 1

# The three explicit, separated search states.
SEARCH_STATE_IDLE = ""
SEARCH_STATE_SEARCHING = "Searching…"
SEARCH_STATE_NO_RESULTS = "No symbols found"

# UI-3.2B — user-facing trading-state labels, rendered ONLY from the
# real ``TradingState`` the existing project path returned. The status
# is never guessed from the symbol text and the raw broker mapping
# stays inside the Core/broker path (Decision 020) — the UI renders
# only the three verdicts below. Fail-closed: an unavailable/unverified
# state is ALWAYS shown as unknown, never as tradable.
STATUS_LABEL_TRADABLE = "قابل معامله"
STATUS_LABEL_NOT_TRADABLE = "غیرقابل معامله"
STATUS_LABEL_UNKNOWN = "نامشخص"

# The status display before any query ran for the current selection.
STATUS_PENDING_LABEL = "در حال دریافت…"

# UI-4 — the visible queue row's data role carries the EXACT
# QueueEntry object; the display is never parsed back into an identity
# and the order is never reconstructed for rendering.
QUEUE_ENTRY_ROLE = Qt.UserRole + 2

# UI-4 — user-facing queue feedback. Status is plain text rendered on
# the page (no message box on a path that must stay fail-closed and
# deterministic offscreen).
QUEUE_STATUS_EMPTY = "No order queued yet — configure the form and click \"Add to Queue\""
QUEUE_STATUS_NO_ACCOUNT = "Cannot queue: no active account — select one on the Accounts page"
QUEUE_STATUS_NO_SYMBOL = "Cannot queue: no symbol selected"
QUEUE_STATUS_INCOMPLETE = "Cannot queue: complete side, price and quantity"
QUEUE_STATUS_NO_IDENTITY = "Cannot queue: the symbol's order identity is not resolved yet — reselect the symbol"
QUEUE_STATUS_BROKER_STALE = "Cannot queue: the order identity belongs to a different broker — reselect the symbol"
QUEUE_STATUS_QUEUED = "Order queued"


def _default_order_identity_resolver(account_store):
    """
    Lazily build the REAL broker ``InstrumentProvider`` that maps a
    TSETMC ``ins_code`` to a broker ``nscId``.

    The provider of the ACTIVE account's broker is used — the binding is
    never guessed and never fabricated. Nothing is built when no account
    is active (fail-closed: the caller treats it as "no identity"). The
    import is deferred so every page construction stays fully offline;
    the provider itself performs no network call here.
    """
    from brokers.manager import BrokerManager

    if account_store is None:
        return None
    active_id = account_store.active_account_id()
    if not active_id:
        return None
    try:
        record = account_store.get(active_id)
    except ValueError:  # AccountStoreError — never guess an identity
        return None
    return BrokerManager().get_instrument_provider(record.broker_name)


class _OrderIdentityWorker(QThread):
    """
    Resolves the broker ``nscId`` of one selected Instrument on a
    background thread, through the EXISTING read-only provider seam
    (``InstrumentProvider.get_nsc_id(ins_code)``).

    ``resolver_factory()`` must return the real provider (production) or
    a stub provider (tests). Plain ``run()`` thread: finishes by itself,
    fully deterministic. Anything unexpected — a failing factory, a
    missing resolver or a provider without a mapping — is reported as a
    failure; the string result is never fabricated in the UI.
    """

    # (ins_code, nsc_id) — the nsc_id string travels as ``object`` so it
    # is passed BY REFERENCE (no marshalling/copying of identity).
    identity_succeeded = Signal(str, object)
    # (ins_code, message) — resolution failed (no identity available).
    identity_failed = Signal(str, str)

    def __init__(self, ins_code, resolver_factory, parent=None):
        super().__init__(parent)
        self.ins_code = ins_code
        self._resolver_factory = resolver_factory

    def run(self):
        try:
            resolver = self._resolver_factory()
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.identity_failed.emit(self.ins_code, str(exc))
            return
        if resolver is None:
            # Fail-closed: no real identity source (e.g. no active
            # account → no broker). Nothing may be guessed/emitted.
            self.identity_failed.emit(
                self.ins_code, "no broker identity resolver available"
            )
            return
        try:
            nsc_id = resolver.get_nsc_id(self.ins_code)
        except Exception as exc:  # noqa: BLE001 — failure must never crash the UI
            self.identity_failed.emit(self.ins_code, str(exc))
            return
        if not isinstance(nsc_id, str) or not nsc_id:
            nsc_id = None
        self.identity_succeeded.emit(self.ins_code, nsc_id)


class OrderConfigurationPage(QWidget):
    """
    Order Configuration page (form and state only — no execution).
    """

    def __init__(
        self,
        account_store,
        config=None,
        order_queue=None,
        parent=None,
    ):
        super().__init__(parent)

        self.store = account_store
        self.config = config if config is not None else OrderConfiguration()
        self.symbol_text = ""

        # --- UI-3.2A: real symbol search state -------------------------
        self._resolver_factory = None  # set via set_resolver_factory()
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(SYMBOL_SEARCH_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._start_symbol_search)
        self._search_sequence = 0          # generation of the latest search
        self._active_search_threads = []   # live worker threads (tests wait on them)
        self._latest_results = []          # the real resolver result objects
        self._searching = False
        self._search_thread = None
        self._search_worker = None
        self._resolve_thread = None
        self._resolve_worker = None

        # --- UI-3.2B: real trading-state display state -----------------
        self._trading_state_factory = None  # set via set_trading_state_query_factory()
        self._trading_state_thread = None
        self._trading_state_worker = None
        self._trading_state_instrument = None  # ins_code the shown state belongs to
        self._trading_state_shown = None       # last TradingState actually rendered

        # --- UI-4: queue + order-identity state ------------------------
        # The EXISTING core OrderQueue is injected by tests (constructor
        # seams, like the resolver/query factories); production keeps
        # ``None`` and the page lazily builds the real queue on the FIRST
        # real Add-to-Queue action (never at construction — offline).
        self._injected_order_queue = order_queue
        self._default_queue = None
        # The nsc_id resolved for the CURRENT (ins_code, broker_name)
        # pair — captured OFF the GUI thread at selection time, so the
        # Add-to-Queue action itself never touches the network.
        self._order_identity_factory = None  # set via set_order_identity_factory()
        self._order_identity_thread = None
        self._order_identity_worker = None
        self._order_identity_instrument = None  # ins_code the nsc_id belongs to
        self._order_identity_broker = None      # broker the nsc_id belongs to
        self._order_nsc_id = None               # the resolved broker nscId

        root_layout = QVBoxLayout(self)

        # ---------------------------------------------
        # Active account (from the existing UI-2.1 store)
        # ---------------------------------------------

        account_group = QGroupBox("Active Account", self)
        account_layout = QHBoxLayout(account_group)
        self.active_account_label = QLabel(self._active_account_text(), account_group)
        account_layout.addWidget(self.active_account_label)
        account_layout.addStretch(1)
        root_layout.addWidget(account_group)

        # ---------------------------------------------
        # Order Configuration group
        # ---------------------------------------------

        form_group = QGroupBox("Order Configuration", self)
        form_grid = QGridLayout(form_group)

        # --- Symbol ---------------------------------------------
        form_grid.addWidget(QLabel("Symbol:", form_group), 0, 0)
        self.symbol_input = QComboBox(form_group)
        self.symbol_input.setEditable(True)
        self.symbol_input.lineEdit().setPlaceholderText(
            "e.g. \u0622\u06a9\u0648 — resolved by the Core in a later task"
        )
        self.symbol_input.lineEdit().textChanged.connect(self._on_symbol_edited)
        form_grid.addWidget(self.symbol_input, 0, 1)

        # --- Real search results (UI-3.2A) ------------------------
        self.search_status_label = QLabel(SEARCH_STATE_IDLE, form_group)
        self.results_list = QListWidget(form_group)
        self.results_list.setMaximumHeight(120)
        self.results_list.itemActivated.connect(self._on_result_selected)
        self.results_list.itemClicked.connect(self._on_result_selected)
        form_grid.addWidget(self.search_status_label, 0, 2)
        form_grid.addWidget(self.results_list, 0, 3)

        # --- Side ---------------------------------------------
        form_grid.addWidget(QLabel("Side:", form_group), 1, 0)
        side_row = QWidget(form_group)
        side_layout = QHBoxLayout(side_row)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_buttons = {}
        for side_value, label in SIDE_LABELS:
            button = QRadioButton(label, side_row)
            button.clicked.connect(
                lambda checked=False, s=side_value: self._on_side_selected(s)
            )
            self.side_buttons[side_value] = button
            side_layout.addWidget(button)
        side_layout.addStretch(1)
        form_grid.addWidget(side_row, 1, 1)

        # --- Price ---------------------------------------------
        form_grid.addWidget(QLabel("Price:", form_group), 2, 0)
        self.price_input = QLineEdit(form_group)
        self.price_input.setPlaceholderText("Rial — numeric")
        self.price_input.editingFinished.connect(self._on_price_changed)
        form_grid.addWidget(self.price_input, 2, 1)

        # --- Quantity ---------------------------------------------
        form_grid.addWidget(QLabel("Quantity:", form_group), 3, 0)
        self.quantity_input = QLineEdit(form_group)
        self.quantity_input.setPlaceholderText("numeric")
        self.quantity_input.editingFinished.connect(self._on_quantity_changed)
        form_grid.addWidget(self.quantity_input, 3, 1)

        # --- Add to Queue (UI-4) --------------------------------
        # Prepares ONE real Order (via the resolved nsc_id + the active
        # account binding) and appends it to the EXISTING OrderQueue.
        self.add_to_queue_button = QPushButton("Add to Queue", form_group)
        self.add_to_queue_button.clicked.connect(self._on_add_to_queue)
        form_grid.addWidget(self.add_to_queue_button, 4, 0, 1, 2)

        # --- Test Button (UI-5 Task 1) ------------------------------
        # UI-only toggle: OFF -> "Test", ON -> "Test (On)".
        # No execution, no dispatch, no broker/network activity.
        # Starts DISABLED: at construction there is nothing queued yet
        # (the lazy core.queue import must never run at construction).
        # The enable/disable refresh runs only on real UI flows.
        self.test_button = QPushButton("Test", form_group)
        self.test_button.setCheckable(True)
        self.test_button.setEnabled(False)
        self.test_button.clicked.connect(self._on_test_toggled)
        form_grid.addWidget(self.test_button, 4, 2)

        # Internal Test Mode state — UI-local only, initialized OFF.
        self._test_mode = False

        # --- UI-5 Task 2: dry-run execution wiring (offline until used) ---
        # The Test action runs its pending entries through the EXISTING
        # execution chain via the runner seam below. The runner is injected
        # like every other lazy seam (resolver / trading-state / queue): no
        # runner is built here, so construction and plain toggling stay
        # fully offline and never import Core/Broker modules. Production
        # MainWindow wires a lazy real runner; tests inject a fake one.
        self._test_runner_factory = None  # set via set_test_runner_factory()
        self._test_runner_instance = None
        # Outcome of the last Test action (Task 3 consumes these).
        self._last_test_run = None    # (plan, execution_id, result)
        self._last_test_entries = None
        self._last_test_error = None

        root_layout.addWidget(form_group)

        # ---------------------------------------------
        # Symbol information / status display area
        # ---------------------------------------------

        info_group = QGroupBox("Symbol Information", self)
        info_form = QFormLayout(info_group)

        self.symbol_name_label = QLabel("—", info_group)
        self.symbol_status_label = QLabel(
            f"Status: {SYMBOL_STATUS_NOT_AVAILABLE}", info_group
        )
        self.trading_state_label = QLabel("—", info_group)
        info_form.addRow("Name:", self.symbol_name_label)
        info_form.addRow("Status:", self.symbol_status_label)
        info_form.addRow("Trading State:", self.trading_state_label)

        root_layout.addWidget(info_group)

        # ---------------------------------------------
        # Amounts group
        # ---------------------------------------------

        amounts_group = QGroupBox("Amounts", self)
        amounts_form = QFormLayout(amounts_group)

        self.base_amount_label = QLabel("—", amounts_group)
        self.fee_label = QLabel("Not available", amounts_group)
        self.final_amount_label = QLabel("Not available", amounts_group)

        amounts_form.addRow("Base Amount:", self.base_amount_label)
        amounts_form.addRow("Fee:", self.fee_label)
        amounts_form.addRow("Final Amount:", self.final_amount_label)

        root_layout.addWidget(amounts_group)

        # ---------------------------------------------
        # Order Queue display (UI-4)
        # ---------------------------------------------

        queue_group = QGroupBox("Order Queue", self)
        queue_layout = QVBoxLayout(queue_group)

        self.queue_status_label = QLabel(QUEUE_STATUS_EMPTY, queue_group)
        queue_layout.addWidget(self.queue_status_label)

        # Visible pending-orders list — rendered ONLY from the existing
        # ``OrderQueue.list_pending()`` at refresh time; left untouched
        # at construction so no queue/core import ever runs offline.
        self.queue_list = QListWidget(queue_group)
        self.queue_list.setMaximumHeight(140)
        queue_layout.addWidget(self.queue_list)

        self.queue_count_label = QLabel("0 order(s) in queue", queue_group)
        queue_layout.addWidget(self.queue_count_label)

        root_layout.addWidget(queue_group)

        root_layout.addStretch(1)

        self._refresh_amounts()
        self._refresh_symbol_info()

    # ---------------------------------------------------------
    # Symbol typing / debounced REAL search (UI-3.2A)
    # ---------------------------------------------------------

    def set_resolver_factory(self, factory):
        """
        Provide the factory that builds the REAL ``SymbolResolver``.

        Production hands in ``None`` (the lazily created repository
        resolver is used); tests may inject a stub resolver factory so
        no network is ever touched. The factory is called on the worker
        thread, immediately before each real search/resolve.
        """
        self._resolver_factory = factory

    def set_trading_state_query_factory(self, factory):
        """
        Provide the factory that builds the REAL trading-state query
        seam (``core.trading_state_query.TradingStateQuery`` backed by
        the real broker/provider pair).

        Production hands in ``None`` (the lazily created repository
        query is used); tests may inject a stub factory so no network is
        ever touched. The factory is called on the worker thread,
        immediately before a real state query runs.
        """
        self._trading_state_factory = factory

    def set_order_identity_factory(self, factory):
        """
        Provide the factory that builds the REAL order-identity resolver
        (the broker ``InstrumentProvider`` exposing
        ``get_nsc_id(ins_code)``).

        Production hands in ``None`` (the lazily created provider for
        the ACTIVE account's broker is used); tests may inject a stub
        factory so no network is ever touched. The factory is called on
        the worker thread, immediately before a real resolution runs.
        """
        self._order_identity_factory = factory

    # ---------------------------------------------------------
    # UI-4: the existing core OrderQueue (lazy, never at construction)
    # ---------------------------------------------------------

    @property
    def order_queue(self):
        """
        The EXISTING ``core.order_queue.OrderQueue`` this page prepares
        orders into.

        Tests inject one through the constructor seam; production leaves
        it to the lazy default below. Accessing the queue for the first
        time imports ``core.order_queue`` — which happens on the first
        real Add-to-Queue action, NEVER at construction (the offline
        construction contracts stay intact).
        """
        if self._injected_order_queue is not None:
            return self._injected_order_queue
        return self._default_order_queue()

    def _default_order_queue(self):
        """Build the REAL repository queue once, lazily (on first use)."""
        if self._default_queue is None:
            from core.order_queue import OrderQueue

            self._default_queue = OrderQueue()
        return self._default_queue

    def _on_symbol_edited(self, text):
        """
        Mirror the typed symbol into the config as text only and (re)arm
        the debounce timer for a real background search.

        A new typing session never masquerades as the previous
        selection: the pending debounce is re-armed, and the stale
        selected instrument (no longer matching the new text) is dropped
        explicitly and deterministically.
        """
        symbol = (text or "").strip()
        self.symbol_text = symbol

        # New text invalidates EVERY in-flight generation immediately:
        # any search/resolve result that arrives after this point belongs
        # to a superseded request and may neither update the results list
        # nor (re)store a selection — a late resolve for text the user
        # has already replaced must never set selected_instrument.
        self._search_sequence += 1

        # The previously displayed results belong to the superseded
        # request: they are removed from the UI and their identity list
        # is dropped, so an old row can never be clicked into a new
        # selection ("typed text != selected instrument").
        self.results_list.clear()
        self._latest_results = []

        if not symbol:
            # Empty input: no search call at all; the pending debounce is
            # cancelled.
            self._debounce_timer.stop()
            self._set_search_status(SEARCH_STATE_IDLE)
            self.config.select_instrument(None)
            self._clear_trading_state()
            self._clear_order_identity()
            self._refresh_symbol_info()
            self._refresh_test_button_state()
            return

        # New text invalidates the previous selection explicitly: typed
        # text must never be treated as the previously selected
        # instrument until a real result is picked. The previous
        # trading state also belongs to the OLD instrument and must
        # never be attributed to the new text (UI-3.2B).
        self._set_search_status(SEARCH_STATE_IDLE)
        self.config.select_instrument(None)
        self._clear_trading_state()
        self._clear_order_identity()
        self._refresh_symbol_info()

        # Whitespace-only input never triggers a search.
        self._debounce_timer.start()

    def _set_search_status(self, text):
        self.search_status_label.setText(text)

    def _start_symbol_search(self):
        """Debounce fired: launch one real background search (if any)."""
        symbol = (self.symbol_input.currentText() or "").strip()
        if not symbol:
            # Debounce fired on empty/whitespace input → no search call.
            self._set_search_status(SEARCH_STATE_IDLE)
            return

        # Deterministic generation counter: only the latest sequence may
        # update the UI later (stale-result protection).
        self._search_sequence += 1
        sequence = self._search_sequence

        self._set_search_status(SEARCH_STATE_SEARCHING)

        # Plain QThread subclass: run() does the work and the thread
        # finishes by itself when run() returns — fully deterministic.
        worker = SymbolSearchWorker(
            symbol,
            sequence,
            resolver_factory=self._resolver_factory,
            parent=self,
        )
        self._search_worker = worker
        self._search_thread = worker
        self._active_search_threads.append(worker)
        worker.search_succeeded.connect(self._on_search_succeeded)
        worker.search_failed.connect(self._on_search_failed)
        # Lifecycle: the worker forgets ITSELF the moment its run()
        # returns (Qt emits ``finished`` on every completion path —
        # success, failure, or a result that will be discarded as
        # stale) — no worker/thread can linger on any path.
        worker.finished.connect(
            lambda w=worker: self._forget_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _forget_worker(self, worker):
        """Drop one finished worker from the live set (all paths)."""
        if worker in self._active_search_threads:
            self._active_search_threads.remove(worker)
        if self._search_thread is worker:
            self._search_thread = None
            self._search_worker = None
        if self._resolve_thread is worker:
            self._resolve_thread = None
            self._resolve_worker = None

    def _current_sequence(self):
        return self._search_sequence

    def _on_search_succeeded(self, sequence, results):
        """
        Apply a successful search ONLY if it is still the latest one.

        A stale result (an older sequence finishing after a newer search
        started) is discarded — it must never overwrite the newer
        result.
        """
        if sequence != self._search_sequence:
            return  # stale generation — discarded deterministically

        self._searching = False
        self.results_list.clear()
        self._latest_results = list(results)
        if not results:
            self._set_search_status(SEARCH_STATE_NO_RESULTS)
            return
        for index, result in enumerate(results):
            item = QListWidgetItem(
                f"{result.get('symbol') or ''} — {result.get('name') or ''}",
                self.results_list,
            )
            # The result's identity travels as the INDEX into the page's
            # shared list of the real resolver result objects — the
            # object itself never passes through a Qt signal (signals
            # marshall/copy payloads), and identity is never rebuilt by
            # parsing the display text. The row is also tagged with its
            # search generation so a superseded row can never resolve.
            item.setData(RESULT_DATA_ROLE, index)
            item.setData(RESULT_SEQUENCE_ROLE, sequence)
            self.results_list.addItem(item)
        self._set_search_status(SEARCH_STATE_IDLE)

    def _on_search_failed(self, sequence, message):
        """
        A failed search never crashes the UI and never shows stale
        results; a newer generation's results are untouched.
        """
        if sequence != self._search_sequence:
            return  # a stale failure must not clobber the newer state
        self._searching = False
        self.results_list.clear()
        self._set_search_status(f"Search failed: {message}")

    def _on_result_selected(self, item):
        """
        Resolve the picked REAL search result into a REAL Instrument via
        ``SymbolResolver.resolve()`` on the worker thread.

        Guards:
          * the row must belong to the CURRENT search generation — a row
            from a superseded generation (the user already retyped) is
            never resolved and never becomes a selection;
          * one resolve at a time — duplicate deliveries of the same
            interaction (itemClicked + itemActivated of one double-click)
            collapse into a single worker instead of racing into two.
        """
        try:
            row_sequence = item.data(RESULT_SEQUENCE_ROLE)
            index = item.data(RESULT_DATA_ROLE)
        except RuntimeError:
            # The row was deleted between the click and this delivery —
            # nothing to resolve, never a crash.
            return
        if row_sequence != self._search_sequence:
            return  # superseded generation — never resolve, never select
        if index is None:
            return  # never parse identity out of display text
        try:
            result = self._latest_results[index]
        except (IndexError, TypeError):
            return  # unknown/stale row — never guess an identity
        if result is None:
            return
        if self._resolve_thread is not None:
            return  # a resolve is already in flight — one worker only

        sequence = self._search_sequence
        self._set_search_status(SEARCH_STATE_SEARCHING)

        worker = SymbolResolveWorker(
            result,
            sequence,
            resolver_factory=self._resolver_factory,
            parent=self,
        )
        self._resolve_worker = worker
        self._resolve_thread = worker
        self._active_search_threads.append(worker)
        worker.resolve_succeeded.connect(self._on_resolve_succeeded)
        worker.resolve_failed.connect(self._on_resolve_failed)
        worker.finished.connect(
            lambda w=worker: self._forget_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def wait_for_workers(self, timeout_ms=5000):
        """
        Wait (bounded) for all background search/resolve threads to
        finish. Used by tests for deterministic teardown; production
        never needs to call this.
        """
        for thread in list(self._active_search_threads):
            if not thread.wait(timeout_ms):
                raise TimeoutError("symbol worker thread did not finish")

    def _on_resolve_succeeded(self, sequence, instrument):
        """Store the resolver-produced REAL Instrument (latest only)."""
        if sequence != self._search_sequence:
            return  # stale resolve — discarded
        # OrderConfiguration.select_instrument re-validates: only a real
        # models.instrument.Instrument is ever stored (fail-closed).
        try:
            self.config.select_instrument(instrument)
        except OrderConfigError as exc:
            # Never store a fabricated object; keep the previous state.
            self._set_search_status(f"Resolve failed: {exc}")
            return
        self._set_search_status(SEARCH_STATE_IDLE)
        self._refresh_symbol_info()
        self._start_trading_state_query(instrument)
        # UI-4: capture the broker nscId of THIS instrument off the GUI
        # thread now, so Add-to-Queue never performs a network call.
        self._start_order_identity_resolution(instrument)
        self._refresh_test_button_state()

    def _on_resolve_failed(self, sequence, message):
        """Resolve failure: previous selection stays, nothing fabricated."""
        if sequence != self._search_sequence:
            return
        self._set_search_status(f"Resolve failed: {message}")

    # ---------------------------------------------------------
    # Trading state display (UI-3.2B — read-only, fail-closed)
    # ---------------------------------------------------------

    def _clear_trading_state(self):
        """
        Drop the displayed trading state of the PREVIOUS instrument.

        The old status must never survive a symbol change or be
        attributed to the new typed text: the in-flight query for the
        old instrument is invalidated (its ins_code can no longer match
        the shown selection) and the display is reset.
        """
        self._trading_state_instrument = None
        self._trading_state_shown = None
        self._cancel_trading_state_query()
        self.trading_state_label.setText("\u2014")

    def _cancel_trading_state_query(self):
        """
        Invalidate any in-flight state query.

        The running worker finishes on its own (its result is discarded
        as stale by _on_trading_state_succeeded/failed) — no thread is
        killed, and the worker is reaped by its own finished-cleanup.
        """
        self._trading_state_worker = None
        self._trading_state_thread = None

    def _start_trading_state_query(self, instrument):
        """
        After a REAL instrument selection, read its trading state from
        the EXISTING project path on a background thread:

            TradingStateQuery(ins_code)
                → provider.get_instrument
                → broker.get_trading_state(nsc_id)
                → TradingState

        The status is rendered ONLY from the returned ``TradingState``;
        it is never guessed from the symbol text and the raw broker
        mapping is never duplicated here — the UI renders only the
        verdict the existing project path already decided. Any expected
        failure is shown as unknown — never a crash, never "tradable".
        """
        self._clear_trading_state()
        if instrument is None:
            return

        ins_code = getattr(instrument, "ins_code", None)
        if not ins_code:
            # No real identity → nothing to query; fail-closed display.
            self.trading_state_label.setText(STATUS_LABEL_UNKNOWN)
            return

        self._trading_state_instrument = ins_code
        self.trading_state_label.setText(STATUS_PENDING_LABEL)

        worker = TradingStateWorker(
            ins_code,
            query_factory=self._trading_state_factory,
            parent=self,
        )
        self._trading_state_worker = worker
        self._trading_state_thread = worker
        worker.state_succeeded.connect(self._on_trading_state_succeeded)
        worker.state_failed.connect(self._on_trading_state_failed)
        # Lifecycle: the worker forgets ITSELF the moment run() returns
        # (same self-reaping pattern as the search/resolve workers).
        worker.finished.connect(
            lambda w=worker: self._forget_trading_state_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _forget_trading_state_worker(self, worker):
        """Drop one finished trading-state worker (all paths)."""
        if self._trading_state_thread is worker:
            self._trading_state_thread = None
            self._trading_state_worker = None

    def wait_for_trading_state_workers(self, timeout_ms=5000):
        """
        Wait (bounded) for the background state query thread to finish.
        Used by tests for deterministic teardown; production never needs
        to call this.
        """
        thread = self._trading_state_thread
        if thread is not None and not thread.wait(timeout_ms):
            raise TimeoutError("trading-state worker thread did not finish")

    def _on_trading_state_succeeded(self, ins_code, state):
        """
        Render the returned ``TradingState`` — but ONLY if it still
        belongs to the currently selected instrument.

        A late result for a symbol the user already replaced is
        discarded: the old status can never be attributed to the new
        symbol or to bare typed text.
        """
        if ins_code != self._trading_state_instrument:
            return  # stale query — discarded deterministically
        if not isinstance(state, TradingState):
            # Anything unexpected from the seam is unknown (fail-closed).
            self._render_trading_state(STATUS_LABEL_UNKNOWN)
            return
        self._trading_state_shown = state
        self._render_trading_state(self._trading_state_text(state))

    def _on_trading_state_failed(self, ins_code, message):
        """
        The query seam reported a failure (e.g. the expected
        TradingStateUnavailable path): the UI must not crash and the
        status is shown as unknown — never tradable, never fabricated.
        """
        if ins_code != self._trading_state_instrument:
            return  # stale query — discarded deterministically
        self._trading_state_shown = None
        self._render_trading_state(STATUS_LABEL_UNKNOWN)

    @staticmethod
    def _trading_state_text(state):
        """
        Map a REAL ``TradingState`` to its user-facing label.

        Exactly the three fail-closed branches the project contract
        defines — no new vocabulary is invented here, and anything that
        is not a real ``TradingState`` is unknown (fail-closed):

            is_verified and allowed      → قابل معامله
            is_verified and not allowed  → غیرقابل معامله
            anything else (UNVERIFIED,
            unknown source, ...)         → نامشخص
        """
        if isinstance(state, TradingState):
            if state.is_verified and state.is_order_entry_allowed:
                return STATUS_LABEL_TRADABLE
            if state.is_verified:
                return STATUS_LABEL_NOT_TRADABLE
        return STATUS_LABEL_UNKNOWN

    def _render_trading_state(self, text):
        self.trading_state_label.setText(text)

    # ---------------------------------------------------------
    # Order identity (UI-4): broker nscId for the selected Instrument
    # ---------------------------------------------------------

    def _clear_order_identity(self):
        """
        Drop the resolved nscId of the PREVIOUS instrument/broker pair.

        An identity is scoped to one (ins_code, broker_name) — a symbol
        change or an account switch always drops it (its in-flight
        worker keeps running and its result is discarded as stale by the
        guards below). Never bound to a different selection.

        The running worker reference is deliberately KEPT (not cleared):
        the worker reaps ITSELF on ``finished``, and keeping the
        reference lets tests (and the page) wait on it deterministically.
        """
        self._order_identity_instrument = None
        self._order_identity_broker = None
        self._order_nsc_id = None

    def _start_order_identity_resolution(self, instrument):
        """
        Resolve the broker ``nscId`` of a REAL instrument selection on a
        background thread, through the EXISTING read-only seam:

            InstrumentProvider.get_nsc_id(ins_code)

        The result is stored ONLY for the (ins_code, broker_name) pair
        captured here; a late result for a replaced symbol or a changed
        account is never used (fail-closed).
        """
        if instrument is None:
            return

        ins_code = getattr(instrument, "ins_code", None)
        if not ins_code:
            # No real identity → nothing to resolve; fail-closed.
            self._clear_order_identity()
            return

        broker_name = self._active_broker_name()

        # A resolution for the SAME (ins_code, broker_name) pair is
        # already in flight — do not start a duplicate worker.
        if (
            self._order_identity_thread is not None
            and not self._order_identity_thread.isFinished()
            and self._order_identity_instrument == ins_code
            and self._order_identity_broker == broker_name
        ):
            return

        self._clear_order_identity()
        self._order_identity_instrument = ins_code
        self._order_identity_broker = broker_name

        factory = (
            self._order_identity_factory
            if self._order_identity_factory is not None
            else lambda: _default_order_identity_resolver(self.store)
        )

        worker = _OrderIdentityWorker(ins_code, factory, parent=self)
        self._order_identity_worker = worker
        self._order_identity_thread = worker
        worker.identity_succeeded.connect(self._on_order_identity_succeeded)
        worker.identity_failed.connect(self._on_order_identity_failed)
        # Lifecycle: the worker forgets ITSELF the moment run() returns
        # (same self-reaping pattern as the other workers).
        worker.finished.connect(
            lambda w=worker: self._forget_order_identity_worker(w)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _forget_order_identity_worker(self, worker):
        """Drop one finished identity worker (all paths)."""
        if self._order_identity_thread is worker:
            self._order_identity_thread = None
            self._order_identity_worker = None

    def wait_for_order_identity_workers(self, timeout_ms=5000):
        """
        Wait (bounded) for the background identity-resolution thread to
        finish. Used by tests for deterministic teardown; production
        never needs to call this.
        """
        thread = self._order_identity_thread
        if thread is not None and not thread.wait(timeout_ms):
            raise TimeoutError("order-identity worker thread did not finish")

    def _on_order_identity_succeeded(self, ins_code, nsc_id):
        """
        Store the resolved broker nscId — but ONLY if it still belongs
        to the currently selected (ins_code, broker_name) pair.

        A late resolution for a symbol the user already replaced, or for
        an account the user already switched, is discarded (fail-closed:
        an identity is never attached to a different selection).
        """
        if ins_code != self._order_identity_instrument:
            return  # stale resolution — discarded deterministically
        if self._order_identity_broker != self._active_broker_name():
            # The active broker changed mid-resolution: this nscId
            # belongs to the OLD broker — never bind it to the new one.
            self._order_nsc_id = None
            return
        self._order_nsc_id = (
            nsc_id if isinstance(nsc_id, str) and nsc_id else None
        )

    def _on_order_identity_failed(self, ins_code, message):
        """A failed resolution leaves the identity unresolved (closed)."""
        if ins_code != self._order_identity_instrument:
            return  # stale failure — discarded deterministically
        self._order_nsc_id = None

    # ---------------------------------------------------------
    # Add to Queue (UI-4): prepare ONE real Order, enqueue it
    # ---------------------------------------------------------

    def _on_add_to_queue(self):
        """
        Prepare ONE ``models.order.Order`` from the current form state
        and append it to the EXISTING ``OrderQueue`` with the active
        account/broker binding.

        Strictly fail-closed — nothing is queued unless EVERY element is
        real and bound coherently:
          * an active account (its broker is the identity's broker),
          * a selected real Instrument,
          * side, price and quantity,
          * a resolved broker nscId for exactly (ins_code, broker_name).

        No dispatch, no broker call, no network happens here: the nscId
        was already captured off the GUI thread at selection time.

        Returns True when an order was queued, False otherwise (the
        queue is left untouched).
        """
        record = self._active_account_record()
        if record is None:
            self._show_queue_status(QUEUE_STATUS_NO_ACCOUNT)
            return False

        instrument = self.config.selected_instrument
        if instrument is None:
            self._show_queue_status(QUEUE_STATUS_NO_SYMBOL)
            return False

        side = self.config.side
        price = self.config.price
        quantity = self.config.quantity
        if side is None or price is None or quantity is None:
            self._show_queue_status(QUEUE_STATUS_INCOMPLETE)
            return False

        ins_code = getattr(instrument, "ins_code", None)
        if ins_code != self._order_identity_instrument:
            # The identity belongs to a different (or no) selection.
            self._show_queue_status(QUEUE_STATUS_NO_IDENTITY)
            return False
        if self._order_identity_broker != record.broker_name:
            # The nscId was resolved for ANOTHER broker — never bind it
            # to the current account. A reselect resolves it afresh.
            self._show_queue_status(QUEUE_STATUS_BROKER_STALE)
            return False
        nsc_id = self._order_nsc_id
        if not nsc_id:
            self._show_queue_status(QUEUE_STATUS_NO_IDENTITY)
            return False

        # One real Order (the Core model) — identity came from the
        # EXISTING provider seam, never guessed or fabricated.
        order = Order(
            nsc_id=nsc_id,
            side=side,
            price=price,
            quantity=quantity,
        )
        self.order_queue.enqueue(
            order,
            account_id=record.account_id,
            broker_name=record.broker_name,
        )
        self._show_queue_status(QUEUE_STATUS_QUEUED)
        self._refresh_queue_display()
        self._refresh_test_button_state()
        return True

    def _refresh_queue_display(self):
        """
        Re-render the visible queue list ONLY from the exact entries the
        EXISTING ``OrderQueue.list_pending()`` returned.

        The entry (and hence the exact queued Order object) is carried in
        the row's data role — orders are never cloned/rebuild for display,
        and display text is never parsed back into identity.
        """
        self.queue_list.clear()
        pending = self.order_queue.list_pending()
        for entry in pending:
            order = entry.order
            side_label = dict(SIDE_LABELS).get(
                getattr(order, "side", None),
                str(getattr(order, "side", "")),
            )
            text = (
                f"{getattr(order, 'nsc_id', '')} | {side_label} | "
                f"{getattr(order, 'price', '')} | "
                f"{getattr(order, 'quantity', '')} | "
                f"{entry.account_id} → {entry.broker_name}"
            )
            item = QListWidgetItem(text, self.queue_list)
            item.setData(QUEUE_ENTRY_ROLE, entry)
        self.queue_count_label.setText(
            f"{len(pending)} order(s) in queue"
        )

    def _show_queue_status(self, text):
        self.queue_status_label.setText(text)

    # ---------------------------------------------------------
    # UI-5 Task 1: Test Button / Test Mode (UI-only toggle)
    # ---------------------------------------------------------

    def _on_test_toggled(self, checked):
        """
        Toggle the UI-only Test Mode state.

        This is a PURE UI state toggle — no execution, no dispatch,
        no broker call, no network activity of any kind. The button
        label reflects the state: OFF -> "Test", ON -> "Test (On)".

        When the toggle turns Test Mode ON, exactly one dry-run Test pass
        is issued through the wired runner (see ``_run_test_pass``) — the
        intentional Test action. Turning OFF never executes anything.
        """
        self._test_mode = bool(checked)
        self.test_button.setText("Test (On)" if self._test_mode else "Test")
        if self._test_mode:
            self._run_test_pass()

    def set_test_runner_factory(self, factory):
        """
        Provide the factory that builds the Test runner (UI-5 Task 2).

        The runner drives the Test action's pending entries through the
        EXISTING dry-run execution chain (UI-4 bridge -> DispatchIntegration
        -> DispatchCore -> OrderEngine). It is built on the FIRST real Test
        pass, never at construction or plain refresh, so no Core/Broker
        import is ever forced by this page (offline contracts preserved).
        Tests inject a fake runner factory so no dispatch is ever issued.
        """
        self._test_runner_factory = factory

    def _test_runner(self):
        """
        Lazily build the wired Test runner (exactly once per factory).

        ``None`` when no runner has been wired — the Test action then
        stays a pure UI toggle (no execution possible).
        """
        if (
            self._test_runner_instance is None
            and self._test_runner_factory is not None
        ):
            self._test_runner_instance = self._test_runner_factory()
        return self._test_runner_instance

    def _run_test_pass(self):
        """
        Issue exactly one dry-run execution pass for the pending entries.

        Only the Test action reaching ON state calls this method; it is
        never invoked from refresh, render, navigation, or any constructor
        or signal-wiring path.

        Guards (fail-closed, no partial execution):
          * Test Mode must be ON (this method is only called then).
          * A runner must actually be wired; otherwise the toggle is a pure
            UI action (Task 1 behavior, no execution).
          * There must be pending queue entries; an empty queue never
            reaches the runner.
          * The active AccountRecord must exist (AccountSource: the pass
            runs for the account the user has selected). Its existing
            ``Account`` object is obtained verbatim from the store — never
            resolved, inferred, fabricated or rebuilt — and passed to the
            runner.
          * The active account's identity (and its broker association) must
            match every queue entry; a mismatch never reaches the runner.

        The resolved ``Account`` object is handed to the runner explicitly
        (``runner.run(entries, account=account)``). No Account is ever
        resolved through a broker or the network, and no queue entry is
        changed by this method.

        Exactly once: one Test action = one ``runner.run(entries, account)``
        call. A blocked/failed result is stored on ``_last_test_run`` /
        ``_last_test_error`` for a later pass to surface; nothing is
        retried and the queue is never mutated by the pass itself.
        """
        if not self._test_mode:
            return

        runner = self._test_runner()
        if runner is None:
            # No runner wired (tests, or UI-only usage): pure toggle.
            return

        entries = list(self.order_queue.list_pending())
        if not entries:
            self._show_queue_status("Test run skipped: no pending orders")
            return

        record = self._active_account_record()
        if record is None:
            self._show_queue_status(
                "Test run skipped: no active account (fail-closed)"
            )
            return

        account = record.account
        for entry in entries:
            if (
                entry.account_id != account.account_id
                or entry.broker_name != record.broker_name
            ):
                self._show_queue_status(
                    "Test run skipped: active account does not match the "
                    "queue entries (fail-closed)"
                )
                return

        try:
            plan, execution_id, result = runner.run(
                entries, account=account
            )
        except Exception as exc:  # fail-closed: surface, never crash the UI
            self._last_test_error = str(exc)
            self._show_queue_status(
                f"Test run could not be issued: {exc}"
            )
            return

        self._last_test_run = (plan, execution_id, result)
        self._last_test_entries = list(entries)
        self._last_test_error = None
        self._show_queue_status(
            f"Test run issued (dry-run): execution {execution_id}"
        )

    def _refresh_test_button_state(self):
        """
        Update the Test button enabled/disabled state based on UI conditions.

        The Test button is disabled when:
          * the queue is empty, OR
          * the required selected account is missing, OR
          * the required selected instrument is missing.

        It becomes enabled only when all three conditions are valid.

        The queue is consulted only when one actually exists (an injected
        queue or a lazily built one) — an untouched page is trivially
        empty, so the lazy ``core.order_queue`` import is never forced on
        a plain navigation or refresh.
        """
        has_queue = False
        if (
            self._injected_order_queue is not None
            or self._default_queue is not None
        ):
            has_queue = len(self.order_queue.list_pending()) > 0
        has_account = self._active_account_record() is not None
        has_instrument = self.config.selected_instrument is not None

        self.test_button.setEnabled(has_queue and has_account and has_instrument)

    # ---------------------------------------------------------
    # Symbol info / status display
    # ---------------------------------------------------------

    def _refresh_symbol_info(self):
        instrument = self.config.selected_instrument
        if instrument is None:
            self.symbol_name_label.setText("—")
        else:
            # Display comes from the REAL Instrument object only.
            market = getattr(instrument, "market", None)
            market_part = f" ({market})" if market else ""
            self.symbol_name_label.setText(
                f"{getattr(instrument, 'symbol', '')} — "
                f"{getattr(instrument, 'name', '')}{market_part}"
            )
        # Fail-closed display: without a verified source this is never
        # "tradable"/"permitted".
        self.symbol_status_label.setText(
            f"Status: {self.config.symbol_status()}"
        )

    # ---------------------------------------------------------
    # Side / Price / Quantity
    # ---------------------------------------------------------

    def _on_side_selected(self, side):
        try:
            self.config.set_side(side)
        except OrderConfigError as exc:  # pragma: no cover — buttons are fixed
            QMessageBox.warning(self, "Invalid side", str(exc))

    def _on_price_changed(self):
        text = self.price_input.text().strip()
        if not text:
            self.config.price = None
            self._refresh_amounts()
            return
        try:
            # The Core Order contract is price: int — integer input only.
            # Fractional input ("15000.5") is rejected, and the previous
            # valid state is preserved.
            self.config.set_price(int(text))
        except (OrderConfigError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid price", str(exc))
        self._refresh_amounts()

    def _on_quantity_changed(self):
        text = self.quantity_input.text().strip()
        if not text:
            self.config.quantity = None
            self._refresh_amounts()
            return
        try:
            # The Core Order contract is quantity: int — integer input
            # only. Fractional input ("500.5") is rejected, and the
            # previous valid state is preserved.
            self.config.set_quantity(int(text))
        except (OrderConfigError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid quantity", str(exc))
        self._refresh_amounts()

    # ---------------------------------------------------------
    # Amounts
    # ---------------------------------------------------------

    def _refresh_amounts(self):
        base = self.config.base_amount()
        # base is an int (price * quantity, both int per the Core Order
        # contract) — format it as a plain integer, no scientific notation.
        self.base_amount_label.setText(
            "—" if base is None else f"{base:,}".replace(",", "\u066c")
        )
        # Fee / Final Amount: no contract exists — never fabricated.
        self.fee_label.setText("Not available")
        self.final_amount_label.setText("Not available")

    # ---------------------------------------------------------
    # Account display (verbatim from the UI-2.1 store)
    # ---------------------------------------------------------

    def _active_account_text(self):
        active_id = self.store.active_account_id()
        if active_id is None:
            # No fallback to accounts[0]/first/default — shown transparently.
            return "No active account — select one on the Accounts page"
        record = self.store.get(active_id)
        return f"{record.account_id} → {record.broker_name}"

    def refresh_active_account(self):
        """Re-mirror the active account from the store into the page."""
        self.active_account_label.setText(self._active_account_text())
        # UI-4: an account switch invalidates the resolved identity (it is
        # broker-scoped). Re-resolve for the current selection if stale.
        self._restart_order_identity_if_stale()
        self._refresh_test_button_state()

    def _active_account_record(self):
        """
        The active AccountRecord, or ``None`` while nothing is active.
        Fail-closed: an unknown/removed id yields ``None`` (never guessed).
        """
        active_id = self.store.active_account_id()
        if active_id is None:
                return None
        try:
                return self.store.get(active_id)
        except ValueError:  # AccountStoreError of the UI-2.1 store
                return None

    def _active_broker_name(self):
        """The active account's broker name, or ``None`` while inactive."""
        record = self._active_account_record()
        if record is None:
                return None
        return record.broker_name

    def _restart_order_identity_if_stale(self):
        """
        Re-resolve the selected instrument's order identity when selecting
        an account made it available (or the broker changed) — so the
        realistic "choose account → pick symbol" order of operations still
        leads to a working Add-to-Queue.
        """
        instrument = self.config.selected_instrument
        if instrument is None:
                return
        if (
                self._order_nsc_id
                and self._order_identity_broker == self._active_broker_name()
        ):
                return  # still coherent — nothing to do
        self._start_order_identity_resolution(instrument)
